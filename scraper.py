#!/usr/bin/env python3

import sys
import threading
import modules.ebay_api as ebay_api
import modules.modes as modes
import modules.discord as discord
from modules import global_vars
from modules.config_tools import reload_config
from modules.logger import logger
from typing import Callable


def command_listener() -> None:
    def _reload_config() -> None:
        logger.info("Reloading configuration...")
        global_vars.config = reload_config()
        logger.info("Configuration reloaded!")
        print_config_summary()

    commands: dict[str, Callable[..., None]] = {
        "reload": _reload_config
    }
    commands = {(":" + k): v for k, v in commands.items()}

    for line in sys.stdin:
        stripped = line.strip()
        for command, function in commands.items():
            if stripped == command:
                function()
                break
            elif stripped.startswith(command + " "):
                function(*stripped[(len(command) + 1):].split())
                break


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


def main() -> None:
    logger.info("Initializing eBay Listing Scraper...")

    print_config_summary()

    # init eBay API
    logger.debug("Connecting to eBay API...")
    initialized = ebay_api.initialize()

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
            discord.send_webhook(
                webhook_url=webhook_url,
                content=f"Script started. This is a test webhook for the '{category_name}' category.",
                embed=None,
                username=f"Testing Webhook: {category_name}",
                raise_exception_instead_of_print=global_vars.config.debug_mode
            )

        logger.info("All webhooks tested successfully.")

    logger.info("Script fully started. Monitoring listings...")
    modes.match()


if __name__ == "__main__":
    try:
        if global_vars.config.commands:
            # Start Command Listener Thread
            threading.Thread(target=command_listener, daemon=True).start()

        # Run Main Loop
        main()
    except KeyboardInterrupt:
        logger.info("Exiting app. There may be missing logs in Discord if the logging queue was not emptied.")
        sys.exit(0)
    except Exception as e:
        logger.exception("An unexpected error occurred in the main loop! Details:")
        sys.exit(1)
