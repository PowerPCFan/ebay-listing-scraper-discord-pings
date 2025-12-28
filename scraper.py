#!/usr/bin/env python3

import sys
import asyncio
import modules.ebay_api as ebay_api
import modules.modes as modes
import modules.discord as discord
from modules import global_vars
from modules.config_tools import reload_config
from modules.logger import logger
from typing import Callable


async def command_listener() -> None:
    prefix = ":"

    def _reload_config() -> None:
        logger.info("Reloading configuration...")
        global_vars.config = reload_config()
        logger.info("Configuration reloaded!")
        print_config_summary()

    def _pause_scraper() -> None:
        global_vars.scraper_paused.clear()
        logger.info("Scraper paused. Use '!resume' in the console to continue.")

    def _resume_scraper() -> None:
        global_vars.scraper_paused.set()
        logger.info("Scraper resumed.")

    def _exit() -> None:
        logger.info("Exiting application.")
        sys.exit(0)

    raw_commands: dict[tuple[str, ...], Callable[..., None]] = {
        ("reload",): _reload_config,
        ("pause", "stop"): _pause_scraper,
        ("resume", "play", "start"): _resume_scraper,
        ("quit", "exit", "q!", "q", "qa", "wq"): _exit
    }

    commands: dict[str, Callable[..., None]] = {}

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
                    function()
                    break
                elif stripped.startswith(command + " "):
                    matched = True
                    function(*stripped[(len(command) + 1):].split())
                    break

            if not matched and stripped.startswith(prefix):
                logger.warning(f"Unknown command: {stripped}")

        except Exception as e:
            logger.error(f"Error in command listener: {e}")
            await asyncio.sleep(1)


def print_config_summary() -> None:
    # uses print since this doesn't really need to go to the log file or discord webhook
    print("\n\nCurrent Configuration Summary:")

    print(f"  - Debug Mode: {global_vars.config.debug_mode}")
    print(f"  - Log API Responses: {global_vars.config.log_api_responses}")
    print(f"  - Send Test Webhooks: {global_vars.config.send_test_webhooks}")
    print(f"  - File Logging: {global_vars.config.file_logging}")
    print(f"  - Ping for Warnings: {global_vars.config.ping_for_warnings}")

    print(f"  - Poll Interval: {global_vars.config.poll_interval_seconds} seconds")

    print(f"  - Global Blocklist Patterns: {'\n    - '.join([""] + global_vars.config.global_blocklist) if global_vars.config.global_blocklist else None}")  # noqa: E501
    print(f"  - Seller Blocklist Patterns: {'\n    - '.join([""] + global_vars.config.seller_blocklist) if global_vars.config.seller_blocklist else None}")  # noqa: E501

    print(f"  - Loaded Ping Configs: {len(global_vars.config.pings)} (Parse Mode: {len([p for p in global_vars.config.pings if p.mode == modes.Mode.PARSE])}, Query Mode: {len([p for p in global_vars.config.pings if p.mode == modes.Mode.QUERY])})")  # noqa: E501

    print("\n\n", end="")


async def main() -> None:
    logger.info("Initializing eBay Listing Scraper...")

    print_config_summary()

    # init eBay API
    logger.debug("Connecting to eBay API...")
    initialized = await ebay_api.initialize()

    if not initialized:
        logger.critical("Failed to initialize eBay API. Exiting.")
        sys.exit(1)
    else:
        logger.info("Successfully connected to eBay API!")

    # if send_test_webhooks is enabled, test every webhook
    # will raise exception if one webhook fails so then it will be caught in the main handler
    if global_vars.config.send_test_webhooks:
        logger.info("Testing webhooks...")

        for ping in global_vars.config.pings:
            webhook_url = ping.webhook
            category_name = ping.category_name

            logger.debug(f"Testing webhook for category: {category_name}")
            await discord.send_webhook(
                webhook_url=webhook_url,
                content=f"Script started. This is a test webhook for the '{category_name}' category.",
                embed=None,
                username=f"Testing Webhook: {category_name}",
                raise_exception_instead_of_print=global_vars.config.debug_mode
            )

        logger.info("All webhooks tested successfully.")

    logger.info("Script fully started. Monitoring listings...")
    await modes.match()


async def run_main():
    tasks = []

    if global_vars.config.commands:
        logger.debug("Starting command listener task...")
        tasks.append(asyncio.create_task(command_listener()))

    tasks.append(asyncio.create_task(main()))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        # Run Async Main Loop
        asyncio.run(run_main())
    except KeyboardInterrupt:
        logger.info("Exiting app. There may be missing logs in Discord if the logging queue was not emptied.")
        sys.exit(0)
    except Exception as e:
        logger.exception("An unexpected error occurred in the main loop! Details:")
        sys.exit(1)
    finally:
        try:
            asyncio.run(ebay_api.close_http_client())
        except Exception:
            pass
