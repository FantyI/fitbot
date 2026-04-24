from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database import models
from keyboards.inline import start_kb, main_menu_kb
from keyboards.reply import main_reply_kb
from services.anti_fraud import check_ref_fraud

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""

    # Parse referral
    args = message.text.split()
    ref_code = None
    if len(args) > 1 and args[1].startswith("REF_"):
        ref_code = args[1][4:]  # strip REF_ prefix

    user = await models.get_user(user_id)
    referrer = None
    is_new = not user

    if not user:
        referred_by = None
        if ref_code:
            referrer = await models.get_user_by_ref_code(ref_code)
            if referrer and referrer["id"] != user_id:
                # Anti-fraud check
                ok = await check_ref_fraud(ref_code, user_id, message.bot)
                if ok:
                    referred_by = referrer["id"]
                    await models.create_referral(referrer["id"], user_id)

        user = await models.create_user(user_id, username, full_name, referred_by)

        if referrer and referred_by:
            # Give referred user bonuses: +3 bonus tryons (total 5) + 20% discount flag
            await models.add_balance(user_id, 3, bonus=True, expire_days=14)
            await message.answer(
                f"👋 Привет, {full_name}!\n\n"
                f"Тебя пригласил <b>{referrer['full_name']}</b>.\n"
                f"Тебе начислено <b>5 бесплатных примерок</b> (действуют 14 дней) "
                f"и скидка <b>20%</b> на первую покупку. 🎁",
                reply_markup=main_reply_kb(),
                parse_mode="HTML"
            )
            await message.answer("👇 Выбери действие:", reply_markup=main_menu_kb())
            return

    if is_new:
        await message.answer(
            f"Привет, {full_name}! 👗\n\n"
            f"FitBot позволяет примерить любую вещь на твоё фото — без примерочной и без возвратов.\n\n"
            f"У тебя <b>2 бесплатные примерки</b>. Попробуй прямо сейчас!",
            reply_markup=main_reply_kb(),
            parse_mode="HTML"
        )
        await message.answer("👇 Выбери действие:", reply_markup=main_menu_kb())
    else:
        await message.answer(
            f"С возвращением, {full_name}! 👗",
            reply_markup=main_reply_kb(),
            parse_mode="HTML"
        )
        await message.answer("👇 Выбери действие:", reply_markup=main_menu_kb())


@router.message(Command("menu"))
@router.callback_query(F.data == "menu")
async def cmd_menu(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    text = "🏠 Главное меню"
    kb = main_menu_kb()
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.edit_text(text, reply_markup=kb)
    else:
        await event.answer(text, reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "❓ <b>Помощь</b>\n\n"
        "/tryon — примерить вещь\n"
        "/wardrobe — мой шкаф\n"
        "/profile — профиль и история\n"
        "/tariffs — тарифы\n"
        "/ref — пригласить друга\n"
        "/promo — ввести промокод\n\n"
        "Проблемы с генерацией? Напиши нам: @FitBotSupport",
        parse_mode="HTML"
    )


@router.message(F.text == "👗 Примерить вещь")
async def btn_tryon_single(message: Message, state: FSMContext):
    from handlers.tryon import start_tryon_single
    await start_tryon_single(message, state)


@router.message(F.text == "🧥 Примерить образ")
async def btn_tryon_outfit(message: Message, state: FSMContext):
    from handlers.tryon import TryonStates
    await state.clear()
    await state.set_state(TryonStates.outfit_waiting_user_photo)
    await message.answer("📸 Отправь своё фото")


@router.message(F.text == "👤 Профиль")
async def btn_profile(message: Message, state: FSMContext):
    from handlers.profile import show_profile
    await show_profile(message, state)


@router.message(F.text == "👜 Шкаф")
async def btn_wardrobe(message: Message, state: FSMContext):
    from handlers.wardrobe import show_wardrobe
    await show_wardrobe(message, state)


@router.message(F.text == "📋 Тарифы")
async def btn_tariffs(message: Message, state: FSMContext):
    from handlers.tariffs import show_tariffs
    await show_tariffs(message, state)


@router.message(F.text == "👥 Пригласить друга")
async def btn_referral(message: Message):
    from handlers.referral import show_referral
    await show_referral(message)


@router.message(F.text == "❓ Помощь")
async def btn_support(message: Message, state: FSMContext):
    from handlers.support import show_support
    await show_support(message, state)
