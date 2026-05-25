import asyncio
import importlib
import inspect
import os
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from modules import config_editor
from modules import global_vars as gv
from modules.bot import bot
from modules.config_editor import authentication as config_editor_auth
from modules.config_tools import reload_config, reload_global_blocklist
from modules.logger import logger
from modules.utils import sigint_current_process

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    Function = Callable[..., None] | Callable[..., Coroutine[Any, Any, Any]]


class CommandListener:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

        self.commands: Mapping[tuple[str, ...], Function] = {
            ("reload", "r"): self._reload_config,
            ("resetcookies", "rc"): self._reset_cookies,
            ("restartws", "reloadws", "rws"): self._restart_web_server,
            ("quit", "qa", "q", "q!", "exit"): self._exit,
            ("help", "h"): self._print_help,
        }

        if gv.config.start_on_command:
            self.commands[("start",)] = self._start_scraper

        self.resolved_commands: Mapping[str, Function] = {
            self.prefix + key: func for keys, func in self.commands.items() for key in keys
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

                for command, function in self.resolved_commands.items():
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
        """Reloads config and global blocklist from disk"""
        logger.info("Reloading config and global blocklist...")

        gv.config = reload_config()
        gv.global_blocklist = reload_global_blocklist()

        logger.info("Reloaded!")

    def _reset_cookies(self) -> None:
        """Resets all config editor sessions"""
        session_version = config_editor_auth.reset_all_sessions()
        logger.info(
            "Reset all config editor sessions via stdin command; new session version is %s.",
            session_version,
        )

    async def _restart_web_server(self) -> None:
        """
        Restarts config editor web server, and applies any code changes, without restarting the app
        """
        logger.info("Restarting config editor web server...")

        await config_editor.stop()
        logger.debug("Stopped web server")

        modules: list[str] = []
        for item in (Path(__file__).parent / "config_editor").iterdir():
            if not item.is_file() or item.suffix != ".py" or item.stem.startswith("_"):
                continue
            modules.append(f"modules.config_editor.{item.stem}")
        modules.append("modules.config_editor")
        logger.debug(f"Identified {len(modules)} modules to reload")

        for idx, module_name in enumerate(modules):
            module = sys.modules.get(module_name)
            if module is not None:
                importlib.reload(module)
                logger.debug(f"Reloaded module #{idx + 1}: `{module_name}`")

        asyncio.create_task(config_editor.start())  # noqa: RUF006
        logger.debug("Sent start() request to web server")

        logger.info("Config editor web server restarted successfully.")

    def _exit(self) -> None:
        """
        Exits the app via a SIGINT signal. Equivalent to Ctrl+C; sometimes works better depending on terminal
        """  # noqa: E501
        logger.info("Exiting application. (note: try pressing \"enter\" if the app doesn't close)")
        sigint_current_process()

    async def _start_scraper(self) -> None:
        """Starts the eBay scraper if not already running."""
        if not gv.config.start_on_command:
            logger.warning("Scraper auto-starts when start_on_command is disabled in config.")
            return

        if bot.scraper_running:
            logger.warning("Scraper is already running!")
            return

        started = await bot.start_scraper()
        if started:
            logger.info("eBay scraper started successfully!")

    def _print_help(self) -> None:
        """Shows this message."""
        try:
            term_width = os.get_terminal_size().columns
        except Exception:
            term_width = 80

        msg = " Available Commands "
        padding = "=" * ((term_width - len(msg)) // 2)
        print("\n" + padding + msg + padding + "\n")
        for aliases, function in self.commands.items():
            doc = "\n    ".join(textwrap.wrap(
                function.__doc__.strip() if function.__doc__ else "No description",
                width=term_width - 10 if term_width - 10 > 20 else 70,  # noqa: PLR2004
            ))

            print(f"• {', '.join(aliases)}\n    \x1b[38;5;245m{doc}\x1b[0m\n")

        print("=" * term_width + "\n\n")
