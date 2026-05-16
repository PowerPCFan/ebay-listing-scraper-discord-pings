import base64
import time
from pathlib import Path
from typing import Any, cast

import httpx

from . import global_vars as gv
from .enums import (
    BuyingOption,
    BuyingOptions,
    Categories,
    Category,
    Condition,
    MarketplaceID,
    Price,
    Seller,
    ShippingOption,
    ShippingOptions,
    ShippingType,
)
from .logger import logger
from .utils import iso_to_unix_timestamp

if gv.config.log_api_responses:
    import json
    from datetime import datetime
else:
    json = None
    datetime = None


json_datetime_alert = "\n".join(
    [
        "Something went wrong, information:",
        "The JSON and Datetime modules are only imported when gv.config.log_api_responses is True.",
        "This function should only be called when gv.config.log_api_responses is True.",
        "However, it somehow was called when gv.config.log_api_responses is False, leading to the module being missing.",  # noqa: E501
        "This is likely a bug in the code, if you are the developer fix this, and if you are a user report this on GitHub.",  # noqa: E501
        "(Also a reminder that this isn't really designed to be a user-facing tool, it's a project that I wrote for myself so there aren't any docs and stuffs)",  # noqa: E501
    ],
)


_token_cache: str | None = None
_token_expires_at: int = 0
_http_client: httpx.AsyncClient | None = None

api_url = "https://api.ebay.com/buy/browse/v1/item_summary/search"


async def get_http_client() -> httpx.AsyncClient:
    global _http_client  # noqa: PLW0603
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


async def close_http_client() -> None:
    global _http_client  # noqa: PLW0603
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _get_response_json_filename(api_source: str) -> Path:
    if datetime is None:
        raise RuntimeError(json_datetime_alert)
    directory = Path(__file__).parent.parent / "responses" / (("".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in api_source).strip("-")) or "unknown")  # noqa: E501
    path = directory / f"response-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

    directory.mkdir(exist_ok=True, parents=True)
    path.touch(exist_ok=True)

    return path


class EbayItem:
    def __init__(self, item_data: dict[str, Any]) -> None:
        # self.data / item_data is the dict returned by search_single_category()
        self.data = item_data

    @property
    def item_id(self) -> int:
        id = self.data.get("legacyItemId", 0)  # noqa: A001
        return int(id)

    @property
    def full_item_id(self) -> str:
        full_id = self.data.get("itemId", "")
        return str(full_id)

    @property
    def title(self) -> str:
        _title = self.data.get("title", "")
        return str(_title)

    @property
    def categories(self) -> Categories:
        cats: list[dict[str, Any]] = self.data.get("categories", [])
        new_cats: Categories = []

        for cat in cats:
            cat_id = cat.get("categoryId", None)
            cat_name = cat.get("categoryName", None)

            new_cat_obj = Category(
                id=int(cat_id) if cat_id else None,
                name=str(cat_name) if cat_name else None,
            )

            new_cats.append(new_cat_obj)

        return new_cats

    @property
    def leaf_categories(self) -> list[int]:
        leaf_cats: list[str] = self.data.get("leafCategoryIds", [])

        return [int(cat_id) for cat_id in leaf_cats if cat_id.isdigit()] if leaf_cats else []

    @property
    def thumbnail(self) -> str | None:
        # for some reason image is smaller than thumbnail
        thumb = dict(self.data.get("image", {})).get("imageUrl", None)

        return str(thumb) if thumb else None

    @property
    def main_image(self) -> str | None:
        thumbnail_images: list[dict[str, str]] | None = self.data.get("thumbnailImages", None)

        if not thumbnail_images or not isinstance(thumbnail_images, list):
            return None

        first_image_dict = thumbnail_images[0] if thumbnail_images else None

        if not first_image_dict or not isinstance(first_image_dict, dict):
            return None

        image = first_image_dict.get("imageUrl", None)

        return str(image) if image else None

    @property
    def price(self) -> Price:
        _price = dict(self.data.get("price", {}))

        p = _price.get("value")
        c = _price.get("currency")

        return Price(currency=str(c) if c else None, value=float(p) if p else None)

    @property
    def url(self) -> str:
        link = self.data.get("itemWebUrl", "")
        return str(link)

    @property
    def seller(self) -> Seller:
        seller_obj = dict(self.data.get("seller", {}))

        username = seller_obj.get("username")
        feedback_score = seller_obj.get("feedbackScore")
        _fbp = seller_obj.get("feedbackPercentage")
        feedback_percentage = float(_fbp) if _fbp is not None else None

        if not feedback_percentage or feedback_percentage <= 0.0:
            feedback_percentage = None

        return Seller(
            username=str(username) if username else None,
            feedback_score=int(feedback_score) if feedback_score else None,
            feedback_percentage=float(feedback_percentage) if feedback_percentage else None,
        )

    @property
    def condition(self) -> Condition:
        condition_id = self.data.get("conditionId", None)
        condition_name = self.data.get("condition", None)

        return Condition(
            id=int(condition_id) if condition_id else None,
            name=str(condition_name) if condition_name else None,
        )

    @property
    def buying_options(self) -> BuyingOptions:
        options: list[str] = self.data.get("buyingOptions", [])

        buying_opts: BuyingOptions = [enum for enum in BuyingOption if enum.value in options]

        if BuyingOption.BEST_OFFER in buying_opts and BuyingOption.FIXED_PRICE not in buying_opts:
            buying_opts.remove(BuyingOption.BEST_OFFER)

        return buying_opts

    @property
    def epid(self) -> int:
        epid = self.data.get("epid", "")
        return int(epid)

    @property
    def date_posted(self) -> int:
        item_creation_date_iso = str(self.data.get("itemCreationDate", "1970-01-01T00:00:00.000Z"))

        return iso_to_unix_timestamp(item_creation_date_iso)

    @property
    def shipping(self) -> ShippingOptions:
        old_shipping_options: list[dict[str, str | dict[str, str]]] = self.data.get(
            "shippingOptions", [],
        )
        new_shipping_options: ShippingOptions = []

        for old_option in old_shipping_options:
            try:
                shipping_type = ShippingType(cast("str", old_option.get("shippingCostType", "")))
            except ValueError:
                shipping_type = ShippingType.UNKNOWN

            shipping_cost_data = cast("dict[str, str]", old_option.get("shippingCost", {}))
            shipping_cost_data_currency = shipping_cost_data.get("currency", None)
            shipping_cost_data_value = shipping_cost_data.get("value", None)
            shipping_cost = Price(
                currency=str(shipping_cost_data_currency) if shipping_cost_data_currency else None,
                value=float(shipping_cost_data_value) if shipping_cost_data_value else None,
            )

            min_estimated_delivery_date_iso = cast(
                "str | None", old_option.get("minEstimatedDeliveryDate", None),
            )
            max_estimated_delivery_date_iso = cast(
                "str | None", old_option.get("maxEstimatedDeliveryDate", None),
            )
            min_estimated_delivery_date = (
                iso_to_unix_timestamp(min_estimated_delivery_date_iso)
                if min_estimated_delivery_date_iso
                else None
            )
            max_estimated_delivery_date = (
                iso_to_unix_timestamp(max_estimated_delivery_date_iso)
                if max_estimated_delivery_date_iso
                else None
            )

            new_option = ShippingOption(
                type=shipping_type,
                cost=shipping_cost,
                min_estimated_delivery_date=min_estimated_delivery_date,
                max_estimated_delivery_date=max_estimated_delivery_date,
            )

            new_shipping_options.append(new_option)

        return new_shipping_options

    @property
    def marketplace_id(self) -> MarketplaceID | None:
        id_str = self.data.get("listingMarketplaceId", None)

        if not id_str:
            return None

        try:
            return MarketplaceID(id_str)
        except ValueError:
            return None

    @property
    def country(self) -> str | None:
        cc = dict(self.data.get("itemLocation", {})).get("country", None)
        return str(cc) if cc else None

    @property
    def top_rated(self) -> bool | None:
        tr = self.data.get("topRatedBuyingExperience", None)
        return bool(tr) if tr is not None else None


async def get_valid_token() -> str | None:
    global _token_cache, _token_expires_at  # noqa: PLW0603

    current_time = int(time.time())

    if _token_cache and current_time < _token_expires_at:
        logger.debug(f"Using cached token (expires in {_token_expires_at - current_time}s)")
        return _token_cache

    try:
        credentials = base64.b64encode(
            f"{gv.config.ebay_app_id}:{gv.config.ebay_cert_id}".encode(),
        ).decode()

        client = await get_http_client()
        response = await client.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
        )

        if response.status_code != 200:  # noqa: PLR2004
            logger.error(f"Token request failed: {response.status_code} {response.text}")
            return None

        data = dict(response.json())
        _token_cache = data["access_token"]
        _token_expires_at = (
            current_time + data.get("expires_in", 7200) - 120
        )  # Refresh 2 minutes before expiry

        logger.debug("New OAuth token generated successfully")
        return _token_cache

    except Exception:
        logger.exception("Token generation error:")
        return None


async def initialize() -> bool:
    token = await get_valid_token()

    if not token:
        msg = "Failed to generate eBay OAuth token"
        raise ValueError(msg)

    logger.debug("eBay Browse API connection initialized successfully")

    return True


def _get_browse_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _log_response_json(response: httpx.Response, api_source: str) -> None:
    if not gv.config.log_api_responses:
        return
    if not json:
        raise RuntimeError(json_datetime_alert)

    parsed = response.json()
    with _get_response_json_filename(api_source).open(mode="w", encoding="utf-8") as f:
        logger.debug("Writing response to file for debugging purposes...")
        json.dump(parsed, f, indent=4, ensure_ascii=False)
        logger.debug("Done.")


class EbayBrowseSummaryApi:
    def __init__(self, source_name: str) -> None:
        self.source_name = source_name

    async def search(self, params: dict[str, str], error_context: str) -> list[dict[str, Any]]:
        token = await get_valid_token()

        if not token:
            logger.error(f"Failed to get OAuth token for {error_context}")
            return []

        gv.api_call_count += 1
        client = await get_http_client()
        response = await client.get(api_url, params=params, headers=_get_browse_headers(token))

        _log_response_json(response, self.source_name)

        if response.status_code in (401, 403):
            global _token_cache, _token_expires_at  # noqa: PLW0603
            _token_cache = None
            _token_expires_at = 0
            return []

        if response.status_code != 200:  # noqa: PLR2004
            logger.error(f"eBay API error for {error_context}: {response.status_code}")
            return []

        data = dict(response.json())
        if not data.get("itemSummaries"):
            return []

        return list(data["itemSummaries"])


summary_category_api = EbayBrowseSummaryApi(source_name="browse_item_summary_category_poll")
summary_query_api = EbayBrowseSummaryApi(source_name="browse_item_summary_keyword_query")


def _build_summary_params(
    *,
    price_filter: str = "",
    category_id: str | None = None,
    query: str | None = None,
) -> dict[str, str]:
    params = {
        "filter": "buyingOptions:{FIXED_PRICE|AUCTION}" + price_filter,
        "sort": "newlyListed",
        "limit": str(gv.limit),
    }
    if category_id:
        params["category_ids"] = category_id
    if query:
        params["q"] = query
    return params


async def search_single_category(category_id: str, price_filter: str = "") -> list[dict[str, Any]]:
    try:
        params = _build_summary_params(price_filter=price_filter, category_id=category_id)
        return await summary_category_api.search(
            params=params,
            error_context=f"category {category_id}",
        )

    except Exception:
        logger.exception(f"Error searching category {category_id}:")
        return []


async def search_query_in_category(
    *,
    category_id: str,
    query: str,
    price_filter: str = "",
) -> list[dict[str, Any]]:
    try:
        params = _build_summary_params(
            price_filter=price_filter,
            category_id=category_id,
            query=query,
        )
        return await summary_query_api.search(
            params=params,
            error_context=f"query '{query}' in category {category_id}",
        )
    except Exception:
        logger.exception(f"Error querying category {category_id}:")
        return []
