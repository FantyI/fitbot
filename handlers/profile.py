from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database import models
from keyboards.inline import profile_kb, history_kb, compare_second_kb, back_to_menu_kb
from services.billing import check_tariff_expiry
from config import TARIFFS, HISTORY_DAYS

router = Router()


def _tariff_label(user) -> str:
    name = TARIFFS.get(user["tariff"], {}).get("name", user["tariff"])
    if user["tariff_expires_at"]:
        try:
            exp = datetime.fromisoformat(user["tariff_expires_at"])
            return f"{name} (до {exp.strftime('%d %b %Y')})"
        except Exception:
            pass
    return name


def _bonus_str(user) -> str:
    bonus = user["bonus_balance"] or 0
    if bonus <= 0:
        return ""
    exp = ""
    if user["bonus_expires_at"]:
        try:
            d = datetime.fromisoformat(user["bonus_expires_at"])
            exp = f" (сгорают {d.strftime('%d %b')})"
        except Exception:
            pass
    return f" + {bonus} бонусных{exp}"


@router.message(Command("profile"))
@router.callback_query(F.data == "profile")
async def show_profile(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = event.from_user.id
    await check_tariff_expiry(user_id)
    user = await models.get_user(user_id)
    if not user:
        user = await models.create_user(user_id, event.from_user.username or "",
                                         event.from_user.full_name or "")

    balance_str = str(user["balance"] or 0) + _bonus_str(user)
    if user["tariff"] == "unlimited":
        balance_str = "∞ безлимит"

    text = (
        f"👤 <b>{user['full_name']}</b>"
        + (f" (@{user['username']})" if user["username"] else "") + "\n\n"
        f"Тариф: <b>{_tariff_label(user)}</b>\n"
        f"Примерки: <b>{balance_str}</b>\n"
        f"Всего сделано примерок: <b>{user['total_tryons'] or 0}</b>\n"
        f"Приглашено друзей: <b>{user['total_referred'] or 0}</b>"
    )
    kb = profile_kb()

    if isinstance(event, CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("history"))
@router.callback_query(F.data.startswith("history:"))
async def show_history(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    user = await models.get_user(user_id)

    if user["tariff"] == "free":
        text = "❌ История примерок доступна с тарифа <b>Старт</b>."
        kb = back_to_menu_kb()
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    page = 0
    if isinstance(event, CallbackQuery):
        page = int(event.data.split(":")[1])
        await event.answer()

    days = HISTORY_DAYS.get(user["tariff"], 30)
    per_page = 5
    rows, total = await models.get_user_history(user_id, offset=page * per_page,
                                                  limit=per_page, days=days)

    if not rows:
        text = "📭 У тебя пока нет примерок."
        kb = back_to_menu_kb()
        if isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=kb)
        else:
            await event.answer(text, reply_markup=kb)
        return

    session_ids = [r["id"] for r in rows]
    kb = history_kb(page, total, per_page, session_ids)

    msg = f"📸 <b>Твои примерки</b> (стр. {page+1}):\n\n"
    for r in rows:
        date_str = r["created_at"][:10] if r["created_at"] else "—"
        msg += f"• Сессия #{r['id']} от {date_str}\n"

    # Send photos
    chat_id = event.message.chat.id if isinstance(event, CallbackQuery) else event.chat.id
    bot = event.bot if hasattr(event, "bot") else event.message.bot
    for r in rows:
        if r["result_file_id"]:
            try:
                await bot.send_photo(chat_id, r["result_file_id"],
                                     caption=f"Примерка #{r['id']} — {(r['created_at'] or '')[:10]}")
            except Exception:
                pass

    if isinstance(event, CallbackQuery):
        await event.message.answer(msg, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(msg, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("compare_pick:"))
async def compare_pick_first(callback: CallbackQuery):
    first_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user = await models.get_user(user_id)

    if user["tariff"] == "free":
        await callback.answer("Сравнение доступно с тарифа Старт", show_alert=True)
        return

    days = HISTORY_DAYS.get(user["tariff"], 30)
    rows, _ = await models.get_user_history(user_id, limit=20, days=days)
    session_ids = [r["id"] for r in rows]

    await callback.answer()
    await callback.message.answer(
        f"Выбери второй образ для сравнения с #{first_id}:",
        reply_markup=compare_second_kb(first_id, session_ids)
    )


@router.callback_query(F.data.startswith("compare_do:"))
async def compare_do(callback: CallbackQuery):
    parts = callback.data.split(":")
    first_id = int(parts[1])
    second_id = int(parts[2])

    s1 = await models.get_session(first_id)
    s2 = await models.get_session(second_id)

    await callback.answer("Собираю коллаж...")

    if not s1 or not s2 or not s1["result_file_id"] or not s2["result_file_id"]:
        await callback.message.answer("❌ Не удалось найти оба образа.")
        return

    # Download both images and create collage
    import io
    from PIL import Image

    bot = callback.message.bot

    async def dl(fid):
        f = await bot.get_file(fid)
        buf = io.BytesIO()
        await bot.download_file(f.file_path, buf)
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    try:
        img1 = await dl(s1["result_file_id"])
        img2 = await dl(s2["result_file_id"])

        # Resize to same height
        h = min(img1.height, img2.height, 800)
        w1 = int(img1.width * h / img1.height)
        w2 = int(img2.width * h / img2.height)
        img1 = img1.resize((w1, h))
        img2 = img2.resize((w2, h))

        collage = Image.new("RGB", (w1 + w2 + 10, h), (240, 240, 240))
        collage.paste(img1, (0, 0))
        collage.paste(img2, (w1 + 10, 0))

        buf = io.BytesIO()
        collage.save(buf, format="JPEG", quality=90)
        buf.seek(0)

        from aiogram.types import BufferedInputFile
        await callback.message.answer_photo(
            BufferedInputFile(buf.read(), "collage.jpg"),
            caption=f"🆚 Образ #{first_id} vs Образ #{second_id}"
        )
    except Exception as e:
        await callback.message.answer(f"❌ Не удалось создать коллаж: {e}")
