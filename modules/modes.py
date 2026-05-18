import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING

from . import ebay_api
from . import global_vars as gv
from .config_tools import ItemConfig, KeywordMode, PingConfig
from .enums import BuyingOption, DealRanges, Match
from .logger import logger
from .psu_utils import find_psu_in_tierlist
from .seen_items import seen_db
from .utils import (
    change_status,
    evaluate_deal,
    is_globally_blocked,
    is_seller_blocked,
    is_within_sleep_hours,
    matches_blocklist_override,
    matches_pattern,
)

if TYPE_CHECKING:
    from .bot import EbayScraperBot


exception_count = 0
exceptions: list[str] = []


async def match(bot: "EbayScraperBot") -> None:
    logger.info("Starting to monitor for new eBay listings...")

    while True:
        try:
            if is_within_sleep_hours():
                logger.info("Currently within sleep hours, skipping current interval.")

                if gv.config.sleep_hours:
                    # convert config time (can be in any timezone) to local time for display
                    end = datetime.fromisoformat(
                        f"1970-01-01T{gv.config.sleep_hours.end}",
                    ).astimezone().strftime("%I:%M %p (%Z)")
                else:
                    end = "<unknown time> (!!! config error !!!)"

                await change_status(
                    bot=bot,
                    logger=logger,
                    message=f"Sleeping until {end}...",
                    emoji="😴",
                )
            else:
                seen_db.clear_temp_seen()
                await match_single_cycle(bot)

                seen_db.commit_seen_items()

                logger.info("Polling interval complete.")
                logger.debug(f"API calls made: {gv.api_call_count}")
                gv.api_call_count = 0  # reset for next interval

                gv.last_scrape_time = time.time()

            if gv.scraper_paused:
                logger.info("Scraper is paused. Waiting for resume command...")
                await change_status(
                    bot=bot,
                    logger=logger,
                    emoji="⏸️",
                    message="Scraper paused, waiting for /resume...",
                )

                while gv.scraper_paused:  # noqa: ASYNC110
                    await asyncio.sleep(1)

                logger.info("Scraper resumed!")
                await change_status(
                    bot=bot,
                    logger=logger,
                    emoji="▶️",
                    message="Scraper resumed, waiting for next action",
                )

            logger.info(f"Waiting {gv.config.poll_interval_seconds} seconds until next poll...")

            if not is_within_sleep_hours():
                await change_status(
                    bot=bot,
                    logger=logger,
                    message="Waiting for next scrape interval...",
                )

            await asyncio.sleep(gv.config.poll_interval_seconds)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Exiting...")
            gv.scraper_was_running = False
            raise
        except Exception as e:
            global exception_count  # noqa: PLW0603

            exception_count += 1

            stack_trace = e.__repr__()
            logger.exception(f"Exception #{exception_count} occurred in main loop")

            if stack_trace not in exceptions:
                exceptions.append(stack_trace)
                logger.error(f"New Exception: {stack_trace}")

            await asyncio.sleep(10)


async def match_single_cycle(bot: "EbayScraperBot") -> None:  # noqa: C901, PLR0912, PLR0915
    await change_status(bot=bot, logger=logger, message="Scraping eBay...")

    all_poll_categories = set()
    ping_to_categories = {}
    ping_to_poll_items: dict[int, list[ItemConfig]] = {}
    ping_to_query_items: dict[int, list[ItemConfig]] = {}

    for index, ping_config in enumerate(gv.config.pings):
        ping_to_categories[index] = ping_config.categories
        poll_items = [
            item_config
            for item_config in ping_config.items
            if item_config.keyword.mode == KeywordMode.POLL
        ]
        query_items = [
            item_config
            for item_config in ping_config.items
            if item_config.keyword.mode == KeywordMode.QUERY
        ]
        ping_to_poll_items[index] = poll_items
        ping_to_query_items[index] = query_items

        if poll_items:
            all_poll_categories.update(ping_config.categories)

    category_cache = {}

    tasks = []
    for category_id in all_poll_categories:
        logger.debug(f"Fetching listings for category: {category_id}")
        task = ebay_api.search_single_category(category_id)
        tasks.append(task)

    results = await asyncio.gather(*tasks)

    for category_id, items in zip(all_poll_categories, results, strict=True):
        category_cache[category_id] = items
        logger.debug(f"Cached {len(items)} items for category {category_id}")

    logger.debug(
        f"Fetched {len(all_poll_categories)} poll categories for {len(gv.config.pings)} pings",
    )

    logger.info(f"Fetched {sum(len(items) for items in results)} items from all categories")

    for i, ping_config in enumerate(gv.config.pings):
        combined_items = {}
        logger.debug(
            f"Processing ping config #{i} ({ping_config.category_name}), "
            f"which has {len(ping_to_categories[i])} categories",
        )

        for category_id in ping_to_categories[i]:
            category_items = category_cache.get(category_id, [])

            logger.debug(f"Category {category_id} has {len(category_items)} items")

            for item_data in category_items:
                item_data: dict
                item_id = item_data.get("itemId", "")

                if item_id and item_id not in combined_items:
                    combined_items[item_id] = item_data

        poll_items_list = list(combined_items.values())
        logger.debug(f"Processing {len(poll_items_list)} poll items for {ping_config.category_name}")  # noqa: E501

        new_matches = 0
        for item_data in poll_items_list:
            item = ebay_api.EbayItem(item_data)

            if seen_db.is_seen(item.full_item_id):
                continue

            matched = matches_ping_criteria(
                item,
                ping_config,
                item_configs=ping_to_poll_items[i],
            )

            if matched.is_match:
                price = _get_item_price(
                    item,
                    include_shipping=gv.config.include_shipping_in_deal_evaluation,
                )

                deal = evaluate_deal(
                    price=price,
                    min_price=matched.min_price,
                    max_price=matched.max_price,
                    deal_ranges=matched.deal_ranges,
                )

                psu_matches = find_psu_in_tierlist(item.title) if ping_config.is_psu else None

                if matched.deal_ranges and deal in matched.deal_ranges.do_not_show:
                    logger.debug(
                        f"Item rejected: deal type '{deal.name}' is in the "
                        "item-level do_not_show list",
                    )
                    continue

                if ping_config.do_not_show and deal in ping_config.do_not_show:
                    logger.debug(
                        f"Item rejected: deal type '{deal.name}' is in the "
                        "category-level do_not_show list",
                    )
                    continue

                if item.country is not None and item.country != "US":
                    logger.debug(
                        f"Item rejected: item country '{item.country}' does not match 'US'",
                    )
                    seen_db.mark_seen(item.full_item_id, ping_config.category_name, item.title)
                    continue

                logger.info(
                    f"New matching listing: '{item.title}' - ${item.price.value:.2f} ({deal.name})",
                )

                await bot.send_listing_notification(
                    item=item,
                    ping_config=ping_config,
                    deal=deal,
                    match_object=matched,
                    psu=psu_matches,
                )

                seen_db.mark_seen(item.full_item_id, ping_config.category_name, item.title)
                new_matches += 1
                await asyncio.sleep(1)
            else:
                seen_db.mark_seen(item.full_item_id, ping_config.category_name, item.title)

        for item_config in ping_to_query_items[i]:
            query_text = item_config.keyword.query
            if not query_text:
                continue

            query_tasks = [
                ebay_api.search_query_in_category(
                    category_id=str(category_id),
                    query=query_text,
                )
                for category_id in ping_to_categories[i]
            ]
            query_results = await asyncio.gather(*query_tasks)

            query_items_by_id: dict[str, dict] = {}
            for result_chunk in query_results:
                for item_data in result_chunk:
                    full_item_id = str(item_data.get("itemId", "")).strip()
                    if full_item_id:
                        query_items_by_id[full_item_id] = item_data

            detail_items = list(query_items_by_id.values())
            logger.debug(
                "Fetched %s query items for query '%s' (%s)",
                len(detail_items),
                query_text,
                ping_config.category_name,
            )

            for item_data in detail_items:
                item = ebay_api.EbayItem(item_data)

                if seen_db.is_seen(item.full_item_id):
                    continue

                matched = matches_ping_criteria(
                    item,
                    ping_config,
                    item_configs=[item_config],
                )

                if not matched.is_match:
                    seen_db.mark_seen(item.full_item_id, ping_config.category_name, item.title)
                    continue

                price = _get_item_price(
                    item,
                    include_shipping=gv.config.include_shipping_in_deal_evaluation,
                )

                deal = evaluate_deal(
                    price=price,
                    min_price=matched.min_price,
                    max_price=matched.max_price,
                    deal_ranges=matched.deal_ranges,
                )

                psu_matches = find_psu_in_tierlist(item.title) if ping_config.is_psu else None

                if matched.deal_ranges and deal in matched.deal_ranges.do_not_show:
                    logger.debug(
                        f"Item rejected: deal type '{deal.name}' is in the "
                        "item-level do_not_show list",
                    )
                    continue

                if ping_config.do_not_show and deal in ping_config.do_not_show:
                    logger.debug(
                        f"Item rejected: deal type '{deal.name}' is in the "
                        "category-level do_not_show list",
                    )
                    continue

                if item.country is not None and item.country != "US":
                    logger.debug(
                        f"Item rejected: item country '{item.country}' does not match 'US'",
                    )
                    seen_db.mark_seen(item.full_item_id, ping_config.category_name, item.title)
                    continue

                logger.info(
                    f"New matching listing: '{item.title}' - ${item.price.value:.2f} ({deal.name})",
                )

                await bot.send_listing_notification(
                    item=item,
                    ping_config=ping_config,
                    deal=deal,
                    match_object=matched,
                    psu=psu_matches,
                )

                seen_db.mark_seen(item.full_item_id, ping_config.category_name, item.title)
                new_matches += 1
                await asyncio.sleep(1)

        if new_matches > 0:
            logger.info(
                f"Found {new_matches} new matching listings for {ping_config.category_name}",
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


def matches_ping_criteria(  # noqa: C901, PLR0912, PLR0915
    item: ebay_api.EbayItem,
    ping_config: PingConfig,
    item_configs: list[ItemConfig] | None = None,
) -> Match:
    title_lower = item.title.lower()

    matches_filter: bool = False
    matched_filter: str | None = None
    matching_min_price: float | None = None
    matching_max_price: float | None = None
    matching_target_price: float | None = None
    matching_friendly_name: str | None = None
    matching_deal_ranges: DealRanges | None = None
    matching_mode_and_query: tuple[KeywordMode, str | None] | None = None

    last_updated = ping_config.price_ranges_last_updated

    active_items = item_configs if item_configs is not None else ping_config.items

    for item_config in active_items:
        item_keyword = item_config.keyword
        filter_text = item_keyword.filter
        min_price = item_config.min_price
        max_price = item_config.max_price
        target_price = item_config.target_price
        friendly_name = item_config.friendly_name
        deal_ranges = item_config.deal_ranges
        mode_and_query = (item_keyword.mode, item_keyword.query)

        if filter_text and not matches_pattern(title_lower, filter_text):
            continue

        if filter_text or item_keyword.mode == KeywordMode.QUERY:
            try:
                if item.price.value:
                    price = _get_item_price(
                        item,
                        include_shipping=gv.config.include_shipping_in_price_filters,
                    )

                    if min_price and price < min_price:
                        logger.debug(
                            f"Item rejected: price ${price} below min ${min_price} "
                            f"for filter '{filter_text}'",
                        )
                        continue

                    if max_price and price > max_price:
                        logger.debug(
                            f"Item rejected: price ${price} above max ${max_price} "
                            f"for filter '{filter_text}'",
                        )
                        continue

                if (
                    item.condition.id
                    and item.condition.id
                    and item.condition.id in gv.config.condition_blocklist
                ):
                    logger.debug(
                        "Item rejected: condition ID "
                        f"'{item.condition.id}' ({item.condition.name}) is blocklisted",
                    )
                    continue
            except (ValueError, TypeError):
                pass

            matches_filter = True
            matched_filter = filter_text
            matching_min_price = min_price
            matching_max_price = max_price
            matching_target_price = target_price
            matching_friendly_name = friendly_name
            matching_deal_ranges = deal_ranges
            matching_mode_and_query = mode_and_query
            break

    if not matches_filter:
        logger.debug(f"Item rejected: no item filter match for '{item.title}...'")
        return Match(
            is_match=False,
            min_price=None,
            max_price=None,
            target_price=None,
            friendly_name=None,
            deal_ranges=None,
            regex=None,
            last_updated=last_updated,
            mode=matching_mode_and_query[0] if matching_mode_and_query else KeywordMode.POLL,
            query=matching_mode_and_query[1] if matching_mode_and_query and matching_mode_and_query[1] else None,  # noqa: E501
        )

    logger.debug(f"Item matched filter '{matched_filter}': {item.title}...")

    for exclude_keyword in ping_config.exclude_keywords:
        if matches_pattern(title_lower, exclude_keyword):
            return Match(
                is_match=False,
                min_price=None,
                max_price=None,
                target_price=None,
                friendly_name=None,
                deal_ranges=None,
                regex=None,
                last_updated=last_updated,
                mode=matching_mode_and_query[0] if matching_mode_and_query else KeywordMode.POLL,
                query=matching_mode_and_query[1] if matching_mode_and_query and matching_mode_and_query[1] else None,  # noqa: E501
            )

    if is_globally_blocked(title_lower) and not matches_blocklist_override(
        title_lower,
        override_patterns=ping_config.blocklist_override,
    ):
        return Match(
            is_match=False,
            min_price=None,
            max_price=None,
            target_price=None,
            friendly_name=None,
            deal_ranges=None,
            regex=None,
            last_updated=last_updated,
            mode=matching_mode_and_query[0] if matching_mode_and_query else KeywordMode.POLL,
            query=matching_mode_and_query[1] if matching_mode_and_query and matching_mode_and_query[1] else None,  # noqa: E501
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
            regex=None,
            last_updated=last_updated,
            mode=matching_mode_and_query[0] if matching_mode_and_query else KeywordMode.POLL,
            query=matching_mode_and_query[1] if matching_mode_and_query and matching_mode_and_query[1] else None,  # noqa: E501
        )

    if BuyingOption.FIXED_PRICE not in item.buying_options:
        return Match(
            is_match=False,
            min_price=None,
            max_price=None,
            target_price=None,
            friendly_name=None,
            deal_ranges=None,
            regex=None,
            last_updated=last_updated,
            mode=matching_mode_and_query[0] if matching_mode_and_query else KeywordMode.POLL,
            query=matching_mode_and_query[1] if matching_mode_and_query and matching_mode_and_query[1] else None,  # noqa: E501
        )

    return Match(
        is_match=True,
        min_price=matching_min_price,
        max_price=matching_max_price,
        target_price=matching_target_price,
        friendly_name=matching_friendly_name,
        deal_ranges=matching_deal_ranges,
        regex=matched_filter,
        last_updated=last_updated,
        mode=matching_mode_and_query[0] if matching_mode_and_query else KeywordMode.POLL,
        query=matching_mode_and_query[1] if matching_mode_and_query and matching_mode_and_query[1] else None,  # noqa: E501
    )
