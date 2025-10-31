from typing import Any, Union, Optional
from collections.abc import Awaitable, Callable
from botbuilder.core import (
    TurnContext,
    MessageFactory,
    CardFactory,
)
from botbuilder.dialogs.prompts import (
    TextPrompt,
    ChoicePrompt,
)
from botbuilder.dialogs import (
    ComponentDialog,
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus,
)
from resources.users import User


class BadgeDialog(ComponentDialog):
    """Dialog for badge assignment workflow"""

    def __init__(
        self,
        bot: Any = None,
        submission_callback: Union[Awaitable, Callable] = None,
        dialog_id: str = "BadgeDialog"
    ):
        super(BadgeDialog, self).__init__(dialog_id)
        self.bot = bot
        self.submission_callback = submission_callback
        self._default_icon = "https://via.placeholder.com/32x32/0078d4/ffffff?text=🏅"  # noqa
        # Add prompts
        self.add_dialog(TextPrompt("TextPrompt"))
        self.add_dialog(ChoicePrompt("ChoicePrompt"))

        # Add waterfall dialog
        self.add_dialog(
            WaterfallDialog("WaterfallDialog", [
                self.ask_for_recipient_step,
                self.process_recipient_step,
                self.ask_for_badge_step,
                self.ask_for_message_step,
                self.confirmation_step,
            ])
        )

        self.initial_dialog_id = "WaterfallDialog"

    async def ask_for_recipient_step(self, step_context: WaterfallStepContext):
        """First step: Ask for recipient name or email"""
        card_content = {
            "type": "AdaptiveCard",
            "body": [
                {
                    "type": "TextBlock",
                    "size": "Medium",
                    "weight": "Bolder",
                    "text": "🏅 Badge Assignment",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "TextBlock",
                    "text": "Please enter the name or email of the person you want to award:",  # noqa
                    "wrap": True
                },
                {
                    "type": "Input.Text",
                    "id": "recipientIdentifier",
                    "placeholder": "Enter name or email address",
                    "maxLength": 100
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Find Person",
                    "data": {
                        "action": "find_recipient"
                    }
                }
            ],
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3"
        }

        card = CardFactory.adaptive_card(card_content)
        await step_context.context.send_activity(
            MessageFactory.attachment(card)
        )

        return DialogTurnResult(DialogTurnStatus.Waiting)

    async def process_recipient_step(self, step_context: WaterfallStepContext):
        """Process the recipient input and find the user"""
        # Get the recipient identifier from the turn state
        activity_value = step_context.context.activity.value
        if not activity_value or 'recipientIdentifier' not in activity_value:
            await step_context.context.send_activity(
                "❌ No recipient information provided. Please try again."
            )
            return await step_context.replace_dialog(self.id)

        recipient_identifier = activity_value['recipientIdentifier'].strip()

        if not recipient_identifier:
            await step_context.context.send_activity(
                "❌ Please provide a valid name or email address."
            )
            return await step_context.replace_dialog(self.id)

        # Try to find the user
        try:
            user = await self._find_user(recipient_identifier)

            if not user:
                # Show error and restart dialog
                error_card = self._create_error_card(
                    "User Not Found",
                    f"No user found with identifier: {recipient_identifier}",
                    "Please check the name or email and try again."
                )
                await step_context.context.send_activity(
                    MessageFactory.attachment(error_card)
                )
                return await step_context.replace_dialog(self.id)

            # Store the found user in values for next step
            step_context.values['recipient'] = user

            return await step_context.next(user)

        except Exception as e:
            self.bot.logger.error(f"Error finding user: {e}")
            await step_context.context.send_activity(
                "❌ An error occurred while searching for the user. Please try again."  # noqa
            )
            return await step_context.replace_dialog(self.id)

    async def ask_for_badge_step(self, step_context: WaterfallStepContext):
        """Second step: Show available badges and ask for selection"""
        recipient = step_context.values.get('recipient')

        if not recipient:
            await step_context.context.send_activity(
                "❌ Recipient information lost. Please start over."
            )
            return await step_context.replace_dialog(self.id)

        try:
            # Get available rewards for this specific user
            available_rewards = await self._get_available_rewards(
                step_context.context,
                recipient
            )

            if not available_rewards:
                await step_context.context.send_activity(
                    f"❌ No badges are available for assignment to {recipient.display_name} at this time."  # noqa
                )
                return await step_context.end_dialog()

            # Create badge selection card
            card_data = self._create_badge_selection_card(
                recipient,
                available_rewards
            )
            card = CardFactory.adaptive_card(card_data)

            await step_context.context.send_activity(
                MessageFactory.attachment(card)
            )

            return DialogTurnResult(DialogTurnStatus.Waiting)

        except Exception as e:
            self.bot.logger.error(
                f"Error getting available rewards: {e}"
            )
            await step_context.context.send_activity(
                "❌ An error occurred while loading available badges. Please try again."  # noqa
            )
            return await step_context.end_dialog()

    async def ask_for_message_step(self, step_context: WaterfallStepContext):
        """Third step: Ask for message after badge selection"""
        activity_value = step_context.context.activity.value
        recipient = step_context.values.get('recipient')

        if not activity_value or activity_value.get('action') != 'select_badge':  # noqa
            await step_context.context.send_activity(
                "❌ Please select a badge first."
            )
            return await step_context.replace_dialog(self.id)

        # Store selected badge info
        step_context.values['selected_reward_id'] = activity_value.get('reward_id')  # noqa
        step_context.values['selected_reward_name'] = activity_value.get('reward_name')  # noqa
        available_rewards = await self._get_available_rewards(
            step_context.context,
            recipient
        )
        selected_reward_object = None
        for reward in available_rewards:
            if str(reward['reward_id']) == str(activity_value.get('reward_id')):  # noqa
                selected_reward_object = reward['reward_object']
                break
        if selected_reward_object:
            step_context.values['selected_reward_object'] = selected_reward_object  # noqa

        # Create message input card
        message_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "size": "Medium",
                    "weight": "Bolder",
                    "text": "✏️ Add Your Message",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {
                            "title": "Recipient:",
                            "value": recipient.display_name
                        },
                        {
                            "title": "Badge:",
                            "value": activity_value.get('reward_name')
                        }
                    ]
                },
                {
                    "type": "TextBlock",
                    "text": "Add a personal message:",
                    "weight": "Bolder"
                },
                {
                    "type": "Input.Text",
                    "id": "message",
                    "isMultiline": True,
                    "maxLength": 500,
                    "placeholder": "Describe why you're giving this person a shoutout..."  # noqa
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "🎉 Award Badge",
                    "data": {
                        "action": "assign_badge"
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "🔙 Back to Badge Selection",
                    "data": {
                        "action": "back_to_badges"
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "❌ Cancel",
                    "data": {
                        "action": "cancel"
                    }
                }
            ]
        }

        card = CardFactory.adaptive_card(message_card)
        await step_context.context.send_activity(
            MessageFactory.attachment(card)
        )

        return DialogTurnResult(DialogTurnStatus.Waiting)

    async def confirmation_step(self, step_context: WaterfallStepContext):
        """Final step: Process the badge assignment"""
        activity_value = step_context.context.activity.value
        recipient = step_context.values.get('recipient')

        if not activity_value or not recipient:
            await step_context.context.send_activity(
                "❌ Badge assignment information is incomplete."
            )
            return await step_context.end_dialog()

        # Handle back to badges action
        if activity_value.get('action') == 'back_to_badges':
            return await step_context.replace_dialog(self.id)

        # Ensure we have assignment action
        if activity_value.get('action') != 'assign_badge':
            await step_context.context.send_activity(
                "❌ Invalid action. Please try again."
            )
            return await step_context.end_dialog()

        try:
            # Extract form data from stored values and current input
            reward_id = step_context.values.get('selected_reward_id')
            reward_name = step_context.values.get('selected_reward_name')
            reward_object = step_context.values.get('selected_reward_object')
            message = activity_value.get('message', '').strip()

            if not reward_id:
                await step_context.context.send_activity(
                    "❌ Badge selection was lost. Please start over."
                )
                return await step_context.replace_dialog(self.id)

            if not message:
                # Create an error card with restart option
                error_card = {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",  # noqa
                    "version": "1.3",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "❌ Message Required",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": "Attention"
                        },
                        {
                            "type": "TextBlock",
                            "text": "Please provide a message for the badge assignment.",  # noqa
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": "Use '/badge' to start over.",
                            "isSubtle": True
                        }
                    ]
                }

                card = CardFactory.adaptive_card(error_card)
                await step_context.context.send_activity(
                    MessageFactory.attachment(card)
                )
                return await step_context.end_dialog()

            # Create badge assignment data
            assignment_data = {
                'reward_id': int(reward_id),
                'reward_object': reward_object,
                'recipient': recipient,
                'message': message,
                'giver_context': step_context.context
            }
            # Compute who is giving the badge

            # Call the submission callback if provided
            if self.submission_callback:
                result = await self.submission_callback(
                    assignment_data,
                    step_context.context
                )

                if result.get('success'):
                    success_card = self._create_success_card(
                        recipient.display_name,
                        result.get('reward_name', reward_name),
                        message
                    )
                    await step_context.context.send_activity(
                        MessageFactory.attachment(success_card)
                    )
                else:
                    error_msg = result.get('error', 'Unknown error occurred')
                    await step_context.context.send_activity(
                        f"❌ Failed to assign badge: {error_msg}"
                    )
            else:
                await step_context.context.send_activity(
                    "✅ Badge assignment submitted successfully!"
                )

            return await step_context.end_dialog()

        except Exception as e:
            self.bot.logger.error(f"Error in badge assignment: {e}")
            await step_context.context.send_activity(
                "❌ An error occurred during badge assignment. Please try again."  # noqa
            )
            return await step_context.end_dialog()

    async def _find_user(self, identifier: str) -> Optional[User]:
        """Find user by name or email"""
        try:
            db = self.bot.app.get('database')
            user = None
            if not db:
                self.bot.logger.error("Database connection not available")
                return None
            async with await db.acquire() as conn:
                # Use the User model to find by email or display name
                User.Meta.connection = conn
                # Try to find by email first
                if '@' in identifier:
                    user = await User.get(email=identifier)
                else:
                    # Try to find by display name (case insensitive)
                    s = ' '.join(word[0].upper() + word[1:] for word in identifier.split())  # noqa
                    print('Finding user by display name:', s)
                    users = await User.filter(
                        display_name=s
                    )
                    user = users[0] if users else None
                return user
            return None

        except Exception as e:
            self.bot.logger.error(f"Error finding user: {e}")
            return None

    async def _get_available_rewards(
        self,
        context: TurnContext,
        user: User
    ) -> list:
        """Get available rewards that can be assigned"""
        try:
            # Get the reward engine from the app
            try:
                reward = self.bot.app['reward_engine']
                if not reward:
                    return []
            except KeyError:
                self.bot.logger.error("Reward engine not found in app context")
                return []

            # Get the bot user (the person assigning the badge) context
            # giver_user = None

            try:
                # Get the user context for the reward engine
                ctx = reward._get_context_user(
                    user
                )
            except Exception as e:
                self.bot.logger.error(f"Error setting user context: {e}")
                return []

            # Get available rewards
            rewards_response = await reward.get_badges_for_user(ctx)
            rewards = []
            for reward in rewards_response:
                if await reward.check_awardee(ctx):
                    # Get emoji from attributes
                    # or use default based on category
                    emoji = self._get_reward_emoji(reward)
                    rewards.append(
                        {
                            'reward_id': reward.id,
                            'reward': reward.name,
                            'description': reward.reward().description,
                            'icon': reward.reward().icon,
                            'type': reward.reward().reward_type,
                            'points': reward.reward().points,
                            'emoji': emoji,
                            'reward_object': reward
                        }
                    )
            return rewards or []

        except Exception as e:
            self.bot.logger.error(
                f"Error getting available rewards: {e}"
            )
            return []

    def _get_reward_emoji(self, reward) -> str:
        """Get emoji for a reward based on attributes or category"""
        # First check the "emoji" attribute in the reward model
        if hasattr(reward, 'emoji') and reward.emoji:
            return reward.emoji.strip()
        # check if reward has an emoji in attributes
        attributes = getattr(reward._reward, 'attributes', {})
        if attributes and isinstance(attributes, dict):
            emoji = attributes.get('emoji')
            if emoji:
                return emoji

        # Fallback to category-based emojis
        category = getattr(reward._reward, 'reward_category', '').lower()
        reward_type = getattr(reward._reward, 'reward_type', '').lower()
        reward_name = getattr(reward._reward, 'reward', '').lower()

        # Category-based emoji mapping
        category_emojis = {
            'recognition': '🏆',
            'sales': '💰',
            'sales targets': '🎯',
            'training': '📚',
            'attendance': '📅',
            'engagement': '🤝',
            'performance': '⭐',
            'teamwork': '👥',
            'innovation': '💡',
            'leadership': '👑',
            'customer service': '😊',
            'safety': '🛡️',
            'quality': '✨',
            'test category': '🧪',
            'test': '🧪'
        }

        # Type-based emoji mapping
        type_emojis = {
            'user badge': '🏅',
            'test badge': '🧪',
            'recognition badge': '🏆',
            'achievement badge': '⭐',
            'automated badge': '🤖',
            'computed badge': '📊'
        }

        # Name-based emoji mapping for specific rewards
        name_emojis = {
            'birthday': '🎂',
            'anniversary': '🎉',
            'walmart': '🛒',
            'welcome': '👋',
            'lottery': '🎰',
            'jackpot': '💎',
            'seller': '💰',
            'attendance': '📅',
            'login': '🔐',
            'onboarding': '🚀'
        }

        # Check name first for most specific match
        for name_key, emoji in name_emojis.items():
            if name_key in reward_name:
                return emoji

        # Check category
        if category in category_emojis:
            return category_emojis[category]

        # Check type
        if reward_type in type_emojis:
            return type_emojis[reward_type]

        # Default emoji
        return '🏅'

    def _create_badge_selection_card(
        self,
        recipient: User,
        rewards: list
    ) -> dict:
        """Create the badge selection adaptive card with icons"""

        # Create the body elements
        body_elements = [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "🏅 Select Badge to Award",
                "horizontalAlignment": "Center"
            },
            {
                "type": "TextBlock",
                "text": f"Awarding badge to: **{recipient.display_name}** ({recipient.email})",  # noqa
                "wrap": True
            },
            {
                "type": "TextBlock",
                "text": "Select a badge:",
                "weight": "Bolder",
                "spacing": "Medium"
            }
        ]

        # Create choice containers with icons
        for reward in rewards:
            # Get icon URL or use default
            # icon_url = reward.get('icon', '').strip() or self._default_icon  # noqa
            emoji = reward.get('emoji', '🏅')  # Get emoji or use default
            choice_container = {
                "type": "Container",
                "style": "emphasis",
                "spacing": "Small",
                "selectAction": {
                    "type": "Action.Submit",
                    "data": {
                        "action": "select_badge",
                        "reward_id": str(reward['reward_id']),
                        "reward_name": reward['reward']
                    }
                },
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
                                        "text": emoji,
                                        "size": "Large",
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
                                        "text": f"**{reward['reward']}**",
                                        "weight": "Bolder",
                                        "size": "Medium"
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": reward['description'],
                                        "isSubtle": True,
                                        "wrap": True
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"{reward.get('points', 0)} pts",  # noqa
                                        "size": "Small",
                                        "color": "Accent",
                                        "horizontalAlignment": "Right"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }

            body_elements.append(choice_container)

        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": body_elements,
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "❌ Cancel",
                    "data": {
                        "action": "cancel"
                    }
                }
            ]
        }

    def _create_error_card(
        self,
        title: str,
        message: str,
        suggestion: str = ""
    ) -> Any:
        """Create an error message card"""
        body = [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": f"❌ {title}",
                "color": "Attention"
            },
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True
            }
        ]

        if suggestion:
            body.append({
                "type": "TextBlock",
                "text": suggestion,
                "wrap": True,
                "style": "emphasis"
            })

        card_content = {
            "type": "AdaptiveCard",
            "body": body,
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Try Again",
                    "data": {"action": "retry"}
                }
            ],
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3"
        }

        return CardFactory.adaptive_card(card_content)

    def _create_success_card(
        self,
        recipient_name: str,
        badge_name: str,
        message: str
    ) -> Any:
        """Create a success message card"""
        card_content = {
            "type": "AdaptiveCard",
            "body": [
                {
                    "type": "TextBlock",
                    "size": "Medium",
                    "weight": "Bolder",
                    "text": "🎉 Badge Awarded Successfully!",
                    "color": "Good",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {
                            "title": "Recipient:",
                            "value": recipient_name
                        },
                        {
                            "title": "Badge:",
                            "value": badge_name
                        },
                        {
                            "title": "Message:",
                            "value": message
                        }
                    ]
                }
            ],
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3"
        }

        return CardFactory.adaptive_card(card_content)
