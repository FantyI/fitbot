import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate: float = 0.33):  # max 3 req/sec → min 0.33s between requests
        self.rate = rate
        self._last_call: dict[int, float] = defaultdict(float)
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        uid = user.id
        async with self._locks[uid]:
            now = asyncio.get_event_loop().time()
            delta = now - self._last_call[uid]
            if delta < self.rate:
                await asyncio.sleep(self.rate - delta)
            self._last_call[uid] = asyncio.get_event_loop().time()

        return await handler(event, data)
