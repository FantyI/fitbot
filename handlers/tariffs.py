from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, LabeledPrice, PreCheckoutQuery)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import models
from keyboards.inline import tariffs_kb, back_to_menu_kb, checkout_kb
from services.billing import apply_tariff, apply_pack, handle_first_purchase
from config import TARIFFS, PACKS

router = Router()

TARIFF_DESCRIPTIONS = {
    "free":      "🆓 Free — 2 примерки, 1 вещь, среднее качество",
    "start":     "🚀 Старт — 20 примерок/мес, до 3 вещей, без водяного знака, история 30 дней",
    "pro":       "💎 Про — 60 примерок/мес, до 6 вещей, шкаф (30), стиль-советник, поиск, история 90 дней",
    "unlimited": "♾️ Безлимит — безлимитные примерки, все функции + приоритет + ранний доступ",
}


class CheckoutStates(StatesGroup):
    promo_input = State()


def _checkout_text(label: str, stars: int, original_stars: int, discount_label: str) -> str:
    text = f"🛒 <b>{label}</b>\n\n"
    if original_stars != stars:
        text += f"Цена: <s>{original_stars} ⭐</s> → <b>{stars} ⭐</b>{discount_label}"
    else:
        text += f"Цена: <b>{stars} ⭐</b>"
    return text


@router.message(Command("tariffs"))
@router.callback_query(F.data == "tariffs")
async def show_tariffs(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "📋 <b>Тарифы FitBot</b>\n\n"
        + "\n".join(TARIFF_DESCRIPTIONS.values()) +
        "\n\n<b>Разовые пакеты:</b>\n"
        "• 5 примерок — 50 ⭐\n"
        "• 15 примерок — 120 ⭐\n"
        "• 1 образ (5+ вещей) — 35 ⭐\n"
        "• Виртуальный шкаф на месяц — 70 ⭐\n\n"
        "Оплата через Telegram Stars ⭐"
    )
    kb = tariffs_kb()
    if isinstance(event, CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("buy_tariff:"))
async def buy_tariff(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    tariff_key = callback.data.split(":")[1]
    tariff = TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    user = await models.get_user(user_id)
    original_stars = tariff["price_stars"]
    stars = original_stars
    discount_label = ""

    if user and user["referred_by"] and not user["first_purchase_done"]:
        stars = int(stars * 0.8)
        discount_label = " (скидка 20% за реферала)"

    label = f"Тариф {tariff['name']}"
    await state.update_data(
        product_type="tariff",
        product_key=tariff_key,
        final_stars=stars,
        original_stars=original_stars,
        product_label=label,
        discount_label=discount_label,
    )

    await callback.answer()
    text = _checkout_text(label, stars, original_stars, discount_label)
    msg = await callback.message.answer(text, reply_markup=checkout_kb(bool(discount_label)), parse_mode="HTML")
    await state.update_data(checkout_msg_id=msg.message_id, checkout_chat_id=callback.message.chat.id)


@router.callback_query(F.data.startswith("buy_pack:"))
async def buy_pack(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    pack_key = callback.data.split(":")[1]
    pack = PACKS.get(pack_key)
    if not pack:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    user = await models.get_user(user_id)
    original_stars = pack["stars"]
    stars = original_stars
    discount_label = ""

    if user and user["referred_by"] and not user["first_purchase_done"]:
        stars = int(stars * 0.8)
        discount_label = " (скидка 20% за реферала)"

    label = pack["name"]
    await state.update_data(
        product_type="pack",
        product_key=pack_key,
        final_stars=stars,
        original_stars=original_stars,
        product_label=label,
        discount_label=discount_label,
    )

    await callback.answer()
    text = _checkout_text(label, stars, original_stars, discount_label)
    msg = await callback.message.answer(text, reply_markup=checkout_kb(bool(discount_label)), parse_mode="HTML")
    await state.update_data(checkout_msg_id=msg.message_id, checkout_chat_id=callback.message.chat.id)


@router.callback_query(F.data == "checkout_enter_promo")
async def checkout_enter_promo(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("product_type"):
        await callback.answer("Сначала выбери товар.", show_alert=True)
        return
    await state.set_state(CheckoutStates.promo_input)
    await callback.answer()
    await callback.message.answer("🎟 Введи промокод:")


@router.message(CheckoutStates.promo_input, F.text)
async def checkout_promo_received(message: Message, state: FSMContext, bot: Bot):
    code = message.text.strip().upper()
    data = await state.get_data()

    product_type = data.get("product_type")
    product_key = data.get("product_key")
    original_stars = data.get("original_stars", 0)
    product_label = data.get("product_label", "")
    checkout_msg_id = data.get("checkout_msg_id")
    checkout_chat_id = data.get("checkout_chat_id")

    await state.set_state(None)

    promo = await models.get_promo_code(code)

    if not promo or not promo["is_active"]:
        await message.answer("❌ Промокод не найден или отключён.")
        return

    if promo["expires_at"]:
        try:
            if datetime.fromisoformat(promo["expires_at"]) < datetime.now():
                await message.answer("❌ Срок действия промокода истёк.")
                return
        except Exception:
            pass

    if promo["max_uses"] and promo["uses_count"] >= promo["max_uses"]:
        await message.answer("❌ Промокод уже исчерпан.")
        return

    user_id = message.from_user.id
    if await models.has_used_promo(user_id, promo["id"]):
        await message.answer("❌ Ты уже использовал этот промокод.")
        return

    if promo["type"] != "discount":
        await message.answer(
            "ℹ️ Этот промокод не даёт скидку на покупку.\n"
            "Активируй его через /promo чтобы получить бонус."
        )
        return

    target = promo["target"] or "all"
    if product_type == "tariff" and target not in ("all", product_key):
        await message.answer(f"❌ Этот промокод действует только для тарифа {target.capitalize()}.")
        return
    if product_type == "pack" and target not in ("all", "packs"):
        await message.answer("❌ Этот промокод не применим к пакетам.")
        return

    if data.get("discount_label"):
        await message.answer("❌ У тебя уже применена скидка. Скидки не суммируются.")
        return

    pct = promo["value"]
    new_stars = max(1, int(original_stars * (100 - pct) / 100))
    discount_label = f" (скидка {pct}% по промокоду)"

    await state.update_data(
        final_stars=new_stars,
        discount_label=discount_label,
        applied_promo_id=promo["id"],
    )

    text = _checkout_text(product_label, new_stars, original_stars, discount_label)
    try:
        await bot.edit_message_text(
            text,
            chat_id=checkout_chat_id,
            message_id=checkout_msg_id,
            reply_markup=checkout_kb(has_promo=True),
            parse_mode="HTML",
        )
        await message.answer("✅ Промокод применён!")
    except Exception:
        await message.answer(f"✅ Промокод применён!\n\n{text}",
                             reply_markup=checkout_kb(has_promo=True), parse_mode="HTML")


@router.callback_query(F.data == "checkout_pay")
async def checkout_pay(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    product_type = data.get("product_type")
    product_key = data.get("product_key")
    final_stars = data.get("final_stars")
    product_label = data.get("product_label", "")
    discount_label = data.get("discount_label", "")

    if not product_type or not product_key or not final_stars:
        await callback.answer("Сессия устарела, выбери товар снова.", show_alert=True)
        return

    await callback.answer()
    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=product_label,
        description=product_label + discount_label,
        payload=f"{product_type}:{product_key}:{callback.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=product_label + discount_label, amount=final_stars)],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    payment = message.successful_payment
    payload = payment.invoice_payload
    charge_id = payment.telegram_payment_charge_id
    stars = payment.total_amount

    parts = payload.split(":")
    product_type = parts[0]
    product_id = parts[1]
    user_id = int(parts[2])

    payment_id = await models.create_payment(user_id, stars, 0, product_type, product_id)
    await models.complete_payment(payment_id, charge_id)

    if product_type == "tariff":
        await apply_tariff(user_id, product_id)
        tariff = TARIFFS[product_id]
        await message.answer(
            f"✅ Оплата прошла! Тариф <b>{tariff['name']}</b> активирован.",
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML"
        )
    elif product_type == "pack":
        await apply_pack(user_id, product_id)
        pack = PACKS[product_id]
        await message.answer(
            f"✅ Оплата прошла! Пакет «{pack['name']}» зачислен.",
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML"
        )

    # Activate promo if was applied
    data = await state.get_data()
    applied_promo_id = data.get("applied_promo_id")
    if applied_promo_id:
        await models.activate_promo(user_id, applied_promo_id)

    await state.clear()
    await handle_first_purchase(user_id, stars)
