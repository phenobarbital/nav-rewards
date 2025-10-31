from datetime import datetime
from typing import Any, Optional
import asyncio
from aiohttp import web
from botbuilder.core import (
    TurnContext,
    CardFactory,
    MessageFactory
)
from botbuilder.dialogs import (
    DialogSet,
)
from navconfig import config
# Notify:
from notify import Notify
# Microsoft Teams
from notify.providers.teams import Teams
from notify.conf import (
    MS_TEAMS_TENANT_ID,
    MS_TEAMS_CLIENT_ID,
    MS_TEAMS_CLIENT_SECRET
)
from notify.models import (
    Actor,
    Chat,
    TeamsCard,
    TeamsChannel
)
from datamodel.exceptions import ValidationError
# Azure Team Bots:
from azure_teambots.bots.abstract import AbstractBot
from .dialogs.badge import BadgeDialog
from .dialogs.kudos import KudosDialog
from ..kudos.models import UserKudos
from ..kudos.handlers import extract_tag_names, update_tag_usage_counts
from ..models import User, UserReward, BadgeAssign, RewardView


class BadgeBot(AbstractBot):
    """Bot that handles badge assignment through interactive dialogs"""
    info_message: str = (
        "I'm the Badge Bot. 🏅\n"
        "Use '/help' to see all available commands! 🏅\n"
        "You can use '/badge' to award badges 🏅 or '/kudos' to send recognition! 🌟"  # noqa
    )

    def __init__(
        self,
        bot_name: str,
        app: web.Application,
        **kwargs
    ):
        # Set the command that triggers the badge dialog
        self.commands = [
            '/badge',
            '/give',
            '/help',
            '/leaderboard',
            '/badges',
            '/kudos',
        ]
        super().__init__(
            bot_name=bot_name,
            app=app,
            welcome_message=self.info_message,
            **kwargs
        )
        self._notification_tasks = set()
        self.notification_method: str = kwargs.get(
            'notification_method',
            'teams'
        )

        # Initialize the badge dialog
        self.badge_dialog = BadgeDialog(
            bot=self,
            submission_callback=self.handle_badge_submission
        )
        self.kudos_dialog = KudosDialog(
            bot=self,
            submission_callback=self.handle_kudos_submission
        )
        # Template System from Navapi:
        try:
            self.template_system = self.app['template']
        except KeyError:
            self.logger.warning(
                "Template system not found in app context, using default."
            )
            self.template_system = None

    def setup(self, app: web.Application):
        """Setup the bot with the application"""
        super().setup(app)

        # Add the badge dialog to the dialog set
        self.dialog_set = DialogSet(self.dialog_state)
        self.dialog_set.add(self.badge_dialog)
        self.dialog_set.add(self.kudos_dialog)

    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming message activities"""
        text = turn_context.activity.text

        # Check if this is a help command
        if text and text.lower().strip() == '/help':
            await self.send_help_card(turn_context)
            return

        # TODO: Add more commands as needed
        # leaderboard, badges, etc.

        # Check if this is a command
        if text and text.lower().strip() in [
            cmd.lower() for cmd in self.commands
        ]:
            command = text.lower().strip()
            # switch case based on the command:
            if command in ['/badge', '/give']:
                # Start the badge dialog
                await self.start_badge_dialog(turn_context)
                return
            elif command in ['/leaderboard']:
                await self.handle_leaderboard_command(turn_context)
                return
            elif command == '/kudos':
                await self.start_kudos_dialog(turn_context)
                return
            elif command == '/badges':
                await self.handle_mybadges_command(turn_context)
                return

        # Check if this is a dialog continuation (adaptive card submission)
        if turn_context.activity.value:
            await self.continue_dialog(turn_context)
            return

        # Default response for other messages
        await turn_context.send_activity(
            "Hi! I'm the Badge Bot. Use '/help' to see all available commands! 🏅"  # noqa
        )

    async def send_help_card(self, turn_context: TurnContext):
        """Send a help card with all available commands"""
        try:
            help_card = self.create_help_card()
            message = MessageFactory.attachment(help_card)
            await turn_context.send_activity(message)
        except Exception as e:
            self.logger.error(f"Error sending help card: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error showing the help. Please try again."  # noqa
            )

    def create_help_card(self) -> Any:
        """Create an adaptive card with help information"""
        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Badge Bot Help 🏅",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": "Here are all the available commands:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Container",
                    "items": [
                        self._create_command_row(
                            "/badge",
                            "Award a badge to a teammate"
                        ),
                        self._create_command_row(
                            "/kudos",
                            "Send recognition with tags to someone"
                        ),
                        self._create_command_row(
                            "/leaderboard",
                            "Show people with most badges"
                        ),
                        self._create_command_row(
                            "/badges",
                            "View all your received badges"
                        ),
                        self._create_command_row(
                            "/help",
                            "Show this help message"
                        )
                    ],
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": "💡 **Badge vs Kudos:** Badges are formal rewards with points, while kudos are quick recognition messages with tags!",  # noqa
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent",
                    "isSubtle": True
                }
            ]
        }
        return self.create_card(card_data)

    def _create_command_row(self, command: str, description: str) -> dict:
        """Helper to create a command row for the help card"""
        return {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "auto",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": command,
                            "weight": "Bolder",
                            "color": "Good"
                        }
                    ]
                },
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": description,
                            "wrap": True
                        }
                    ]
                }
            ]
        }

    async def handle_leaderboard_command(self, turn_context: TurnContext):
        """
        Handle /leaderboard command - show top 10 employees with most badges
        """
        try:
            # Get database connection
            db = self.app.get('database')
            if not db:
                await turn_context.send_activity(
                    "❌ Database connection not available.."
                )
                return

            async with await db.acquire() as conn:
                # Execute the leaderboard query
                query = """
                SELECT receiver_email, receiver_user, u.display_name,
                count(*) as number_of_rewards
                FROM rewards.users_rewards r
                JOIN auth.vw_users u ON u.user_id = r.receiver_user
                GROUP BY receiver_email, receiver_user, u.display_name
                ORDER BY number_of_rewards DESC
                LIMIT 10
                """

                results = await conn.fetch_all(query)

                if not results:
                    await turn_context.send_activity(
                        "📊 No badge data available yet. Start awarding badges to see the leaderboard!"  # noqa
                    )
                    return

                # Create the leaderboard adaptive card
                card = self._create_leaderboard_card(
                    [dict(row) for row in results]
                )
                message = MessageFactory.attachment(card)
                await turn_context.send_activity(message)

        except Exception as e:
            self.logger.error(f"Error handling leaderboard command: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error retrieving the leaderboard. Please try again."  # noqa
            )

    def _create_leaderboard_card(self, leaderboard_data: list) -> Any:
        """Create an adaptive card for the badge leaderboard"""

        # Medal emojis for top 3
        medals = ["🥇", "🥈", "🥉"]

        # Create leaderboard items
        leaderboard_items = []

        for i, employee in enumerate(leaderboard_data):
            rank = i + 1

            # Get medal or rank number
            if rank <= 3:
                rank_display = medals[rank - 1]
                rank_color = "Good" if rank == 1 else "Warning" if rank == 2 else "Accent"  # noqa
            else:
                rank_display = f"{rank}."
                rank_color = "Default"

            # Determine badge count display
            badge_count = employee['number_of_rewards']
            badge_text = f"{badge_count} badge{'s' if badge_count != 1 else ''}"  # noqa

            # Create the leaderboard row
            leaderboard_item = {
                "type": "Container",
                "style": "emphasis" if rank <= 3 else "default",
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": rank_display,
                                        "size": "Large" if rank <= 3 else "Medium",  # noqa
                                        "weight": "Bolder",
                                        "color": rank_color,
                                        "horizontalAlignment": "Center"
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": employee['display_name'],
                                        "weight": "Bolder" if rank <= 3 else "Default",  # noqa
                                        "size": "Medium" if rank <= 3 else "Default"  # noqa
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": employee['receiver_email'],
                                        "isSubtle": True,
                                        "size": "Small"
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": badge_text,
                                        "weight": "Bolder" if rank <= 3 else "Default",  # noqa
                                        "color": "Accent",
                                        "horizontalAlignment": "Right"
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "spacing": "Small"
            }

            leaderboard_items.append(leaderboard_item)

        # Create the card
        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "🏆 Badge Leaderboard",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "TextBlock",
                    "text": f"Top {len(leaderboard_data)} Leaderboard:",
                    "wrap": True,
                    "spacing": "Medium",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "Container",
                    "items": leaderboard_items,
                    "spacing": "Medium"
                }
            ]
        }

        # Add footer with tips
        if len(leaderboard_data) >= 3:
            card_data["body"].append({
                "type": "TextBlock",
                "text": "🎯 **Tip:** Use '/badge' to award badges and help your teammates climb the leaderboard!",  # noqa
                "wrap": True,
                "spacing": "Large",
                "color": "Accent",
                "isSubtle": True,
                "horizontalAlignment": "Center"
            })

        return CardFactory.adaptive_card(card_data)

    # Placeholder methods for future commands
    async def handle_mybadges_command(self, turn_context: TurnContext):
        """Handle /mybadges command - placeholder implementation"""
        await turn_context.send_activity(
            "🏅 My Badges feature coming soon! You'll be able to view all your earned badges here."  # noqa
        )

    async def start_badge_dialog(self, turn_context: TurnContext):
        """Start the badge assignment dialog"""
        try:
            # Create dialog context
            dialog_context = await self.dialog_set.create_context(turn_context)

            # Check if dialog is already active
            if dialog_context.active_dialog is not None:
                # Continue existing dialog
                await dialog_context.continue_dialog()
            else:
                # Start new badge dialog
                await dialog_context.begin_dialog(self.badge_dialog.id)

            # Save conversation state
            await self.save_state_changes(turn_context)

        except Exception as e:
            self.logger.error(f"Error starting badge dialog: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error starting the Badge System. Please try again."  # noqa
            )

    async def start_kudos_dialog(self, turn_context: TurnContext):
        """Start the kudos recognition dialog"""
        try:
            dialog_context = await self.dialog_set.create_context(turn_context)

            if dialog_context.active_dialog is not None:
                await dialog_context.continue_dialog()
            else:
                await dialog_context.begin_dialog(self.kudos_dialog.id)

            await self.save_state_changes(turn_context)

        except Exception as e:
            self.logger.error(f"Error starting kudos dialog: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error starting the Kudos System. Please try again."  # noqa
            )

    async def continue_dialog(self, turn_context: TurnContext):
        """Continue an active dialog (badge or kudos)"""
        try:
            dialog_context = await self.dialog_set.create_context(turn_context)

            # Check for cancel action
            activity_value = turn_context.activity.value
            if activity_value and activity_value.get('action') == 'cancel':
                await dialog_context.cancel_all_dialogs()
                await turn_context.send_activity("Operation cancelled.")
                await self.save_state_changes(turn_context)
                return

            # Continue the dialog
            if dialog_context.active_dialog is not None:
                await dialog_context.continue_dialog()
            else:
                # No active dialog, determine
                # which one to start based on context
                # Default to badge dialog
                await dialog_context.begin_dialog(self.badge_dialog.id)

            await self.save_state_changes(turn_context)

        except Exception as e:
            self.logger.error(f"Error continuing dialog: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error processing your request."
            )

    async def handle_badge_submission(
        self,
        assignment_data: dict,
        context: TurnContext
    ) -> dict:
        """Handle the final badge assignment submission"""
        try:
            reward_object = assignment_data.get('reward_object')
            reward_id = assignment_data['reward_id']
            recipient = assignment_data['recipient']
            message = assignment_data['message']

            if not reward_object:
                return {
                    'success': False,
                    'error': 'Reward object not found'
                }

            # Get user info from the context (the person assigning the badge)
            user_profile = await self.user_profile_accessor.get(context, None)
            giver_info = None

            if user_profile and hasattr(user_profile, 'email'):
                # Try to find the giver in the system
                try:
                    db = self.app['database']
                    async with await db.acquire() as conn:
                        User.Meta.connection = conn
                        giver = await User.get(
                            email=user_profile.email
                        )
                        giver_info = {
                            'user_id': giver.user_id,
                            'email': giver.email,
                            'display_name': giver.display_name,
                            'employee': giver.associate_id or ''
                        }
                except Exception as e:
                    self.logger.warning(
                        f"Could not find giver user: {user_profile.email}: {e}"
                    )

            # Extract reward information from reward_object
            try:
                # Get the reward details from the reward object
                reward_details = reward_object.reward()
                reward_points = reward_details.points or 0
                reward_name = reward_details.reward
                reward_type = reward_details.reward_type
            except Exception as e:
                self.logger.warning(f"Could not extract reward details: {e}")
                # Fallback values
                reward_points = 0
                reward_name = "Badge"
                reward_type = "User Badge"

            # Create the badge assignment
            assignment_args = {
                'reward_id': reward_id,
                'reward': reward_name,
                'reward_type': reward_type,
                'user_id': recipient['user_id'],
                'receiver_user': recipient['user_id'],
                'receiver_email': recipient['email'],
                'receiver_employee': recipient['associate_id'] or '',
                'receiver_id': recipient['user_id'],
                'display_name': recipient['display_name'],
                'points': reward_points,
                'message': message
            }

            # Add giver information if available
            if giver_info:
                assignment_args |= {
                    'giver_user': giver_info['user_id'],
                    'giver_email': giver_info['email'],
                    'giver_employee': giver_info.get('employee', ''),
                }

            # Create the badge assignment using the model
            badge_assignment = BadgeAssign(**assignment_args)

            self.logger.info(
                f"Badge assignment: {reward_name} awarded to {recipient['display_name']} "  # noqa
                f"with message: '{message}' "
                f"by {giver_info['display_name'] if giver_info else 'Unknown'}"
            )
            # Save the badge assignment to the database
            try:
                db = self.app.get('database')
                async with await db.acquire() as conn:
                    UserReward.Meta.connection = conn
                    save_assignment = UserReward(
                        **badge_assignment.to_dict(as_values=True)  # noqa
                    )
                    await save_assignment.insert()
            except ValidationError as ve:
                self.logger.error(
                    f"Validation error saving badge assignment: {ve}"
                )
                return {
                    'success': False,
                    'error': 'Invalid data for badge assignment',
                    'details': str(ve.payload)
                }
            except Exception as e:
                self.logger.error(
                    f"Error saving badge assignment: {e}"
                )
                return {
                    'success': False,
                    'error': 'Failed to save badge assignment to database',
                    'details': str(e)
                }
            # Fire-and-forget notification call
            self._call_notification(
                self.send_notification,
                badge_assignment,
                None  # saved_kudos is None for badge assignments
            )
            return {
                'success': True,
                'reward_name': reward_name,
                'assignment': badge_assignment
            }

        except Exception as e:
            self.logger.error(
                f"Error handling badge submission: {e}"
            )
            return {
                'success': False,
                'error': str(e)
            }

    def create_card(self, card_data: dict) -> Any:
        """Create an adaptive card from card data"""
        return CardFactory.adaptive_card(card_data)

    # Override the commands_callback for compatibility
    async def send_adaptive_card(
        self,
        turn_context: TurnContext,
        user_profile=None
    ):
        """Send an adaptive card (compatibility method)"""
        await self.start_badge_dialog(turn_context)

    async def handle_kudos_submission(
        self,
        kudos_data: dict,
        context: TurnContext
    ) -> dict:
        """Handle the kudos submission"""
        try:
            recipient = kudos_data['recipient']
            message = kudos_data['message']
            tags = kudos_data['tags']

            # Get user info from the context (the person sending kudos)
            user_profile = await self.user_profile_accessor.get(context, None)
            giver_info = None

            if user_profile and hasattr(user_profile, 'email'):
                # Try to find the real user
                try:
                    db = self.app.get('database')
                    async with await db.acquire() as conn:
                        User.Meta.connection = conn
                        giver = await User.get(email=user_profile.email)
                        giver_info = {
                            'user_id': giver.user_id,
                            'email': giver.email,
                            'display_name': giver.display_name
                        }
                except Exception as e:
                    self.logger.warning(
                        f"Could not find giver user: {user_profile.email}: {e}"
                    )

            # If no user profile or user not found, create anonymous giver
            if not giver_info:
                self.logger.info(
                    "No sender information available, creating anonymous kudos"
                )
                giver_info = {
                    'user_id': 0,  # Anonymous user ID
                    'email': 'anonymous@system.local',
                    'display_name': 'Anonymous (Test User)'
                }

            # Prevent self-kudos (but allow anonymous kudos to anyone)
            if giver_info['user_id'] != 0 and giver_info['user_id'] == recipient.user_id:  # noqa
                return {
                    'success': False,
                    'error': 'You cannot send kudos to yourself'
                }

            # Create the kudos record
            kudos_args = {
                'receiver_user_id': recipient.user_id,
                'receiver_email': recipient.email,
                'receiver_name': recipient.display_name,
                'giver_user_id': giver_info['user_id'],
                'giver_email': giver_info['email'],
                'giver_name': giver_info['display_name'],
                'message': message,
                'tags': tags,
                'is_public': True  # Default to public
            }

            # Save to database
            try:
                db = self.app.get('database')
                async with await db.acquire() as conn:
                    UserKudos.Meta.connection = conn
                    kudos = UserKudos(**kudos_args)
                    saved_kudos = await kudos.insert()

                    sender_name = giver_info['display_name']
                    if giver_info['user_id'] == 0:
                        sender_name += " (Demo Mode)"

                    self.logger.info(
                        f"Kudos sent: {sender_name} -> {recipient.display_name} "  # noqa
                        f"with tags: {tags}"
                    )

                    # Update tag usage counts
                    # if you want to track trending tags
                    await self._update_tag_usage(conn, tags)
                    # Fire-and-forget notification call
                    self._call_notification(
                        self.send_notification,
                        None,
                        saved_kudos
                    )
                    return {
                        'success': True,
                        'kudos': saved_kudos,
                        'is_anonymous': giver_info['user_id'] == 0
                    }

            except Exception as e:
                self.logger.error(f"Error saving kudos: {e}")
                return {
                    'success': False,
                    'error': 'Failed to save kudos to database'
                }

        except Exception as e:
            self.logger.error(f"Error handling kudos submission: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _update_tag_usage(self, conn, tags: list):
        """Update usage count for tags (for trending analysis)"""
        try:
            if not tags:
                return
            # Update tag usage counts in database
            await update_tag_usage_counts(conn, tags)

            self.logger.info(f"Updated tag usage for: {tags}")

        except Exception as e:
            self.logger.error(f"Error updating tag usage: {e}")

    def _call_notification(self, coro, *args, **kwargs):
        """
        Fire-and-forget coroutine execution with proper task management

        Args:
            coro: The coroutine function to execute
            *args: Arguments to pass to the coroutine
            **kwargs: Keyword arguments to pass to the coroutine
        """
        task = asyncio.create_task(
            coro(*args, **kwargs)
        )
        try:
            # Add to our set to prevent garbage collection
            self._notification_tasks.add(task)
            # Add a done callback to clean up and handle exceptions
            task.add_done_callback(
                self._task_done_callback
            )
            return task
        except Exception as e:
            self.logger.error(f"Error scheduling notification task: {e}")
            # Clean up the task if it fails to schedule
            self._notification_tasks.discard(task)

    def _task_done_callback(self, task: asyncio.Task):
        """Callback to handle completed fire-and-forget tasks"""
        # Remove from our tracking set
        self._notification_tasks.discard(task)
        # Check for exceptions
        try:
            # This will raise any exception that occurred in the task
            task.result()
        except Exception as e:
            self.logger.error(
                f"Fire-and-forget notification task failed: {e}"
            )

    async def send_notification(
        self,
        badge_assignment: Optional[BadgeAssign] = None,
        saved_kudos: Optional[Any] = None
    ):
        """
        Send notifications (MS Teams and Email) for badge assignments or kudos.
        """
        try:
            if badge_assignment:
                await self._send_badge_notifications(
                    badge_assignment
                )
            elif saved_kudos:
                await self._send_kudos_notifications(
                    saved_kudos
                )
            else:
                self.logger.warning(
                    "send_notification called with no data"
                )

        except Exception as e:
            self.logger.error(
                f"Error sending notifications: {e}"
            )

    async def _send_badge_notifications(self, badge_assignment: BadgeAssign):
        """Send notifications for badge assignments"""
        try:
            account = badge_assignment.receiver_email
            recipient = Actor(**{
                "name": badge_assignment.display_name,
                "account": {
                    "address": account
                }
            })
            # Use the configured notification method
            if self.notification_method == 'teams':
                sender = Teams(
                    client_id=MS_TEAMS_CLIENT_ID,
                    client_secret=MS_TEAMS_CLIENT_SECRET,
                    tenant_id=MS_TEAMS_TENANT_ID,
                    as_user=True
                )
                # Load JSON card for badge assignment:
                _now = datetime.now()
                message = await self.template_system.render(
                    'rewards/to_user.json',
                    {
                        "reward": badge_assignment.reward,
                        "points": badge_assignment.points,
                        "achievement": badge_assignment,
                        "message": badge_assignment.message,
                        "giver_name": badge_assignment.giver_name or 'the system',  # noqa
                        "receiver_name": badge_assignment.display_name,
                        "grant_date": _now.strftime('%Y-%m-%d %H:%M:%S'),  # noqa
                    }
                )
                args = {
                    "recipient": recipient,
                    "message": message
                }
            else:
                credentials = {
                    "hostname": config.get('smtp_host'),
                    "port": config.get('smtp_port'),
                    "username": config.get('smtp_host_user'),
                    "password": config.get('smtp_host_password')
                }
                sender = Notify('email', **credentials)
                args = {
                    "recipient": recipient,
                    "subject": f"You've been awarded a badge: {badge_assignment.reward}",  # noqa
                    "body": f"Congratulations {badge_assignment.display_name}!\n\n"  # noqa
                            f"You have been awarded the '{badge_assignment.reward}' badge.\n\n"  # noqa
                            f"Message from {badge_assignment.giver_email or 'the system'}: {badge_assignment.message}",  # noqa
                    # template='email_applied.html'
                }
            async with sender as message:
                result = await message.send(
                    **args
                )
                res = {
                    "provider": self.notification_method,
                    "status": result,
                    "title": f"Reward from {badge_assignment.giver_email}"
                }
                self.logger.info(
                    f"MS Teams Badge notification sent: {res}"
                )
        except Exception as e:
            self.logger.error(
                f"Error sending badge notifications: {e}"
            )
            raise

    async def _send_kudos_notifications(self, saved_kudos: Any):
        """Send notifications for kudos"""
        try:
            account = saved_kudos.receiver_email
            recipient = Actor(**{
                "name": saved_kudos.receiver_name,
                "account": {
                    "address": account
                }
            })
            # Format the sent date
            _sent_date = saved_kudos.sent_at or datetime.now()
            # Format tags for display (ensure they start with #)
            formatted_tags = []
            for tag in saved_kudos.tags:
                if not tag.startswith('#'):
                    tag = f"#{tag}"
                formatted_tags.append(tag)
            # Use the configured notification method
            if self.notification_method == 'teams':
                sender = Teams(
                    client_id=MS_TEAMS_CLIENT_ID,
                    client_secret=MS_TEAMS_CLIENT_SECRET,
                    tenant_id=MS_TEAMS_TENANT_ID,
                    as_user=True
                )
                # Load and render JSON card for kudos:
                message = await self.template_system.render(
                    'rewards/to_kudos.json',
                    {
                        "message": saved_kudos.message,
                        "giver_name": saved_kudos.giver_name,
                        "giver_email": saved_kudos.giver_email,
                        "receiver_name": saved_kudos.receiver_name,
                        "receiver_email": saved_kudos.receiver_email,
                        "tags": formatted_tags,
                        "sent_date": _sent_date.strftime('%Y-%m-%d %H:%M:%S'),
                        "is_public": saved_kudos.is_public
                    }
                )
                args = {
                    "recipient": recipient,
                    "message": message
                }
            else:
                credentials = {
                    "hostname": config.get('smtp_host'),
                    "port": config.get('smtp_port'),
                    "username": config.get('smtp_host_user'),
                    "password": config.get('smtp_host_password')
                }
                sender = Notify('email', **credentials)
                args = {
                    "recipient": recipient,
                    "subject": f"Kudos from {saved_kudos.giver_name}",
                    "body": f"You've received kudos from {saved_kudos.giver_name}!\n\n"  # noqa
                            f"Message: {saved_kudos.message}\n\n"
                            f"Tags: {', '.join(saved_kudos.tags)}"
                }
            async with sender as message:
                result = await message.send(
                    **args
                )
                res = {
                    "provider": self.notification_method,
                    "status": result,
                    "title": f"Kudos from {saved_kudos.giver_name}"
                }
                self.logger.info(
                    f"Kudos notification sent: {res}"
                )

        except Exception as e:
            self.logger.error(
                f"Error sending kudos notifications: {e}"
            )
            raise
