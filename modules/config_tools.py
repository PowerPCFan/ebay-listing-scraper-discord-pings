from dataclasses import dataclass, field
from pathlib import Path

import json5

from .enums import Deal, DealRanges, DealTuple, PriceRange

CONFIG_JSON_POSSIBLE = ["config.json", "config.jsonc"]
CONFIG_JSON = None

for filename in CONFIG_JSON_POSSIBLE:
    path = Path(__file__).parent.parent / filename
    if path.exists():
        CONFIG_JSON = path
        break

GLOBAL_BLOCKLIST_TXT = Path(__file__).parent.parent / "global_blocklist.txt"


def get_config_path() -> Path:
    if CONFIG_JSON is None:
        msg = "No config file found. Please create a config.json or config.jsonc file."
        raise FileNotFoundError(msg)
    return CONFIG_JSON


def get_raw_config() -> str:
    with get_config_path().open(encoding="utf-8") as f:
        return f.read()


def get_parsed_config() -> dict:
    raw = get_raw_config()
    data = json5.loads(raw)
    if not isinstance(data, dict):
        msg = "Config root must be a JSON object."
        raise TypeError(msg)
    return data


@dataclass
class GlobalBlocklist:
    items: list[str] = field(default_factory=list)

    @staticmethod
    def load() -> "GlobalBlocklist":
        if not GLOBAL_BLOCKLIST_TXT.exists():
            GLOBAL_BLOCKLIST_TXT.touch()
            return GlobalBlocklist()

        with GLOBAL_BLOCKLIST_TXT.open(encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        return GlobalBlocklist(items=lines)

    def save(self) -> None:
        with GLOBAL_BLOCKLIST_TXT.open("w", encoding="utf-8") as f:
            for item in self.items:
                f.write(f"{item}\n")

    def add(self, item: str) -> bool:
        item = item.strip().lower()
        if item and item not in [i.lower() for i in self.items]:
            self.items.append(item)
            self.save()
            return True
        return False

    def remove(self, item: str) -> bool:
        item = item.strip().lower()
        for i, existing_item in enumerate(self.items):
            if existing_item.lower() == item:
                self.items.pop(i)
                self.save()
                return True
        return False


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


Keywords = list[Keyword]


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
    do_not_show: list[DealTuple] = field(default_factory=list)
    is_psu: bool = False


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

    seller_blocklist: list[str]
    condition_blocklist: list[int]

    pings: list[PingConfig]
    self_roles: list[SelfRoleGroup] = field(default_factory=list)

    logger_webhook: str | None = None
    logger_webhook_ping: int | None = None
    sleep_hours: SleepHours | None = None
    config_editor_password: str | None = None

    @staticmethod
    def load() -> "Config":  # noqa: C901, PLR0912, PLR0915
        data: dict = get_parsed_config()

        data.pop("$schema", None)
        data.pop("config_editor", None)

        # The global blocklist is stored in global_blocklist.txt, not in the main config.
        # Older/buggy editor versions may have written it into the config root.
        data.pop("blocklist", None)
        data.pop("global_blocklist", None)

        pings_data = data.pop("pings", [])
        self_roles_data = data.pop("self_roles", [])
        sleep_hours_data = data.pop("sleep_hours", None)
        pings: list[PingConfig] = []
        self_roles: list[SelfRoleGroup] = []
        sleep_hours: SleepHours | None = None

        def _to_int(val: str | int) -> int:
            if isinstance(val, str):
                return int(val)
            elif isinstance(val, int):
                return val

            try:
                return int(val)
            except Exception as e:
                msg = f"Error converting {val} to an int: {e}"
                raise ValueError(msg) from e

        for ping_data in pings_data:
            if "channel_id" in ping_data:
                ping_data["channel_id"] = _to_int(ping_data["channel_id"])
            if "role" in ping_data:
                ping_data["role"] = _to_int(ping_data["role"])
            if "categories" in ping_data and isinstance(ping_data["categories"], list):
                ping_data["categories"] = [_to_int(c) for c in ping_data["categories"]]

            if ping_data.get("keywords") and isinstance(ping_data["keywords"], list):
                keywords = []
                for kw_data in ping_data["keywords"]:
                    deal_ranges = None
                    if "deal_ranges" in kw_data:
                        ranges_data: dict = kw_data.pop("deal_ranges")

                        fire_deal: dict = ranges_data.get("fire_deal", {"start": 0, "end": 0})
                        great_deal: dict = ranges_data.get("great_deal", {"start": 0, "end": 0})
                        good_deal: dict = ranges_data.get("good_deal", {"start": 0, "end": 0})
                        ok_deal: dict = ranges_data.get("ok_deal", {"start": 0, "end": 0})
                        do_not_show: list[str] = ranges_data.get("do_not_show", [])

                        deal_ranges = DealRanges(
                            fire_deal=PriceRange(**fire_deal),
                            great_deal=PriceRange(**great_deal),
                            good_deal=PriceRange(**good_deal),
                            ok_deal=PriceRange(**ok_deal),
                            do_not_show=[getattr(Deal, dns.upper()) for dns in do_not_show],
                        )

                    keyword = Keyword(deal_ranges=deal_ranges, **kw_data)
                    keywords.append(keyword)
                ping_data["keywords"] = keywords

            dns = ping_data.get("do_not_show")
            if dns:
                ping_data["do_not_show"] = [getattr(Deal, a.upper()) for a in dns]

            pings.append(PingConfig(**ping_data))

        for group_data in self_roles_data:
            roles = []
            for role_data in group_data.get("roles", []):
                if "id" in role_data:
                    role_data["id"] = _to_int(role_data["id"])
                roles.append(SelfRole(**role_data))

            max_roles = 25
            if len(roles) > max_roles:
                msg = "A self-role group cannot have more than 25 roles due to Discord limitations."
                raise ValueError(msg)
            self_roles.append(SelfRoleGroup(title=group_data["title"], roles=roles))

        if sleep_hours_data:
            sleep_hours = SleepHours(**sleep_hours_data)

        for key in ["discord_guild_id", "admin_role_id", "logger_webhook_ping"]:
            if key in data:
                data[key] = _to_int(data[key])

        return Config(pings=pings, self_roles=self_roles, sleep_hours=sleep_hours, **data)


def reload_config() -> Config:
    return Config.load()


def reload_global_blocklist() -> GlobalBlocklist:
    return GlobalBlocklist.load()
