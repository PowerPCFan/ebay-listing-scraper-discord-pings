import json
import os
from dataclasses import dataclass, field
from .enums import PriceRange, DealRanges

CONFIG_JSON = "config.json"


@dataclass
class Keyword:
    keyword: str
    min_price: int | None = None
    max_price: int | None = None
    deal_ranges: DealRanges | None = None


type Keywords = list[Keyword]


@dataclass
class PingConfig:
    category_name: str
    categories: list[int]
    webhook: str
    role: int | None
    keywords: Keywords
    exclude_keywords: list[str] = field(default_factory=list)
    blocklist_override: list[str] = field(default_factory=list)


@dataclass
class Config:
    debug_mode: bool
    log_api_responses: bool
    send_test_webhooks: bool
    file_logging: bool
    ping_for_warnings: bool
    commands: bool

    poll_interval_seconds: int

    ebay_app_id: str
    ebay_cert_id: str
    ebay_dev_id: str

    global_blocklist: list[str]
    seller_blocklist: list[str]

    pings: list[PingConfig]

    logger_webhook: str | None = None
    logger_webhook_ping: int | None = None

    @staticmethod
    def load() -> "Config":
        if not os.path.exists(CONFIG_JSON):
            raise FileNotFoundError(f"Error: {CONFIG_JSON} not found.")

        with open(CONFIG_JSON) as f:
            data = json.load(f)

        pings_data = data.pop("pings", [])
        pings: list[PingConfig] = []

        for ping_data in pings_data:
            if ping_data.get("keywords") and isinstance(ping_data["keywords"], list):
                keywords = []
                for kw_data in ping_data["keywords"]:
                    deal_ranges = None
                    if any(key in kw_data for key in ["fire_deal", "great_deal", "good_deal", "ok_deal"]):
                        deal_ranges = DealRanges(
                            fire_deal=PriceRange(**kw_data.pop("fire_deal", {"start": 0, "end": 0})),
                            great_deal=PriceRange(**kw_data.pop("great_deal", {"start": 0, "end": 0})),
                            good_deal=PriceRange(**kw_data.pop("good_deal", {"start": 0, "end": 0})),
                            ok_deal=PriceRange(**kw_data.pop("ok_deal", {"start": 0, "end": 0}))
                        )

                    keyword = Keyword(deal_ranges=deal_ranges, **kw_data)
                    keywords.append(keyword)
                ping_data["keywords"] = keywords

            pings.append(PingConfig(**ping_data))

        return Config(pings=pings, **data)


def reload_config() -> Config:
    return Config.load()
