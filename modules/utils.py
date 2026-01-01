import os
import signal
import re as regexp
from datetime import datetime, timezone
from . import global_vars as gv
from .enums import (
    BuyingOptions,
    BuyingOption,
    ShippingType,
    ShippingOption,
    Emojis,
    Deal,
    DealTuple,
    DealRanges
)


def matches_pattern(text: str, pattern: str, regex_prefix: str = 'regexp::') -> bool:
    text_lower = text.lower()

    if pattern.startswith(regex_prefix):
        length = len(regex_prefix)
        regex_pattern = pattern[length:]
        try:
            return bool(regexp.search(regex_pattern, text_lower, regexp.IGNORECASE))
        except regexp.error:
            return regex_pattern.lower() in text_lower
    else:
        return pattern.lower() in text_lower


def is_globally_blocked(content: str, extra1: str = "", extra2: str = "") -> bool:
    if not gv.config.global_blocklist:
        return False

    content_to_check = f"{content} {extra1} {extra2}".lower().strip()

    for blocked_pattern in gv.config.global_blocklist:
        if matches_pattern(content_to_check, blocked_pattern):
            return True

    return False


def matches_blocklist_override(
    content: str,
    extra1: str = "",
    extra2: str = "",
    override_patterns: list[str] | None = None
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
    return f"<t:{str(timestamp)}:{suffix}>"


def get_listing_type_display(buying_options: BuyingOptions) -> str:
    if not buying_options:
        return "Unknown"

    labels = []

    if BuyingOption.AUCTION in buying_options:
        labels.append("Auction")

    if BuyingOption.FIXED_PRICE in buying_options:
        text = "Buy It Now"

        if BuyingOption.BEST_OFFER in buying_options:
            text += f" ({Emojis.OBO} or Best Offer)"

        labels.append(text)

    if not labels:
        return "Unknown"

    result = ", ".join(labels)

    return result


def iso_to_unix_timestamp(iso_string: str) -> int:
    datetime_obj = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    unix_timestamp = int(datetime_obj.replace(tzinfo=timezone.utc).timestamp())

    return unix_timestamp


def generate_shipping_string(shipping: ShippingOption) -> str:
    shipping_string = "Internal Error"

    if shipping.type == ShippingType.CALCULATED:
        shipping_string = "Calculated at Checkout"
    elif shipping.type == ShippingType.FIXED:
        if shipping.cost.value is not None and shipping.cost.value > 0:
            shipping_string = format_price(shipping.cost.value) + " " + (shipping.cost.currency or "USD")
        else:
            shipping_string = "Free Shipping"
    elif shipping.type == ShippingType.UNKNOWN:
        shipping_string = "Unknown Shipping Type"

    return shipping_string


def build_shipping_embed_value(shipping: ShippingOption | None) -> str:
    if not shipping:
        return "Shipping info not available"

    shipping_cost = generate_shipping_string(shipping)
    arrival_info = ""

    if shipping.min_estimated_delivery_date and shipping.max_estimated_delivery_date:
        # min_ts = create_discord_timestamp((shipping.min_estimated_delivery_date or 0), suffix='D')
        # max_ts = create_discord_timestamp((shipping.max_estimated_delivery_date or 0), suffix='D')
        min_ts = create_discord_timestamp((shipping.min_estimated_delivery_date or 0), suffix='d')
        max_ts = create_discord_timestamp((shipping.max_estimated_delivery_date or 0), suffix='d')
        # arrival_info = f"\nArrival Date: {min_ts} to {max_ts}"
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
        # note: this URL supports the param ?sellerName=... to add a message that says:
        # "💡Tip: Try searching for "{sellerName}" on eBay."
        # however with how this function works, username would be None here, so we can't add that param
        return "https://www.powerpcfan.xyz/ebay-listing-scraper-discord-pings-internal/error-retrieving-seller-url"

    return f"https://www.ebay.com/sch/i.html?_ssn={username}"


def evaluate_deal(
    price: float | None,
    min_price: float | None,
    max_price: float | None,
    deal_ranges: DealRanges | None = None
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
    elif price <= min_price + 2 * quarter:
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
