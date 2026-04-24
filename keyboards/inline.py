from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👗 Примерить вещь", callback_data="tryon_single"),
        InlineKeyboardButton(text="🧥 Примерить образ", callback_data="tryon_outfit"),
    )
    builder.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="👜 Шкаф", callback_data="wardrobe"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Тарифы", callback_data="tariffs"),
        InlineKeyboardButton(text="👥 Пригласить друга", callback_data="referral"),
    )
    builder.row(
        InlineKeyboardButton(text="❓ Помощь", callback_data="support"),
    )
    return builder.as_markup()


def start_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👗 Попробовать примерку", callback_data="tryon_single"),
        InlineKeyboardButton(text="📋 Тарифы", callback_data="tariffs"),
    )
    return builder.as_markup()


def tryon_result_kb(tariff: str, session_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    pro_plus = tariff in ("pro", "unlimited")
    if pro_plus:
        builder.row(
            InlineKeyboardButton(text="💡 Совет по стилю", callback_data=f"style_advice:{session_id}"),
            InlineKeyboardButton(text="🔍 Найти похожее", callback_data=f"find_similar:{session_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="🌿 Другой сезон", callback_data=f"season_adapt:{session_id}"),
        )
    builder.row(
        InlineKeyboardButton(text="🔄 Примерить другую вещь", callback_data="tryon_single"),
    )
    return builder.as_markup()


def outfit_add_or_start_kb(item_count: int, max_items: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if item_count < max_items:
        builder.row(InlineKeyboardButton(text="➕ Добавить ещё вещь", callback_data="outfit_add_more"))
    if item_count >= 2:
        builder.row(InlineKeyboardButton(text="✅ Начать примерку", callback_data="outfit_start"))
    return builder.as_markup()


def season_kb(session_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for season, emoji in [("spring", "🌸 Весна"), ("summer", "☀️ Лето"),
                           ("autumn", "🍂 Осень"), ("winter", "❄️ Зима")]:
        builder.button(text=emoji, callback_data=f"season:{session_id}:{season}")
    builder.adjust(2)
    return builder.as_markup()


def profile_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📸 История примерок", callback_data="history:0"),
        InlineKeyboardButton(text="👥 Пригласить друга", callback_data="referral"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Сменить тариф", callback_data="tariffs"),
        InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="promo"),
    )
    return builder.as_markup()


def history_kb(page: int, total: int, per_page: int = 5, session_ids: list = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if session_ids:
        for sid in session_ids:
            builder.row(InlineKeyboardButton(text=f"🆚 Сравнить #{sid}", callback_data=f"compare_pick:{sid}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"history:{page-1}"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"history:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 В профиль", callback_data="profile"))
    return builder.as_markup()


def compare_second_kb(first_id: int, session_ids: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sid in session_ids:
        if sid != first_id:
            builder.row(InlineKeyboardButton(text=f"Образ #{sid}", callback_data=f"compare_do:{first_id}:{sid}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="history:0"))
    return builder.as_markup()


def tariffs_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⭐ Старт — 130 звёзд", callback_data="buy_tariff:start"))
    builder.row(InlineKeyboardButton(text="⭐ Про — 270 звёзд", callback_data="buy_tariff:pro"))
    builder.row(InlineKeyboardButton(text="⭐ Безлимит — 500 звёзд", callback_data="buy_tariff:unlimited"))
    builder.row(InlineKeyboardButton(text="── Разовые пакеты ──", callback_data="noop"))
    builder.row(
        InlineKeyboardButton(text="⭐ 5 примерок — 50⭐", callback_data="buy_pack:pack_5"),
        InlineKeyboardButton(text="⭐ 15 примерок — 120⭐", callback_data="buy_pack:pack_15"),
    )
    builder.row(
        InlineKeyboardButton(text="⭐ 1 образ (5+) — 35⭐", callback_data="buy_pack:pack_outfit"),
        InlineKeyboardButton(text="⭐ Шкаф на месяц — 70⭐", callback_data="buy_pack:pack_wardrobe"),
    )
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="menu"))
    return builder.as_markup()


def referral_kb(ref_link: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📤 Поделиться ссылкой",
                             url=f"https://t.me/share/url?url={ref_link}&text=Попробуй+виртуальную+примерку+одежды+в+FitBot!")
    )
    builder.row(InlineKeyboardButton(text="🔙 В профиль", callback_data="profile"))
    return builder.as_markup()


def wardrobe_kb(page: int, total: int, items: list, per_page: int = 5, tariff: str = "free") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(
            InlineKeyboardButton(text=f"🗑 {item['name']}", callback_data=f"wardrobe_del:{item['id']}"),
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"wardrobe_page:{page-1}"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"wardrobe_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text="➕ Добавить вещь", callback_data="wardrobe_add"),
        InlineKeyboardButton(text="👗 Выбрать для примерки", callback_data="wardrobe_select"),
    )
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="menu"))
    return builder.as_markup()


def admin_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promos"),
        InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_promo_create"),
    )
    builder.row(
        InlineKeyboardButton(text="📬 Ящик", callback_data="admin_inbox"),
    )
    return builder.as_markup()


def inbox_list_kb(tickets: list, page: int, total: int, per_page: int = 5) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in tickets:
        icon = "🐛" if t["type"] == "bug" else "💬"
        uname = f"@{t['username']}" if t["username"] else t["full_name"]
        preview = (t["message"] or "")[:30]
        if len(t["message"] or "") > 30:
            preview += "…"
        new_badge = "🆕 " if t["status"] == "new" else ""
        builder.row(InlineKeyboardButton(
            text=f"{new_badge}{icon} {uname}: {preview}",
            callback_data=f"inbox_view:{t['id']}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"inbox:{page - 1}"))
    total_pages = max(1, (total + per_page - 1) // per_page)
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"inbox:{page + 1}"))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
    return builder.as_markup()


def ticket_actions_kb(user_id: int, is_bug: bool, ticket_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row = [InlineKeyboardButton(text="📩 Ответить", callback_data=f"support_reply:{user_id}")]
    if is_bug:
        row.append(InlineKeyboardButton(text="🎟 Промокод", callback_data=f"support_promo:{user_id}"))
    builder.row(*row)
    builder.row(
        InlineKeyboardButton(text="✅ Закрыть", callback_data=f"inbox_close:{ticket_id}"),
        InlineKeyboardButton(text="🔙 В ящик", callback_data="admin_inbox"),
    )
    return builder.as_markup()


def promo_choice_kb(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Создать новый промокод", callback_data=f"promo_choice_new:{user_id}"))
    builder.row(InlineKeyboardButton(text="📋 Выбрать существующий", callback_data=f"promo_choice_existing:{user_id}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_main"))
    return builder.as_markup()


def existing_promos_for_user_kb(promos: list, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in promos[:10]:
        label = f"🎟 {p['code']} [{p['type']} +{p['value']}]"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"promo_send_existing:{p['id']}:{user_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"support_promo:{user_id}"))
    return builder.as_markup()


def admin_promos_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_promo_create"))
    builder.row(InlineKeyboardButton(text="📋 Список активных", callback_data="admin_promo_list"))
    builder.row(InlineKeyboardButton(text="🚫 Отключить промокод", callback_data="admin_promo_disable"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
    return builder.as_markup()


def admin_broadcast_target_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Все пользователи", callback_data="broadcast_all"))
    builder.row(InlineKeyboardButton(text="Только платные", callback_data="broadcast_paid"))
    builder.row(
        InlineKeyboardButton(text="Тариф Старт", callback_data="broadcast_tariff:start"),
        InlineKeyboardButton(text="Тариф Про", callback_data="broadcast_tariff:pro"),
        InlineKeyboardButton(text="Безлимит", callback_data="broadcast_tariff:unlimited"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_main"))
    return builder.as_markup()


def checkout_kb(has_promo: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Оплатить", callback_data="checkout_pay"))
    if not has_promo:
        builder.row(InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="checkout_enter_promo"))
    builder.row(InlineKeyboardButton(text="🔙 Назад к тарифам", callback_data="tariffs"))
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="menu"))
    return builder.as_markup()


def retry_tryon_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Повторить", callback_data="tryon_single"),
        InlineKeyboardButton(text="🔙 В меню", callback_data="menu"),
    )
    return builder.as_markup()


def sizes_skip_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="tryon_skip_sizes"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu"))
    return builder.as_markup()
