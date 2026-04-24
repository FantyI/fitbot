from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder


# ─── Promo creation wizard keyboards ──────────────────────────────────────

def promo_cancel_only_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def promo_back_cancel_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="◀ Назад"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def promo_type_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🏷 Скидка"), KeyboardButton(text="🎁 Бонус"))
    builder.row(KeyboardButton(text="🆓 Пробный"), KeyboardButton(text="🤝 Партнёрский"))
    builder.row(KeyboardButton(text="◀ Назад"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def promo_trial_tariff_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⭐ Старт"), KeyboardButton(text="🔥 Про"), KeyboardButton(text="♾ Безлимит"))
    builder.row(KeyboardButton(text="◀ Назад"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def promo_yes_no_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="✅ Да"), KeyboardButton(text="🚫 Нет"))
    builder.row(KeyboardButton(text="◀ Назад"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def promo_target_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="👥 Все"), KeyboardButton(text="⭐ Старт"), KeyboardButton(text="🔥 Про"))
    builder.row(KeyboardButton(text="♾ Безлимит"), KeyboardButton(text="📦 Пакеты"))
    builder.row(KeyboardButton(text="◀ Назад"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def promo_confirm_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="✅ Создать"))
    builder.row(KeyboardButton(text="◀ Назад"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# ──────────────────────────────────────────────────────────────────────────

def main_reply_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="👗 Примерить вещь"),
        KeyboardButton(text="🧥 Примерить образ"),
    )
    builder.row(
        KeyboardButton(text="👤 Профиль"),
        KeyboardButton(text="👜 Шкаф"),
    )
    builder.row(
        KeyboardButton(text="📋 Тарифы"),
        KeyboardButton(text="👥 Пригласить друга"),
    )
    builder.row(
        KeyboardButton(text="❓ Помощь"),
    )
    return builder.as_markup(resize_keyboard=True)
