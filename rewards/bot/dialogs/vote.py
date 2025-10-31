from typing import Any, List, Dict, Callable
from botbuilder.core import (
    TurnContext,
    CardFactory,
    MessageFactory
)
from botbuilder.dialogs import (
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    Dialog
)
from datetime import datetime


class VoteDialog(WaterfallDialog):
    """Dialog for handling the voting process in nomination campaigns"""

    def __init__(
        self,
        bot: Any,
        vote_callback: Callable[[dict, TurnContext], dict],
        dialog_id: str = "vote_dialog"
    ):
        super().__init__(dialog_id)

        self.bot = bot
        self.vote_callback = vote_callback

        # Add waterfall steps
        self.add_step(self.show_campaigns_step)
        self.add_step(self.show_nominees_step)
        self.add_step(self.confirm_vote_step)
        self.add_step(self.process_vote_step)
        self.add_step(self.final_step)

    async def show_campaigns_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """First step: Show available voting campaigns"""
        try:
            # Get active campaigns
            campaigns = await self.bot.get_active_campaigns()

            if not campaigns:
                await step_context.context.send_activity(
                    "📊 No active voting campaigns at the moment. Check back later!"  # noqa
                )
                return await step_context.end_dialog()

            # Create adaptive card with campaign selection
            card = self._create_campaign_selection_card(campaigns)
            message = MessageFactory.attachment(card)

            await step_context.context.send_activity(message)

            # Store campaigns in dialog state for later use
            step_context.values["campaigns"] = campaigns

            return Dialog.end_of_turn

        except Exception as e:
            self.bot.logger.error(f"Error in show_campaigns_step: {e}")
            await step_context.context.send_activity(
                "❌ Sorry, I encountered an error retrieving campaigns. Please try again."  # noqa
            )
            return await step_context.end_dialog()

    async def show_nominees_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Second step: Show nominees for selected campaign"""
        try:
            # Get the selected campaign from user input
            activity_value = step_context.context.activity.value

            if not activity_value or 'selected_campaign' not in activity_value:
                await step_context.context.send_activity(
                    "❌ Please select a campaign to proceed."
                )
                return await step_context.end_dialog()

            campaign_id = int(activity_value['selected_campaign'])

            # Find the selected campaign details
            campaigns = step_context.values["campaigns"]
            selected_campaign = next(
                (c for c in campaigns if c['campaign_id'] == campaign_id),
                None
            )

            if not selected_campaign:
                await step_context.context.send_activity(
                    "❌ Invalid campaign selection."
                )
                return await step_context.end_dialog()

            # Get nominees for this campaign
            nominees = await self.bot.get_campaign_nominees(campaign_id)

            if not nominees:
                await step_context.context.send_activity(
                    f"📊 No nominees found for '{selected_campaign['campaign_name']}'."
                )
                return await step_context.end_dialog()

            # Store selected campaign and nominees
            step_context.values["selected_campaign"] = selected_campaign
            step_context.values["nominees"] = nominees

            # Create adaptive card with nominee selection
            card = self._create_nominee_selection_card(selected_campaign, nominees)
            message = MessageFactory.attachment(card)

            await step_context.context.send_activity(message)

            return Dialog.end_of_turn

        except Exception as e:
            self.bot.logger.error(f"Error in show_nominees_step: {e}")
            await step_context.context.send_activity(
                "❌ Sorry, I encountered an error retrieving nominees. Please try again."
            )
            return await step_context.end_dialog()

    async def confirm_vote_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Third step: Confirm vote selection"""
        try:
            activity_value = step_context.context.activity.value

            if not activity_value or 'selected_nominee' not in activity_value:
                await step_context.context.send_activity(
                    "❌ Please select a nominee to vote for."
                )
                return await step_context.end_dialog()

            nomination_id = int(activity_value['selected_nominee'])
            vote_comment = activity_value.get('vote_comment', '').strip()

            # Find the selected nominee details
            nominees = step_context.values["nominees"]
            selected_nominee = next(
                (n for n in nominees if n['nomination_id'] == nomination_id),
                None
            )

            if not selected_nominee:
                await step_context.context.send_activity(
                    "❌ Invalid nominee selection."
                )
                return await step_context.end_dialog()

            # Store vote details
            step_context.values["selected_nominee"] = selected_nominee
            step_context.values["vote_comment"] = vote_comment

            # Create confirmation card
            card = self._create_vote_confirmation_card(
                step_context.values["selected_campaign"],
                selected_nominee,
                vote_comment
            )
            message = MessageFactory.attachment(card)

            await step_context.context.send_activity(message)

            return Dialog.end_of_turn

        except Exception as e:
            self.bot.logger.error(f"Error in confirm_vote_step: {e}")
            await step_context.context.send_activity(
                "❌ Sorry, I encountered an error processing your selection."
            )
            return await step_context.end_dialog()

    async def process_vote_step(
        self,
        step_context: WaterfallStepContext
    ) -> DialogTurnResult:
        """Fourth step: Process the actual vote"""
        try:
            activity_value = step_context.context.activity.value

            if not activity_value or activity_value.get('action') != 'confirm_vote':
                if activity_value and activity_value.get('action') == 'cancel':
                    await step_context.context.send_activity("Vote cancelled.")
                    return await step_context.end_dialog()
                else:
                    await step_context.context.send_activity(
                        "❌ Please confirm your vote to proceed."
                    )
                    return await step_context.end_dialog()

            # Prepare vote data
            vote_data = {
                'campaign_id': step_context.values["selected_campaign"]['campaign_id'],
                'nomination_id': step_context.values["selected_nominee"]['nomination_id'],
                'vote_comment': step_context.values["vote_comment"]
            }

            # Submit the vote through the callback
            result = await self.vote_callback(vote_data, step_context.context)

            # Store result for final step
            step_context.values["vote_result"] = result

            return await step_context.next(result)

        except Exception as e:
            self.bot.logger.error(f"Error in process_vote_step: {e}")
            await step_context.context.send_activity(
                "❌ Sorry, I encountered an error processing your vote."
            )
            return await step_context.end_dialog()

    async def final_step(self, step_context: WaterfallStepContext) -> DialogTurnResult:
        """Final step: Show vote result and current standings"""
        try:
            result = step_context.values["vote_result"]

            if result['success']:
                # Create success card with current standings
                card = self._create_vote_success_card(
                    step_context.values["selected_campaign"],
                    step_context.values["selected_nominee"],
                    result.get('vote_stats', [])
                )
            else:
                # Create error card
                card = self._create_vote_error_card(
                    step_context.values["selected_campaign"],
                    step_context.values["selected_nominee"],
                    result.get('error', 'Unknown error')
                )

            message = MessageFactory.attachment(card)
            await step_context.context.send_activity(message)

            return await step_context.end_dialog()

        except Exception as e:
            self.bot.logger.error(f"Error in final_step: {e}")
            await step_context.context.send_activity(
                "❌ Sorry, I encountered an error showing the results."
            )
            return await step_context.end_dialog()

    def _create_campaign_selection_card(self, campaigns: List[Dict]) -> Any:
        """Create adaptive card for campaign selection"""

        # Create radio button choices
        choices = []
        for campaign in campaigns:
            # Calculate time remaining
            if campaign['voting_end']:
                try:
                    voting_end = datetime.fromisoformat(campaign['voting_end'].replace('Z', '+00:00'))
                    now = datetime.now(voting_end.tzinfo)
                    time_remaining = voting_end - now

                    if time_remaining.total_seconds() > 0:
                        hours_remaining = int(time_remaining.total_seconds() // 3600)
                        time_text = f" (ends in {hours_remaining}h)" if hours_remaining > 0 else " (ending soon)"
                    else:
                        time_text = " (ended)"
                except Exception:
                    time_text = ""
            else:
                time_text = ""

            choice_text = f"**{campaign['campaign_name']}**{time_text}\n{campaign['reward_name']} - {campaign['total_nominations']} candidates"

            choices.append({
                "title": choice_text,
                "value": str(campaign['campaign_id'])
            })

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Select Voting Campaign 🗳️",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": "Choose a campaign to vote in:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selected_campaign",
                    "style": "expanded",
                    "choices": choices,
                    "placeholder": "Select a campaign"
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Continue",
                    "style": "positive",
                    "data": {
                        "action": "select_campaign"
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

        return CardFactory.adaptive_card(card_data)

    def _create_nominee_selection_card(self, campaign: Dict, nominees: List[Dict]) -> Any:
        """Create adaptive card for nominee selection"""

        # Create radio button choices for nominees
        choices = []
        for nominee in nominees:
            department_text = f" ({nominee['department']})" if nominee['department'] else ""
            vote_text = f" • {nominee['vote_count']} votes" if nominee['vote_count'] > 0 else ""

            choice_text = f"**{nominee['nominee_name']}**{department_text}{vote_text}\n{nominee['reason'][:100]}{'...' if len(nominee['reason']) > 100 else ''}"

            choices.append({
                "title": choice_text,
                "value": str(nominee['nomination_id'])
            })

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"Vote in: {campaign['campaign_name']}",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": f"**Reward:** {campaign['reward_name']} ({campaign['points']} points)",
                    "wrap": True,
                    "spacing": "Small"
                },
                {
                    "type": "TextBlock",
                    "text": "Select the candidate you want to vote for:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selected_nominee",
                    "style": "expanded",
                    "choices": choices,
                    "placeholder": "Select a candidate"
                },
                {
                    "type": "Input.Text",
                    "id": "vote_comment",
                    "placeholder": "Optional: Add a comment about why you're voting for this person",
                    "isMultiline": True,
                    "maxLength": 500,
                    "spacing": "Medium"
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Continue",
                    "style": "positive",
                    "data": {
                        "action": "select_nominee"
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "Back",
                    "data": {
                        "action": "back"
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

        return CardFactory.adaptive_card(card_data)

    def _create_vote_confirmation_card(
        self,
        campaign: Dict,
        nominee: Dict,
        comment: str
    ) -> Any:
        """Create adaptive card for vote confirmation"""

        comment_section = []
        if comment:
            comment_section = [
                {
                    "type": "TextBlock",
                    "text": "**Your Comment:**",
                    "weight": "Bolder",
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": comment,
                    "wrap": True,
                    "style": "emphasis"
                }
            ]

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Confirm Your Vote 🗳️",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": "Please confirm your vote:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Container",
                    "style": "emphasis",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"**Campaign:** {campaign['campaign_name']}",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Voting for:** {nominee['nominee_name']}",
                            "wrap": True,
                            "weight": "Bolder",
                            "color": "Good"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Reason:** {nominee['reason']}",
                            "wrap": True
                        }
                    ] + comment_section,
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": "⚠️ **Note:** Once submitted, your vote cannot be changed.",
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Warning",
                    "isSubtle": True
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "✅ Confirm Vote",
                    "style": "positive",
                    "data": {
                        "action": "confirm_vote"
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "← Back",
                    "data": {
                        "action": "back"
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

        return CardFactory.adaptive_card(card_data)

    def _create_vote_success_card(
        self,
        campaign: Dict,
        nominee: Dict,
        vote_stats: List[Dict]
    ) -> Any:
        """Create adaptive card for successful vote"""

        # Create current standings
        standings_items = []
        if vote_stats:
            standings_items.append({
                "type": "TextBlock",
                "text": "**Current Standings:**",
                "weight": "Bolder",
                "spacing": "Medium"
            })

            for i, candidate in enumerate(vote_stats[:5]):  # Show top 5
                rank_emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i] if i < 5 else f"{i+1}."
                standings_items.append({
                    "type": "TextBlock",
                    "text": f"{rank_emoji} {candidate['nominee_name']} - {candidate['vote_count']} votes",
                    "wrap": True
                })

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Vote Submitted Successfully! 🎉",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Good"
                },
                {
                    "type": "TextBlock",
                    "text": f"Thank you for voting in **{campaign['campaign_name']}**!",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Container",
                    "style": "good",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"Your vote for **{nominee['nominee_name']}** has been recorded.",
                            "wrap": True,
                            "weight": "Bolder"
                        }
                    ],
                    "spacing": "Medium"
                }
            ] + standings_items + [
                {
                    "type": "TextBlock",
                    "text": "Use '/campaigns' to check other active voting campaigns!",
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent",
                    "isSubtle": True
                }
            ]
        }

        return CardFactory.adaptive_card(card_data)

    def _create_vote_error_card(self, campaign: Dict, nominee: Dict, error: str) -> Any:
        """Create adaptive card for vote error"""

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Vote Could Not Be Processed ❌",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Attention"
                },
                {
                    "type": "TextBlock",
                    "text": f"**Campaign:** {campaign['campaign_name']}",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": f"**Attempted vote for:** {nominee['nominee_name']}",
                    "wrap": True
                },
                {
                    "type": "Container",
                    "style": "attention",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"**Reason:** {error}",
                            "wrap": True,
                            "weight": "Bolder"
                        }
                    ],
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": "💡 **Tip:** Use '/status' to check your current voting status, or try '/vote' again later.",
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent",
                    "isSubtle": True
                }
            ]
        }

        return CardFactory.adaptive_card(card_data)
