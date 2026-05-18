import asyncio
import inspect
import sys
from typing import TYPE_CHECKING, Any

from modules import global_vars as gv
from modules.bot import bot
from modules.config_tools import reload_config, reload_global_blocklist
from modules.logger import logger
from modules.utils import sigint_current_process

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    SyncOrAsyncFunc = Callable[..., None] | Callable[..., Coroutine[Any, Any, Any]]


class CommandListener:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

        self.commands: Mapping[str, SyncOrAsyncFunc] = {
            self.prefix + key: func
            for keys, func in {
                ("reload", "r"): self._reload_config,
                ("start",): self._start,
                ("quit", "exit", "q!", "q", "qa", "wq"): self._exit,
            }.items()
            for key in keys
        }

    async def start(self) -> None:
        """
        Listens for defined commands via `stdin` and executes functions accordingly
        """

        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break

                stripped = line.strip()
                matched = False

                for command, function in self.commands.items():
                    if stripped == command:
                        matched = True
                        if inspect.iscoroutinefunction(function):
                            await function()
                        else:
                            function()
                        break

                    if stripped.startswith(command + " "):
                        matched = True
                        args = stripped[(len(command) + 1) :].split()
                        if inspect.iscoroutinefunction(function):
                            await function(*args)
                        else:
                            function(*args)
                        break

                if not matched and stripped.startswith(self.prefix):
                    logger.warning(f"Unknown command: {stripped}")

            except Exception:
                logger.exception("Error in command listener:")
                await asyncio.sleep(1)

    def _reload_config(self) -> None:
        logger.info("Reloading config and global blocklist...")

        gv.config = reload_config()
        gv.global_blocklist = reload_global_blocklist()

        logger.info("Reloaded!")

    def _exit(self) -> None:
        logger.info("Exiting application.")
        sigint_current_process()

    async def _start(self) -> None:
        if not gv.config.start_on_command:
            logger.warning("Scraper auto-starts when start_on_command is disabled in config.")
            return

        if bot.scraper_running:
            logger.warning("Scraper is already running!")
            return

        started = await bot.start_scraper()
        if started:
            logger.info("eBay scraper started successfully!")
