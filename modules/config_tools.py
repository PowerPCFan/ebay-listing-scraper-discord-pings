import json
import os
from dataclasses import dataclass, field
from .enums import Mode

CONFIG_JSON = "config.json"


@dataclass
class Keyword:
    keyword: str
    min_price: int | None = None
    max_price: int | None = None


type Keywords = list[Keyword]


@dataclass
class Query:
    query: str
    min_price: int | None = None
    max_price: int | None = None


@dataclass
class PingConfig:
    category_name: str
    mode: Mode
    categories: list[int]
    webhook: str
    role: int | None
    keywords: Keywords | None = None
    query: Query | None = None
    exclude_keywords: list[str] = field(default_factory=list)
    blocklist_override: list[str] = field(default_factory=list)


@dataclass
class Config:
    debug_mode: bool
    log_api_responses: bool
    full_tracebacks: bool
    send_test_webhooks: bool
    file_logging: bool
    ping_for_warnings: bool

    poll_interval_seconds: int

    logger_webhook: str
    logger_webhook_ping: int | None

    ebay_app_id: str
    ebay_cert_id: str
    ebay_dev_id: str

    pings: list[PingConfig]
    global_blocklist: list[str]

    @staticmethod
    def load() -> "Config":
        if not os.path.exists(CONFIG_JSON):
            raise FileNotFoundError(f"Error: {CONFIG_JSON} not found.")

        with open(CONFIG_JSON) as f:
            data = json.load(f)

        pings_data = data.pop("pings", [])
        pings: list[PingConfig] = []

        for ping_data in pings_data:
            if ping_data.get("mode") and isinstance(ping_data["mode"], str):
                ping_data["mode"] = Mode(ping_data["mode"])
            if ping_data.get("keywords") and isinstance(ping_data["keywords"], list):
                keywords = []
                for kw_data in ping_data["keywords"]:
                    keywords.append(Keyword(**kw_data))
                ping_data["keywords"] = keywords
            if ping_data.get("query") and isinstance(ping_data["query"], dict):
                ping_data["query"] = Query(**ping_data["query"])

            pings.append(PingConfig(**ping_data))

        pings_count = len(pings)
        parse_count = len([ping for ping in pings if ping.mode == Mode.PARSE])
        query_count = len([ping for ping in pings if ping.mode == Mode.QUERY])

        return Config(pings=pings, **data)
