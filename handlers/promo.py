from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import models
from keyboards.inline import back_to_menu_kb
from services.billing import apply_tariff

router = Router()


class PromoStates(StatesGroup):
    waiting_code = State()


@router.message(Command("promo"))
@router.callback_query(F.data == "promo")
async def start_promo(event: Message | CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.waiting_code)
    text = "🎟 Введи промокод:"
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text)
    else:
        await event.answer(text)


@router.message(PromoStates.waiting_code, F.text)
async def apply_promo(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    user = await models.get_user(user_id)
    if not user:
        user = await models.create_user(user_id, message.from_user.username or "",
                                         message.from_user.full_name or "")

    await state.clear()

    promo = await models.get_promo_code(code)

    if not promo:
        await message.answer("❌ Промокод не найден.", reply_markup=back_to_menu_kb())
        return
    if not promo["is_active"]:
        await message.answer("❌ Промокод отключён.", reply_markup=back_to_menu_kb())
        return
    if promo["expires_at"]:
        try:
            if datetime.fromisoformat(promo["expires_at"]) < datetime.now():
                await message.answer("❌ Срок действия промокода истёк.", reply_markup=back_to_menu_kb())
                return
        except Exception:
            pass
    if promo["max_uses"] and promo["uses_count"] >= promo["max_uses"]:
        await message.answer("❌ Промокод уже использован максимальное количество раз.",
                             reply_markup=back_to_menu_kb())
        return
    if promo["new_users_only"] and user["total_tryons"] > 0:
        await message.answer("❌ Этот промокод только для новых пользователей.",
                             reply_markup=back_to_menu_kb())
        return
    if await models.has_used_promo(user_id, promo["id"]):
        await message.answer("❌ Ты уже использовал этот промокод.", reply_markup=back_to_menu_kb())
        return

    # Check target restriction
    target = promo["target"] or "all"
    if target not in ("all", user["tariff"]) and target != "packs":
        await message.answer(
            f"❌ Этот промокод действует только для тарифа {target.capitalize()}.",
            reply_markup=back_to_menu_kb()
        )
        return

    # Apply promo
    await models.activate_promo(user_id, promo["id"])
    ptype = promo["type"]
    value = promo["value"]

    if ptype == "bonus":
        await models.add_balance(user_id, value)
        await message.answer(
            f"✅ Промокод активирован!\n+{value} примерок зачислено на баланс 🎉",
            reply_markup=back_to_menu_kb()
        )
    elif ptype == "trial":
        from datetime import timedelta
        tariff_key = promo["trial_tariff"] or "start"
        from database.models import update_user
        expires = (datetime.now() + timedelta(days=value)).isoformat()
        await update_user(user_id, tariff=tariff_key, tariff_expires_at=expires)
        from config import TARIFFS
        name = TARIFFS.get(tariff_key, {}).get("name", tariff_key)
        await message.answer(
            f"✅ Промокод активирован!\nТариф <b>{name}</b> на {value} дней 🎉",
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML"
        )
    elif ptype == "discount":
        await message.answer(
            f"🎟 Промокод <b>{code}</b> даёт скидку <b>{value}%</b> на покупку.\n\n"
            f"Введи его при оплате:\n"
            f"<b>Тарифы → выбери тариф → 🎟 Ввести промокод</b>",
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML"
        )
        return
    elif ptype == "partner":
        await models.add_balance(user_id, value)
        await message.answer(
            f"✅ Партнёрский промокод активирован!\n+{value} примерок 🎉",
            reply_markup=back_to_menu_kb()
        )
    else:
        await message.answer("✅ Промокод активирован!", reply_markup=back_to_menu_kb())
