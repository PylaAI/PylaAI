import asyncio
import time
from io import BytesIO

from discord import app_commands
import discord
from PIL import Image
from utils import load_toml_as_dict
from window_controller import WindowController
try:
    from early_access.early_access import register_early_access_commands
    early_access = True
except ImportError:
    early_access = False
    def register_early_access_commands(a):
        pass


TIMEOUT = 300


class DiscordBot:
    def __init__(self, runtime_manager, data_service):
        self.runtime_manager = runtime_manager
        self.data_service = data_service
        self.window_controller: WindowController = None
        self.started = False
        self.commands_synced = False

        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self.register_events()
        self.register_commands()
        register_early_access_commands(self)

    def set_window_controller(self, window_controller):
        self.window_controller = window_controller

    @staticmethod
    def _extract_discord_id(value):
        digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    def get_authorized_user_id(self):
        config = load_toml_as_dict("cfg/webhook_config.toml", cache=False)
        return self._extract_discord_id(config.get("discord_id", ""))

    def get_configured_guild_id(self):
        guild_id = str(load_toml_as_dict("cfg/webhook_config.toml", cache=False).get("discord_guild_id", "")).strip()
        if not guild_id:
            return None

        try:
            return int(guild_id)
        except ValueError:
            print(f"Invalid discord_guild_id in cfg/webhook_config.toml: {guild_id}")
            return None

    def get_configured_guild(self):
        guild_id = self.get_configured_guild_id()
        if not guild_id:
            return None

        return discord.Object(id=guild_id)

    async def require_authorized_user(self, interaction: discord.Interaction) -> bool:
        authorized_id = self.get_authorized_user_id()
        if authorized_id is None:
            return True

        if interaction.user.id == authorized_id:
            return True

        await interaction.response.send_message(
            "You are not authorized to use this command.",
            ephemeral=True
        )
        return False

    async def sync_commands(self):
        guild = self.get_configured_guild()
        if guild:
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
            return len(commands), "guild"

        commands = await self.tree.sync()
        return len(commands), "global"

    def register_events(self):
        @self.client.event
        async def on_ready():
            print(f"Discord bot logged in as {self.client.user}")
            if self.commands_synced:
                return

            configured_guild_id = self.get_configured_guild_id()
            if configured_guild_id:
                guild = discord.Object(id=configured_guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"Discord slash commands synced to guild {configured_guild_id}.")
            else:
                await self.tree.sync()
                print("Discord slash commands synced globally.")
            self.commands_synced = True

    def register_commands(self):
        @self.tree.command(
            name="screenshot",
            description="Get a screenshot of the current game window",
        )
        async def screenshot(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            if not self.window_controller:
                await interaction.response.send_message(
                    "Failed to take a screenshot, is the bot running ?",
                    ephemeral=True
                )
                return
            screenshot_frame = self.window_controller.screenshot()
            if screenshot_frame is None:
                await interaction.response.send_message(
                    "Failed to take a screenshot, is the bot running ?",
                    ephemeral=True
                )
                return

            screenshot_buffer = BytesIO()
            Image.fromarray(screenshot_frame).save(screenshot_buffer, format="PNG")
            screenshot_buffer.seek(0)

            await interaction.response.send_message(
                "Here's a screenshot of the current game window:",
                files=[discord.File(screenshot_buffer, filename="screenshot.png")],
                ephemeral=True
            )

        @self.tree.command(
            name="stop",
            description="Stops the bot once it finishes its current task",
        )
        async def stop(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            status = self.runtime_manager.get_status()
            if status.get("state") == "idle" or not status.get("is_running"):
                await interaction.response.send_message(
                    "The bot is not currently running.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "stopping":
                await interaction.response.send_message(
                    "The bot is already stopping, please wait.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "error":
                await interaction.response.send_message(
                    f"The bot is in an error state :\n{status['last_error']}\nPlease wait a few seconds or check the logs.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "pausing":
                await interaction.response.send_message(
                    "The bot is currently pausing, please wait before trying to stop it.",
                    ephemeral=True
                )
                return
            else:
                stop = self.runtime_manager.stop()
                await interaction.response.send_message(
                    f"{('Success' if stop.get('ok') else 'Failed')} ! {stop.get('message', '')}",
                    ephemeral=True
                )

                start_time = time.time()
                while time.time() - start_time < TIMEOUT:
                    status = self.runtime_manager.get_status()
                    if status.get("state") == "idle":
                        user_id = self.get_authorized_user_id()
                        await interaction.followup.send(
                            f"{('' if user_id is None else f'<@{user_id}> ')}The bot has stopped.",
                            ephemeral=True
                        )
                        return
                    elif status.get("state") != "stopping":
                        user_id = self.get_authorized_user_id()
                        await interaction.followup.send(
                            f"{('' if user_id is None else f'<@{user_id}> ')}The bot has unexpectedly stopped stopping. Current state: {status.get('state')}.",
                            ephemeral=True
                        )
                        return
                    await asyncio.sleep(1)

        @self.tree.command(
            name="pause",
            description="Makes the bot pause once it reaches the lobby",
        )
        async def pause(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            status = self.runtime_manager.get_status()
            if status.get("state") == "idle" or not status.get("is_running"):
                await interaction.response.send_message(
                    "The bot is not currently running.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "pausing":
                await interaction.response.send_message(
                    "The bot is already pausing, please wait.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "paused":
                await interaction.response.send_message(
                    "The bot is already paused.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "error":
                await interaction.response.send_message(
                    f"The bot is in an error state :\n{status['last_error']}\nPlease wait a few seconds or check the logs.",
                    ephemeral=True
                )
                return
            elif status.get("state") == "stopping":
                await interaction.response.send_message(
                    "The bot is currently stopping, pausing isn't available.",
                    ephemeral=True
                )
                return
            else:
                pause = self.runtime_manager.pause()
                await interaction.response.send_message(
                    f"{('Success' if pause.get('ok') else 'Failed')} ! {pause.get('message', '')}",
                    ephemeral=True
                )

                start_time = time.time()
                while time.time() - start_time < TIMEOUT:
                    status = self.runtime_manager.get_status()
                    if status.get("state") == "paused":
                        user_id = self.get_authorized_user_id()
                        await interaction.followup.send(
                            f"{('' if user_id is None else f'<@{user_id}> ')}The bot is now paused.",
                            ephemeral=True
                        )
                        return
                    elif status.get("state") != "pausing":
                        user_id = self.get_authorized_user_id()
                        await interaction.followup.send(
                            f"{('' if user_id is None else f'<@{user_id}> ')}The bot has unexpectedly stopped pausing. Current state: {status.get('state')}.",
                            ephemeral=True
                        )
                        return
                    await asyncio.sleep(1)


        @self.tree.command(
            name="start",
            description="Starts the bot if it's not already running",
        )
        async def start(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            start_result = self.runtime_manager.start_current_queue(self)
            await interaction.response.send_message(
                f"{('Success' if start_result.get('ok') else 'Failed')} ! {start_result.get('message', '')}",
                ephemeral=True
            )

        @self.tree.command(
            name="status",
            description="Returns the current status of the bot",
        )
        async def status(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            status = self.runtime_manager.get_status()
            if not status.get("is_running"):
                await interaction.response.send_message(
                    "The bot is currently not running.",
                    ephemeral=True
                )
                return

            state = status.get("state", "unknown").capitalize()
            last_error = status.get("last_error")
            message = f"The bot is currently **{state}**."
            if last_error:
                message += f"\nLast error: {last_error}"

            active_playstyle = self.data_service.get_playstyles_payload().get("current")
            playstyle_name = active_playstyle.get("name") if active_playstyle else None
            message += f"\n Playstyle : {playstyle_name or 'None'}"
            message += "\n Queue : do `/view_queue` to see the current queue."
            await interaction.response.send_message(
                message,
                ephemeral=True
            )

        @self.tree.command(
            name="restart_brawl_stars",
            description="Restarts Brawl Stars if the bot is running",
        )
        async def restart_brawl_stars(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            status = self.runtime_manager.get_status()
            if status.get("state") == "idle" or not status.get("is_running"):
                await interaction.response.send_message(
                    "The bot is not currently running.",
                    ephemeral=True
                )
                return
            await interaction.response.send_message(
                f"Restarting brawl stars !",
                ephemeral=True
            )
            self.window_controller.restart_brawl_stars()

        @self.tree.command(
            name="view_queue",
            description="View the current queue of the bot",
        )
        async def view_queue(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            queue = self.data_service.get_queue_data()
            if not queue:
                await interaction.response.send_message(
                    "The queue is currently empty.",
                    ephemeral=True
                )
                return

            message = "Current queue:\n"
            responded = False

            for queue_item in queue:
                brawler = queue_item.get("brawler", "Unknown")
                push_type = queue_item.get("type", "Unknown")
                target_amount = queue_item.get("push_until", "Unknown")
                current_amount = queue_item.get("trophies") if push_type == "trophies" else queue_item.get("wins")
                auto_pick = queue_item.get("automatically_pick", False)
                message += f"- {brawler} : {current_amount}/{target_amount} {push_type} {('(Automatically picked)' if auto_pick else '')}\n"

                if len(message) > 1500:
                    if not responded:
                        await interaction.response.send_message(message, ephemeral=True)
                        responded = True
                    else:
                        await interaction.followup.send(message, ephemeral=True)
                    message = ""

            if message:
                if not responded:
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)

        @self.tree.command(
            name="help",
            description="Show the list of available commands",
        )
        async def help_command(interaction: discord.Interaction):
            if not await self.require_authorized_user(interaction):
                return

            commands = {
                "screenshot": "Get a screenshot of the current game window (only works when the bot is running)",
                "stop": "Makes the bot stop once it reaches the lobby",
                "pause": "Makes the bot pause once it reaches the lobby",
                "start": "Starts the bot if it's not already running",
                "status": "Returns the current status of the bot",
                "restart_brawl_stars": "Restarts Brawl Stars if the bot is running",
                "view_queue": "View the current queue of the bot",
                "add_to_queue": ("**Premium Only :**" if not early_access else "") + "Add a brawler to the queue (only works when the bot is not running)",
                "remove_from_queue": ("**Premium Only :**" if not early_access else "") + "Remove a brawler from the queue (only works when the bot is not running)",
                "clear_queue": ("**Premium Only :**" if not early_access else "") + "Clear the current queue (only works when the bot is not running)",
                "push_all": ("**Premium Only :**" if not early_access else "") + "Add all brawlers below target trophies to the queue (only works when the bot is not running)",
                "switch_player_tag": ("**Premium Only :**" if not early_access else "") + "Switch or view the player tag for the current instance (only works when the bot is not running)",
                "activate_playstyle": ("**Premium Only Only :**" if not early_access else "") + "Activate a playstyle (only works when the bot is not running)",
            }
            message = "**Available commands:**\n" + "\n".join(f"- `{command}`: {description}" for command, description in commands.items())
            if not early_access:
                message += "\n\n**Unlock Premium:** Obtain the premium module to obtain access to additional features and commands. Check https://pyla-ai.angelfirela.dev/premium for more information."
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
    def run_bot(self):
        discord_bot_token = str(load_toml_as_dict("cfg/webhook_config.toml").get("discord_bot_token", "")).strip()
        if not discord_bot_token:
            print("Discord bot token is not configured. Skipping Discord bot startup.")
            return
        if self.started:
            return

        self.started = True
        try:
            self.client.run(discord_bot_token)
        finally:
            self.started = False
