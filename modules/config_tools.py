from dataclasses import dataclass, field
from pathlib import Path
from typing import Self, overload

import json5

from .enums import Deal, DealRanges, DealTuple

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

    @classmethod
    def load(cls) -> Self:
        if not GLOBAL_BLOCKLIST_TXT.exists():
            GLOBAL_BLOCKLIST_TXT.touch()
            return cls()

        with GLOBAL_BLOCKLIST_TXT.open(encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        return cls(items=lines)

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

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "target_price": self.target_price,
            "friendly_name": self.friendly_name,
            "deal_ranges": self.deal_ranges.to_dict() if self.deal_ranges else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        ranges = data.get("deal_ranges")

        return cls(
            keyword=data["keyword"],
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
            target_price=data.get("target_price"),
            friendly_name=data.get("friendly_name"),
            deal_ranges=DealRanges.from_dict(ranges) if ranges else None,
        )


@dataclass
class SelfRole:
    name: str
    id: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "id": Config.to_str(self.id),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Self:
        return cls(name=data["name"], id=Config.to_int(data["id"]))


@dataclass
class SelfRoleGroup:
    title: str
    roles: list[SelfRole] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "roles": [role.to_dict() for role in self.roles],
        }


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

    def to_dict(self) -> dict:
        return {
            "category_name": self.category_name,
            "categories": [Config.to_str(c) for c in self.categories],
            "keywords": [kw.to_dict() for kw in self.keywords],
            "channel_id": Config.to_str(self.channel_id),
            "role": Config.to_str(self.role),
            "price_ranges_last_updated": self.price_ranges_last_updated,
            "exclude_keywords": self.exclude_keywords,
            "blocklist_override": self.blocklist_override,
            "do_not_show": [deal.id.lower() for deal in self.do_not_show],
            "is_psu": self.is_psu,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return cls(
            category_name=data["category_name"],
            categories=[c for c in [Config.to_int(v) for v in data["categories"]] if c],
            keywords=[Keyword.from_dict(d) for d in data["keywords"]],
            channel_id=Config.to_int(str(data["channel_id"])),
            role=Config.to_int(str(data["role"])),
            price_ranges_last_updated=data.get(
                "price_ranges_last_updated",
                "1970-01-01T00:00:00.000+00:00",
            ),
            exclude_keywords=data.get("exclude_keywords", []),
            blocklist_override=data.get("blocklist_override", []),
            do_not_show=[Deal.from_str(dt) for dt in data.get("do_not_show", [])],
            is_psu=data.get("is_psu", False),
        )


@dataclass
class SleepHours:
    start: str
    end: str

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return cls(start=data["start"], end=data["end"])


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
    config_editor_host: str | None = None
    config_editor_port: int | None = None

    @overload
    @staticmethod
    def to_str(val: str | int) -> str: ...

    @overload
    @staticmethod
    def to_str(val: str | int | None) -> str | None: ...

    @staticmethod
    def to_str(val):
        if val is None:
            return None
        return str(val)

    @overload
    @staticmethod
    def to_int(val: str | int) -> int: ...

    @overload
    @staticmethod
    def to_int(val: str | int | None) -> int | None: ...

    @staticmethod
    def to_int(val):
        if val is None or str(val).lower().strip() == "none":
            return None
        if isinstance(val, str):
            return int(val)
        if isinstance(val, int):
            return val

        try:
            return int(val)
        except ValueError:
            return None

    def to_dict(self) -> dict:
        result = {
            "debug_mode": self.debug_mode,
            "discord_py_debug_mode": self.discord_py_debug_mode,
            "log_api_responses": self.log_api_responses,
            "file_logging": self.file_logging,
            "ping_for_warnings": self.ping_for_warnings,
            "start_on_command": self.start_on_command,
            "bot_debug_commands": self.bot_debug_commands,
            "include_shipping_in_deal_evaluation": self.include_shipping_in_deal_evaluation,
            "include_shipping_in_price_filters": self.include_shipping_in_price_filters,
            "poll_interval_seconds": self.poll_interval_seconds,
            "ebay_app_id": self.ebay_app_id,
            "ebay_cert_id": self.ebay_cert_id,
            "ebay_dev_id": self.ebay_dev_id,
            "discord_bot_token": self.discord_bot_token,
            "discord_guild_id": self.to_str(self.discord_guild_id),
            "admin_role_id": self.to_str(self.admin_role_id),
            "seller_blocklist": self.seller_blocklist,
            "condition_blocklist": self.condition_blocklist,
            "pings": [ping.to_dict() for ping in self.pings],
            "self_roles": [group.to_dict() for group in self.self_roles],
        }

        if self.logger_webhook is not None:
            result["logger_webhook"] = self.logger_webhook
        if self.logger_webhook_ping is not None:
            result["logger_webhook_ping"] = self.to_str(self.logger_webhook_ping)
        if self.sleep_hours is not None:
            result["sleep_hours"] = self.sleep_hours.to_dict()
        if self.config_editor_password is not None:
            result["config_editor_password"] = self.config_editor_password
        if self.config_editor_host is not None:
            result["config_editor_host"] = self.config_editor_host
        if self.config_editor_port is not None:
            result["config_editor_port"] = self.config_editor_port

        return result

    def save(self, path: Path | None = None) -> None:
        if path is None:
            path = get_config_path()

        with path.open("w", encoding="utf-8") as f:
            f.write(json5.dumps(self.to_dict(), indent=4))

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        data = data.copy()
        data.pop("config_editor", None)

        pings_data = data.pop("pings", [])
        self_roles_data = data.pop("self_roles", [])
        sleep_hours_data = data.pop("sleep_hours", None)

        pings: list[PingConfig] = [PingConfig.from_dict(pd) for pd in pings_data]
        self_roles: list[SelfRoleGroup] = []
        sleep_hours: SleepHours | None = None

        for group_data in self_roles_data:
            roles = [SelfRole.from_dict(role_data) for role_data in group_data.get("roles", [])]

            max_roles = 25
            if len(roles) > max_roles:
                msg = "A self-role group cannot have more than 25 roles due to Discord limitations."
                raise ValueError(msg)
            self_roles.append(SelfRoleGroup(title=group_data["title"], roles=roles))

        if sleep_hours_data:
            sleep_hours = SleepHours.from_dict(sleep_hours_data)

        for key in ["discord_guild_id", "admin_role_id", "logger_webhook_ping"]:
            if key in data:
                data[key] = Config.to_int(data[key])

        return cls(pings=pings, self_roles=self_roles, sleep_hours=sleep_hours, **data)

    @staticmethod
    def from_json(json_str: str) -> "Config":
        data = json5.loads(json_str)
        return Config.from_dict(data)  # pyright: ignore[reportArgumentType]

    def to_json(self) -> str:
        return json5.dumps(self.to_dict(), indent=4)

    @staticmethod
    def load() -> "Config":
        data: dict = get_parsed_config()

        data.pop("$schema", None)
        data.pop("config_editor", None)

        data.pop("blocklist", None)
        data.pop("global_blocklist", None)

        pings_data = data.pop("pings", [])
        self_roles_data = data.pop("self_roles", [])
        sleep_hours_data = data.pop("sleep_hours", None)

        pings: list[PingConfig] = [PingConfig.from_dict(pd) for pd in pings_data]
        self_roles: list[SelfRoleGroup] = []
        sleep_hours: SleepHours | None = None

        for group_data in self_roles_data:
            roles = [SelfRole.from_dict(rd) for rd in group_data.get("roles", [])]

            max_roles = 25
            if len(roles) > max_roles:
                msg = "A self-role group cannot have more than 25 roles due to Discord limitations."
                raise ValueError(msg)
            self_roles.append(SelfRoleGroup(title=group_data["title"], roles=roles))

        if sleep_hours_data:
            sleep_hours = SleepHours.from_dict(sleep_hours_data)

        for key in ["discord_guild_id", "admin_role_id", "logger_webhook_ping"]:
            if key in data:
                data[key] = Config.to_int(data[key])

        return Config(pings=pings, self_roles=self_roles, sleep_hours=sleep_hours, **data)


def reload_config() -> Config:
    return Config.load()


def reload_global_blocklist() -> GlobalBlocklist:
    return GlobalBlocklist.load()
