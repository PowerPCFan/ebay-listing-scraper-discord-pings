import asyncio
import time
from . import ebay_api
from . import global_vars as gv
from .config_tools import PingConfig
from .utils import (
    matches_pattern,
    is_globally_blocked,
    matches_blocklist_override,
    is_seller_blocked,
    evaluate_deal,
    change_status,
    is_within_sleep_hours
)
from .logger import logger
from .seen_items import seen_db
from .enums import BuyingOption, Match, DealRanges
from datetime import datetime
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .bot import EbayScraperBot


exception_count = 0
exceptions: list[str] = []


async def match(bot: "EbayScraperBot") -> None:
    logger.info("Starting to monitor for new eBay listings...")

    while True:
        try:
            if is_within_sleep_hours():
                logger.debug("Currently within sleep hours - skipping scrape cycle...")

                if gv.config.sleep_hours:
                    end = datetime.fromisoformat(f"1970-01-01T{gv.config.sleep_hours.end}").strftime("%H:%M %Z")
                else:
                    end = None

                await change_status(bot=bot, logger=logger, message=f"Sleeping until {end}...", emoji="😴")
            else:
                await match_single_cycle(bot)

                logger.info("Polling interval complete.")
                logger.debug(f"API calls made: {gv.api_call_count}")
                gv.api_call_count = 0  # reset for next interval

                gv.last_scrape_time = time.time()

            if gv.scraper_paused:
                logger.info("Scraper is paused. Waiting for resume command...")
                await change_status(bot=bot, logger=logger, emoji="⏸️", message="Scraper paused, waiting for /resume...")  # noqa: E501
                while gv.scraper_paused:
                    await asyncio.sleep(1)
                logger.info("Scraper resumed!")
                await change_status(bot=bot, logger=logger, emoji="▶️", message="Scraper resumed, waiting for next action")  # noqa: E501

            logger.info(f"Waiting {gv.config.poll_interval_seconds} seconds until next poll...")

            if not is_within_sleep_hours():
                await change_status(bot=bot, logger=logger, message="Waiting for next scrape interval...")

            await asyncio.sleep(gv.config.poll_interval_seconds)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Exiting...")
            gv.scraper_was_running = False
            raise
        except Exception as e:
            global exception_count, exceptions

            exception_count += 1

            stack_trace = e.__repr__()
            logger.exception(f"Exception #{exception_count} occurred in main loop")

            if stack_trace not in exceptions:
                exceptions.append(stack_trace)
                logger.error(f"New Exception: {stack_trace}")

            await asyncio.sleep(10)


async def match_single_cycle(bot: "EbayScraperBot") -> None:
    await change_status(bot=bot, logger=logger, message="Scraping eBay...")

    all_categories = set()
    ping_to_categories = {}

    for index, ping_config in enumerate(gv.config.pings):
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
        f"Fetched {len(all_categories)} unique categories for {len(gv.config.pings)} pings"
    )

    logger.info(f"Fetched {sum(len(items) for items in results)} items from all categories")

    for i, ping_config in enumerate(gv.config.pings):
        combined_items = {}
        logger.debug(f"Processing ping config #{i} ({ping_config.category_name}), which has {len(ping_to_categories[i])} categories")  # noqa: E501

        for category_id in ping_to_categories[i]:
            category_items = category_cache.get(category_id, [])

            logger.debug(f"Category {category_id} has {len(category_items)} items")

            for item_data in category_items:
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

            matched = matches_ping_criteria(item, ping_config)

            if matched.is_match:
                logger.info(f"New matching listing: {item.title}... - ${item.price.value}")

                price = _get_item_price(item, include_shipping=gv.config.include_shipping_in_deal_evaluation)

                deal = evaluate_deal(
                    price=price,
                    min_price=matched.min_price,
                    max_price=matched.max_price,
                    deal_ranges=matched.deal_ranges
                )

                await bot.send_listing_notification(item=item, ping_config=ping_config, deal=deal, match_object=matched)

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

    logger.debug(f"Finished processing {len(gv.config.pings)} ping configs")


def _get_item_price(item: ebay_api.EbayItem, include_shipping: bool = False) -> float:
    base_price = item.price.value or 0.0

    if not include_shipping:
        return base_price

    shipping_cost = 0.0

    if len(item.shipping) > 0 and item.shipping[0].cost.value is not None:
        shipping_cost = item.shipping[0].cost.value

    return base_price + shipping_cost


def matches_ping_criteria(item: ebay_api.EbayItem, ping_config: PingConfig) -> Match:
    title_lower = item.title.lower()

    matches_keyword:        bool               = False  # noqa
    matched_keyword:        str | None         = None   # noqa
    matching_min_price:     float | None       = None   # noqa
    matching_max_price:     float | None       = None   # noqa
    matching_target_price:  float | None       = None   # noqa
    matching_friendly_name: str | None         = None   # noqa
    matching_deal_ranges:   DealRanges | None  = None   # noqa

    for keyword_data in ping_config.keywords:
        keyword = keyword_data.keyword
        min_price = keyword_data.min_price
        max_price = keyword_data.max_price
        target_price = keyword_data.target_price
        friendly_name = keyword_data.friendly_name
        deal_ranges = keyword_data.deal_ranges

        if matches_pattern(title_lower, keyword):
            try:
                if item.price.value:
                    price = _get_item_price(item, include_shipping=gv.config.include_shipping_in_price_filters)

                    if min_price and price < min_price:
                        logger.debug(f"Item rejected: price ${price} below min ${min_price} for keyword '{keyword}'")
                        continue

                    if max_price and price > max_price:
                        logger.debug(f"Item rejected: price ${price} above max ${max_price} for keyword '{keyword}'")
                        continue

                if item.condition.id:
                    if item.condition.id and item.condition.id in gv.config.condition_blocklist:
                        logger.debug(
                            f"Item rejected: condition ID '{item.condition.id}' ({item.condition.name}) is blocklisted"
                        )
                        continue
            except (ValueError, TypeError):
                pass

            matches_keyword = True
            matched_keyword = keyword
            matching_min_price = min_price
            matching_max_price = max_price
            matching_target_price = target_price
            matching_friendly_name = friendly_name
            matching_deal_ranges = deal_ranges
            break

    if not matches_keyword:
        logger.debug(f"Item rejected: no keyword match for '{item.title}...'")
        return Match(
            is_match=False,
            min_price=None,
            max_price=None,
            target_price=None,
            friendly_name=None,
            deal_ranges=None,
            regex=None
        )

    logger.debug(f"Item matched keyword '{matched_keyword}': {item.title}...")

    for exclude_keyword in ping_config.exclude_keywords:
        if matches_pattern(title_lower, exclude_keyword):
            return Match(
                is_match=False,
                min_price=None,
                max_price=None,
                target_price=None,
                friendly_name=None,
                deal_ranges=None,
                regex=None
            )

    if is_globally_blocked(title_lower, "", ""):
        if not matches_blocklist_override(title_lower, override_patterns=ping_config.blocklist_override):
            return Match(
                is_match=False,
                min_price=None,
                max_price=None,
                target_price=None,
                friendly_name=None,
                deal_ranges=None,
                regex=None
            )
    if is_seller_blocked(item.seller.username):
        logger.debug(f"Item rejected: seller '{item.seller.username}' is blocklisted")
        return Match(
            is_match=False,
            min_price=None,
            max_price=None,
            target_price=None,
            friendly_name=None,
            deal_ranges=None,
            regex=None
        )

    if BuyingOption.FIXED_PRICE not in item.buying_options:
        return Match(
            is_match=False,
            min_price=None,
            max_price=None,
            target_price=None,
            friendly_name=None,
            deal_ranges=None,
            regex=None
        )

    return Match(
        is_match=True,
        min_price=matching_min_price,
        max_price=matching_max_price,
        target_price=matching_target_price,
        friendly_name=matching_friendly_name,
        deal_ranges=matching_deal_ranges,
        regex=matched_keyword
    )
