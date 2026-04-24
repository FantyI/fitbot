from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from database import models
from keyboards.inline import referral_kb, back_to_menu_kb

router = Router()

BOT_USERNAME = "FitBot"  # Will be set dynamically


@router.message(Command("ref"))
@router.callback_query(F.data == "referral")
async def show_referral(event: Message | CallbackQuery):
    user_id = event.from_user.id
    user = await models.get_user(user_id)
    if not user:
        user = await models.create_user(user_id, event.from_user.username or "",
                                         event.from_user.full_name or "")

    bot = event.bot if isinstance(event, Message) else event.message.bot
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    ref_link = f"https://t.me/{bot_username}?start=REF_{user['ref_code']}"
    total_refs = user["total_referred"] or 0

    # Count how many tryons earned from refs
    # Compute milestone progress
    next_milestone = None
    if total_refs < 5:
        next_milestone = f"До бесплатного Старта: ещё {5 - total_refs} друга"
    elif total_refs < 15:
        next_milestone = f"До бесплатного Про: ещё {15 - total_refs} друга"
    else:
        next_milestone = "🏆 Все бонусы получены!"

    text = (
        f"👥 <b>Твоя реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"Приглашено: <b>{total_refs}</b> друг(а)\n"
        f"{next_milestone}\n\n"
        f"<b>Что получишь за каждого друга:</b>\n"
        f"• +5 примерок (сгорают через 14 дней)\n"
        f"• +10% от первой оплаты друга\n"
        f"• 5 друзей → бесплатный месяц <b>Старт</b>\n"
        f"• 15 друзей → бесплатный месяц <b>Про</b>"
    )

    kb = referral_kb(ref_link)

    if isinstance(event, CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
