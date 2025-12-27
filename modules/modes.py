import time
from . import ebay_api
from . import global_vars
from .config_tools import PingConfig
from .global_vars import config
from .utils import matches_pattern, is_globally_blocked, matches_blocklist_override
from .logger import logger
from .discord import print_new_listing
from .seen_items import seen_db
from .enums import BuyingOption, Mode


exception_count = 0
exceptions: list[str] = []


def match() -> None:
    logger.info("Starting to monitor for new eBay listings...")

    while True:
        try:
            parse_mode_pings = [ping for ping in config.pings if ping.mode == Mode.PARSE]
            query_mode_pings = [ping for ping in config.pings if ping.mode == Mode.QUERY]

            if parse_mode_pings:
                all_categories = set()
                ping_to_categories = {}

                for index, ping_config in enumerate(parse_mode_pings):
                    ping_to_categories[index] = ping_config.categories
                    all_categories.update(ping_config.categories)

                category_cache = {}

                for category_id in all_categories:
                    logger.debug(f"Fetching listings for category: {category_id}")
                    items = ebay_api.search_single_category(category_id)
                    category_cache[category_id] = items
                    logger.debug(f"Cached {len(items)} items for category {category_id}")

                logger.debug(
                    f"Parse mode: fetched {len(all_categories)} unique categories for {len(parse_mode_pings)} pings"
                )

                for i, ping_config in enumerate(parse_mode_pings):
                    combined_items = {}

                    for category_id in ping_to_categories[i]:
                        for item_data in category_cache.get(category_id, []):
                            item_id = item_data.get('itemId', '')
                            if item_id and item_id not in combined_items:
                                combined_items[item_id] = item_data

                    items_list = list(combined_items.values())
                    logger.debug(f"Processing {len(items_list)} items for {ping_config.category_name} (parse mode)")

                    new_matches = 0
                    for item_data in items_list:
                        item = ebay_api.EbayItem(item_data)

                        if seen_db.is_seen(item.item_id):
                            continue

                        if matches_ping_criteria_parse(item, ping_config):
                            logger.info(f"New matching listing: {item.title[:25]}... - ${item.price.value}")
                            print_new_listing(item, ping_config)
                            seen_db.mark_seen(item.item_id, ping_config.category_name, item.title, Mode.PARSE.value)
                            new_matches += 1
                            time.sleep(1)
                        else:
                            seen_db.mark_seen(item.item_id, ping_config.category_name, item.title, Mode.PARSE.value)

                    if new_matches > 0:
                        logger.info(
                            f"Found {new_matches} new matching listings for {ping_config.category_name} (parse)"
                        )
                    else:
                        logger.debug(f"No new matches for {ping_config.category_name} (parse)")

            if query_mode_pings:
                for ping_config in query_mode_pings:
                    if ping_config.query and ping_config.query.query:
                        logger.debug(f"Searching query: {ping_config.query.query}")
                        items = ebay_api.search_query(
                            ping_config.query.query,
                            [str(c) for c in ping_config.categories],
                            ping_config.query.min_price,
                            ping_config.query.max_price
                        )

                        logger.debug(f"Query returned {len(items)} items for {ping_config.category_name}")
                        new_matches = 0
                        for item_data in items:
                            item = ebay_api.EbayItem(item_data)

                            if seen_db.is_seen(item.item_id):
                                continue

                            if matches_ping_criteria_query(item, ping_config):
                                logger.info(f"New matching listing: {item.title[:25]}... - ${item.price.value}")
                                print_new_listing(item, ping_config)
                                seen_db.mark_seen(item.item_id, ping_config.category_name, item.title, Mode.QUERY.value)
                                new_matches += 1
                                time.sleep(1)
                            else:
                                seen_db.mark_seen(item.item_id, ping_config.category_name, item.title, Mode.QUERY.value)

                        if new_matches > 0:
                            logger.info(
                                f"Found {new_matches} new matching listings for {ping_config.category_name} (query)"
                            )
                        else:
                            logger.debug(f"No new matches for {ping_config.category_name} (query)")

            logger.debug("Polling interval complete.")
            logger.debug(f"API calls made: {global_vars.api_call_count}")
            global_vars.api_call_count = 0  # reset for next interval
            logger.debug(f"Waiting {config.poll_interval_seconds} seconds until next poll...")
            time.sleep(config.poll_interval_seconds)
        except Exception:
            global exception_count
            exception_count += 1

            if exception_count < 5:
                logger.exception("Error in loop. Retrying in 20 seconds...")
                time.sleep(20)
            else:
                logger.critical("Repeated errors in loop. Check configuration and eBay API status.")
                raise


def matches_ping_criteria_parse(item: ebay_api.EbayItem, ping_config: PingConfig) -> bool:
    title_lower = item.title.lower()

    matches_keyword = False
    matched_keyword = None
    assert ping_config.keywords is not None

    for keyword_data in ping_config.keywords:
        keyword = keyword_data.keyword
        min_price = keyword_data.min_price
        max_price = keyword_data.max_price

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
            break

    if not matches_keyword:
        logger.debug(f"Item rejected: no keyword match for '{item.title[:30]}...'")
        return False

    logger.debug(f"Item matched keyword '{matched_keyword}': {item.title[:30]}...")

    for exclude_keyword in ping_config.exclude_keywords:
        if matches_pattern(title_lower, exclude_keyword):
            return False

    if is_globally_blocked(title_lower, "", ""):
        if not matches_blocklist_override(title_lower, "", "", ping_config.blocklist_override):
            return False

    if BuyingOption.FIXED_PRICE not in item.buying_options:
        return False

    return True


def matches_ping_criteria_query(item: ebay_api.EbayItem, ping_config: PingConfig) -> bool:
    title_lower = item.title.lower()

    for exclude_keyword in ping_config.exclude_keywords:
        if matches_pattern(title_lower, exclude_keyword):
            return False

    if is_globally_blocked(title_lower, "", ""):
        if not matches_blocklist_override(title_lower, "", "", ping_config.blocklist_override):
            return False

    if BuyingOption.FIXED_PRICE not in item.buying_options:
        return False

    return True
