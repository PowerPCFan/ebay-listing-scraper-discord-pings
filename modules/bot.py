import asyncio
import logging
import discord
import time
from datetime import datetime, timezone, timedelta
from discord.ext import commands
from discord import app_commands
from urllib.parse import quote
from .logger import logger, discordPyLevelValue
from .config_tools import PingConfig, reload_config, SelfRoleGroup, SelfRole
from .rolepicker_config_tools import RolePickerRole, RolePickerState
from .ebay_api import EbayItem
from .enums import ConditionEnum, DealTuple, Emojis, Match
from . import global_vars as gv
from . import ebay_api
from . import modes
from typing import cast, Literal
from .utils import (
    create_discord_timestamp,
    format_price,
    get_ebay_seller_url,
    get_listing_type_display,
    build_shipping_embed_value,
    sigint_current_process,
    restart_current_process,
    restart_current_process_2,
    change_status
)


custom_dedent = lambda t, s: "\n".join([l[s:] if l.startswith(" " * s) else l for l in t.splitlines()])  # noqa: E731, E741, E501


class NotificationToggleButton(discord.ui.Button):
    def __init__(self, role_id: int):
        super().__init__(
            label="Toggle Notifications",
            style=discord.ButtonStyle.primary,
            custom_id=f"NotificationToggleButton{role_id}",
            emoji="🔔"
        )
        self.role_id: int = role_id

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            logger.warning("Interaction expired for notification toggle button")
            try:
                await interaction.followup.send(
                    content="Interaction failed. Please try again.",
                    ephemeral=True
                )
            except Exception:
                logger.warning("Failed to send followup message for expired interaction")
            return
        except Exception as e:
            logger.error(f"Failed to defer interaction: {e}")
            return

        member = interaction.user
        guild = interaction.guild

        if not isinstance(member, discord.Member):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Error",
                    description="Could not fetch your member information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if not guild:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Error",
                    description="Could not fetch guild information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        role = guild.get_role(self.role_id)

        if not role:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Role Not Found",
                    description="The notification role could not be found in this server.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Notifications Disabled",
                        description=f"You have disabled notifications for {role.mention}.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            elif role not in member.roles:
                await member.add_roles(role)
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Notifications Enabled",
                        description=f"You have enabled notifications for {role.mention}.",
                        color=discord.Color.green()
                    ),
                    ephemeral=True
                )
            else:
                raise Exception("Unexpected role state.")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Permissions Error",
                    description="The bot does not have permission to manage your roles.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.exception("Error toggling notification role:")
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Error",
                    description=f"An unexpected error occurred: {type(e).__name__}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )


class ListingButtonView(discord.ui.View):
    def __init__(self, item: EbayItem, ping_config: PingConfig):
        super().__init__(timeout=None)
        self.item = item
        self.ping_config = ping_config

        self.add_notification_toggle_button()
        self.add_share_button()

    def add_share_button(self):
        encoded_url = quote(self.item.url, safe='')
        encoded_name = quote(self.item.title, safe='')
        share_url = (
            "https://www.powerpcfan.xyz/ebay-listing-scraper-discord-pings-internal/"
            f"share-sheet?url={encoded_url}&name={encoded_name}"
        )

        button = discord.ui.Button(
            label="Share Listing",
            style=discord.ButtonStyle.link,
            url=share_url,
            emoji="🔗"
        )
        self.add_item(button)

    def add_notification_toggle_button(self):
        button = NotificationToggleButton(role_id=self.ping_config.role)
        self.add_item(button)


class EbayScraperBot(commands.Bot):
    def __init__(self):
        self._scraper_running = False
        self._persistent_views: dict[int, dict] = {}

        intents = discord.Intents.default()
        intents.message_content = True

        discord_logger = logging.getLogger('discord')
        discord_logger.handlers = []
        for handler in logger.handlers:
            discord_logger.addHandler(handler)
        discord_logger.setLevel(discordPyLevelValue)

        # i'm not using the voice version of discord.py and i'm also not using VoiceClient
        # but for some reason it's still yelling at me in logs
        # which is why this line exists
        discord.VoiceClient.warn_nacl = False

        super().__init__(
            command_prefix="e!",
            intents=intents,
            help_command=None
        )

        self.admin_list: str | None = None
        self.notification_channels = {}

    async def on_ready(self) -> None:
        logger.info(f'Logged in as {self.user}')

        logger.info("Syncing command tree...")

        # Sync to specific guild and get admin list
        guild = self.get_guild(gv.config.discord_guild_id)
        if guild:
            await self.tree.sync(guild=guild)
            admin_role = guild.get_role(gv.config.admin_role_id)
            if admin_role:
                admins = [member.mention for member in admin_role.members]
                self.admin_list = ", ".join(admins) if admins else None

        # Sync globally just in case the guild sync doesn't work for whatever reason
        await self.tree.sync()

        # Leave all servers except allowed ones in config
        # to make sure people can't do things like force quit my bot with the admin commands
        for guild in bot.guilds:
            if guild.id != gv.config.discord_guild_id:
                logger.warning(f"Bot was invited to an unauthorized guild, {guild.name} ({guild.id}). Leaving guild...")
                await guild.leave()

        # Set up persistent role pickers
        await self.setup_persistent_role_pickers()

        logger.info("Bot ready! Starting eBay scraper...")

        logger.debug("Connecting to eBay API...")
        await change_status(bot=self, logger=logger, message="Connecting to eBay API...")
        initialized = await ebay_api.initialize()

        if not initialized:
            logger.critical("Failed to initialize eBay API. Bot will remain online but scraping is disabled.")
            await change_status(bot=self, logger=logger, emoji="❌", message="eBay API connection failed")
            return
        else:
            logger.info("Successfully connected to eBay API!")

        if (not gv.config.start_on_command or gv.scraper_was_running) and gv.last_scrape_time is not None:
            if gv.last_scrape_time > 0:
                elapsed = time.time() - gv.last_scrape_time
                remaining = max(0, gv.config.poll_interval_seconds - elapsed)

                if remaining > 5:
                    logger.info(f"Preserving interval timing - waiting {remaining:.0f}s before next scrape...")
                    await asyncio.sleep(remaining)

            await self.start_scraper()
        else:
            logger.info("Scraper ready but waiting for start command. Use /start (Discord) or :start (Terminal)")
            await change_status(bot=self, logger=logger, message="Idling (use /start to begin scraping)")

    async def setup_persistent_role_pickers(self):
        """Sets up persistent role picker views (survives bot restarts) from the role picker states file"""
        logger.info("Setting up persistent role picker views...")

        try:
            gv.role_picker_states = gv.role_picker_states.load()
            persistent_states = gv.role_picker_states.states

            views_added = 0
            invalid_roles = []

            self._persistent_views.clear()

            for state in persistent_states:
                try:
                    valid_roles = []
                    for role_data in state.roles:
                        guild = self.get_guild(gv.config.discord_guild_id)
                        if guild and guild.get_role(role_data.id):
                            valid_roles.append(SelfRole(name=role_data.name, id=role_data.id))
                        else:
                            invalid_roles.append(f"{role_data.name} (ID: {role_data.id})")

                    if valid_roles:
                        role_group = SelfRoleGroup(title=state.title, roles=valid_roles)
                        view = SelfRoleView(role_group)

                        for message_id in state.message_ids:
                            self.add_view(view, message_id=message_id)
                            self._persistent_views[message_id] = {
                                'view': view,
                                'role_group': role_group,
                                'created_at': state.created_at
                            }
                        views_added += 1

                except Exception as e:
                    logger.error(f"Failed to restore role picker for {state.title}: {e}")

            if invalid_roles:
                logger.warning(f"Found {len(invalid_roles)} deleted/invalid roles: {', '.join(invalid_roles)}")

            logger.info(f"Successfully restored {views_added} persistent role picker views")

        except Exception as e:
            logger.warning(f"Failed to load persistent role pickers: {e}. Creating fresh views from config...")
            await self._fallback_to_config_views()

    async def save_picker_state_from_messages(self, message_ids: list[int], role_groups: list[SelfRoleGroup]):
        """Saves role picker states based on message IDs and role groups"""
        states = []
        for i, role_group in enumerate(role_groups):
            if i < len(message_ids):
                roles = [RolePickerRole(name=role.name, id=role.id) for role in role_group.roles]
                state = RolePickerState(
                    title=role_group.title,
                    roles=roles,
                    message_ids=[message_ids[i]],
                    created_at=datetime.now(tz=timezone.utc).isoformat()
                )
                states.append(state)

        # Update global states and save
        try:
            gv.role_picker_states.states = states
            gv.role_picker_states.save()
            logger.info(f"Saved persistent state for {len(states)} role picker groups")
        except Exception:
            logger.exception("Failed to save role picker states:")

    async def _fallback_to_config_views(self):
        """Fallback function to recreate views from the config file, if loading persistent states fails"""
        logger.info("Using fallback: creating views from current config...")

        for role_group in gv.config.self_roles:
            view = SelfRoleView(role_group)
            self.add_view(view)
            logger.debug(f"Added fallback view for role group: {role_group.title}")

        logger.info(f"Created {len(gv.config.self_roles)} fallback role picker views")

    async def start_scraper(self) -> bool:
        """Starts the eBay scraper, if it's not already running"""
        if self._scraper_running:
            logger.warning("Scraper is already running!")
            return False

        logger.info("Starting eBay monitoring...")
        self._scraper_running = True
        gv.scraper_was_running = True
        await change_status(bot=self, logger=logger, message="Starting scraper...")
        asyncio.create_task(modes.match(self))
        return True

    async def send_listing_notification(
        self,
        item: EbayItem,
        ping_config: PingConfig,
        deal: DealTuple,
        match_object: Match
    ) -> None:
        channel_id = ping_config.channel_id
        if not channel_id:
            logger.warning(f"No channel_id configured for {ping_config.category_name}")
            return

        channel = cast(discord.TextChannel, self.get_channel(channel_id))
        if not channel:
            logger.error(f"Could not find channel with ID {channel_id}")
            return

        embed, view = self.create_listing_embed_with_buttons(item, deal, ping_config, match_object)

        mention = f"<@&{ping_config.role}>"

        try:
            await channel.send(content=mention, embed=embed, view=view)
            logger.debug(f"Sent Discord notification for {ping_config.category_name}")
        except discord.Forbidden:
            logger.error(f"No permission to send messages in channel {channel.name}")
        except Exception:
            logger.exception("Error sending notification:")

    def create_listing_embed_with_buttons(
        self,
        item: EbayItem,
        deal: DealTuple,
        ping_config: PingConfig,
        match_object: Match
    ) -> tuple[discord.Embed, ListingButtonView]:
        view = ListingButtonView(item, ping_config)
        embed = self.create_listing_embed(item, deal, match_object)
        return embed, view

    def create_listing_embed(
        self,
        item: EbayItem,
        deal: DealTuple,
        match_object: Match
    ) -> discord.Embed:
        shipping = item.shipping[0] if item.shipping else None
        feedback_score = item.seller.feedback_score if item.seller.feedback_score is not None else "Unknown"
        condition = item.condition.name if (item.condition is not None and item.condition.name is not None) else "Unknown"  # noqa: E501
        price = format_price(price=item.price.value, currency=item.price.currency)

        embed = discord.Embed(
            color=deal.color,
            title=item.title,
            url=item.url,
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"{deal.emoji} {deal.name}")

        embed.add_field(
            name=f"{Emojis.PRICE} Price:",
            value=f"**{price}**",
            inline=True
        )

        embed.add_field(
            name=f"{Emojis.CONDITION} Condition:",
            value=f"**{condition}**",
            inline=True
        )

        embed.add_field(
            name=f"{Emojis.SHIPPING} Shipping:",
            value=build_shipping_embed_value(shipping),
            inline=True
        )

        embed.add_field(
            name=f"{Emojis.PRICE} Criteria:",
            value="\n".join([
                f"- Max Price: **{format_price(match_object.max_price)}**",
                f"- Min Price: **{format_price(match_object.min_price)}**",
                f"- Target Price: **{format_price(match_object.target_price)}**",
                # f"- Regex: `{match_object.regex}`"
            ])
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
            text=f"Friendly Name: \"{match_object.friendly_name}\"  •  Item ID: {item.item_id}",
            # todo: find a better way to host this, maybe github or discord or my website or something
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
        self.button_id = f"SelfRoleButton{role_id}"
        super().__init__(
            label=role_name,
            style=discord.ButtonStyle.secondary,
            row=index // 5,
            custom_id=self.button_id
        )
        self.role_id: int = role_id
        self.role_name: str = role_name

    async def callback(self, interaction: discord.Interaction):
        guild = cast(discord.Guild, interaction.guild)

        role = guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Role Deleted",
                    description=(
                        f"The role `{self.role_name}` (ID: {self.role_id}) has been deleted from this server.\n",
                        "Please contact one of the following administrators, "
                        f"and provide them with a screenshot of this message: {bot.admin_list}"
                    )
                ),
                ephemeral=True
            )
            logger.warning(f"Role picker button {self.button_id} tried to assign the deleted role {self.role_id} to user {interaction.user.id}")  # noqa: E501
            return

        try:
            member = guild.get_member(interaction.user.id)
            if not member:
                member = await guild.fetch_member(interaction.user.id)
        except discord.NotFound:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Account Not Found",
                    description=(
                        f"An account with user ID `{interaction.user.id}` was not found.\n"
                        f"Please contact an admin for further assistance: {bot.admin_list}"
                    )
                ),
                ephemeral=True
            )
            return
        except Exception:
            logger.exception(f"Error fetching member {interaction.user.id}:")
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Fetching Error",
                    description=(
                        f"An error occurred while fetching your account information. "
                        f"Please contact an admin for further assistance: {bot.admin_list}"
                    )
                ),
                ephemeral=True
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Role Removed",
                        description=f"Successfully removed {role.mention} from {member.mention}!",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                logger.info(f"Removed role @{role.name} from user @{member.name}")
            else:
                await member.add_roles(role)
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Role Added",
                        description=f"Successfully added {role.mention} to {member.mention}!",
                        color=discord.Color.green()
                    ),
                    ephemeral=True
                )
                logger.info(f"Added role @{role.name} to user @{member.name}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permissions Error",
                    description=f"There was a permissions error when trying to add/remove the role {role.mention} to you ({member.mention}). "  # noqa: E501
                ),
                ephemeral=True
            )
        except Exception:
            logger.exception(f"Error managing role {role.name} for user {member.name}:")
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Unexpected Error",
                    description=(
                        "An error occurred while managing your role. "
                        f"Please contact one of the following admins for assistance: {bot.admin_list}",
                    )
                ),
                ephemeral=True
            )


def setup_commands(bot: EbayScraperBot):
    if gv.config.bot_debug_commands:
        @bot.tree.command(name='restart-bot', description="[WARNING: Very buggy!] Restart the bot")
        @app_commands.describe(method="Method to use for restarting the bot. 'replace' replaces the process and 'spawn' starts a new one and then kills the current one.")  # noqa: E501
        @commands.is_owner()
        async def restart_bot_command(interaction: discord.Interaction, method: Literal["replace", "spawn"]) -> None:
            try:
                logger.info("Restarted bot via Discord")

                embed = discord.Embed(
                    title="Bot Restarting",
                    description="The bot is restarting now...",
                    color=discord.Color.orange()
                )

                if method == "replace":
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    restart_current_process()
                elif method == "spawn":
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    restart_current_process_2()
                else:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Invalid Method",
                            description="The specified restart method is invalid.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
            except Exception as e:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Bot Restart Failed",
                        description=f"Failed to restart: {type(e).__name__}",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                logger.error(f"Failed to restart bot via Discord /restart-bot: {e}")

    @bot.tree.command(name='start', description="Start the eBay listing scraper (when in start_on_command mode)")
    @commands.is_owner()
    async def start_command(interaction: discord.Interaction):
        if not gv.config.start_on_command:
            embed = discord.Embed(
                title="Cannot Start",
                description="Scraper auto-starts when `start_on_command` is disabled in config.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        started = await bot.start_scraper()
        if started:
            embed = discord.Embed(
                title="Scraper Started",
                description="eBay listing scraper started successfully!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
        else:
            embed = discord.Embed(
                title="Already Running",
                description="Scraper is already running.",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name='reload-config', description="Reload the script's config.json file")
    @commands.is_owner()
    async def reload_config_command(interaction: discord.Interaction):
        try:
            gv.config = reload_config()

            embed = discord.Embed(
                title="Configuration Reloaded",
                description="Successfully reloaded configuration.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            logger.info("Configuration reloaded via /reload-config command")

        except Exception as e:
            embed = discord.Embed(
                title="Configuration Reload Failed",
                description=f"Error: {str(e)}",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.error(f"Failed to reload config via Discord: {e}")

    @bot.tree.command(name='estimate-daily-api-calls', description="Estimate the number of eBay API calls made per day based on current config")  # noqa: E501
    @commands.is_owner()
    async def estimate_daily_api_calls_command(interaction: discord.Interaction):
        try:
            all_categories = set()
            for ping in gv.config.pings:
                all_categories.update(ping.categories)

            unique_categories = len(all_categories)
            poll_interval_seconds = gv.config.poll_interval_seconds

            seconds_per_day = 24 * 60 * 60

            active_seconds_per_day = seconds_per_day
            sleep_hours_info = ""

            if gv.config.sleep_hours:
                try:
                    start_dt = datetime.fromisoformat(f"1970-01-01T{gv.config.sleep_hours.start}:00")
                    end_dt = datetime.fromisoformat(f"1970-01-01T{gv.config.sleep_hours.end}:00")

                    start_time = start_dt.timetz()
                    end_time = end_dt.timetz()

                    if start_time <= end_time:
                        # Same day sleep period
                        start_datetime = datetime.combine(datetime.min, start_time.replace(tzinfo=None))
                        end_datetime = datetime.combine(datetime.min, end_time.replace(tzinfo=None))
                        sleep_timedelta = end_datetime - start_datetime
                        sleep_duration = sleep_timedelta.total_seconds()
                    else:
                        # Sleep period crosses midnight
                        start_datetime = datetime.combine(datetime.min, start_time.replace(tzinfo=None))
                        end_datetime = datetime.combine(datetime.min, end_time.replace(tzinfo=None))
                        midnight = datetime.combine(datetime.min + timedelta(days=1), datetime.min.time())
                        sleep_timedelta = (midnight - start_datetime) + (end_datetime - datetime.combine(datetime.min, datetime.min.time()))  # noqa: E501
                        sleep_duration = sleep_timedelta.total_seconds()

                    active_seconds_per_day = seconds_per_day - sleep_duration
                    sleep_hours_duration = sleep_duration / 3600
                    sleep_hours_info = f"\n- **Sleep hours:** {sleep_hours_duration:.1f}h ({gv.config.sleep_hours.start[:-6]} to {gv.config.sleep_hours.end[:-6]} - UTC Offset {gv.config.sleep_hours.start[-6:]})"  # noqa: E501
                except Exception:
                    pass

            polls_per_day = active_seconds_per_day / poll_interval_seconds
            api_calls_per_day = polls_per_day * unique_categories

            minutes_between_polls = poll_interval_seconds / 60
            hours_between_polls = poll_interval_seconds / 3600
            active_hours_per_day = active_seconds_per_day / 3600

            embed = discord.Embed(
                title="Stats",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow(),
                description=(
                    f"- **Active hours per day:** {active_hours_per_day:.1f}h{sleep_hours_info}\n"
                    f"- **Polls per day:** {polls_per_day:.1f}\n"
                    f"- **Minutes between polls:** {minutes_between_polls:.1f}\n"
                    f"- **API calls per poll:** {unique_categories}\n"
                    f"- **API calls per day:** {api_calls_per_day:.0f}"
                )
            )

            rate_limit = 5000

            if api_calls_per_day > rate_limit:
                embed.add_field(
                    name="⚠️ Warning",
                    value=(
                        f"{api_calls_per_day:.0f} calls/day exceeds eBay's rate limit of {rate_limit} calls/day.\n"
                        "Consider increasing the poll interval, reducing the number of categories, or lengthening sleep hours."  # noqa: E501
                    )
                )
            elif api_calls_per_day > rate_limit * 0.8:
                embed.add_field(
                    name="⚠️ Warning",
                    value=(
                        f"{api_calls_per_day:.0f} calls/day is nearing eBay's rate limit of {rate_limit} calls/day.\n"
                        "Consider increasing the poll interval, reducing the number of categories, or lengthening sleep hours."  # noqa: E501
                    )
                )
            else:
                embed.add_field(
                    name="✅ Within Limit",
                    value=f"{api_calls_per_day:.0f} calls/day is within eBay's rate limit of {rate_limit} calls/day. {Emojis.NICE}"  # noqa: E501
                )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Calculation Error",
                    description=f"Error calculating daily API calls: {type(e).__name__}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
            )

    @bot.tree.command(name='ping', description="Measure bot latency")
    async def ping_command(interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Pong!",
                description=f"Delay: {round(bot.latency * 1000)}ms"
            )
        )

    # @bot.tree.command(name='view-config', description="Send the contents of the bot's config.json")
    # @commands.is_owner()
    # async def view_config_command(interaction: discord.Interaction):
    #     try:
    #         file = discord.File(
    #             io.BytesIO(config_tools.get_raw_config().encode('utf-8')),
    #             filename="summary.txt"
    #         )

    #         await interaction.response.send_message(
    #             content="This file contains sensitive information. Do not share it!",
    #             file=file,
    #             ephemeral=True
    #         )

    #     except Exception as e:
    #         await interaction.response.send_message(
    #             embed=discord.Embed(
    #                 title="Error",
    #                 description=f"Error retrieving config: {type(e).__name__}",
    #                 color=discord.Color.red(),
    #                 timestamp=discord.utils.utcnow()
    #             ),
    #             ephemeral=True
    #         )

    @bot.tree.command(name='config-summary', description="Send a summary of the current bot configuration")
    @commands.is_owner()
    async def config_summary_command(interaction: discord.Interaction, ephemeral: bool = True):
        try:
            embed = discord.Embed(title="Config Summary", color=discord.Color.blurple())

            embed.add_field(
                name="Boolean Flags",
                value="\n".join([
                    f"- **Debug Mode:** `{gv.config.debug_mode}`",
                    f"- **Discord.py Debug Mode:** `{gv.config.discord_py_debug_mode}`",
                    f"- **Log API Responses:** `{gv.config.log_api_responses}`",
                    f"- **File Logging:** `{gv.config.file_logging}`",
                    f"- **Ping for Warnings:** `{gv.config.ping_for_warnings}`",
                    f"- **Start on Command:** `{gv.config.start_on_command}`",
                    f"- **Bot Debug Commands:** `{gv.config.bot_debug_commands}`",
                    f"- **Include Shipping in Deal Evaluation:** `{gv.config.include_shipping_in_deal_evaluation}`",
                    f"- **Include Shipping in Price Filters:** `{gv.config.include_shipping_in_price_filters}`"
                ])
            )

            embed.add_field(
                name="Polling Settings",
                value="\n".join([
                    f"- **Poll Interval:** {gv.config.poll_interval_seconds}s ({f"{(gv.config.poll_interval_seconds / 60):.0f}" if (gv.config.poll_interval_seconds / 60).is_integer() else f"{(gv.config.poll_interval_seconds / 60):.1f}"} minutes)",  # noqa: E501
                    f"- **Sleep Hours:** {gv.config.sleep_hours.start[:-6] if gv.config.sleep_hours else 'N/A'} to {gv.config.sleep_hours.end[:-6] if gv.config.sleep_hours else 'N/A'} (UTC Offset {gv.config.sleep_hours.start[-6:] if gv.config.sleep_hours else 'N/A'})"  # noqa: E501
                ])
            )

            embed.add_field(
                name="Discord Settings",
                value="\n".join([
                    f"- **Logging to Webhook:** {'Enabled' if gv.config.logger_webhook else 'Disabled'}",
                    f"- **Logger Webhook Ping:** <@{gv.config.logger_webhook_ping}>",
                    f"- **Discord Guild ID:** `{gv.config.discord_guild_id}`",
                    f"- **Admin Role ID:** <@&{gv.config.admin_role_id}>"
                ])
            )

            embed.add_field(
                name="Keyword Blocklist",
                value="\n".join("- " + item for item in gv.config.global_blocklist)
            )

            embed.add_field(
                name="Seller Blocklist",
                value="\n".join("- " + item for item in gv.config.seller_blocklist)
            )

            embed.add_field(
                name="Condition Blocklist",
                value="\n".join(f"- `{ConditionEnum(cid)._name_}` (`{cid}`)" for cid in gv.config.condition_blocklist)
            )

            embed.add_field(
                name="Self Roles",
                value="\n".join(f"- <@&{role.id}>" for self_role in gv.config.self_roles for role in self_role.roles)
            )

            embed.add_field(
                name="Pings",
                value="\n".join([
                    f"- **Amount of Pings:** {len(gv.config.pings)}",
                    f"- **Categories:**\n{'\n'.join(f'  - {ping.category_name}' for ping in gv.config.pings)}"
                ])
            )

            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description=f"Error generating config summary: {type(e).__name__}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                ),
                ephemeral=ephemeral
            )

    @bot.tree.command(name='pause', description="Pause the eBay listing scraper at the end of the current interval")
    @commands.is_owner()
    async def pause_command(interaction: discord.Interaction):
        if gv.scraper_paused:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Scraper Already Paused",
                    description="The scraper is already paused.",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                ),
                ephemeral=True
            )
            return

        gv.scraper_paused = True
        embed = discord.Embed(
            title="Scraper Paused",
            description="The scraper will pause after the current polling interval ends. Use /resume to continue, and use /force-stop to immediately quit the bot and scraper. (This will require a manual restart!)",  # noqa: E501
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("eBay scraper paused via Discord command")

    @bot.tree.command(name='resume', description="Resume the scraper (if it's paused)")
    @commands.is_owner()
    async def resume_command(interaction: discord.Interaction):
        if not gv.scraper_paused:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Scraper Not Paused",
                    description="The scraper is not paused.",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                ),
                ephemeral=True
            )
            return

        gv.scraper_paused = False
        embed = discord.Embed(
            title="Scraper Resumed",
            description="The scraper has been resumed.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("eBay scraper resumed via Discord command")

    @bot.tree.command(name='force-stop', description="Force quit the script")
    @commands.is_owner()
    async def force_stop_command(interaction: discord.Interaction):
        base_interaction = interaction

        view = discord.ui.View(timeout=120)

        class ConfirmButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="Confirm", style=discord.ButtonStyle.danger)

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer()
                await base_interaction.edit_original_response(
                    embed=discord.Embed(
                        title="Force Stop",
                        description="Forcing application shutdown...",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    ),
                    view=None
                )

                await asyncio.sleep(1.0)

                await base_interaction.edit_original_response(
                    embed=discord.Embed(
                        title="Application Stopped",
                        description="The application has been successfully stopped.",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    ),
                    view=None
                )

                logger.warning(f"Force stop initiated by {base_interaction.user} via Discord command! If this was unintentional, there may be permissions issues with the force stop command.")  # noqa: E501

                sigint_current_process()

        view.add_item(ConfirmButton())

        await base_interaction.response.send_message(
            embed=discord.Embed(
                title="Confirm Force Stop",
                description="Are you sure you want to force stop the application? This will immediately `SIGINT` the bot and scraper. Click the **Confirm** button below to proceed.",  # noqa: E501
                color=discord.Color.red(),
            ),
            view=view,
            ephemeral=True
        )

    @bot.tree.command(name='generate-self-role-picker', description="Generate self role pickers in the current channel")
    @commands.is_owner()
    async def generate_self_role_picker_command(interaction: discord.Interaction):
        gv.role_picker_states = gv.role_picker_states.load()

        old_picker_ids = []
        for state in gv.role_picker_states.states:
            old_picker_ids.extend(state.message_ids)

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
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Self Role Groups Configured",
                    description="There are no self role groups configured.",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                ),
                ephemeral=True
            )
            return

        for i, role_group in enumerate(gv.config.self_roles):
            logger.info(f"Generating self role picker for group {i + 1}: {role_group.title}")

            embed = discord.Embed(
                title=f"{role_group.title}",
                description="Click the buttons below to add or remove roles.",
                color=discord.Color.blurple(),
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

        await bot.save_picker_state_from_messages(picker_ids, gv.config.self_roles)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Pickers Generated",
                description="Self role pickers have been successfully generated and sent in this channel.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            ),
            ephemeral=True
        )


bot = EbayScraperBot()
setup_commands(bot)
