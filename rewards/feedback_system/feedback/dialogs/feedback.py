"""
Feedback Dialog for MS Teams Bot Integration.

Provides an interactive dialog for submitting feedback on badges,
kudos, and nominations through MS Teams.

Usage:
    User types /feedback in Teams to start the dialog.
"""
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from botbuilder.core import (
    TurnContext,
    CardFactory,
    MessageFactory
)
from botbuilder.dialogs import (
    ComponentDialog,
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus
)
from botbuilder.dialogs.prompts import (
    TextPrompt,
    ChoicePrompt,
    PromptOptions
)
from botbuilder.dialogs.choices import Choice
from navconfig.logging import logging
from ..models import (
    UserFeedback,
    FeedbackType,
    TargetType,
    POINTS_FOR_GIVER,
    POINTS_FOR_RECEIVER
)


class FeedbackDialog(ComponentDialog):
    """
    Interactive dialog for submitting feedback via MS Teams.
    
    Flow:
        1. Ask for target type (badge/kudos/nomination)
        2. Ask for target ID or search
        3. Show target details and confirm
        4. Display feedback form (type, rating, message)
        5. Submit and confirm
    """
    
    def __init__(
        self,
        bot: Any,
        submission_callback: Optional[Callable] = None
    ):
        super().__init__(FeedbackDialog.__name__)
        
        self.bot = bot
        self.submission_callback = submission_callback
        self.logger = logging.getLogger('feedback_dialog')
        
        # Add prompts
        self.add_dialog(TextPrompt(TextPrompt.__name__))
        self.add_dialog(ChoicePrompt(ChoicePrompt.__name__))
        
        # Add waterfall dialog
        self.add_dialog(
            WaterfallDialog(
                "FeedbackWaterfall",
                [
                    self.select_target_type_step,
                    self.enter_target_id_step,
                    self.validate_target_step,
                    self.show_feedback_form_step,
                    self.process_submission_step,
                    self.confirmation_step
                ]
            )
        )
        
        self.initial_dialog_id = "FeedbackWaterfall"
    
    async def select_target_type_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Step 1: Select target type."""
        choices = [
            Choice(value="badge", synonyms=["Badge", "BADGE", "badges"]),
            Choice(value="kudos", synonyms=["Kudos", "KUDOS", "kudo"]),
            Choice(value="nomination", synonyms=["Nomination", "NOMINATION", "nom"])
        ]
        
        return await step_context.prompt(
            ChoicePrompt.__name__,
            PromptOptions(
                prompt=MessageFactory.text(
                    "🎯 What would you like to give feedback on?\n\n"
                    "• **Badge** - A badge someone received\n"
                    "• **Kudos** - A kudos recognition\n"
                    "• **Nomination** - A nomination award"
                ),
                choices=choices
            )
        )
    
    async def enter_target_id_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Step 2: Enter target ID."""
        target_type = step_context.result.value
        step_context.values['target_type'] = target_type
        
        return await step_context.prompt(
            TextPrompt.__name__,
            PromptOptions(
                prompt=MessageFactory.text(
                    f"📝 Please enter the **{target_type} ID** you want to give feedback on.\n\n"
                    "_You can find this ID in the notification or on the rewards page._"
                )
            )
        )
    
    async def validate_target_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Step 3: Validate target exists and show details."""
        try:
            target_id = int(step_context.result)
        except ValueError:
            await step_context.context.send_activity(
                "❌ Invalid ID format. Please enter a valid number."
            )
            return await step_context.replace_dialog(self.id)
        
        step_context.values['target_id'] = target_id
        target_type = step_context.values['target_type']
        
        # Validate target exists (simplified - actual implementation would query DB)
        # For now, we'll proceed and let the handler validate
        
        step_context.values['validated'] = True
        
        return await step_context.next(None)
    
    async def show_feedback_form_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Step 4: Show feedback form as adaptive card."""
        target_type = step_context.values['target_type']
        target_id = step_context.values['target_id']
        
        # Create adaptive card for feedback form
        card = self._create_feedback_form_card(target_type, target_id)
        
        await step_context.context.send_activity(
            MessageFactory.attachment(CardFactory.adaptive_card(card))
        )
        
        return await step_context.prompt(
            TextPrompt.__name__,
            PromptOptions(
                prompt=MessageFactory.text(
                    "_Submit the form above or type 'cancel' to exit._"
                )
            )
        )
    
    async def process_submission_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Step 5: Process the feedback submission."""
        # Check for cancel
        if step_context.result and step_context.result.lower() == 'cancel':
            await step_context.context.send_activity("Operation cancelled.")
            return await step_context.end_dialog()
        
        # Get form data from activity value (adaptive card submission)
        activity_value = step_context.context.activity.value
        
        if not activity_value:
            await step_context.context.send_activity(
                "❌ No feedback data received. Please try again."
            )
            return await step_context.replace_dialog(self.id)
        
        # Extract feedback data
        feedback_data = {
            'target_type': step_context.values['target_type'],
            'target_id': step_context.values['target_id'],
            'feedback_type': activity_value.get('feedback_type'),
            'rating': activity_value.get('rating'),
            'message': activity_value.get('message', '')
        }
        
        step_context.values['feedback_data'] = feedback_data
        
        # Call submission callback if provided
        if self.submission_callback:
            try:
                result = await self.submission_callback(
                    step_context.context,
                    feedback_data
                )
                step_context.values['submission_result'] = result
            except Exception as e:
                self.logger.error(f"Feedback submission error: {e}")
                step_context.values['submission_error'] = str(e)
        
        return await step_context.next(None)
    
    async def confirmation_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Step 6: Show confirmation."""
        if 'submission_error' in step_context.values:
            error = step_context.values['submission_error']
            await step_context.context.send_activity(
                f"❌ Failed to submit feedback: {error}"
            )
        else:
            feedback_data = step_context.values.get('feedback_data', {})
            
            # Create confirmation card
            card = self._create_confirmation_card(
                feedback_data,
                step_context.values.get('submission_result')
            )
            
            await step_context.context.send_activity(
                MessageFactory.attachment(CardFactory.adaptive_card(card))
            )
        
        return await step_context.end_dialog()
    
    def _create_feedback_form_card(
        self,
        target_type: str,
        target_id: int
    ) -> Dict[str, Any]:
        """Create adaptive card for feedback form."""
        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "📝 Give Feedback",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": f"Providing feedback on **{target_type.title()}** #{target_id}",
                    "wrap": True,
                    "spacing": "Small"
                },
                {
                    "type": "Container",
                    "spacing": "Medium",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": "Feedback Type *",
                            "weight": "Bolder",
                            "size": "Small"
                        },
                        {
                            "type": "Input.ChoiceSet",
                            "id": "feedback_type",
                            "style": "compact",
                            "isRequired": True,
                            "choices": [
                                {"title": "🙏 Appreciation", "value": "appreciation"},
                                {"title": "💥 Great Impact", "value": "impact"},
                                {"title": "✨ Inspiring", "value": "inspiring"},
                                {"title": "🏆 Well Deserved", "value": "well_deserved"},
                                {"title": "🤝 Team Player", "value": "teamwork"},
                                {"title": "📈 Shows Growth", "value": "growth"},
                                {"title": "👑 Leadership", "value": "leadership"},
                                {"title": "💡 Innovative", "value": "innovation"},
                                {"title": "💪 Dedication", "value": "dedication"},
                                {"title": "⭐ Excellence", "value": "excellence"}
                            ]
                        }
                    ]
                },
                {
                    "type": "Container",
                    "spacing": "Medium",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": "Rating (Optional)",
                            "weight": "Bolder",
                            "size": "Small"
                        },
                        {
                            "type": "Input.ChoiceSet",
                            "id": "rating",
                            "style": "expanded",
                            "choices": [
                                {"title": "⭐", "value": "1"},
                                {"title": "⭐⭐", "value": "2"},
                                {"title": "⭐⭐⭐", "value": "3"},
                                {"title": "⭐⭐⭐⭐", "value": "4"},
                                {"title": "⭐⭐⭐⭐⭐", "value": "5"}
                            ]
                        }
                    ]
                },
                {
                    "type": "Container",
                    "spacing": "Medium",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": "Message (Optional)",
                            "weight": "Bolder",
                            "size": "Small"
                        },
                        {
                            "type": "Input.Text",
                            "id": "message",
                            "placeholder": "Share your thoughts about this recognition...",
                            "isMultiline": True,
                            "maxLength": 500
                        }
                    ]
                },
                {
                    "type": "TextBlock",
                    "text": f"💰 You'll earn **{POINTS_FOR_GIVER} points** for giving feedback!",
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Good",
                    "size": "Small"
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Submit Feedback",
                    "style": "positive",
                    "data": {
                        "action": "submit_feedback"
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "Cancel",
                    "style": "destructive",
                    "data": {
                        "action": "cancel"
                    }
                }
            ]
        }
    
    def _create_confirmation_card(
        self,
        feedback_data: Dict[str, Any],
        submission_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create adaptive card for confirmation."""
        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "✅ Feedback Submitted!",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Good"
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {
                            "title": "Target:",
                            "value": f"{feedback_data.get('target_type', '').title()} #{feedback_data.get('target_id')}"
                        },
                        {
                            "title": "Type:",
                            "value": feedback_data.get('feedback_type', 'N/A').replace('_', ' ').title()
                        },
                        {
                            "title": "Rating:",
                            "value": "⭐" * int(feedback_data.get('rating', 0)) if feedback_data.get('rating') else "Not provided"
                        },
                        {
                            "title": "Points Earned:",
                            "value": f"+{POINTS_FOR_GIVER} points"
                        }
                    ]
                },
                {
                    "type": "TextBlock",
                    "text": f"The recipient also earned **{POINTS_FOR_RECEIVER} points** from your feedback! 🎉",
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent"
                }
            ]
        }


class FeedbackBotMixin:
    """
    Mixin to add feedback functionality to existing bot.
    
    Add this mixin to BadgeBot to enable /feedback command.
    """
    
    def _init_feedback_dialog(self):
        """Initialize feedback dialog. Call in bot __init__."""
        self.feedback_dialog = FeedbackDialog(
            bot=self,
            submission_callback=self.handle_feedback_submission
        )
    
    def _setup_feedback_dialog(self, dialog_set):
        """Add feedback dialog to dialog set. Call in bot setup."""
        dialog_set.add(self.feedback_dialog)
    
    async def start_feedback_dialog(self, turn_context: TurnContext):
        """Start the feedback dialog."""
        try:
            dialog_context = await self.dialog_set.create_context(turn_context)
            
            if dialog_context.active_dialog is not None:
                await dialog_context.continue_dialog()
            else:
                await dialog_context.begin_dialog(self.feedback_dialog.id)
            
            await self.save_state_changes(turn_context)
            
        except Exception as e:
            self.logger.error(f"Error starting feedback dialog: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error starting the Feedback System. Please try again."
            )
    
    async def handle_feedback_submission(
        self,
        turn_context: TurnContext,
        feedback_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle feedback submission from dialog.
        
        Override this method to implement actual database operations.
        """
        try:
            # Get user info from turn context
            user_id = turn_context.activity.from_property.id
            user_name = turn_context.activity.from_property.name
            
            # Get reward engine from app
            reward_engine = self.app.get('reward_engine')
            if not reward_engine:
                raise Exception("Reward engine not available")
            
            async with await reward_engine.connection.acquire() as conn:
                UserFeedback.Meta.connection = conn
                
                # Get feedback type ID
                feedback_type_id = None
                if feedback_data.get('feedback_type'):
                    type_query = """
                        SELECT feedback_type_id FROM rewards.feedback_types
                        WHERE type_name = $1
                    """
                    type_result = await conn.fetch_one(
                        type_query,
                        feedback_data['feedback_type']
                    )
                    if type_result:
                        feedback_type_id = type_result['feedback_type_id']
                
                # Note: Full implementation would validate target and get receiver info
                # This is a simplified version
                
                feedback = UserFeedback(
                    target_type=feedback_data['target_type'],
                    target_id=feedback_data['target_id'],
                    giver_user_id=int(user_id) if user_id.isdigit() else 0,
                    giver_name=user_name,
                    receiver_user_id=0,  # Would be populated from target validation
                    feedback_type_id=feedback_type_id,
                    rating=int(feedback_data['rating']) if feedback_data.get('rating') else None,
                    message=feedback_data.get('message'),
                    points_given=POINTS_FOR_GIVER,
                    points_received=POINTS_FOR_RECEIVER
                )
                
                await feedback.insert()
                
                return {
                    'success': True,
                    'feedback_id': feedback.feedback_id,
                    'points_earned': POINTS_FOR_GIVER
                }
                
        except Exception as e:
            self.logger.error(f"Error saving feedback: {e}")
            raise


# Export dialog and mixin
__all__ = [
    'FeedbackDialog',
    'FeedbackBotMixin'
]
