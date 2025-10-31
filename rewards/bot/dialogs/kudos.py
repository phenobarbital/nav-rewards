from typing import Any, Union, Optional, List, Dict
from collections.abc import Awaitable, Callable
from botbuilder.core import (
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
from navigator_auth.models import User
from ...kudos.models import KudosTag, INITIAL_KUDOS_TAGS


class KudosDialog(ComponentDialog):
    """Dialog for kudos recognition workflow"""

    def __init__(
        self,
        bot: Any = None,
        submission_callback: Union[Awaitable, Callable] = None,
        dialog_id: str = "KudosDialog"
    ):
        super(KudosDialog, self).__init__(dialog_id)
        self.bot = bot
        self.submission_callback = submission_callback

        # Add prompts
        self.add_dialog(TextPrompt("TextPrompt"))
        self.add_dialog(ChoicePrompt("ChoicePrompt"))

        # Add waterfall dialog
        self.add_dialog(
            WaterfallDialog("WaterfallDialog", [
                self.ask_for_recipient_step,
                self.process_recipient_step,
                self.ask_for_kudos_step,
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
                    "text": "🌟 Send Kudos Recognition",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "TextBlock",
                    "text": "Who would you like to recognize?",
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

    async def ask_for_kudos_step(self, step_context: WaterfallStepContext):
        """Second step: Ask for kudos message and tags"""
        recipient = step_context.values.get('recipient')

        if not recipient:
            await step_context.context.send_activity(
                "❌ Recipient information lost. Please start over."
            )
            return await step_context.replace_dialog(self.id)

        try:
            # Get available tags
            available_tags = await self._get_available_tags()

            # Create kudos input card
            card_data = self._create_kudos_input_card(
                recipient,
                available_tags
            )
            card = CardFactory.adaptive_card(card_data)

            await step_context.context.send_activity(
                MessageFactory.attachment(card)
            )

            return DialogTurnResult(DialogTurnStatus.Waiting)

        except Exception as e:
            self.bot.logger.error(f"Error creating kudos input: {e}")
            await step_context.context.send_activity(
                "❌ An error occurred while preparing the kudos form. Please try again."  # noqa
            )
            return await step_context.end_dialog()

    async def confirmation_step(self, step_context: WaterfallStepContext):
        """Final step: Process the kudos submission"""
        activity_value = step_context.context.activity.value
        recipient = step_context.values.get('recipient')

        if not activity_value or not recipient:
            await step_context.context.send_activity(
                "❌ Kudos information is incomplete."
            )
            return await step_context.end_dialog()

        # Handle cancel action
        if activity_value.get('action') == 'cancel':
            await step_context.context.send_activity("Kudos cancelled.")
            return await step_context.end_dialog()

        # Ensure we have send kudos action
        if activity_value.get('action') != 'send_kudos':
            await step_context.context.send_activity(
                "❌ Invalid action. Please try again."
            )
            return await step_context.end_dialog()

        try:
            # Extract form data
            message = activity_value.get('message', '').strip()
            selected_tags = activity_value.get('selectedTags', [])
            custom_tags = activity_value.get('customTags', '').strip()

            if not message:
                await step_context.context.send_activity(
                    "❌ Please provide a recognition message."
                )
                return await step_context.replace_dialog(self.id)

            # Process tags
            all_tags = []
            if isinstance(selected_tags, str):
                tag_list = [
                    tag.strip() for tag in selected_tags.split(',') if tag.strip()  # noqa
                ]
                all_tags.extend(tag_list)

            # Add custom tags
            if custom_tags:
                custom_tag_list = [
                    tag.strip() for tag in custom_tags.split(',')
                    if tag.strip()
                ]
                all_tags.extend(custom_tag_list)

            # Ensure tags start with # and normalize
            normalized_tags = []
            for tag in all_tags:
                if tag := tag.strip():
                    if not tag.startswith('#'):
                        tag = f"#{tag}"
                    normalized_tags.append(tag)

            # Create kudos data
            kudos_data = {
                'recipient': recipient,
                'message': message,
                'tags': normalized_tags,
                'giver_context': step_context.context
            }

            # Call the submission callback if provided
            if self.submission_callback:
                result = await self.submission_callback(
                    kudos_data,
                    step_context.context
                )

                if result.get('success'):
                    success_card = self._create_success_card(
                        recipient.display_name,
                        message,
                        normalized_tags
                    )
                    await step_context.context.send_activity(
                        MessageFactory.attachment(success_card)
                    )
                else:
                    error_msg = result.get('error', 'Unknown error occurred')
                    await step_context.context.send_activity(
                        f"❌ Failed to send kudos: {error_msg}"
                    )
            else:
                await step_context.context.send_activity(
                    "✅ Kudos sent successfully!"
                )

            return await step_context.end_dialog()

        except Exception as e:
            self.bot.logger.error(f"Error in kudos submission: {e}")
            await step_context.context.send_activity(
                "❌ An error occurred while sending kudos. Please try again."
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
                User.Meta.connection = conn
                # Try to find by email first
                if '@' in identifier:
                    user = await User.get(email=identifier)
                else:
                    # Try to find by display name (case insensitive)
                    formatted_name = ' '.join(
                        word[0].upper() + word[1:]
                        for word in identifier.split()
                    )
                    users = await User.filter(display_name=formatted_name)
                    user = users[0] if users else None
                return user

        except Exception as e:
            self.bot.logger.error(f"Error finding user: {e}")
            return None

    async def _get_available_tags(self) -> List[Dict]:
        """Get available predefined tags from database"""
        try:
            # Import the KudosTag model here to avoid circular imports
            db = self.bot.app.get('database')
            if not db:
                self.bot.logger.error(
                    "Database connection not available"
                )
                return self._get_fallback_tags()

            async with await db.acquire() as conn:
                KudosTag.Meta.connection = conn
                tags = await KudosTag.filter(
                    is_active=True
                )  # .order_by('usage_count', 'desc').limit(12)
                # TODO: Implement ordering and limiting if needed
                # get only 12 tags for performance
                if not tags:
                    self.bot.logger.warning("No active kudos tags found")
                    return self._get_fallback_tags()
                tags = sorted(
                    tags,
                    key=lambda x: x.usage_count,
                    reverse=True
                )[:12]  # Limit to top 12 by usage count
                return [
                    {
                        "tag_name": tag.tag_name,
                        "display_name": tag.display_name,
                        "emoji": tag.emoji or "",
                        "category": tag.category,
                        "usage_count": tag.usage_count
                    }
                    for tag in tags
                ]

        except Exception as e:
            self.bot.logger.error(f"Error getting tags from database: {e}")
            return self._get_fallback_tags()

    def _get_fallback_tags(self) -> List[Dict]:
        """Fallback tags if database is unavailable"""
        return INITIAL_KUDOS_TAGS

    def _create_kudos_input_card(
        self,
        recipient: User,
        available_tags: List[Dict]
    ) -> dict:
        """Create the kudos input adaptive card with grouped tags"""

        # Group tags by category
        categories = {}
        for tag in available_tags:
            category = tag.get('category', 'other')
            if category not in categories:
                categories[category] = []
            categories[category].append(tag)

        # Create tag choices grouped by category
        tag_choices = []

        # Sort categories for consistent display
        sorted_categories = sorted(categories.keys())

        for category in sorted_categories:
            category_tags = categories[category]

            # Add category header (visual separator)
            if category != 'other':
                category_name = category.replace('_', ' ').title()
                for tag in category_tags:
                    emoji = tag.get('emoji', '')
                    usage_info = ""
                    if tag.get('usage_count', 0) > 0:
                        usage_info = f" ({tag['usage_count']} times used)"

                    display_text = f"{emoji} {tag['display_name']}{usage_info}" if emoji else f"{tag['display_name']}{usage_info}"  # noqa
                    tag_choices.append({
                        "title": display_text,
                        "value": tag['tag_name']
                    })

        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "size": "Medium",
                    "weight": "Bolder",
                    "text": "🌟 Recognize Someone Special",
                    "horizontalAlignment": "Center"
                },
                {
                    "type": "Container",
                    "style": "emphasis",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"**Sending kudos to:** {recipient.display_name}",  # noqa
                            "wrap": True,
                            "weight": "Bolder"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Email: {recipient.email}",
                            "wrap": True,
                            "size": "Small",
                            "isSubtle": True
                        }
                    ],
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": "**Recognition Message:**",
                    "weight": "Bolder",
                    "spacing": "Medium"
                },
                {
                    "type": "Input.Text",
                    "id": "message",
                    "isMultiline": True,
                    "maxLength": 500,
                    "placeholder": "Describe why you want to recognize this person... (be specific about what they did!)"  # noqa
                },
                {
                    "type": "TextBlock",
                    "text": "**Recognition Qualities (select all that apply):**",  # noqa
                    "weight": "Bolder",
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": "Choose from our trending qualities:",
                    "size": "Small",
                    "isSubtle": True
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selectedTags",
                    "choices": tag_choices,
                    "style": "compact",
                    "isMultiSelect": True,
                    "wrap": True
                },
                {
                    "type": "TextBlock",
                    "text": "**Custom Qualities (optional):**",
                    "weight": "Bolder",
                    "spacing": "Medium"
                },
                {
                    "type": "Input.Text",
                    "id": "customTags",
                    "placeholder": "Add your own qualities separated by commas (e.g., Patient, Detail-oriented, Funny)",  # noqa
                    "maxLength": 200
                },
                {
                    "type": "TextBlock",
                    "text": "💡 **Tip:** Custom qualities will automatically get a # hashtag. Be creative - your custom tags help build our recognition vocabulary!",  # noqa
                    "wrap": True,
                    "size": "Small",
                    "isSubtle": True,
                    "spacing": "Small"
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "🌟 Send Kudos",
                    "style": "positive",
                    "data": {
                        "action": "send_kudos"
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
        message: str,
        tags: List[str],
        is_anonymous: bool = False
    ) -> Any:
        """Create a success message card"""
        tags_text = " ".join(tags) if tags else "No tags selected"

        # Customize message based on anonymous status
        if is_anonymous:
            title = "🎉 Demo Kudos Sent Successfully!"
            thank_you_msg = "Demo kudos sent! In production, this would notify the recipient. 🌟"  # noqa
            sender_info = "**Sent by:** Anonymous (Demo Mode)"
        else:
            title = "🎉 Kudos Sent Successfully!"
            thank_you_msg = "Thank you for recognizing your teammate! 🌟"
            sender_info = ""

        facts = [
            {
                "title": "Recognized:",
                "value": recipient_name
            },
            {
                "title": "Message:",
                "value": message
            },
            {
                "title": "Qualities:",
                "value": tags_text
            }
        ]

        # Add sender info for anonymous kudos
        if sender_info:
            facts.insert(0, {
                "title": "Mode:",
                "value": "Demo/Test Mode"
            })

        body_items = [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": title,
                "color": "Good",
                "horizontalAlignment": "Center"
            },
            {
                "type": "FactSet",
                "facts": facts
            },
            {
                "type": "TextBlock",
                "text": thank_you_msg,
                "wrap": True,
                "horizontalAlignment": "Center",
                "spacing": "Medium",
                "color": "Good"
            }
        ]

        # Add demo notice for anonymous kudos
        if is_anonymous:
            body_items.append({
                "type": "TextBlock",
                "text": "💡 **Note:** This is a demo/test environment. In production, kudos would be associated with your actual user account.",  # noqa
                "wrap": True,
                "size": "Small",
                "isSubtle": True,
                "spacing": "Small"
            })

        card_content = {
            "type": "AdaptiveCard",
            "body": body_items,
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3"
        }

        return CardFactory.adaptive_card(card_content)
