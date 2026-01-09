import httpx
import asyncio


async def _send_async(webhook_url: str, content: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                webhook_url,
                json={"content": content}
            )
    except Exception:
        # use print instead of logger to avoid infinite error loop
        print("[ ERROR ] Failed to send log to Discord webhook!")


def send(webhook_url: str, content: str) -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send_async(webhook_url, content))
        else:
            asyncio.run(_send_async(webhook_url, content))
    except RuntimeError:
        asyncio.run(_send_async(webhook_url, content))
