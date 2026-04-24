from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from database import models


class BlockCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        db_user = await models.get_user(user.id)
        if db_user and db_user["is_blocked"]:
            if isinstance(event, CallbackQuery):
                await event.answer("❌ Ваш доступ ограничен", show_alert=True)
            elif isinstance(event, Message):
                try:
                    await event.answer("❌ Ваш доступ к боту ограничен.")
                except Exception:
                    pass
            return None

        return await handler(event, data)
