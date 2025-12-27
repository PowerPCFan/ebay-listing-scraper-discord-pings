#!/usr/bin/env python3

import sys
import traceback
from modules.logger import logger
import modules.ebay_api as ebay_api
import modules.modes as modes
import modules.discord as discord
from modules.global_vars import config


def main() -> None:
    logger.info("Initializing eBay Listing Scraper...")

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
    if config.send_test_webhooks:
        logger.info("Testing webhooks...")

        for ping in config.pings:
            webhook_url = ping.webhook
            category_name = ping.category_name

            logger.debug(f"Testing webhook for category: {category_name}")
            discord.send_webhook(
                webhook_url=webhook_url,
                content=f"Script started. This is a test webhook for the '{category_name}' category.",
                embed=None,
                username=f"Testing Webhook: {category_name}",
                raise_exception_instead_of_print=config.debug_mode
            )

        logger.info("All webhooks tested successfully.")

    # print welcome text
    logger.newline()
    logger.info("eBay Listing Scraper (Discord Pings Edition) starting...")
    logger.info(f"eBay App ID: {config.ebay_app_id[:5]}...{config.ebay_app_id[-5:]}")
    logger.info(f"Debug Mode: {config.debug_mode}")
    logger.info(f"Full Tracebacks: {config.full_tracebacks}")
    logger.info(f"Send Test Webhooks: {config.send_test_webhooks}")
    logger.info(f"Ping for Warnings: {config.ping_for_warnings}")
    logger.info(f"File Logging: {config.file_logging}")
    logger.info(f"Poll Interval: {config.poll_interval_seconds} seconds")
    logger.info(f"Configured {len(config.pings)} ping categories")
    logger.info(f"Configured global blocklist with {len(config.global_blocklist)} patterns")
    logger.info("Press Ctrl+C to exit")
    logger.newline()

    # Start matching mode
    logger.info("Starting listing monitoring...")
    modes.match()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Exiting app. There may be missing logs in Discord if the logging queue was not emptied.")
        sys.exit(0)
    except Exception as e:
        logger.critical("An unexpected error occurred!")
        logger.error(f"Error details: {str(e)}")

        if config.full_tracebacks:
            logger.error("Full traceback:")
            # traceback.print_exception(type(e), e, e.__traceback__)
            for line in traceback.format_exception(type(e), e, e.__traceback__):
                logger.error(line.strip())

        sys.exit(1)
