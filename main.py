import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN
from database.db import init_db
from services.queue import start_worker
from middlewares.throttling import ThrottlingMiddleware
from middlewares.block_check import BlockCheckMiddleware

from handlers import start, tryon, profile, wardrobe, tariffs, referral, promo, admin, support

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in .env")

    # Init DB
    await init_db()
    logger.info("Database initialized")

    # Start generation worker
    await start_worker()
    logger.info("Generation worker started")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Block-check runs first (before throttling) to short-circuit banned users
    dp.message.middleware(BlockCheckMiddleware())
    dp.callback_query.middleware(BlockCheckMiddleware())

    # Throttling middleware
    dp.message.middleware(ThrottlingMiddleware(rate=0.33))
    dp.callback_query.middleware(ThrottlingMiddleware(rate=0.33))

    # Register routers (order matters — admin/specific before generic)
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(tryon.router)
    dp.include_router(profile.router)
    dp.include_router(wardrobe.router)
    dp.include_router(tariffs.router)
    dp.include_router(referral.router)
    dp.include_router(promo.router)
    dp.include_router(support.router)

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
