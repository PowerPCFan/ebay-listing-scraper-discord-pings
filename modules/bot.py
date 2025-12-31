import asyncio
import textwrap
import logging
import discord
from discord import app_commands
from discord.ext import commands
from .logger import logger, setLevelValue
from .config_tools import PingConfig, reload_config
from .ebay_api import EbayItem
from .enums import DealTuple, Emojis
from . import global_vars as gv
from . import ebay_api
from . import modes
from typing import cast
from .utils import (
    create_discord_timestamp,
    format_price,
    get_ebay_seller_url,
    get_listing_type_display,
    build_shipping_embed_value
)


custom_dedent = lambda t, s: "\n".join([l[s:] if l.startswith(" " * s) else l for l in t.splitlines()])  # noqa: E731, E741, E501


async def print_new_listing(item: EbayItem, ping_config: PingConfig, deal: DealTuple) -> None:
    logger.debug(f"Sending Discord notification for {ping_config.category_name}")

    try:
        channel = cast(discord.TextChannel, bot.get_channel(ping_config.channel_id))

        if channel:
            embed = bot.create_listing_embed(item, deal)
            mention = f"<@&{ping_config.role}>" if ping_config.role else ""
            await channel.send(content=mention, embed=embed)
            return
    except Exception:
        logger.exception("Failed to send via bot:")


class EbayScraperBot(commands.Bot):
    def __init__(self):
        self._scraper_running = False

        intents = discord.Intents.default()
        intents.message_content = True

        discord_logger = logging.getLogger('discord')
        discord_logger.handlers = []
        for handler in logger.handlers:
            discord_logger.addHandler(handler)
        discord_logger.setLevel(setLevelValue)

        super().__init__(
            command_prefix="e!",
            intents=intents,
            help_command=None
        )

        self.notification_channels = {}

    async def on_ready(self) -> None:
        logger.info(f'Logged in as {self.user}')

        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.custom,
            name="test test test"
        ))

        logger.info("Syncing command tree...")

        # Sync to specific guild
        guild = self.get_guild(gv.config.discord_guild_id)
        if guild:
            await self.tree.sync(guild=guild)

        # Sync globally
        await self.tree.sync()

        logger.info("Bot ready! Starting eBay scraper...")

        logger.debug("Connecting to eBay API...")
        initialized = await ebay_api.initialize()

        if not initialized:
            logger.critical("Failed to initialize eBay API. Bot will remain online but scraping is disabled.")
            return
        else:
            logger.info("Successfully connected to eBay API!")

        if not gv.config.start_on_command:
            await self.start_scraper()
        else:
            logger.info("Scraper ready but waiting for start command. Use /start (Discord) or :start (Terminal)")

    async def start_scraper(self) -> bool:
        if self._scraper_running:
            logger.warning("Scraper is already running!")
            return False

        logger.info("Starting eBay monitoring...")
        self._scraper_running = True
        asyncio.create_task(modes.match(self))
        return True

    async def send_listing_notification(self, item: EbayItem, ping_config: PingConfig, deal: DealTuple):
        channel_id = ping_config.channel_id
        if not channel_id:
            logger.warning(f"No channel_id configured for {ping_config.category_name}")
            return

        channel = cast(discord.TextChannel, self.get_channel(channel_id))
        if not channel:
            logger.error(f"Could not find channel with ID {channel_id}")
            return

        embed = self.create_listing_embed(item, deal)

        mention = f"<@&{ping_config.role}>"

        try:
            await channel.send(content=mention, embed=embed)
            logger.debug(f"Sent Discord notification for {ping_config.category_name}")
        except discord.Forbidden:
            logger.error(f"No permission to send messages in channel {channel.name}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    def create_listing_embed(
        self,
        item: EbayItem,
        deal: DealTuple
    ) -> discord.Embed:
        shipping = item.shipping[0] if item.shipping else None
        feedback_score = item.seller.feedback_score if item.seller.feedback_score is not None else "Unknown"
        condition = item.condition.name if (item.condition is not None and item.condition.name is not None) else "Unknown"  # noqa: E501
        price = format_price(item.price.value) + " " + (item.price.currency or "USD")

        embed = discord.Embed(
            color=deal.color,
            title=item.title,
            url=item.url,
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"{deal.emoji} {deal.name}")

        embed.add_field(
            name=f"{Emojis.PRICE} Price:",
            value=price,
            inline=True
        )

        embed.add_field(
            name=f"{Emojis.CONDITION} Condition:",
            value=condition,
            inline=True
        )

        embed.add_field(
            name=f"{Emojis.SHIPPING} Shipping:",
            value=build_shipping_embed_value(shipping),
            inline=False
        )

        embed.add_field(
            name=f"{Emojis.SELLER} Seller:",
            value=(
                f"- Username: [{item.seller.username}]({get_ebay_seller_url(item.seller.username)})\n"
                f"- **{feedback_score}** feedback score\n"
                f"- **{item.seller.feedback_percentage}%** positive feedback"
            ),
            inline=False,
        )

        embed.add_field(
            name=f"{Emojis.CALENDAR} Date Posted:",
            value=create_discord_timestamp(item.date_posted),
            inline=False
        )

        embed.add_field(
            name=f"{Emojis.LISTING_TYPE} Listing Type(s):",
            value=get_listing_type_display(item.buying_options),
            inline=False
        )

        embed.set_footer(
            text=f"eBay Item ID: {item.item_id}",
            icon_url="https://i.ibb.co/Cs9ZFL2C/Untitled-drawing-1.png",
        )

        if item.main_image:
            embed.set_thumbnail(url=item.main_image)

        return embed


def setup_commands(bot: EbayScraperBot):
    if gv.config.bot_debug_commands:
        @bot.tree.command(name='reload-command')
        @commands.has_permissions(administrator=True)
        @app_commands.describe(command="The name of the command to reload")
        async def reload_command(interaction: discord.Interaction, command: str) -> None:
            try:
                await bot.unload_extension(f'commands.{command}')
                await bot.load_extension(f'commands.{command}')
                await interaction.response.send_message(
                    content=f"Reloaded command: {command}",
                    ephemeral=True
                )
                logger.info(f"Reloaded command: {command} via Discord")
            except Exception as e:
                await interaction.response.send_message(
                    content=f"Failed to reload commands.{command}: {str(e)}",
                    ephemeral=True
                )
                logger.error(f"Failed to reload command: {command} via Discord: {e}")

    @bot.tree.command(name='start')
    @commands.has_permissions(administrator=True)
    async def start_command(interaction: discord.Interaction):
        if not gv.config.start_on_command:
            embed = discord.Embed(
                title="Cannot Start",
                description="Scraper auto-starts when `start_on_command` is disabled in config.",
                color=0xff0000,
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        started = await bot.start_scraper()
        if started:
            embed = discord.Embed(
                title="Scraper Started",
                description="eBay listing scraper started successfully!",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
        else:
            embed = discord.Embed(
                title="Already Running",
                description="Scraper is already running.",
                color=0xffaa00,
                timestamp=discord.utils.utcnow()
            )
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name='reload-config')
    @commands.has_permissions(administrator=True)
    async def reload_config_command(interaction: discord.Interaction):
        try:
            gv.config = reload_config()

            embed = discord.Embed(
                title="Configuration Reloaded",
                description="Successfully reloaded configuration.",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            logger.info("Configuration reloaded via /reload-config command")

        except Exception as e:
            embed = discord.Embed(
                title="Configuration Reload Failed",
                description=f"Error: {str(e)}",
                color=0xff0000,
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.error(f"Failed to reload config via Discord: {e}")

    @bot.tree.command(name='estimate-daily-api-calls')
    @commands.has_permissions(administrator=True)
    async def estimate_daily_api_calls_command(interaction: discord.Interaction):
        try:
            all_categories = set()
            for ping in gv.config.pings:
                all_categories.update(ping.categories)

            unique_categories = len(all_categories)
            poll_interval_seconds = gv.config.poll_interval_seconds

            seconds_per_day = 24 * 60 * 60
            polls_per_day = seconds_per_day / poll_interval_seconds
            api_calls_per_day = polls_per_day * unique_categories

            minutes_between_polls = poll_interval_seconds / 60
            hours_between_polls = poll_interval_seconds / 3600

            message = textwrap.dedent(f"""\
                ## Stats
                - **Polls per day:** {polls_per_day:.1f}
                - **Minutes between polls:** {minutes_between_polls:.1f}
                - **API calls per poll:** {unique_categories}
                - **API calls per day:** {api_calls_per_day:.0f}
            """)

            rate_limit = 5000

            if api_calls_per_day > rate_limit:
                message += textwrap.dedent(f"""\
                    ### ⚠️ Warning
                    {api_calls_per_day:.0f} API calls per day exceeds eBay's rate limit of {rate_limit} calls/day.
                    Consider increasing the poll interval or reducing the number of categories.
                """)

            await interaction.response.send_message(content=message, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                content=f"Error calculating: {str(e)}",
                ephemeral=True
            )

    @bot.tree.command(name='ping')
    @commands.has_permissions(administrator=True)
    async def ping_command(interaction: discord.Interaction):
        await interaction.response.send_message(f"Pong! Delay: {round(bot.latency * 1000)}ms", ephemeral=True)

    @bot.tree.command(name='config-summary')
    @commands.has_permissions(administrator=True)
    async def config_command(interaction: discord.Interaction):
        try:
            config_summary = "## Config Summary\n\n"

            config_summary += custom_dedent(f"""\
                - Debug Mode: {gv.config.debug_mode}
                - Log API Responses: {gv.config.log_api_responses}
                - File Logging: {gv.config.file_logging}
                - Ping for Warnings: {gv.config.ping_for_warnings}
                - Start on Command: {gv.config.start_on_command}
                - Bot Debug Commands: {gv.config.bot_debug_commands}
                - Poll Interval: {gv.config.poll_interval_seconds} seconds


                - Global Blocklist Patterns:{'\n  - '.join([""] + gv.config.global_blocklist) if gv.config.global_blocklist else None}


                - Seller Blocklist Patterns:{'\n  - '.join([""] + gv.config.seller_blocklist) if gv.config.seller_blocklist else None}


                - Ping Configs:
            """, 16)  # noqa: E501, W293

            for ping in gv.config.pings:
                config_summary += custom_dedent(f"""\
                  - {ping.category_name}:
                    - Keywords:\
                """, 16)  # noqa: W293

                for keyword in ping.keywords:
                    config_summary += custom_dedent(f"""\

                      - {keyword.keyword}:
                        - Min Price: {keyword.min_price or 'None'}
                        - Max Price: {keyword.max_price or 'None'}\
                    """, 16)  # noqa: W293

                    if keyword.deal_ranges:
                        config_summary += custom_dedent(f"""\
                        - Deal Ranges:
                          - Fire Deal: {keyword.deal_ranges.fire_deal or 'None'}
                          - Great Deal: {keyword.deal_ranges.great_deal or 'None'}
                          - Good Deal: {keyword.deal_ranges.good_deal or 'None'}
                          - OK Deal: {keyword.deal_ranges.ok_deal or 'None'}
                        """, 16)

                config_summary += custom_dedent(f"""
                    - Categories: {', '.join(str(ctg) for ctg in ping.categories) if ping.categories else 'None'}
                    - Channel ID: {ping.channel_id or 'None'}
                    - Role: {ping.role or 'None'}
                """, 16)  # noqa: W293

            with open("aaaa.txt", "w", encoding="utf-8") as f:
                f.write(config_summary)

            await interaction.response.send_message(content=config_summary, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                content=f"Error retrieving config: {str(e)}",
                ephemeral=True
            )

    @bot.tree.command(name='help')
    async def help_command(interaction: discord.Interaction):
        # auto-generate a bullet list of every command
        msg = "# Commands\n\n"
        for command in bot.tree.walk_commands():
            msg += f"- /{command.name}\n"

        await interaction.response.send_message(content=msg, ephemeral=True)


bot = EbayScraperBot()
setup_commands(bot)
