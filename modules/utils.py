import os
import re as regexp
import signal
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from . import global_vars as gv
from .enums import (
    BuyingOption,
    BuyingOptions,
    Deal,
    DealRanges,
    DealTuple,
    ShippingOption,
    ShippingType,
)
from .logger import logger

if TYPE_CHECKING:
    from .bot import EbayScraperBot
    from .logger import CustomLogger


def matches_pattern(text: str, pattern: str, regex_prefix: str = "regexp::") -> bool:
    text_lower = text.lower()

    if pattern.startswith(regex_prefix):
        length = len(regex_prefix)
        regex_pattern = pattern[length:]
        try:
            # return bool(regexp.search(regex_pattern, text_lower, regexp.IGNORECASE))
            matches = regexp.findall(
                pattern=regex_pattern,
                string=text_lower,
                flags=regexp.IGNORECASE,
            )
            return bool(matches)
        except regexp.error:
            return regex_pattern.lower() in text_lower
    else:
        return pattern.lower() in text_lower


def is_within_sleep_hours() -> bool:
    if not gv.config.sleep_hours:
        return False

    try:
        start_str = gv.config.sleep_hours.start
        end_str = gv.config.sleep_hours.end

        start_dt = datetime.fromisoformat(f"1970-01-01T{start_str}")
        end_dt = datetime.fromisoformat(f"1970-01-01T{end_str}")

        now_utc = datetime.now(UTC)
        now_in_sleep_tz = now_utc.astimezone(start_dt.tzinfo)

        current_time = now_in_sleep_tz.timetz()
        start_time = start_dt.timetz()
        end_time = end_dt.timetz()

        if start_time <= end_time:
            return start_time <= current_time <= end_time
        else:  # noqa: RET505
            return current_time >= start_time or current_time <= end_time
    except (ValueError, TypeError):
        logger.exception("Invalid sleep_hours format. Expected HH:MM+/-HH:MM (e.g., '23:00-05:00')")
        return True


def is_globally_blocked(content: str, extra1: str = "", extra2: str = "") -> bool:
    if not gv.global_blocklist.items:
        return False

    content_to_check = f"{content} {extra1} {extra2}".lower().strip()

    for blocked_pattern in gv.global_blocklist.items:
        if matches_pattern(content_to_check, blocked_pattern):
            return True

    return False


def matches_blocklist_override(
    content: str,
    extra1: str = "",
    extra2: str = "",
    override_patterns: list[str] | None = None,
) -> bool:
    if not override_patterns:
        return False

    content_to_check = f"{content} {extra1} {extra2}".lower().strip()

    for override_pattern in override_patterns:
        if matches_pattern(content_to_check, override_pattern):
            return True

    return False


def is_seller_blocked(seller_username: str | None) -> bool:
    if not gv.config.seller_blocklist or not seller_username:
        return False

    seller_lower = seller_username.lower()

    for blocked_seller in gv.config.seller_blocklist:
        if matches_pattern(seller_lower, blocked_seller):
            return True

    return False


def create_discord_timestamp(timestamp: str | int, suffix: str = "f") -> str:
    return f"<t:{timestamp!s}:{suffix}>"


def get_listing_type_display(buying_options: BuyingOptions) -> str:
    if not buying_options:
        return "Unknown"

    labels = []

    if BuyingOption.AUCTION in buying_options:
        labels.append("Auction")

    if BuyingOption.FIXED_PRICE in buying_options:
        text = "**Buy It Now**"

        # if BuyingOption.BEST_OFFER in buying_options:
        #     text += f" ({Emojis.OBO} or Best Offer)"

        labels.append(text)

    if not labels:
        return "Unknown"

    return ", ".join(labels)


def iso_to_unix_timestamp(iso_string: str) -> int:
    return int(datetime.fromisoformat(iso_string).replace(tzinfo=UTC).timestamp())


def generate_shipping_string(shipping: ShippingOption) -> str:
    shipping_string = "Internal Error"

    if shipping.type == ShippingType.CALCULATED:
        shipping_string = "*Calculated at Checkout*"
    elif shipping.type == ShippingType.FIXED:
        if shipping.cost.value is not None and shipping.cost.value > 0:
            fp = format_price(price=shipping.cost.value, currency=shipping.cost.currency)
            if fp == "Price unavailable":
                shipping_string = "*Shipping cost unavailable*"
            else:
                shipping_string = f"**{fp}**"
        else:
            shipping_string = "**Free Shipping**"
    elif shipping.type == ShippingType.UNKNOWN:
        shipping_string = "*Unknown Shipping Type*"

    return shipping_string


def build_shipping_embed_value(shipping: ShippingOption | None) -> str:
    if not shipping:
        return "*Shipping info not available*"

    shipping_cost = generate_shipping_string(shipping)
    arrival_info = ""

    if shipping.min_estimated_delivery_date and shipping.max_estimated_delivery_date:
        # min_ts = create_discord_timestamp((shipping.min_estimated_delivery_date or 0), suffix="d")
        max_ts = create_discord_timestamp((shipping.max_estimated_delivery_date or 0), suffix="d")
        arrival_info = f"\nArrives by {max_ts}"

    return shipping_cost + arrival_info


def format_price(price: float | None, currency: str | None = None) -> str:
    if not price:
        return "Price unavailable"

    str_price = f"${price:,.2f}"  # Format with commas and 2 decimal places

    if currency:
        str_price += f" {currency}"

    return str_price


def get_ebay_seller_url(username: str | None) -> str:
    if not username:
        return "https://www.powerpcfan.xyz/ebay-listing-scraper-discord-pings-internal/error-retrieving-seller-url"

    return f"https://www.ebay.com/sch/i.html?_ssn={username}"


def evaluate_deal(  # noqa: PLR0911
    price: float | None,
    min_price: float | None,
    max_price: float | None,
    deal_ranges: DealRanges | None = None,
) -> DealTuple:
    if price is None:
        return Deal.UNKNOWN_DEAL

    if deal_ranges is not None:
        return deal_ranges.get_deal_type(price)

    # fall back to old logic if deal ranges arent provided
    if min_price is None or max_price is None:
        return Deal.UNKNOWN_DEAL

    if price < min_price or price > max_price:
        return Deal.UNKNOWN_DEAL

    # Divide the price range into segments for each deal level:
    #   Fire Deal - first quarter
    #   Great Deal - second quarter
    #   Good Deal - third quarter
    #   Ok Deal - fourth quarter
    # with the lowest quarter being the first 25% and highest quarter being the last 25%.

    range_span = max_price - min_price
    quarter = range_span / 4

    if price <= min_price + quarter:
        # price is in the first quarter
        return Deal.FIRE_DEAL
    elif price <= min_price + 2 * quarter:  # noqa: RET505
        # price is in the second quarter
        return Deal.GREAT_DEAL
    elif price <= min_price + 3 * quarter:
        # price is in the third quarter
        return Deal.GOOD_DEAL
    elif price <= min_price + 4 * quarter:
        # price is in the fourth quarter
        return Deal.OK_DEAL
    else:
        return Deal.UNKNOWN_DEAL


def sigint_current_process() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def restart_current_process() -> None:
    os.execv(sys.executable, [sys.executable, *sys.argv])  # noqa: S606


def restart_current_process_2() -> None:
    subprocess.Popen([sys.executable, *sys.argv])  # noqa: S603
    sys.exit(0)


async def change_status(
    bot: "EbayScraperBot",
    logger: "CustomLogger | None",
    message: str,
    emoji: str | None = None,
) -> None:
    try:
        status_message = f"{emoji} {message}" if emoji else message

        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.custom,
                name="Custom Status",
                state=status_message,
            ),
        )

        if logger:
            logger.debug(f"Changed Discord presence to '{status_message}'")
    except Exception:
        if logger:
            logger.exception("Failed to change Discord presence:")


def determine_risk(
    feedback_score: float | None,
    positive_feedback: float | None,
    title: str,  # noqa: ARG001
) -> tuple[bool, str | None]:
    """
    Determines the risk level of a listing based on seller attributes.

    Returns a `tuple[bool, str | None]` where the `bool` indicates if the listing is high risk, and the `str` is an optional message describing the flag reason.
    """  # noqa: E501

    if feedback_score is None and positive_feedback is None:
        return (
            True,
            (
                "The seller has no feedback, which could indicate a "
                "new account or lack of sale history."
            ),
        )

    feedback_threshold = 90.0
    feedback_score_threshold = 40

    if not positive_feedback or positive_feedback < feedback_threshold:
        positive_feedback = positive_feedback or 0.0
        return (
            True,
            f"The seller has a low positive feedback percentage of {positive_feedback:.2f}%.",
        )

    if not feedback_score or feedback_score < feedback_score_threshold:
        feedback_score = feedback_score or 0.0
        return (True, f"The seller has a low feedback score of {feedback_score:.0f}.")

    # risky_keywords: list[str] = []

    # for keyword in risky_keywords:
    #     if keyword.lower() in title.lower():
    #         return (True, f"The listing title contains the keyword '{keyword}'.")

    return (False, None)
