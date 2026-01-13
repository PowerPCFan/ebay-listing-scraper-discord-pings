import json5
from pathlib import Path
from dataclasses import dataclass, field
from .enums import PriceRange, DealRanges


CONFIG_JSON_POSSIBLE = ["config.json", "config.jsonc", "config.json5"]
CONFIG_JSON = None

for filename in CONFIG_JSON_POSSIBLE:
    path = Path(__file__).parent.parent / filename
    if path.exists():
        CONFIG_JSON = path
        break


@dataclass
class Keyword:
    keyword: str
    min_price: int | None = None
    max_price: int | None = None
    target_price: int | None = None
    friendly_name: str | None = None
    deal_ranges: DealRanges | None = None


@dataclass
class SelfRole:
    name: str
    id: int


@dataclass
class SelfRoleGroup:
    title: str
    roles: list[SelfRole] = field(default_factory=list)


type Keywords = list[Keyword]


@dataclass
class PingConfig:
    category_name: str
    categories: list[int]
    keywords: Keywords
    channel_id: int
    role: int
    price_ranges_last_updated: str = "1970-01-01T00:00:00.000+00:00"
    exclude_keywords: list[str] = field(default_factory=list)
    blocklist_override: list[str] = field(default_factory=list)


@dataclass
class SleepHours:
    start: str
    end: str


@dataclass
class Config:
    debug_mode: bool
    discord_py_debug_mode: bool
    log_api_responses: bool
    file_logging: bool
    ping_for_warnings: bool
    start_on_command: bool
    bot_debug_commands: bool
    include_shipping_in_deal_evaluation: bool
    include_shipping_in_price_filters: bool

    poll_interval_seconds: int

    ebay_app_id: str
    ebay_cert_id: str
    ebay_dev_id: str

    discord_bot_token: str
    discord_guild_id: int
    admin_role_id: int

    global_blocklist: list[str]
    seller_blocklist: list[str]
    condition_blocklist: list[int]

    pings: list[PingConfig]
    self_roles: list[SelfRoleGroup] = field(default_factory=list)

    logger_webhook: str | None = None
    logger_webhook_ping: int | None = None
    sleep_hours: SleepHours | None = None

    @staticmethod
    def load() -> "Config":
        if CONFIG_JSON is None:
            raise FileNotFoundError(
                "No config file found. Please create a config.json, config.jsonc, or config.json5 file."
            )

        with open(CONFIG_JSON) as f:
            data: dict = json5.load(f)

        data.pop("$schema", None)

        pings_data = data.pop("pings", [])
        self_roles_data = data.pop("self_roles", [])
        sleep_hours_data = data.pop("sleep_hours", None)
        pings: list[PingConfig] = []
        self_roles: list[SelfRoleGroup] = []
        sleep_hours: SleepHours | None = None

        for ping_data in pings_data:
            if ping_data.get("keywords") and isinstance(ping_data["keywords"], list):
                keywords = []
                for kw_data in ping_data["keywords"]:
                    deal_ranges = None
                    if "deal_ranges" in kw_data:
                        deal_ranges_data = kw_data.pop("deal_ranges")
                        deal_ranges = DealRanges(
                            fire_deal=PriceRange(**deal_ranges_data.get("fire_deal", {"start": 0, "end": 0})),
                            great_deal=PriceRange(**deal_ranges_data.get("great_deal", {"start": 0, "end": 0})),
                            good_deal=PriceRange(**deal_ranges_data.get("good_deal", {"start": 0, "end": 0})),
                            ok_deal=PriceRange(**deal_ranges_data.get("ok_deal", {"start": 0, "end": 0}))
                        )

                    keyword = Keyword(deal_ranges=deal_ranges, **kw_data)
                    keywords.append(keyword)
                ping_data["keywords"] = keywords

            pings.append(PingConfig(**ping_data))

        for group_data in self_roles_data:
            roles = []
            for role_data in group_data.get("roles", []):
                roles.append(SelfRole(**role_data))
            if len(roles) > 25:
                raise ValueError("A self-role group cannot have more than 25 roles due to Discord limitations.")
            self_roles.append(SelfRoleGroup(
                title=group_data["title"],
                roles=roles
            ))

        if sleep_hours_data:
            sleep_hours = SleepHours(**sleep_hours_data)

        return Config(pings=pings, self_roles=self_roles, sleep_hours=sleep_hours, **data)


def reload_config() -> Config:
    return Config.load()


def get_raw_config() -> str:
    if CONFIG_JSON is None:
        raise FileNotFoundError(
            "No config file found. Please create a config.json, config.jsonc, or config.json5 file."
        )

    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
        return f.read()
