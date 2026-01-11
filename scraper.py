#!/usr/bin/env python3

import sys
import asyncio
import inspect
import modules.ebay_api as ebay_api
from modules import global_vars as gv
from modules.config_tools import reload_config
from modules.logger import logger
from modules.bot import bot as discord_bot
from typing import Callable, Coroutine, Any
from modules.utils import sigint_current_process


async def command_listener() -> None:
    """
    Listens for defined commands via `stdin` and executes functions accordingly
    """

    prefix = ":"

    def _reload_config() -> None:
        logger.info("Reloading configuration...")
        gv.config = reload_config()
        logger.info("Configuration reloaded!")

    def _exit() -> None:
        logger.info("Exiting application.")
        sigint_current_process()

    async def _start() -> None:
        if not gv.config.start_on_command:
            logger.warning("Scraper auto-starts when start_on_command is disabled in config.")
            return
        if hasattr(discord_bot, '_scraper_running') and discord_bot._scraper_running:
            logger.warning("Scraper is already running!")
            return
        started = await discord_bot.start_scraper()
        if started:
            logger.info("eBay scraper started successfully!")

    raw_commands: dict[tuple[str, ...], Callable[..., None] | Callable[..., Coroutine[Any, Any, Any]]] = {
        ("reload",): _reload_config,
        ("start",): _start,
        ("quit", "exit", "q!", "q", "qa", "wq"): _exit
    }

    commands: dict[str, Callable[..., Any]] = {}

    for keys, func in raw_commands.items():
        for key in keys:
            commands[prefix + key] = func

    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break

            stripped = line.strip()
            matched = False

            for command, function in commands.items():
                if stripped == command:
                    matched = True
                    if inspect.iscoroutinefunction(function):
                        await function()
                    else:
                        function()
                    break
                elif stripped.startswith(command + " "):
                    matched = True
                    args = stripped[(len(command) + 1):].split()
                    if inspect.iscoroutinefunction(function):
                        await function(*args)
                    else:
                        function(*args)
                    break

            if not matched and stripped.startswith(prefix):
                logger.warning(f"Unknown command: {stripped}")

        except Exception:
            logger.exception("Error in command listener:")
            await asyncio.sleep(1)


async def start_discord_bot() -> None:
    """Starts the Discord bot."""

    try:
        await discord_bot.start(gv.config.discord_bot_token)
    except Exception:
        raise


async def run_main() -> None:
    """
    Starts the main components of the app:
    - the Discord bot (which starts the scraper once connected)
    - the stdin command listener
    """
    tasks = []
    logger.info("Starting Discord bot...")
    tasks.append(asyncio.create_task(start_discord_bot()))

    logger.info("Starting stdin command listener...")
    tasks.append(asyncio.create_task(command_listener()))

    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        logger.info("Exiting app. There may be missing logs in Discord if the logging queue was not emptied.")
        sys.exit(0)
    except Exception:
        logger.exception("An unexpected error occurred in the main loop! Details:")
        sys.exit(1)
    finally:
        try:
            asyncio.run(ebay_api.close_http_client())
        except Exception:
            pass
