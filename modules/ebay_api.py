import time
import base64
import requests
from pathlib import Path
from typing import Any, cast
from . import global_vars
from .logger import logger
from .global_vars import config
from .utils import iso_to_unix_timestamp
from .enums import (
    Category, Categories, Price, Seller, Condition, BuyingOption,
    BuyingOptions, ShippingType, ShippingOption, ShippingOptions,
    MarketplaceID
)

if config.debug_mode:
    import json
    from datetime import datetime
else:
    json = None
    datetime = None


_token_cache: str | None = None
_token_expires_at: int = 0

api_url = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def _get_response_json_filename() -> Path:
    assert datetime is not None

    directory = Path(__file__).parent.parent / "responses"
    path = directory / f"response-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.json"

    directory.mkdir(exist_ok=True, parents=True)
    path.touch(exist_ok=True)

    return path


class EbayItem:
    def __init__(self, item_data: dict[str, Any]) -> None:
        # self.data / item_data is the dict returned by search_single_category()
        self.data = item_data

    @property
    def item_id(self) -> int:
        id = self.data.get("legacyItemId", 0)
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
                name=str(cat_name) if cat_name else None
            )

            new_cats.append(new_cat_obj)

        return new_cats

    @property
    def leaf_categories(self) -> list[int]:
        leaf_cats: list[str] = self.data.get("leafCategoryIds", [])

        return [int(cat_id) for cat_id in leaf_cats if cat_id.isdigit()] if leaf_cats else []

    @property
    def thumbnail(self) -> str | None:
        thumb = dict(self.data.get(
            "image", {}
        )).get("imageUrl", None)  # for some reason image is smaller than thumbnail

        return str(thumb) if thumb else None

    @property
    def price(self) -> Price:
        _price = dict(self.data.get("price", {}))

        p = _price.get("value", None)
        c = _price.get("currency", None)

        return Price(
            currency=str(c) if c else None,
            value=float(p) if p else None
        )

    @property
    def url(self) -> str:
        link = self.data.get("itemWebUrl", "")
        return str(link)

    @property
    def seller(self) -> Seller:
        seller_obj = dict(self.data.get("seller", {}))

        username = seller_obj.get("username", None)
        feedback_score = seller_obj.get("feedbackScore", None)
        feedback_percentage = seller_obj.get("feedbackPercentage", None)

        return Seller(
            username=str(username) if username else None,
            feedback_score=int(feedback_score) if feedback_score else None,
            feedback_percentage=float(feedback_percentage) if feedback_percentage else None
        )

    @property
    def condition(self) -> Condition:
        condition_id = self.data.get("conditionId", None)
        condition_name = self.data.get("condition", None)

        return Condition(
            id=int(condition_id) if condition_id else None,
            name=str(condition_name) if condition_name else None
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
        old_shipping_options: list[dict[str, str | dict[str, str]]] = self.data.get("shippingOptions", [])
        new_shipping_options: ShippingOptions = []

        for old_option in old_shipping_options:
            try:
                shipping_type = ShippingType(cast(str, old_option.get("shippingCostType", "")))
            except ValueError:
                shipping_type = ShippingType.UNKNOWN

            shipping_cost_data = cast(dict[str, str], old_option.get("shippingCost", {}))
            shipping_cost_data_currency = shipping_cost_data.get("currency", None)
            shipping_cost_data_value = shipping_cost_data.get("value", None)
            shipping_cost = Price(
                currency=str(shipping_cost_data_currency) if shipping_cost_data_currency else None,
                value=float(shipping_cost_data_value) if shipping_cost_data_value else None
            )

            min_estimated_delivery_date_iso = cast(str | None, old_option.get("minEstimatedDeliveryDate", None))
            max_estimated_delivery_date_iso = cast(str | None, old_option.get("maxEstimatedDeliveryDate", None))
            min_estimated_delivery_date = (
                iso_to_unix_timestamp(min_estimated_delivery_date_iso) if
                min_estimated_delivery_date_iso else None
            )
            max_estimated_delivery_date = (
                iso_to_unix_timestamp(max_estimated_delivery_date_iso) if
                max_estimated_delivery_date_iso else None
            )

            new_option = ShippingOption(
                type=shipping_type,
                cost=shipping_cost,
                min_estimated_delivery_date=min_estimated_delivery_date,
                max_estimated_delivery_date=max_estimated_delivery_date
            )

            new_shipping_options.append(new_option)

        return new_shipping_options

    @property
    def marketplace_id(self) -> MarketplaceID | None:
        id_str = self.data.get("listingMarketplaceId", None)

        if not id_str:
            return None

        try:
            id_enum = MarketplaceID(id_str)
            return id_enum
        except ValueError:
            return None


def get_valid_token() -> str | None:
    global _token_cache, _token_expires_at

    current_time = int(time.time())

    if _token_cache and current_time < _token_expires_at:
        logger.debug(f"Using cached token (expires in {_token_expires_at - current_time}s)")
        return _token_cache

    try:
        if not config.ebay_app_id or not config.ebay_cert_id:
            raise ValueError("eBay App ID and Cert ID must be configured")

        credentials = base64.b64encode(f"{config.ebay_app_id}:{config.ebay_cert_id}".encode()).decode()

        response = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}"
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=30
        )

        if not response.ok:
            logger.error(f"Token request failed: {response.status_code} {response.text}")
            return None

        data = dict(response.json())
        _token_cache = data["access_token"]
        _token_expires_at = current_time + data.get("expires_in", 7200) - 120  # Refresh 2 minutes before expiry

        logger.debug("New OAuth token generated successfully")
        return _token_cache

    except Exception:
        logger.exception("Token generation error:")
        return None


def initialize() -> bool:
    token = get_valid_token()

    if not token:
        raise ValueError("Failed to generate eBay OAuth token")

    logger.debug("eBay Browse API connection initialized successfully")

    return True


def search_query(
    query: str,
    categories: list[str],
    min_price: int | None = None,
    max_price: int | None = None
) -> list[dict[str, Any]]:
    try:
        token = get_valid_token()
        if not token:
            logger.error(f"Failed to get OAuth token for query: {query}")
            return []

        params = {
            "q": query,
            "category_ids": ",".join(categories),
            "filter": "buyingOptions:{FIXED_PRICE|AUCTION}",
            "sort": "newlyListed",
            "limit": str(global_vars.limit)
        }

        if min_price or max_price:
            price_filter = ""
            if min_price and max_price:
                price_filter = f",price:[{min_price}..{max_price}],priceCurrency:USD"
            elif min_price:
                price_filter = f",price:[{min_price}],priceCurrency:USD"
            elif max_price:
                price_filter = f",price:[..{max_price}],priceCurrency:USD"
            params["filter"] += price_filter

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        global_vars.api_call_count += 1
        response = requests.get(api_url, params=params, headers=headers, timeout=30)

        if config.log_api_responses:
            assert json is not None

            parsed = json.loads(response.text)
            with open(
                _get_response_json_filename(),
                mode="w",
                encoding="utf-8"
            ) as f:
                json.dump(parsed, f, indent=4)

        if response.status_code == 401 or response.status_code == 403:
            global _token_cache, _token_expires_at
            _token_cache = None
            _token_expires_at = 0
            return []

        if not response.ok:
            logger.error(f"eBay API error for query '{query}': {response.status_code}")
            return []

        data = response.json()
        return data.get("itemSummaries", [])

    except Exception:
        logger.exception(f"Error searching query '{query}':")
        return []


def search_single_category(category_id: str, price_filter: str = "") -> list[dict[str, Any]]:
    try:
        token = get_valid_token()

        if not token:
            logger.error(f"Failed to get OAuth token for category {category_id}")
            return []

        params = {
            "category_ids": category_id,
            "filter": "buyingOptions:{FIXED_PRICE|AUCTION}" + price_filter,
            "sort": "newlyListed",
            "limit": str(global_vars.limit)
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        global_vars.api_call_count += 1
        response = requests.get(api_url, params=params, headers=headers, timeout=30)

        if config.log_api_responses:
            assert json is not None

            parsed = json.loads(response.text)
            with open(
                _get_response_json_filename(),
                mode="w",
                encoding="utf-8"
            ) as f:
                logger.debug("Writing response to file for debugging purposes...")
                json.dump(parsed, f, indent=4, ensure_ascii=False)
                logger.debug("Done.")

        if response.status_code in (401, 403):
            global _token_cache, _token_expires_at
            _token_cache = None
            _token_expires_at = 0
            return []

        if not response.ok:
            logger.error(f"eBay API error for category {category_id}: {response.status_code}")
            return []

        data = dict(response.json())
        if not data.get("itemSummaries"):
            return []

        return [item for item in data["itemSummaries"]]

    except Exception:
        logger.exception(f"Error searching category {category_id}:")
        return []
