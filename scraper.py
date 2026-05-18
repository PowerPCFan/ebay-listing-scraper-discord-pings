#!/usr/bin/env python3

import asyncio
import contextlib
import sys

from modules import ebay_api
from modules import global_vars as gv
from modules.bot import bot as discord_bot
from modules.command_listener import CommandListener
from modules.config_web_server import start_config_web_server
from modules.logger import logger


async def start_discord_bot() -> None:
    """Starts the Discord bot."""

    logger.info("Starting Discord bot... (scraper will start once bot connects)")

    await discord_bot.start(gv.config.discord_bot_token)


async def start_command_listener() -> None:
    """Starts the command listener."""

    logger.info("Starting stdin command listener...")

    listener = CommandListener(":")
    await listener.start()


async def run_main() -> None:
    """
    Starts the main components of the app
    """

    tasks = []

    tasks.append(asyncio.create_task(start_command_listener()))
    tasks.append(asyncio.create_task(start_discord_bot()))
    tasks.append(asyncio.create_task(start_config_web_server()))

    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        logger.info(
            "Exiting app. There may be missing logs in Discord "
            "if the logging queue was not emptied.",
        )
        sys.exit(0)
    except Exception:
        logger.exception("An unexpected error occurred in the main loop! Details:")
        sys.exit(1)
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(ebay_api.close_http_client())
