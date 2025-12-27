import requests
import threading


def _send(webhook_url: str, content: str) -> None:
    try:
        requests.post(
            webhook_url,
            json={"content": content},
            timeout=10
        )
    except Exception:
        # use print instead of logger to avoid infinite error loop
        print("[ ERROR ] Failed to send log to Discord webhook!")


def send(webhook_url: str, content: str) -> None:
    threading.Thread(target=_send, args=(webhook_url, content), daemon=True).start()
