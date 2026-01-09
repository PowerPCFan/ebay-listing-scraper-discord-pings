from .config_tools import Config
from .rolepicker_config_tools import RolePickerStates

config = Config.load()
role_picker_states = RolePickerStates.load()

api_call_count = 0  # self explanatory, amount of api calls per interval
limit = 200  # max is 200, anything above will return no results + error 400
scraper_paused = False  # boolean flag to pause scraper with commands at end of polling interval
