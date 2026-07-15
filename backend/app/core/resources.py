import inspect


async def close_async_resource(resource: object) -> None:
    close = getattr(resource, "aclose", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result
