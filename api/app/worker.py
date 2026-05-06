"""Arq worker entrypoint.

Tasks are registered in `app.services.jobs`; they are imported at module load
so the worker discovers them.
"""
from arq.connections import RedisSettings


async def startup(ctx: dict) -> None:
    pass


async def shutdown(ctx: dict) -> None:
    pass


class WorkerSettings:
    redis_settings = RedisSettings(host="redis", port=6379, database=0)
    functions: list = []
    on_startup = startup
    on_shutdown = shutdown
