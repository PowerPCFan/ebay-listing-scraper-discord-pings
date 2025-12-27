import requests
import time
from .utils import create_discord_timestamp, format_price, get_listing_type_display, build_shipping_embed_value
from .logger import logger
from .global_vars import config
from .config_tools import PingConfig
from .ebay_api import EbayItem
from .enums import Emojis


def print_new_listing(item: EbayItem, ping_config: PingConfig) -> None:
    logger.debug(f"Sending Discord notification for {ping_config.category_name}")

    send_webhook(
        webhook_url=ping_config.webhook,
        content=f"<@&{ping_config.role}>" if ping_config.role else "",
        username="eBay Listing Scraper Alerts",
        embed=create_listing_embed(item),
        raise_exception_instead_of_print=config.debug_mode,
    )


def create_listing_embed(
    item: EbayItem
) -> dict:
    shipping = item.shipping[0] if item.shipping else None
    feedback_score = item.seller.feedback_score if item.seller.feedback_score is not None else 'Unknown'
    condition = item.condition.name if (item.condition is not None and item.condition.name is not None) else "Unknown"

    embed = {
        "title": item.title,
        "url": item.url,
        "color": 0x0064D3,
        "fields": [
            {
                "name": f"{Emojis.SELLER} Seller:",
                "value": (
                    f"- Username: [{item.seller.username}](https://www.ebay.com/usr/{item.seller.username})\n"
                    f"- **{feedback_score}** feedback score\n"
                    f"- **{item.seller.feedback_percentage}%** positive feedback"
                ),
                "inline": False,
            },
            {
                "name": f"{Emojis.PRICE} Price:",
                "value": format_price(item.price.value),
                "inline": False
            },
            {
                "name": f"{Emojis.SHIPPING} Shipping:",
                "value": build_shipping_embed_value(shipping),
                "inline": False
            },
            {
                "name": f"{Emojis.CALENDAR} Date Posted:",
                "value": create_discord_timestamp(item.date_posted),
                "inline": False
            },
            {
                "name": f"{Emojis.CONDITION} Condition:",
                "value": condition,
                "inline": False
            },
            {
                "name": f"{Emojis.LISTING_TYPE} Listing Type(s):",
                "value": get_listing_type_display(item.buying_options),
                "inline": False
            }
        ],
        "footer": {
            "text": f"eBay Item ID: {item.item_id}",
            "icon_url": "https://i.ibb.co/Cs9ZFL2C/Untitled-drawing-1.png",
        }
    }

    if item.thumbnail:
        embed["image"] = {"url": item.thumbnail}

    return embed


def send_webhook(
    webhook_url: str,
    content: str | None,
    embed: dict | None,
    username: str | None,
    raise_exception_instead_of_print: bool = False,
) -> None:
    json_data = {
        "content": content if content is not None else "",
        "embeds": [embed] if embed is not None else [],
        "username": username if username is not None else "",
    }

    logger.debug(f"Sending Discord webhook to {webhook_url[:30]} (truncated)...")

    try:
        response = requests.post(webhook_url, json=json_data, timeout=10)

        if response.status_code == 429:
            default_retry = 2

            logger.warning("Rate limited by Discord, retrying...")

            try:
                retry_after = dict(response.json()).get(
                    "retry_after", response.headers.get("Retry-After", default_retry)
                )
                logger.debug(f"Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
                response = requests.post(webhook_url, json=json_data)
            except ValueError:
                time.sleep(default_retry)
                response = requests.post(webhook_url, json=json_data)

        if response.status_code not in [200, 204]:
            logger.error(
                f"Webhook failed with status {response.status_code}: {response.text}"
            )
        else:
            logger.debug("Discord webhook sent successfully")
    except requests.exceptions.RequestException as e:
        msg = "Error sending webhook:"

        if raise_exception_instead_of_print:
            raise Exception(msg + f" {e}")
        else:
            logger.exception(msg)
