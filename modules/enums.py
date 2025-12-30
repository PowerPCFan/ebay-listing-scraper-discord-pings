from enum import Enum
from typing import NamedTuple


class Category(NamedTuple):
    id: int | None
    name: str | None


type Categories = list[Category]


class Price(NamedTuple):
    currency: str | None
    value: float | None


class Seller(NamedTuple):
    username: str | None
    feedback_score: int | None
    feedback_percentage: float | None


class Condition(NamedTuple):
    id: int | None
    name: str | None


class BuyingOption(Enum):
    FIXED_PRICE = "FIXED_PRICE"
    BEST_OFFER = "BEST_OFFER"  # note: FIXED_PRICE must be present for BEST_OFFER to appear
    AUCTION = "AUCTION"


type BuyingOptions = list[BuyingOption]


class ShippingType(Enum):
    FIXED = "FIXED"
    CALCULATED = "CALCULATED"
    UNKNOWN = "UNKNOWN"


class ShippingOption(NamedTuple):
    type: ShippingType
    cost: Price
    min_estimated_delivery_date: int | None
    max_estimated_delivery_date: int | None


type ShippingOptions = list[ShippingOption]


class MarketplaceID(Enum):
    """
    Source: [eBay API Docs](https://developer.ebay.com/api-docs/sell/account/types/ba:MarketplaceIdEnum#s0-1-30-4-7-5-children-heading)
    """  # noqa: E501

    EBAY_AT = "EBAY_AT"
    EBAY_AU = "EBAY_AU"
    EBAY_BE = "EBAY_BE"
    EBAY_CA = "EBAY_CA"
    EBAY_CH = "EBAY_CH"
    EBAY_DE = "EBAY_DE"
    EBAY_ES = "EBAY_ES"
    EBAY_FR = "EBAY_FR"
    EBAY_GB = "EBAY_GB"
    EBAY_HK = "EBAY_HK"
    EBAY_IE = "EBAY_IE"
    EBAY_IT = "EBAY_IT"
    EBAY_MY = "EBAY_MY"
    EBAY_NL = "EBAY_NL"
    EBAY_PH = "EBAY_PH"
    EBAY_PL = "EBAY_PL"
    EBAY_SG = "EBAY_SG"
    EBAY_TH = "EBAY_TH"
    EBAY_TW = "EBAY_TW"
    EBAY_US = "EBAY_US"
    EBAY_VN = "EBAY_VN"


class Match(NamedTuple):
    is_match: bool
    min_price: float | None
    max_price: float | None


class Emojis:
    OBO = "<:obo:1453585974213873695>"
    SHIPPING = "<:shipping:1453716706017935482>"
    CALENDAR = "<:calendar:1453717238702932028>"
    PRICE = "<:price:1453719493686853632>"
    SELLER = "<:seller:1453721027103428609>"
    CONDITION = "<:condition:1453722903609610504>"
    LISTING_TYPE = "<:listing_type:1453723643766112388>"
    WARNING = "<:warning:1455577563425673403>"


class DealEmojis:
    # Currently unused since custom emojis don't work in the embed "Author" field
    # FIRE_DEAL = "<:fire_deal:1454943220000755924>"
    # GREAT_DEAL = "<:great_deal:1455334348134813696>"
    # GOOD_DEAL = "<:good_deal:1455334351850963083>"
    # OK_DEAL = "<:ok_deal:1455334349900742786>"

    FIRE_DEAL = "🔥"
    GREAT_DEAL = "🟢"
    GOOD_DEAL = "🟡"
    OK_DEAL = "🟠"

    UNKNOWN = ""


class DealColors:
    # These colors were roughly estimated based on the emojis
    # FIRE_DEAL = 0xE03A3A
    FIRE_DEAL = 0x48862D
    GREAT_DEAL = 0x48862D
    GOOD_DEAL = 0xFFDD00
    OK_DEAL = 0xF2900F

    UNKNOWN = 0x0064D3


class DealTuple(NamedTuple):
    name: str
    emoji: str
    color: int


class Deal:
    """
    Each value is a `_DealTuple` - `(name: str, emoji: str, color: int)`.
    """

    FIRE_DEAL = DealTuple(
        name="Fire Deal",
        emoji=DealEmojis.FIRE_DEAL,
        color=DealColors.FIRE_DEAL
    )

    GREAT_DEAL = DealTuple(
        name="Great Deal",
        emoji=DealEmojis.GREAT_DEAL,
        color=DealColors.GREAT_DEAL
    )

    GOOD_DEAL = DealTuple(
        name="Good Deal",
        emoji=DealEmojis.GOOD_DEAL,
        color=DealColors.GOOD_DEAL
    )

    OK_DEAL = DealTuple(
        name="Average Deal",
        emoji=DealEmojis.OK_DEAL,
        color=DealColors.OK_DEAL
    )

    UNKNOWN_DEAL = DealTuple(
        name="Unknown Deal",
        emoji=DealEmojis.UNKNOWN,
        color=DealColors.UNKNOWN
    )
