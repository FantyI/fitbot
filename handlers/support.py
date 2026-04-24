from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database import models

router = Router()


class SupportStates(StatesGroup):
    choosing_type = State()
    waiting_message = State()


def support_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💬 Задать вопрос", callback_data="support_type:question"))
    builder.row(InlineKeyboardButton(text="🐛 Сообщить об ошибке", callback_data="support_type:bug"))
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="menu"))
    return builder.as_markup()


def admin_notify_kb(user_id: int, is_bug: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row = [InlineKeyboardButton(text="📩 Ответить", callback_data=f"support_reply:{user_id}")]
    if is_bug:
        row.append(InlineKeyboardButton(text="🎟 Промокод", callback_data=f"support_promo:{user_id}"))
    builder.row(*row)
    builder.row(InlineKeyboardButton(text="📬 Открыть ящик", callback_data="admin_inbox"))
    return builder.as_markup()


async def show_support(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SupportStates.choosing_type)
    await message.answer(
        "❓ <b>Помощь</b>\n\n"
        "Выбери тип обращения:\n\n"
        "🐛 За найденные ошибки мы дарим <b>промокод</b>!",
        reply_markup=support_menu_kb(),
    )


@router.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await show_support(callback.message, state)


@router.callback_query(F.data.startswith("support_type:"), SupportStates.choosing_type)
async def support_type_chosen(callback: CallbackQuery, state: FSMContext):
    stype = callback.data.split(":")[1]
    await state.update_data(support_type=stype)
    await state.set_state(SupportStates.waiting_message)
    await callback.answer()

    if stype == "question":
        prompt = "💬 Напиши свой вопрос, и мы ответим в ближайшее время:"
    else:
        prompt = (
            "🐛 Опиши найденную ошибку как можно подробнее:\n\n"
            "<i>Что делал → что ожидал → что произошло</i>"
        )
    await callback.message.edit_text(prompt)


@router.message(SupportStates.waiting_message, F.text)
async def support_message_received(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    stype = data.get("support_type", "question")
    await state.clear()

    user = message.from_user
    is_bug = stype == "bug"

    ticket_id = await models.create_support_ticket(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
        type_=stype,
        message=message.text,
    )

    type_label = "🐛 Баг" if is_bug else "💬 Вопрос"
    admin_text = (
        f"<b>{type_label} #{ticket_id}</b>\n"
        f"От: <b>{user.full_name}</b> (@{user.username or '—'}) <code>[{user.id}]</code>\n\n"
        f"«{message.text}»"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_notify_kb(user.id, is_bug))
        except Exception:
            pass

    if is_bug:
        reply = (
            "✅ <b>Спасибо за сообщение об ошибке!</b>\n\n"
            "Мы проверим и свяжемся с тобой.\n"
            "🎟 Если ошибка подтвердится — получишь промокод!"
        )
    else:
        reply = "✅ <b>Вопрос отправлен!</b>\n\nМы ответим в ближайшее время."

    from keyboards.inline import back_to_menu_kb
    await message.answer(reply, reply_markup=back_to_menu_kb())
