import asyncio
from collections import defaultdict
from typing import Callable, Any

# Priority queue: unlimited users go first
_priority_queue: asyncio.Queue = asyncio.Queue()
_normal_queue: asyncio.Queue = asyncio.Queue()

# Track active jobs per user
_user_active: dict[int, int] = defaultdict(int)
MAX_PER_USER = 2

NUM_WORKERS = 5  # concurrent generation jobs
_worker_tasks: list[asyncio.Task] = []


async def enqueue(user_id: int, priority: bool, job: Callable, *args, **kwargs) -> asyncio.Future:
    """Enqueue a generation job. Returns a future with the result."""
    if _user_active[user_id] >= MAX_PER_USER:
        raise TooManyJobsError("У тебя уже 2 генерации в очереди. Подожди немного.")

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    item = (user_id, future, job, args, kwargs)
    _user_active[user_id] += 1

    if priority:
        await _priority_queue.put(item)
    else:
        await _normal_queue.put(item)

    return future


async def _worker():
    while True:
        # Priority first
        try:
            item = _priority_queue.get_nowait()
        except asyncio.QueueEmpty:
            try:
                item = _normal_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
                continue

        user_id, future, job, args, kwargs = item
        try:
            result = await job(*args, **kwargs)
            if not future.done():
                future.set_result(result)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
        finally:
            _user_active[user_id] = max(0, _user_active[user_id] - 1)


async def start_worker():
    global _worker_tasks
    _worker_tasks = [asyncio.create_task(_worker()) for _ in range(NUM_WORKERS)]


class TooManyJobsError(Exception):
    pass
