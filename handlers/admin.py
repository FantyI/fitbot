from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import models
from keyboards.inline import (admin_main_kb, admin_promos_kb,
                               admin_broadcast_target_kb, back_to_menu_kb,
                               inbox_list_kb, ticket_actions_kb,
                               promo_choice_kb, existing_promos_for_user_kb)
from keyboards.reply import (promo_cancel_only_kb, promo_back_cancel_kb, promo_type_kb,
                              promo_trial_tariff_kb, promo_yes_no_kb, promo_target_kb,
                              promo_confirm_kb)
from config import ADMIN_IDS, TARIFFS

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ─── Admin guard ──────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    await message.answer("🔧 <b>Панель администратора</b>",
                         reply_markup=admin_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_main")
async def admin_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("🔧 <b>Панель администратора</b>",
                                      reply_markup=admin_main_kb(), parse_mode="HTML")


# ─── Stats ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    s = await models.get_stats()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"<b>Новые пользователи:</b>\n"
        f"• Сегодня: {s['new_today']}\n"
        f"• Неделя: {s['new_week']}\n"
        f"• Месяц: {s['new_month']}\n\n"
        f"<b>Примерки:</b>\n"
        f"• Сегодня: {s['tryons_today']}\n"
        f"• Неделя: {s['tryons_week']}\n"
        f"• Месяц: {s['tryons_month']}\n\n"
        f"<b>Выручка (⭐):</b>\n"
        f"• Сегодня: {s['rev_today']}\n"
        f"• Месяц: {s['rev_month']}\n\n"
        f"<b>Активных подписок:</b> {s['active_subs']}"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── Promo management ─────────────────────────────────────────────────────

class PromoCreateStates(StatesGroup):
    code = State()
    type_ = State()
    trial_tariff = State()   # only used when type == "trial"
    value = State()
    max_uses = State()
    expires = State()
    new_only = State()
    target = State()
    confirm = State()


_CANCEL = "❌ Отмена"
_BACK = "◀ Назад"

_TYPE_MAP = {
    "🏷 Скидка": "discount",
    "🎁 Бонус": "bonus",
    "🆓 Пробный": "trial",
    "🤝 Партнёрский": "partner",
}
_TRIAL_TARIFF_MAP = {
    "⭐ Старт": "start",
    "🔥 Про": "pro",
    "♾ Безлимит": "unlimited",
}
_TARGET_MAP = {
    "👥 Все": "all",
    "⭐ Старт": "start",
    "🔥 Про": "pro",
    "♾ Безлимит": "unlimited",
    "📦 Пакеты": "packs",
}
_TYPE_LABELS = {"discount": "🏷 Скидка", "bonus": "🎁 Бонус", "trial": "🆓 Пробный", "partner": "🤝 Партнёрский"}
_TARGET_LABELS = {"all": "👥 Все", "start": "⭐ Старт", "pro": "🔥 Про", "unlimited": "♾ Безлимит", "packs": "📦 Пакеты"}
_TARIFF_LABELS = {"start": "⭐ Старт", "pro": "🔥 Про", "unlimited": "♾ Безлимит"}


async def _cancel_wizard(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание промокода отменено.", reply_markup=ReplyKeyboardRemove())
    await message.answer("🎟 <b>Промокоды</b>", reply_markup=admin_promos_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_promos")
async def admin_promos(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("🎟 <b>Промокоды</b>",
                                      reply_markup=admin_promos_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_promo_list")
async def admin_promo_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    promos = await models.get_active_promos()
    if not promos:
        await callback.answer("Активных промокодов нет", show_alert=True)
        return
    await callback.answer()
    lines = []
    for p in promos[:20]:
        exp = p["expires_at"][:10] if p["expires_at"] else "∞"
        lines.append(f"• <code>{p['code']}</code> [{p['type']}] val={p['value']} "
                     f"uses={p['uses_count']}/{p['max_uses'] or '∞'} exp={exp}")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promos"))
    await callback.message.answer(
        "📋 <b>Активные промокоды:</b>\n\n" + "\n".join(lines),
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_promo_create")
async def admin_promo_create_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await state.set_state(PromoCreateStates.code)
    await callback.answer()
    await callback.message.answer(
        "📝 <b>Создание промокода</b>\n\nВведи код (до 20 символов, без пробелов):",
        reply_markup=promo_cancel_only_kb(), parse_mode="HTML"
    )


@router.message(PromoCreateStates.code, F.text)
async def promo_create_code(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    code = message.text.strip().upper().replace(" ", "")[:20]
    existing = await models.get_promo_code(code)
    if existing:
        await message.answer("❌ Такой код уже существует. Введи другой:")
        return
    await state.update_data(code=code)
    await state.set_state(PromoCreateStates.type_)
    await message.answer("Выбери тип промокода:", reply_markup=promo_type_kb())


@router.message(PromoCreateStates.type_, F.text)
async def promo_create_type(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        await state.set_state(PromoCreateStates.code)
        await message.answer("Введи код промокода (до 20 символов, без пробелов):",
                             reply_markup=promo_cancel_only_kb())
        return
    ptype = _TYPE_MAP.get(message.text)
    if not ptype:
        await message.answer("Выбери тип из кнопок:", reply_markup=promo_type_kb())
        return
    await state.update_data(type_=ptype)
    if ptype == "trial":
        await state.set_state(PromoCreateStates.trial_tariff)
        await message.answer("Какой тариф предоставить в пробный период?",
                             reply_markup=promo_trial_tariff_kb())
    else:
        await state.set_state(PromoCreateStates.value)
        hints = {"discount": "% скидки, например 10 или 20",
                 "bonus": "кол-во примерок", "partner": "кол-во примерок"}
        await message.answer(f"Введи значение ({hints.get(ptype, 'число')}):",
                             reply_markup=promo_back_cancel_kb())


@router.message(PromoCreateStates.trial_tariff, F.text)
async def promo_create_trial_tariff(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        await state.set_state(PromoCreateStates.type_)
        await message.answer("Выбери тип промокода:", reply_markup=promo_type_kb())
        return
    tariff = _TRIAL_TARIFF_MAP.get(message.text)
    if not tariff:
        await message.answer("Выбери тариф из кнопок:", reply_markup=promo_trial_tariff_kb())
        return
    await state.update_data(trial_tariff=tariff)
    await state.set_state(PromoCreateStates.value)
    await message.answer("Введи кол-во дней пробного периода:",
                         reply_markup=promo_back_cancel_kb())


@router.message(PromoCreateStates.value, F.text)
async def promo_create_value(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        data = await state.get_data()
        if data.get("type_") == "trial":
            await state.set_state(PromoCreateStates.trial_tariff)
            await message.answer("Какой тариф предоставить в пробный период?",
                                 reply_markup=promo_trial_tariff_kb())
        else:
            await state.set_state(PromoCreateStates.type_)
            await message.answer("Выбери тип промокода:", reply_markup=promo_type_kb())
        return
    try:
        value = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    await state.update_data(value=value)
    await state.set_state(PromoCreateStates.max_uses)
    await message.answer("Лимит активаций (число или «безлимит»):",
                         reply_markup=promo_back_cancel_kb())


@router.message(PromoCreateStates.max_uses, F.text)
async def promo_create_max_uses(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        data = await state.get_data()
        ptype = data.get("type_", "bonus")
        hints = {"discount": "% скидки, например 10 или 20",
                 "bonus": "кол-во примерок", "trial": "кол-во дней", "partner": "кол-во примерок"}
        await state.set_state(PromoCreateStates.value)
        await message.answer(f"Введи значение ({hints.get(ptype, 'число')}):",
                             reply_markup=promo_back_cancel_kb())
        return
    text = message.text.strip().lower()
    max_uses = None if text in ("безлимит", "0", "-") else int(text) if text.isdigit() else None
    await state.update_data(max_uses=max_uses)
    await state.set_state(PromoCreateStates.expires)
    await message.answer("Дата истечения (YYYY-MM-DD или «нет»):",
                         reply_markup=promo_back_cancel_kb())


@router.message(PromoCreateStates.expires, F.text)
async def promo_create_expires(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        await state.set_state(PromoCreateStates.max_uses)
        await message.answer("Лимит активаций (число или «безлимит»):",
                             reply_markup=promo_back_cancel_kb())
        return
    text = message.text.strip().lower()
    expires = None
    if text not in ("нет", "no", "-"):
        try:
            datetime.strptime(text, "%Y-%m-%d")
            expires = text
        except ValueError:
            await message.answer("❌ Формат даты: YYYY-MM-DD или «нет»:")
            return
    await state.update_data(expires=expires)
    await state.set_state(PromoCreateStates.new_only)
    await message.answer("Только для новых пользователей?", reply_markup=promo_yes_no_kb())


@router.message(PromoCreateStates.new_only, F.text)
async def promo_create_new_only(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        await state.set_state(PromoCreateStates.expires)
        await message.answer("Дата истечения (YYYY-MM-DD или «нет»):",
                             reply_markup=promo_back_cancel_kb())
        return
    if message.text not in ("✅ Да", "🚫 Нет"):
        await message.answer("Выбери из кнопок:", reply_markup=promo_yes_no_kb())
        return
    new_only = message.text == "✅ Да"
    await state.update_data(new_only=new_only)
    await state.set_state(PromoCreateStates.target)
    await message.answer("Ограничение по тарифу:", reply_markup=promo_target_kb())


@router.message(PromoCreateStates.target, F.text)
async def promo_create_target(message: Message, state: FSMContext):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        await state.set_state(PromoCreateStates.new_only)
        await message.answer("Только для новых пользователей?", reply_markup=promo_yes_no_kb())
        return
    target = _TARGET_MAP.get(message.text)
    if not target:
        await message.answer("Выбери из кнопок:", reply_markup=promo_target_kb())
        return
    await state.update_data(target=target)
    await state.set_state(PromoCreateStates.confirm)
    data = await state.get_data()

    lines = [
        "📋 <b>Проверь промокод:</b>\n",
        f"Код: <code>{data.get('code', '—')}</code>",
        f"Тип: {_TYPE_LABELS.get(data.get('type_', ''), data.get('type_', '—'))}",
    ]
    if data.get("type_") == "trial":
        lines.append(f"Тариф пробного: {_TARIFF_LABELS.get(data.get('trial_tariff', 'start'), '—')}")
    lines += [
        f"Значение: {data.get('value', '—')}",
        f"Лимит: {data.get('max_uses') or '∞'}",
        f"Истекает: {data.get('expires') or '∞'}",
        f"Только новым: {'Да' if data.get('new_only') else 'Нет'}",
        f"Тариф: {_TARGET_LABELS.get(data.get('target', 'all'), data.get('target', '—'))}",
    ]
    await message.answer("\n".join(lines), reply_markup=promo_confirm_kb(), parse_mode="HTML")


@router.message(PromoCreateStates.confirm, F.text)
async def promo_create_confirm(message: Message, state: FSMContext, bot: Bot):
    if message.text == _CANCEL:
        return await _cancel_wizard(message, state)
    if message.text == _BACK:
        await state.set_state(PromoCreateStates.target)
        await message.answer("Ограничение по тарифу:", reply_markup=promo_target_kb())
        return
    if message.text != "✅ Создать":
        await message.answer("Нажми «✅ Создать» или «❌ Отмена»:")
        return
    data = await state.get_data()
    send_to_uid = data.get("send_to_uid")
    await state.clear()
    await models.create_promo_code(
        code=data["code"],
        type_=data["type_"],
        value=data["value"],
        target=data.get("target", "all"),
        max_uses=data.get("max_uses"),
        new_users_only=data.get("new_only", False),
        expires_at=data.get("expires"),
        trial_tariff=data.get("trial_tariff", "start"),
    )
    await message.answer(
        f"✅ Промокод <code>{data['code']}</code> создан!",
        reply_markup=ReplyKeyboardRemove(), parse_mode="HTML"
    )
    if send_to_uid:
        try:
            await bot.send_message(
                send_to_uid,
                f"🎟 <b>Промокод за найденную ошибку:</b>\n\n"
                f"<code>{data['code']}</code>\n\n"
                f"Введи его через /promo или кнопку «Ввести промокод» в профиле.",
                parse_mode="HTML"
            )
            await message.answer(f"📤 Отправлен пользователю <code>{send_to_uid}</code>.",
                                 parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить пользователю: {e}")
    await message.answer("🎟 <b>Промокоды</b>", reply_markup=admin_promos_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_promo_disable")
async def admin_promo_disable(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("Введи код промокода для отключения:")
    await state.set_state(PromoDisableState.waiting_code)


class PromoDisableState(StatesGroup):
    waiting_code = State()


@router.message(PromoDisableState.waiting_code, F.text)
async def promo_disable_do(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    promo = await models.get_promo_code(code)
    if not promo:
        await message.answer("❌ Промокод не найден.")
        await state.clear()
        return
    await models.set_promo_active(promo["id"], False)
    await state.clear()
    await message.answer(f"🚫 Промокод <code>{code}</code> отключён.", parse_mode="HTML",
                         reply_markup=admin_promos_kb())


# ─── User management ──────────────────────────────────────────────────────

class UserSearchState(StatesGroup):
    waiting_query = State()
    selected_user_id = State()
    manual_balance = State()
    manual_tariff = State()


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(UserSearchState.waiting_query)
    await callback.answer()
    await callback.message.answer("🔍 Введи username или user_id для поиска:")


@router.message(UserSearchState.waiting_query, F.text)
async def admin_user_search(message: Message, state: FSMContext):
    results = await models.search_users(message.text.strip())
    if not results:
        await message.answer("Пользователи не найдены.")
        await state.clear()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for u in results[:10]:
        label = f"{u['full_name']} (@{u['username'] or u['id']})"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"admin_view_user:{u['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
    await state.clear()
    await message.answer("Результаты поиска:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_view_user:"))
async def admin_view_user(callback: CallbackQuery, state: FSMContext):
    uid = int(callback.data.split(":")[1])
    user = await models.get_user(uid)
    if not user:
        await callback.answer("Не найден", show_alert=True)
        return
    await callback.answer()

    text = (
        f"👤 <b>{user['full_name']}</b> (@{user['username'] or '—'})\n"
        f"ID: <code>{user['id']}</code>\n"
        f"Тариф: {user['tariff']}\n"
        f"Баланс: {user['balance']} (+{user['bonus_balance']} бонус)\n"
        f"Примерок всего: {user['total_tryons']}\n"
        f"Рефералов: {user['total_referred']}\n"
        f"Заблокирован: {'Да' if user['is_blocked'] else 'Нет'}\n"
        f"Зарегистрирован: {(user['created_at'] or '')[:10]}"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Начислить примерки", callback_data=f"admin_add_bal:{uid}"),
        InlineKeyboardButton(text="🔄 Сменить тариф", callback_data=f"admin_set_tariff:{uid}"),
    )
    builder.row(
        InlineKeyboardButton(text="🚫 Заблокировать" if not user["is_blocked"] else "✅ Разблокировать",
                             callback_data=f"admin_toggle_block:{uid}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
    await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_toggle_block:"))
async def admin_toggle_block(callback: CallbackQuery):
    uid = int(callback.data.split(":")[1])
    user = await models.get_user(uid)
    new_state = not bool(user["is_blocked"])
    await models.update_user(uid, is_blocked=int(new_state))
    await callback.answer(f"{'Заблокирован' if new_state else 'Разблокирован'}")
    await admin_view_user(callback, None)


@router.callback_query(F.data.startswith("admin_add_bal:"))
async def admin_add_bal_start(callback: CallbackQuery, state: FSMContext):
    uid = int(callback.data.split(":")[1])
    await state.update_data(target_uid=uid)
    await state.set_state(UserSearchState.manual_balance)
    await callback.answer()
    await callback.message.answer("Сколько примерок начислить? Введи число:")


@router.message(UserSearchState.manual_balance, F.text)
async def admin_add_bal_do(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data["target_uid"]
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    await models.add_balance(uid, amount)
    await state.clear()
    await message.answer(f"✅ Начислено {amount} примерок пользователю {uid}.")


@router.callback_query(F.data.startswith("admin_set_tariff:"))
async def admin_set_tariff_start(callback: CallbackQuery, state: FSMContext):
    uid = int(callback.data.split(":")[1])
    await state.update_data(target_uid=uid)
    await state.set_state(UserSearchState.manual_tariff)
    await callback.answer()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for k in TARIFFS:
        builder.button(text=TARIFFS[k]["name"], callback_data=f"admin_tariff_set:{uid}:{k}")
    builder.adjust(2)
    await callback.message.answer("Выбери тариф:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_tariff_set:"))
async def admin_tariff_set_do(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    uid = int(parts[1])
    tariff_key = parts[2]
    from services.billing import apply_tariff
    await apply_tariff(uid, tariff_key)
    await state.clear()
    await callback.answer(f"✅ Тариф {tariff_key} установлен для {uid}")
    await callback.message.answer(f"✅ Тариф <b>{TARIFFS[tariff_key]['name']}</b> установлен для пользователя {uid}.",
                                   parse_mode="HTML", reply_markup=admin_main_kb())


# ─── Broadcast ────────────────────────────────────────────────────────────

class BroadcastState(StatesGroup):
    waiting_text = State()
    waiting_target = State()
    confirm = State()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(BroadcastState.waiting_text)
    await callback.answer()
    await callback.message.answer("📢 Введи текст рассылки:")


@router.message(BroadcastState.waiting_text, F.text)
async def broadcast_got_text(message: Message, state: FSMContext):
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastState.waiting_target)
    await message.answer("Выбери аудиторию:", reply_markup=admin_broadcast_target_kb())


@router.callback_query(F.data.startswith("broadcast_"), BroadcastState.waiting_target)
async def broadcast_target(callback: CallbackQuery, state: FSMContext):
    target = callback.data.replace("broadcast_", "")
    await state.update_data(target=target)
    await state.set_state(BroadcastState.confirm)
    data = await state.get_data()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_main"),
    )
    await callback.answer()
    await callback.message.answer(
        f"Текст:\n<i>{data['broadcast_text']}</i>\n\nАудитория: <b>{target}</b>\n\nПодтвердить?",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )


@router.callback_query(F.data == "broadcast_confirm", BroadcastState.confirm)
async def broadcast_do(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data["broadcast_text"]
    target = data["target"]
    await state.clear()
    await callback.answer()

    users = await models.get_all_users()
    sent = 0
    failed = 0

    for user in users:
        if user["is_blocked"]:
            continue
        if target == "paid" and user["tariff"] == "free":
            continue
        if target.startswith("tariff:") and user["tariff"] != target.split(":")[1]:
            continue

        try:
            await callback.message.bot.send_message(user["id"], text)
            sent += 1
        except Exception:
            failed += 1

    await callback.message.answer(
        f"📢 Рассылка завершена!\nОтправлено: {sent}\nОшибок: {failed}",
        reply_markup=admin_main_kb()
    )


# ─── Promo creation back navigation ───────────────────────────────────────

@router.callback_query(F.data.startswith("promo_back:"))
async def promo_back(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    current_state = await state.get_state()
    if not current_state or "PromoCreateStates" not in current_state:
        await callback.answer("Сначала начни создание промокода.", show_alert=True)
        return
    step = int(callback.data.split(":")[1])
    await callback.answer()
    data = await state.get_data()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    if step == 1:
        await state.set_state(PromoCreateStates.code)
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"))
        await callback.message.answer(
            "📝 <b>Создание промокода</b>\n\nШаг 1/7. Введи код (до 20 символов, без пробелов):",
            reply_markup=b.as_markup()
        )

    elif step == 2:
        await state.set_state(PromoCreateStates.type_)
        _type_labels = {"discount": "🏷 Скидка", "bonus": "🎁 Бонус",
                        "trial": "🆓 Пробный", "partner": "🤝 Партнёрский"}
        b = InlineKeyboardBuilder()
        for t, label in _type_labels.items():
            b.button(text=label, callback_data=f"promo_type:{t}")
        b.adjust(2)
        b.row(
            InlineKeyboardButton(text="◀ Назад", callback_data="promo_back:1"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"),
        )
        await callback.message.answer("Шаг 2/7. Выбери тип:", reply_markup=b.as_markup())

    elif step == 3:
        await state.set_state(PromoCreateStates.value)
        ptype = data.get("type_", "bonus")
        hints = {"discount": "% скидки (10/20/30)", "bonus": "кол-во примерок",
                 "trial": "кол-во дней", "partner": "кол-во примерок"}
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="◀ Назад", callback_data="promo_back:2"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"),
        )
        await callback.message.answer(
            f"Шаг 3/7. Введи значение ({hints.get(ptype, 'число')}):", reply_markup=b.as_markup()
        )

    elif step == 4:
        await state.set_state(PromoCreateStates.max_uses)
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="◀ Назад", callback_data="promo_back:3"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"),
        )
        await callback.message.answer("Шаг 4/7. Лимит активаций (число или «безлимит»):", reply_markup=b.as_markup())

    elif step == 5:
        await state.set_state(PromoCreateStates.expires)
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="◀ Назад", callback_data="promo_back:4"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"),
        )
        await callback.message.answer("Шаг 5/7. Дата истечения (YYYY-MM-DD или «нет»):", reply_markup=b.as_markup())

    elif step == 6:
        await state.set_state(PromoCreateStates.new_only)
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="Да", callback_data="promo_newonly:1"),
            InlineKeyboardButton(text="Нет", callback_data="promo_newonly:0"),
        )
        b.row(
            InlineKeyboardButton(text="◀ Назад", callback_data="promo_back:5"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"),
        )
        await callback.message.answer("Шаг 6/7. Только для новых пользователей?", reply_markup=b.as_markup())

    elif step == 7:
        await state.set_state(PromoCreateStates.target)
        _target_labels = {"all": "👥 Все", "start": "⭐ Старт", "pro": "🔥 Про",
                          "unlimited": "♾ Безлимит", "packs": "📦 Пакеты"}
        b = InlineKeyboardBuilder()
        for t, label in _target_labels.items():
            b.button(text=label, callback_data=f"promo_target:{t}")
        b.adjust(3)
        b.row(
            InlineKeyboardButton(text="◀ Назад", callback_data="promo_back:6"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos"),
        )
        await callback.message.answer("Шаг 7/7. Ограничение по тарифу:", reply_markup=b.as_markup())


# ─── Support Inbox ─────────────────────────────────────────────────────────

class AdminReplyStates(StatesGroup):
    waiting_reply = State()


async def _show_inbox(callback: CallbackQuery, page: int):
    per_page = 5
    tickets, total = await models.get_support_tickets(limit=per_page, offset=page * per_page)
    new_count = await models.count_new_tickets()
    if not total:
        text = "📬 <b>Ящик пуст</b>"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
        try:
            await callback.message.edit_text(text, reply_markup=b.as_markup())
        except Exception:
            await callback.message.answer(text, reply_markup=b.as_markup())
        return
    text = f"📬 <b>Ящик</b> · всего {total}"
    if new_count:
        text += f", <b>новых {new_count}</b>"
    try:
        await callback.message.edit_text(text, reply_markup=inbox_list_kb(tickets, page, total, per_page))
    except Exception:
        await callback.message.answer(text, reply_markup=inbox_list_kb(tickets, page, total, per_page))


@router.callback_query(F.data == "admin_inbox")
async def admin_inbox_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await _show_inbox(callback, page=0)


@router.callback_query(F.data.startswith("inbox:"))
async def admin_inbox_page(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await _show_inbox(callback, page=page)


@router.callback_query(F.data.startswith("inbox_view:"))
async def admin_inbox_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    ticket_id = int(callback.data.split(":")[1])
    ticket = await models.get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return
    await callback.answer()
    if ticket["status"] == "new":
        await models.mark_ticket_read(ticket_id)
    type_label = "🐛 Баг" if ticket["type"] == "bug" else "💬 Вопрос"
    status_map = {"new": "🆕 Новый", "open": "📖 Прочитан", "closed": "✅ Закрыт"}
    status_label = status_map.get(ticket["status"], ticket["status"])
    uname = f"@{ticket['username']}" if ticket["username"] else "—"
    created = (ticket["created_at"] or "")[:16]
    text = (
        f"{type_label} <b>#{ticket['id']}</b> · {status_label}\n"
        f"<b>{ticket['full_name']}</b> ({uname}) <code>[{ticket['user_id']}]</code>\n"
        f"<i>{created}</i>\n\n"
        f"«{ticket['message']}»"
    )
    is_bug = ticket["type"] == "bug"
    try:
        await callback.message.edit_text(text, reply_markup=ticket_actions_kb(ticket["user_id"], is_bug, ticket_id))
    except Exception:
        await callback.message.answer(text, reply_markup=ticket_actions_kb(ticket["user_id"], is_bug, ticket_id))


@router.callback_query(F.data.startswith("inbox_close:"))
async def admin_inbox_close(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    ticket_id = int(callback.data.split(":")[1])
    await models.close_support_ticket(ticket_id)
    await callback.answer("✅ Тикет закрыт")
    await _show_inbox(callback, page=0)


# ─── Support: reply to user ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("support_reply:"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await state.update_data(reply_to_uid=user_id)
    await state.set_state(AdminReplyStates.waiting_reply)
    await callback.answer()
    await callback.message.answer(f"📩 Введи ответ пользователю <code>{user_id}</code>:")


@router.message(AdminReplyStates.waiting_reply, F.text)
async def admin_reply_send(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    uid = data["reply_to_uid"]
    await state.clear()
    try:
        await bot.send_message(uid, f"📩 <b>Ответ от поддержки:</b>\n\n{message.text}")
        await message.answer(f"✅ Ответ отправлен пользователю <code>{uid}</code>.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")


# ─── Support: promo for bug reporter ──────────────────────────────────────

@router.callback_query(F.data.startswith("support_promo:"))
async def admin_promo_choice(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await callback.answer()
    text = f"🎟 Выдать промокод пользователю <code>{user_id}</code>. Выбери способ:"
    try:
        await callback.message.edit_text(text, reply_markup=promo_choice_kb(user_id))
    except Exception:
        await callback.message.answer(text, reply_markup=promo_choice_kb(user_id))


@router.callback_query(F.data.startswith("promo_choice_new:"))
async def promo_choice_new(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await state.update_data(send_to_uid=user_id)
    await state.set_state(PromoCreateStates.code)
    await callback.answer()
    await callback.message.answer(
        f"📝 Создание промокода (будет отправлен <code>{user_id}</code>)\n\n"
        f"Шаг 1/7. Введи код (до 20 символов, без пробелов):"
    )


@router.callback_query(F.data.startswith("promo_choice_existing:"))
async def promo_choice_existing(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    promos = await models.get_active_promos()
    await callback.answer()
    if not promos:
        await callback.message.answer("Нет активных промокодов. Создай новый.")
        return
    text = f"📋 Выбери промокод для пользователя <code>{user_id}</code>:"
    try:
        await callback.message.edit_text(text, reply_markup=existing_promos_for_user_kb(promos, user_id))
    except Exception:
        await callback.message.answer(text, reply_markup=existing_promos_for_user_kb(promos, user_id))


@router.callback_query(F.data.startswith("promo_send_existing:"))
async def promo_send_existing(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")
    promo_id = int(parts[1])
    uid = int(parts[2])
    promo = await models.get_promo_by_id(promo_id)
    await callback.answer()
    if not promo:
        await callback.message.answer("❌ Промокод не найден.")
        return
    try:
        await bot.send_message(
            uid,
            f"🎟 <b>Промокод за найденную ошибку:</b>\n\n"
            f"<code>{promo['code']}</code>\n\n"
            f"Введи его через /promo или кнопку «Ввести промокод» в профиле.",
        )
        await callback.message.answer(
            f"✅ Промокод <code>{promo['code']}</code> отправлен пользователю <code>{uid}</code>."
        )
    except Exception as e:
        await callback.message.answer(f"❌ Не удалось отправить: {e}")
