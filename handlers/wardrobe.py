from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import models
from keyboards.inline import wardrobe_kb, back_to_menu_kb
from config import WARDROBE_LIMIT

router = Router()

MAX_PHOTO_SIZE = 10 * 1024 * 1024
WARDROBE_PACK_LIMIT = 30  # when granted via standalone pack


def _get_wardrobe_limit(user) -> int:
    """Return effective wardrobe slot limit: max of tariff limit and active standalone pack."""
    tariff_limit = WARDROBE_LIMIT.get(user["tariff"], 0)
    pack_until = user["wardrobe_until"] if "wardrobe_until" in user.keys() else None
    if pack_until:
        try:
            if datetime.fromisoformat(pack_until) > datetime.now():
                return max(tariff_limit, WARDROBE_PACK_LIMIT)
        except Exception:
            pass
    return tariff_limit


class WardrobeStates(StatesGroup):
    waiting_photo = State()
    waiting_name = State()


@router.message(Command("wardrobe"))
@router.callback_query(F.data == "wardrobe")
async def show_wardrobe(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = event.from_user.id
    user = await models.get_user(user_id)
    if not user:
        user = await models.create_user(user_id, event.from_user.username or "",
                                         event.from_user.full_name or "")

    tariff = user["tariff"]
    limit = _get_wardrobe_limit(user)
    if limit == 0:
        text = ("❌ Виртуальный шкаф доступен с тарифа <b>Про</b> "
                "или по пакету «Шкаф на месяц» в /tariffs.")
        kb = back_to_menu_kb()
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    await _send_wardrobe_page(event, user_id, tariff, limit, page=0)


async def _send_wardrobe_page(event, user_id: int, tariff: str, limit: int, page: int):
    items, total = await models.get_wardrobe_items(user_id, offset=page * 5, limit=5)
    text = f"👜 <b>Твой шкаф</b> ({total}/{limit} вещей)"
    kb = wardrobe_kb(page, total, [dict(i) for i in items], tariff=tariff)

    if isinstance(event, CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("wardrobe_page:"))
async def wardrobe_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user = await models.get_user(user_id)
    limit = _get_wardrobe_limit(user)
    await _send_wardrobe_page(callback, user_id, user["tariff"], limit, page)


@router.callback_query(F.data == "wardrobe_add")
async def wardrobe_add_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await models.get_user(user_id)
    limit = _get_wardrobe_limit(user)
    _, total = await models.get_wardrobe_items(user_id, limit=1)

    if limit == 0:
        await callback.answer("❌ Шкаф недоступен на твоём тарифе", show_alert=True)
        return
    if total >= limit:
        await callback.answer(f"❌ Шкаф полон ({limit}/{limit} вещей)", show_alert=True)
        return

    await state.set_state(WardrobeStates.waiting_photo)
    await callback.answer()
    await callback.message.answer("📸 Отправь фото вещи")


@router.message(WardrobeStates.waiting_photo, F.photo)
async def wardrobe_got_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_PHOTO_SIZE:
        await message.answer("❌ Фото слишком большое (максимум 10 МБ).")
        return
    await state.update_data(file_id=photo.file_id)
    await state.set_state(WardrobeStates.waiting_name)
    await message.answer("✏️ Придумай название для этой вещи:")


@router.message(WardrobeStates.waiting_name, F.text)
async def wardrobe_got_name(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data["file_id"]
    name = message.text.strip()[:50]
    user_id = message.from_user.id

    await models.add_wardrobe_item(user_id, name, file_id)
    await state.clear()
    await message.answer(f"✅ Вещь «{name}» добавлена в шкаф!", reply_markup=back_to_menu_kb())


@router.callback_query(F.data.startswith("wardrobe_del:"))
async def wardrobe_delete(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    item = await models.get_wardrobe_item(item_id)
    if item and item["user_id"] == user_id:
        await models.delete_wardrobe_item(item_id, user_id)
        await callback.answer("🗑 Удалено")
        # Refresh wardrobe
        user = await models.get_user(user_id)
        limit = _get_wardrobe_limit(user)
        await _send_wardrobe_page(callback, user_id, user["tariff"], limit, page=0)
    else:
        await callback.answer("❌ Вещь не найдена", show_alert=True)


@router.callback_query(F.data == "wardrobe_select")
async def wardrobe_select(callback: CallbackQuery, state: FSMContext):
    """User wants to pick wardrobe item for tryon."""
    user_id = callback.from_user.id
    items, total = await models.get_wardrobe_items(user_id, limit=50)
    if not items:
        await callback.answer("Шкаф пуст. Добавь вещи сначала.", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(InlineKeyboardButton(
            text=f"👗 {item['name']}",
            callback_data=f"wardrobe_use:{item['id']}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="wardrobe"))
    await callback.answer()
    await callback.message.answer("Выбери вещь для примерки:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("wardrobe_use:"))
async def wardrobe_use_item(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split(":")[1])
    item = await models.get_wardrobe_item(item_id)
    if not item:
        await callback.answer("Вещь не найдена", show_alert=True)
        return

    from handlers.tryon import TryonStates
    await state.update_data(user_photo_file_id=None, wardrobe_item_fid=item["file_id"])
    await state.set_state(TryonStates.waiting_user_photo)
    await callback.answer()
    await callback.message.answer(
        f"✅ Выбрана вещь: <b>{item['name']}</b>\n\n"
        f"📸 Теперь отправь своё фото для примерки",
        parse_mode="HTML"
    )
