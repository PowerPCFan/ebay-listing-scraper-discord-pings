import asyncio
import textwrap
import logging
import discord
from discord import app_commands
from discord.ext import commands
from .logger import logger, setLevelValue
from .config_tools import PingConfig, reload_config, SelfRoleGroup
from .ebay_api import EbayItem
from .enums import DealTuple, Emojis
from . import global_vars as gv
from . import ebay_api
from . import modes
from typing import cast
from pathlib import Path
from .utils import (
    create_discord_timestamp,
    format_price,
    get_ebay_seller_url,
    get_listing_type_display,
    build_shipping_embed_value,
    sigint_current_process
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

        self.admin_list = "Error retrieving admins!"
        self.notification_channels = {}

    async def on_ready(self) -> None:
        logger.info(f'Logged in as {self.user}')

        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.custom,
            name="test test test"
        ))

        logger.info("Syncing command tree...")

        # Sync to specific guild and get admin list
        guild = self.get_guild(gv.config.discord_guild_id)
        if guild:
            await self.tree.sync(guild=guild)
            admin_role = guild.get_role(1447247941889691872)
            if admin_role:
                admins = [member.mention for member in admin_role.members]
                self.admin_list = ", ".join(admins) if admins else "No admins found!"

        # Sync globally just in case the guild sync doesn't work for whatever reason
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
            inline=True
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


class SelfRoleView(discord.ui.View):
    def __init__(self, role_group: SelfRoleGroup):
        super().__init__(timeout=None)
        self.role_group = role_group

        for i, role in enumerate(role_group.roles):
            button = SelfRoleButton(role.name, role.id, i)
            self.add_item(button)


class SelfRoleButton(discord.ui.Button):
    def __init__(self, role_name: str, role_id: int, index: int):
        super().__init__(
            label=role_name,
            style=discord.ButtonStyle.secondary,
            row=index // 5
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        guild = cast(discord.Guild, interaction.guild)

        role = guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(
                content=(
                    f"Error retrieving role {self.role_id}."
                    f"Please contact one of the following administrators: {bot.admin_list}"
                ),
                ephemeral=True
            )
            return

        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message(
                content=(
                    f"I was unable to find an account with user ID {interaction.user.id}."
                    f"Please contact an admin for further assistance: {bot.admin_list}"
                ),
                ephemeral=True
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(f"Removed {role.mention}!", ephemeral=True)
            else:
                await member.add_roles(role)
                await interaction.response.send_message(f"Added {role.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Uh-oh, I don't have permission to manage your roles!",
                ephemeral=True
            )
        except Exception:
            logger.exception(f"Error managing role {role.name} for user {interaction.user}:")
            await interaction.response.send_message(f"An error occurred while managing your role. Please contact one of the following admins for assistance: {bot.admin_list}", ephemeral=True)  # noqa: E501


def setup_commands(bot: EbayScraperBot):
    if gv.config.bot_debug_commands:
        @bot.tree.command(name='reload-command', description="Reload a bot command")
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

    @bot.tree.command(name='start', description="Start the eBay listing scraper (when in start_on_command mode)")
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

    @bot.tree.command(name='reload-config', description="Reload the script's config.json file")
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

    @bot.tree.command(name='estimate-daily-api-calls', description="Estimate the number of eBay API calls made per day based on current config")  # noqa: E501
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

    @bot.tree.command(name='ping', description="Measure bot latency")
    @commands.has_permissions(administrator=True)
    async def ping_command(interaction: discord.Interaction):
        await interaction.response.send_message(f"Pong! Delay: {round(bot.latency * 1000)}ms", ephemeral=True)

    @bot.tree.command(name='config-summary', description="Create a summary of the bot's config.json")
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

    @bot.tree.command(name='pause', description="Pause the eBay listing scraper at the end of the current interval")
    @commands.has_permissions(administrator=True)
    async def pause_command(interaction: discord.Interaction):
        if gv.scraper_paused:
            await interaction.response.send_message("Scraper is already paused.", ephemeral=True)
            return

        gv.scraper_paused = True
        embed = discord.Embed(
            title="Scraper Paused",
            description="The scraper will pause after the current polling interval ends. Use /resume to continue, and use /force-stop to immediately quit the bot and scraper. (This will require a manual restart!)",  # noqa: E501
            color=0xffa500,
            timestamp=discord.utils.utcnow()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("eBay scraper paused via Discord command")

    @bot.tree.command(name='resume', description="Resume the scraper (if it's paused)")
    @commands.has_permissions(administrator=True)
    async def resume_command(interaction: discord.Interaction):
        if not gv.scraper_paused:
            await interaction.response.send_message("Scraper is not paused.", ephemeral=True)
            return

        gv.scraper_paused = False
        embed = discord.Embed(
            title="Scraper Resumed",
            description="The scraper has been resumed.",
            color=0x00ff00,
            timestamp=discord.utils.utcnow()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("eBay scraper resumed via Discord command")

    @bot.tree.command(name='force-stop', description="Force quit the script (Dangerous!)")
    @commands.has_permissions(administrator=True)
    async def force_stop_command(interaction: discord.Interaction):
        embed = discord.Embed(
            title="Force Stop",
            description="Forcing application shutdown...",
            color=0xff0000,
            timestamp=discord.utils.utcnow()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.warning("Force stop initiated via Discord command! If this was unintentional, there may be permissions issues with the force stop command.")  # noqa: E501

        # kill after sending message
        sigint_current_process()

    @bot.tree.command(name='generate-self-role-picker', description="Generate self role pickers in the current channel")
    @commands.has_permissions(administrator=True)
    async def generate_self_role_picker(interaction: discord.Interaction):
        pickers_path = Path(__file__).parent.parent / "pickers.txt"
        pickers_path.parent.mkdir(parents=True, exist_ok=True)
        pickers_path.touch(exist_ok=True)

        # load existing pickers to delete them before adding new ones
        with open(pickers_path, "r", encoding="utf-8") as f:
            old_picker_ids = [int(line) for line in f if line.strip()]

        for picker_id in old_picker_ids:
            try:
                old_message = await cast(discord.TextChannel, interaction.channel).fetch_message(picker_id)
                await old_message.delete()
                logger.info(f"Deleted old self role picker message with ID {picker_id}")
            except Exception:
                logger.warning(f"Could not delete old self role picker message with ID {picker_id}")

        channel_to_send_pickers_in = cast(discord.TextChannel, interaction.channel)
        picker_ids = []

        if not gv.config.self_roles:
            await interaction.response.send_message("No self role groups configured.", ephemeral=True)
            return

        for i, role_group in enumerate(gv.config.self_roles):
            logger.info(f"Generating self role picker for group {i + 1}: {role_group.title}")

            embed = discord.Embed(
                title=f"{role_group.title}",
                description="Click the buttons below to add or remove roles.",
                color=0x5865f2,
                timestamp=discord.utils.utcnow()
            )

            role_names = [f"- {role.name}" for role in role_group.roles]
            if role_names:
                embed.add_field(
                    name="Available Roles",
                    value="\n".join(role_names),
                    inline=False
                )

            view = SelfRoleView(role_group)

            msg = await channel_to_send_pickers_in.send(embed=embed, view=view)
            picker_ids.append(msg.id)
            logger.info(f"Generated self role picker for group: {role_group.title}")

        # overwrite file with new ids
        with open(pickers_path, "w", encoding="utf-8") as f:
            for pid in picker_ids:
                f.write(f"{pid}\n")

        await interaction.response.send_message(content="Done!", ephemeral=True)

    @bot.tree.command(name='help', description="Show the bot's help message")
    async def help_command(interaction: discord.Interaction):
        # auto-generate a bullet list of every command
        msg = "# Commands\n\n"
        for command in bot.tree.walk_commands():
            msg += f"- /{command.name}{': ' + command.description if command.description else ''}\n"

        await interaction.response.send_message(content=msg, ephemeral=True)


bot = EbayScraperBot()
setup_commands(bot)
