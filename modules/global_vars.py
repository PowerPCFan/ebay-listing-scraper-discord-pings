from .config_tools import Config
from .rolepicker_config_tools import RolePickerStates

config: Config = Config.load()
role_picker_states: RolePickerStates = RolePickerStates.load()

api_call_count: int = 0  # self explanatory, amount of api calls per interval
limit: int = 200  # max is 200, anything above will return no results + error 400
scraper_paused: bool = False  # boolean flag to pause scraper with commands at end of polling interval

last_scrape_time: float | None = None
scraper_was_running: bool = False
