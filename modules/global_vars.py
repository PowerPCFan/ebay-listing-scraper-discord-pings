from .config_tools import Config
import asyncio

config = Config.load()

api_call_count = 0
limit = 200  # max is 200, anything above will return no results + error 400

scraper_paused = asyncio.Event()
scraper_paused.set()
