import asyncio
from . import ebay_api
from . import global_vars
from .config_tools import PingConfig
from .global_vars import config
from .utils import (
    matches_pattern,
    is_globally_blocked,
    matches_blocklist_override,
    is_seller_blocked,
    evaluate_deal
)
from .logger import logger
from .discord import print_new_listing
from .seen_items import seen_db
from .enums import BuyingOption, Match, DealRanges


exception_count = 0
exceptions: list[str] = []


async def match() -> None:
    logger.info("Starting to monitor for new eBay listings...")

    while True:
        try:
            all_categories = set()
            ping_to_categories = {}

            for index, ping_config in enumerate(config.pings):
                ping_to_categories[index] = ping_config.categories
                all_categories.update(ping_config.categories)

            category_cache = {}

            tasks = []
            for category_id in all_categories:
                logger.debug(f"Fetching listings for category: {category_id}")
                task = ebay_api.search_single_category(category_id)
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            for category_id, items in zip(all_categories, results):
                category_cache[category_id] = items
                logger.debug(f"Cached {len(items)} items for category {category_id}")

            logger.debug(
                f"Fetched {len(all_categories)} unique categories for {len(config.pings)} pings"
            )

            for i, ping_config in enumerate(config.pings):
                combined_items = {}

                for category_id in ping_to_categories[i]:
                    for item_data in category_cache.get(category_id, []):
                        item_data: dict
                        item_id = item_data.get('itemId', '')
                        if item_id and item_id not in combined_items:
                            combined_items[item_id] = item_data

                items_list = list(combined_items.values())
                logger.debug(f"Processing {len(items_list)} items for {ping_config.category_name}")

                new_matches = 0
                for item_data in items_list:
                    item = ebay_api.EbayItem(item_data)

                    if seen_db.is_seen(item.item_id):
                        continue

                    matches, min_price, max_price, deal_ranges = matches_ping_criteria(item, ping_config)
                    if matches:
                        logger.info(f"New matching listing: {item.title[:25]}... - ${item.price.value}")
                        await print_new_listing(item, ping_config, evaluate_deal(
                            item.price.value,
                            min_price,
                            max_price,
                            deal_ranges
                        ))
                        seen_db.mark_seen(item.item_id, ping_config.category_name, item.title)
                        new_matches += 1
                        await asyncio.sleep(1)
                    else:
                        seen_db.mark_seen(item.item_id, ping_config.category_name, item.title)

                if new_matches > 0:
                    logger.info(
                        f"Found {new_matches} new matching listings for {ping_config.category_name}"
                    )
                else:
                    logger.debug(f"No new matches for {ping_config.category_name}")

            logger.debug("Polling interval complete.")
            logger.debug(f"API calls made: {global_vars.api_call_count}")
            global_vars.api_call_count = 0  # reset for next interval
            logger.debug(f"Waiting {config.poll_interval_seconds} seconds until next poll...")

            await asyncio.sleep(config.poll_interval_seconds)
        except Exception:
            global exception_count
            exception_count += 1

            if exception_count < 5:
                logger.exception("Error in loop. Retrying in 20 seconds...")
                await asyncio.sleep(20)
            else:
                logger.critical("Repeated errors in loop. Check configuration and eBay API status.")
                raise


def matches_ping_criteria(item: ebay_api.EbayItem, ping_config: PingConfig) -> Match:
    title_lower = item.title.lower()

    matches_keyword:       bool               = False  # noqa
    matched_keyword:       str | None         = None   # noqa
    matching_min_price:    float | None       = None   # noqa
    matching_max_price:    float | None       = None   # noqa
    matching_deal_ranges:  DealRanges | None  = None   # noqa

    for keyword_data in ping_config.keywords:
        keyword = keyword_data.keyword
        min_price = keyword_data.min_price
        max_price = keyword_data.max_price
        deal_ranges = keyword_data.deal_ranges

        if matches_pattern(title_lower, keyword):
            try:
                if item.price.value:
                    price = item.price.value
                    if min_price and price < min_price:
                        logger.debug(f"Item rejected: price ${price} below min ${min_price} for keyword '{keyword}'")
                        continue
                    if max_price and price > max_price:
                        logger.debug(f"Item rejected: price ${price} above max ${max_price} for keyword '{keyword}'")
                        continue
            except (ValueError, TypeError):
                pass

            matches_keyword = True
            matched_keyword = keyword
            matching_min_price = min_price
            matching_max_price = max_price
            matching_deal_ranges = deal_ranges
            break

    if not matches_keyword:
        logger.debug(f"Item rejected: no keyword match for '{item.title[:30]}...'")
        return Match(is_match=False, min_price=None, max_price=None, deal_ranges=None)

    logger.debug(f"Item matched keyword '{matched_keyword}': {item.title[:30]}...")

    for exclude_keyword in ping_config.exclude_keywords:
        if matches_pattern(title_lower, exclude_keyword):
            return Match(is_match=False, min_price=None, max_price=None, deal_ranges=None)

    if is_globally_blocked(title_lower, "", ""):
        if not matches_blocklist_override(title_lower, "", "", ping_config.blocklist_override):
            return Match(is_match=False, min_price=None, max_price=None, deal_ranges=None)

    if is_seller_blocked(item.seller.username):
        logger.debug(f"Item rejected: seller '{item.seller.username}' is blocklisted")
        return Match(is_match=False, min_price=None, max_price=None, deal_ranges=None)

    if BuyingOption.FIXED_PRICE not in item.buying_options:
        return Match(is_match=False, min_price=None, max_price=None, deal_ranges=None)

    return Match(
        is_match=True,
        min_price=matching_min_price,
        max_price=matching_max_price,
        deal_ranges=matching_deal_ranges
    )
