import asyncio
import json
import io
import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import models
from keyboards.inline import (tryon_result_kb, outfit_add_or_start_kb,
                               season_kb, retry_tryon_kb, back_to_menu_kb,
                               sizes_skip_kb, item_source_kb)
from services import polza_client, PolzaAPIError, enqueue, TooManyJobsError
from services.billing import get_tryon_cost, can_afford
from config import TARIFFS, WARDROBE_LIMIT

router = Router()
logger = logging.getLogger(__name__)

MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10 MB


class TryonStates(StatesGroup):
    waiting_user_photo = State()
    waiting_item_photo = State()
    waiting_sizes = State()
    outfit_waiting_user_photo = State()
    outfit_waiting_items = State()


SIZES_PROMPT = (
    "📏 Укажи свой размер и размер вещи — так примерка получится точнее.\n\n"
    "Например: <i>мой размер M, размер вещи L</i>\n\n"
    "Это необязательный шаг — можешь пропустить."
)
MAX_SIZES_LEN = 200


async def _ensure_user(user_id: int, username: str, full_name: str):
    user = await models.get_user(user_id)
    if not user:
        user = await models.create_user(user_id, username or "", full_name or "")
    return user


async def _download_photo(bot: Bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    return buf.getvalue()


def _get_quality(tariff: str) -> str:
    return TARIFFS.get(tariff, {}).get("quality", "medium")


def _user_has_wardrobe_access(user) -> bool:
    if WARDROBE_LIMIT.get(user["tariff"], 0) > 0:
        return True
    pack_until = user["wardrobe_until"] if "wardrobe_until" in user.keys() else None
    if pack_until:
        try:
            if datetime.fromisoformat(pack_until) > datetime.now():
                return True
        except Exception:
            pass
    return False


# ─── Single tryon ─────────────────────────────────────────────────────────

@router.message(Command("tryon"))
@router.callback_query(F.data == "tryon_single")
async def start_tryon_single(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TryonStates.waiting_user_photo)
    text = "📸 Отправь своё фото в полный рост или по пояс"
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text)
    else:
        await event.answer(text)


@router.message(TryonStates.waiting_user_photo, F.photo)
async def got_user_photo_single(message: Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_PHOTO_SIZE:
        await message.answer("❌ Фото слишком большое (максимум 10 МБ). Сожми фото и попробуй снова.")
        return

    data = await state.get_data()
    preselected_item_fid = data.get("wardrobe_item_fid")

    if preselected_item_fid:
        # Wardrobe flow: item already chosen, jump straight to sizes step
        await state.update_data(
            user_photo_file_id=photo.file_id,
            item_photos=[preselected_item_fid],
            flow_type="single",
        )
        await state.set_state(TryonStates.waiting_sizes)
        await message.answer(SIZES_PROMPT, parse_mode="HTML", reply_markup=sizes_skip_kb())
        return

    user = await _ensure_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await state.update_data(user_photo_file_id=photo.file_id)
    await state.set_state(TryonStates.waiting_item_photo)

    if _user_has_wardrobe_access(user):
        await message.answer(
            "👗 Отправь фото вещи или выбери из шкафа:",
            reply_markup=item_source_kb()
        )
    else:
        await message.answer("👗 Теперь отправь фото вещи, которую хочешь примерить")


@router.message(TryonStates.waiting_item_photo, F.photo)
async def got_item_photo_single(message: Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_PHOTO_SIZE:
        await message.answer("❌ Фото слишком большое (максимум 10 МБ). Сожми фото и попробуй снова.")
        return

    await state.update_data(item_photos=[photo.file_id], flow_type="single")
    await state.set_state(TryonStates.waiting_sizes)
    await message.answer(SIZES_PROMPT, parse_mode="HTML", reply_markup=sizes_skip_kb())


@router.callback_query(TryonStates.waiting_item_photo, F.data == "tryon_from_wardrobe")
async def tryon_pick_from_wardrobe(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    items, total = await models.get_wardrobe_items(user_id, limit=50)
    if not items:
        await callback.answer("Шкаф пуст — сначала добавь вещи в /wardrobe.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(InlineKeyboardButton(
            text=f"👗 {item['name']}",
            callback_data=f"tryon_wp:{item['id']}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="tryon_wp_back"))
    await callback.answer()
    await callback.message.answer("Выбери вещь из шкафа:", reply_markup=builder.as_markup())


@router.callback_query(TryonStates.waiting_item_photo, F.data == "tryon_wp_back")
async def tryon_wp_back(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "👗 Отправь фото вещи или выбери из шкафа:",
        reply_markup=item_source_kb()
    )


@router.callback_query(TryonStates.waiting_item_photo, F.data.startswith("tryon_wp:"))
async def tryon_wardrobe_pick(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split(":")[1])
    item = await models.get_wardrobe_item(item_id)
    if not item:
        await callback.answer("Вещь не найдена", show_alert=True)
        return

    await state.update_data(item_photos=[item["file_id"]], flow_type="single")
    await state.set_state(TryonStates.waiting_sizes)
    await callback.answer()
    await callback.message.answer(
        f"✅ Выбрана: <b>{item['name']}</b>\n\n{SIZES_PROMPT}",
        parse_mode="HTML",
        reply_markup=sizes_skip_kb()
    )


# ─── Sizes step (shared between single & outfit) ──────────────────────────

@router.message(TryonStates.waiting_sizes, F.text)
async def got_sizes_text(message: Message, state: FSMContext, bot: Bot):
    sizes = message.text.strip()[:MAX_SIZES_LEN]
    await _launch_from_sizes(bot, message.chat.id, message.from_user, state, sizes)


@router.callback_query(TryonStates.waiting_sizes, F.data == "tryon_skip_sizes")
async def skip_sizes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await _launch_from_sizes(bot, callback.message.chat.id, callback.from_user, state, None)


async def _launch_from_sizes(bot: Bot, chat_id: int, from_user, state: FSMContext, sizes: str | None):
    data = await state.get_data()
    flow_type = data.get("flow_type", "single")
    user_photo_fid = data.get("user_photo_file_id")
    item_fids = data.get("item_photos") or []

    if not user_photo_fid or not item_fids:
        await state.clear()
        await bot.send_message(chat_id, "❌ Что-то пошло не так, попробуй снова.", reply_markup=back_to_menu_kb())
        return

    await _launch_tryon(bot, chat_id, from_user, state, flow_type,
                        user_photo_fid, item_fids, sizes)


async def _launch_tryon(bot: Bot, chat_id: int, from_user, state: FSMContext,
                         flow_type: str, user_photo_fid: str, item_fids: list,
                         sizes: str | None = None):
    user_id = from_user.id
    user = await _ensure_user(user_id, from_user.username, from_user.full_name)

    if flow_type == "outfit":
        cost = get_tryon_cost("outfit", len(item_fids))
        insufficient_msg = f"❌ Недостаточно примерок ({cost} нужно). Пополни баланс в /tariffs"
        progress_text = "⏳ Генерирую образ... обычно занимает 15–30 секунд"
    else:
        cost = 1
        insufficient_msg = "❌ Недостаточно примерок на балансе.\n\nПополни баланс в /tariffs"
        progress_text = "⏳ Генерирую примерку... обычно занимает 15–30 секунд"

    if not await can_afford(user_id, cost):
        await state.clear()
        await bot.send_message(chat_id, insufficient_msg, reply_markup=back_to_menu_kb())
        return

    await state.clear()
    progress_msg = await bot.send_message(chat_id, progress_text)

    session_id = await models.create_session(user_id, flow_type, user_photo_fid)
    await models.update_session(session_id, status="processing",
                                item_photos=json.dumps(item_fids), cost=cost)
    deducted_from = await models.deduct_balance_tracked(user_id, cost)

    priority = user["tariff"] == "unlimited"
    try:
        future = await enqueue(
            user_id, priority,
            _run_generation,
            bot, user_photo_fid, item_fids, _get_quality(user["tariff"]), None, sizes
        )
    except TooManyJobsError as e:
        await _refund(user_id, cost, deducted_from)
        await models.update_session(session_id, status="failed")
        await progress_msg.edit_text(str(e))
        return

    asyncio.create_task(
        _await_result(bot, chat_id, progress_msg.message_id,
                      future, session_id, user["tariff"], cost, user_id, deducted_from)
    )


async def _refund(user_id: int, cost: int, deducted_from: dict | None):
    """Refund cost to the buckets it was taken from (bonus-aware)."""
    if not deducted_from:
        await models.add_balance(user_id, cost)
        return
    bonus_part = deducted_from.get("bonus", 0)
    main_part = deducted_from.get("main", 0)
    if bonus_part:
        await models.add_balance(user_id, bonus_part, bonus=True,
                                  expire_days=deducted_from.get("bonus_expire_days"))
    if main_part:
        await models.add_balance(user_id, main_part)


# ─── Outfit tryon ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "tryon_outfit")
async def start_tryon_outfit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TryonStates.outfit_waiting_user_photo)
    await callback.answer()
    await callback.message.answer("📸 Отправь своё фото")


@router.message(TryonStates.outfit_waiting_user_photo, F.photo)
async def got_user_photo_outfit(message: Message, state: FSMContext):
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_PHOTO_SIZE:
        await message.answer("❌ Фото слишком большое (максимум 10 МБ).")
        return
    user_id = message.from_user.id
    user = await _ensure_user(user_id, message.from_user.username, message.from_user.full_name)
    max_items = TARIFFS.get(user["tariff"], {}).get("max_items", 1)

    await state.update_data(user_photo_file_id=photo.file_id, item_photos=[], max_items=max_items)
    await state.set_state(TryonStates.outfit_waiting_items)
    await message.answer("👗 Отправь фото первой вещи")


@router.message(TryonStates.outfit_waiting_items, F.photo)
async def got_outfit_item(message: Message, state: FSMContext):
    photo = message.photo[-1]
    data = await state.get_data()
    items = data.get("item_photos", [])
    max_items = data.get("max_items", 8)

    if len(items) >= max_items:
        await message.answer(f"❌ Максимум {max_items} вещей на твоём тарифе.")
        return

    items.append(photo.file_id)
    await state.update_data(item_photos=items)
    await message.answer(
        f"✅ Добавлено вещей: {len(items)}/{max_items}",
        reply_markup=outfit_add_or_start_kb(len(items), max_items)
    )


@router.callback_query(F.data == "outfit_add_more")
async def outfit_add_more(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("👗 Отправь фото следующей вещи")


@router.callback_query(F.data == "outfit_start")
async def outfit_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data.get("item_photos", [])

    if len(items) < 2:
        await callback.answer("Добавь минимум 2 вещи!", show_alert=True)
        return

    await state.update_data(flow_type="outfit")
    await state.set_state(TryonStates.waiting_sizes)
    await callback.answer()
    await callback.message.answer(SIZES_PROMPT, parse_mode="HTML", reply_markup=sizes_skip_kb())


# ─── Core generation ───────────────────────────────────────────────────────

async def _run_generation(bot: Bot, user_photo_fid: str, item_fids: list,
                           quality: str, season: str = None, sizes: str = None) -> bytes:
    user_bytes = await _download_photo(bot, user_photo_fid)
    item_bytes = [await _download_photo(bot, fid) for fid in item_fids]
    return await polza_client.tryon(user_bytes, item_bytes, quality, season, sizes)


async def _await_result(bot: Bot, chat_id: int, progress_msg_id: int,
                         future: asyncio.Future, session_id: int,
                         tariff: str, cost: int, user_id: int,
                         deducted_from: dict | None = None):
    try:
        done, _ = await asyncio.wait({future}, timeout=30)
        if not done:
            try:
                await bot.edit_message_text(
                    "🕐 Генерация занимает больше времени, ждём...",
                    chat_id=chat_id, message_id=progress_msg_id
                )
            except Exception:
                pass
            result_bytes = await future
        else:
            result_bytes = future.result()

        if not result_bytes:
            raise ValueError("Empty result from API")

        photo_file = BufferedInputFile(result_bytes, filename="result.jpg")
        sent = await bot.send_photo(chat_id, photo_file, caption="✨ Твоя примерка готова!")
        result_file_id = sent.photo[-1].file_id

        await models.update_session(session_id, status="done", result_file_id=result_file_id)

        try:
            await bot.delete_message(chat_id, progress_msg_id)
        except Exception:
            pass

        await bot.send_message(
            chat_id, "Что хочешь сделать дальше?",
            reply_markup=tryon_result_kb(tariff, session_id)
        )

    except Exception as e:
        logger.error(f"Generation failed for session {session_id}: {type(e).__name__}: {e}", exc_info=True)
        await _refund(user_id, cost, deducted_from)
        await models.update_session(session_id, status="failed")
        if isinstance(e, PolzaAPIError):
            error_text = f"❌ {e}\n\nПримерка не списана."
        else:
            error_text = f"❌ Ошибка генерации. Попробуй снова.\n\nПримерка не списана."
        try:
            await bot.edit_message_text(
                error_text,
                chat_id=chat_id, message_id=progress_msg_id,
                reply_markup=retry_tryon_kb()
            )
        except Exception:
            await bot.send_message(chat_id, error_text, reply_markup=retry_tryon_kb())


# ─── Post-result actions ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("style_advice:"))
async def style_advice(callback: CallbackQuery):
    session_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user = await models.get_user(user_id)

    if user["tariff"] not in ("pro", "unlimited"):
        await callback.answer("💎 Доступно с тарифа Про", show_alert=True)
        return

    await callback.answer("⏳ Получаю совет...")
    session = await models.get_session(session_id)
    try:
        advice = await polza_client.style_advice(
            f"Образ из сессии #{session_id}, тип: {session['session_type']}"
        )
        await callback.message.answer(f"💡 <b>Совет по стилю:</b>\n\n{advice}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Style advice error: {e}")
        await callback.message.answer("❌ Не удалось получить совет. Попробуй позже.")


@router.callback_query(F.data.startswith("find_similar:"))
async def find_similar(callback: CallbackQuery):
    session_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user = await models.get_user(user_id)

    if user["tariff"] not in ("pro", "unlimited"):
        await callback.answer("💎 Доступно с тарифа Про", show_alert=True)
        return

    await callback.answer("🔍 Ищу похожее...")
    try:
        items = await polza_client.similar_items(f"вещь из примерки #{session_id}")
        if not items:
            await callback.message.answer("😔 Похожих товаров не найдено.")
            return
        text = "🛍 <b>Похожие товары:</b>\n\n"
        for i, item in enumerate(items[:5], 1):
            text += f"{i}. <a href='{item.get('url', '#')}'>{item.get('name', 'Товар')}</a>\n"
        await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=False)
    except Exception as e:
        logger.error(f"Similar items error: {e}")
        await callback.message.answer("❌ Поиск временно недоступен.")


@router.callback_query(F.data.startswith("season_adapt:"))
async def season_adapt(callback: CallbackQuery):
    session_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user = await models.get_user(user_id)

    if user["tariff"] not in ("pro", "unlimited"):
        await callback.answer("💎 Доступно с тарифа Про", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("🌿 Выбери сезон:", reply_markup=season_kb(session_id))


@router.callback_query(F.data.startswith("season:"))
async def do_season_adapt(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    session_id = int(parts[1])
    season = parts[2]

    user_id = callback.from_user.id
    user = await models.get_user(user_id)
    session = await models.get_session(session_id)

    cost = 1
    if not await can_afford(user_id, cost):
        await callback.answer("❌ Недостаточно примерок", show_alert=True)
        return

    await callback.answer()
    deducted_from = await models.deduct_balance_tracked(user_id, cost)

    items = json.loads(session["item_photos"] or "[]")
    progress_msg = await callback.message.answer("⏳ Адаптирую образ под сезон...")

    priority = user["tariff"] == "unlimited"
    try:
        future = await enqueue(
            user_id, priority,
            _run_generation,
            bot, session["user_photo_file_id"], items, _get_quality(user["tariff"]), season
        )
    except TooManyJobsError as e:
        await _refund(user_id, cost, deducted_from)
        await progress_msg.edit_text(str(e))
        return

    new_session_id = await models.create_session(user_id, session["session_type"],
                                                  session["user_photo_file_id"])
    await models.update_session(new_session_id, status="processing",
                                item_photos=session["item_photos"], cost=cost)

    asyncio.create_task(
        _await_result(bot, callback.message.chat.id, progress_msg.message_id,
                      future, new_session_id, user["tariff"], cost, user_id, deducted_from)
    )
