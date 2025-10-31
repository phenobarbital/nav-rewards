from datetime import datetime
from typing import Any, List, Dict, Optional
from aiohttp import web
from botbuilder.core import (
    TurnContext,
    CardFactory,
    MessageFactory
)
from botbuilder.dialogs import (
    DialogSet,
)
from azure_teambots.bots.abstract import AbstractBot
from ..rewards.nomination.obj import NominationAward
from ..rewards.nomination.models import (
    NominationCampaign,
    Nomination,
    NominationVote
)
from ..context import EvalContext
from ..env import Environment
from .dialogs.vote import VoteDialog
from ..models import User


class NominationBot(AbstractBot):
    """Bot that handles nomination and voting processes through interactive dialogs
    and adaptive cards.

    This bot allows users to participate in nomination campaigns, vote for nominations,
    and view campaign statuses and results. It uses adaptive cards for rich UI interactions
    and dialog management for step-by-step user interactions.

    """  # noqa: E501

    info_message: str = (
        "I'm the Nomination Bot! 🗳️\n"
        "I help you participate in nomination and voting processes.\n"
        "Use '/help' to see all available commands! 🗳️"
    )

    def __init__(
        self,
        bot_name: str,
        app: web.Application,
        **kwargs
    ):
        # Set the commands that this bot handles
        self.commands = [
            '/vote',
            '/nominate',
            '/campaigns',
            '/status',
            '/results',
            '/help'
        ]
        super().__init__(
            bot_name=bot_name,
            app=app,
            welcome_message=self.info_message,
            **kwargs
        )

        # Initialize the vote dialog
        self.vote_dialog = VoteDialog(
            bot=self,
            vote_callback=self.handle_vote_submission
        )

    def setup(self, app: web.Application):
        """Setup the bot with the application"""
        super().setup(app)

        # Add the vote dialog to the dialog set
        self.dialog_set = DialogSet(self.dialog_state)
        self.dialog_set.add(self.vote_dialog)

    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming message activities"""
        text = turn_context.activity.text

        # Check if this is a help command
        if text and text.lower().strip() == '/help':
            await self.send_help_card(turn_context)
            return

        # Check if this is a command
        if text and text.lower().strip() in [
            cmd.lower() for cmd in self.commands
        ]:
            command = text.lower().strip()

            if command == '/vote':
                await self.start_vote_dialog(turn_context)
                return
            elif command == '/campaigns':
                await self.handle_campaigns_command(turn_context)
                return
            elif command == '/status':
                await self.handle_status_command(turn_context)
                return
            elif command == '/results':
                await self.handle_results_command(turn_context)
                return
            elif command == '/nominate':
                await self.handle_nominate_command(turn_context)
                return

        # Check if this is a dialog continuation (adaptive card submission)
        if turn_context.activity.value:
            await self.continue_vote_dialog(turn_context)
            return

        # Default response for other messages
        await turn_context.send_activity(
            "Hi! I'm the Nomination Bot. Use '/help' to see all available commands! 🗳️"  # noqa
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
                    "text": "Nomination Bot Help 🗳️",
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
                            "/vote",
                            "Vote in active nomination campaigns"
                        ),
                        self._create_command_row(
                            "/campaigns",
                            "View all active campaigns"
                        ),
                        self._create_command_row(
                            "/status",
                            "Check voting status of campaigns"
                        ),
                        self._create_command_row(
                            "/results",
                            "View results of closed campaigns"
                        ),
                        self._create_command_row(
                            "/nominate",
                            "Submit nominations (if available)"
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
                    "text": "💡 **Tip:** Use '/vote' to participate in any active voting process!",  # noqa
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent",
                    "isSubtle": True
                }
            ]
        }
        return self.create_card(card_data)

    def _create_command_row(self, command: str, description: str) -> Dict:
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

    async def start_vote_dialog(self, turn_context: TurnContext):
        """Start the voting dialog"""
        try:
            # Create dialog context
            dialog_context = await self.dialog_set.create_context(turn_context)

            # Check if dialog is already active
            if dialog_context.active_dialog is not None:
                await dialog_context.continue_dialog()
            else:
                # Start new vote dialog
                await dialog_context.begin_dialog(self.vote_dialog.id)

            # Save conversation state
            await self.save_state_changes(turn_context)

        except Exception as e:
            self.logger.error(f"Error starting vote dialog: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error starting the voting process. Please try again."  # noqa
            )

    async def continue_vote_dialog(self, turn_context: TurnContext):
        """Continue an active vote dialog"""
        try:
            # Create dialog context
            dialog_context = await self.dialog_set.create_context(turn_context)

            # Check for cancel action
            activity_value = turn_context.activity.value
            if activity_value and activity_value.get('action') == 'cancel':
                await dialog_context.cancel_all_dialogs()
                await turn_context.send_activity("Voting process cancelled.")
                await self.save_state_changes(turn_context)
                return

            # Continue the dialog
            if dialog_context.active_dialog is not None:
                await dialog_context.continue_dialog()
            else:
                # No active dialog, start a new one
                await dialog_context.begin_dialog(self.vote_dialog.id)

            # Save conversation state
            await self.save_state_changes(turn_context)

        except Exception as e:
            self.logger.error(f"Error continuing vote dialog: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error processing your vote. Please try again with '/vote'."  # noqa
            )

    async def handle_vote_submission(
        self,
        vote_data: dict,
        context: TurnContext
    ) -> dict:
        """Handle the final vote submission"""
        try:
            campaign_id = vote_data['campaign_id']
            nomination_id = vote_data['nomination_id']
            vote_comment = vote_data.get('vote_comment', '')

            # Get user info from the context
            user_profile = await self.user_profile_accessor.get(context, None)
            if not user_profile or not hasattr(user_profile, 'email'):
                return {
                    'success': False,
                    'error': 'Could not identify user'
                }

            # Find the user in the system
            try:
                reward_engine = self.app['reward_engine']
                async with await reward_engine.connection.acquire() as conn:
                    User.Meta.connection = conn
                    user = await User.get(email=user_profile.email)
            except Exception as e:
                self.logger.error(
                    f"Could not find user: {user_profile.email}: {e}"
                )
                return {
                    'success': False,
                    'error': 'User not found in system'
                }

            # Get the campaign and nomination award
            try:
                env = Environment(
                    connection=reward_engine.connection,
                    cache=reward_engine.get_cache()
                )

                async with await env.connection.acquire() as conn:
                    NominationCampaign.Meta.connection = conn
                    campaign = await NominationCampaign.get(
                        campaign_id=campaign_id
                    )

                    nomination_award = await reward_engine.get_reward(
                        campaign.reward_id
                    )
                    if not isinstance(nomination_award, NominationAward):
                        return {
                            'success': False,
                            'error': 'Invalid nomination award type'
                        }

                # Create evaluation context
                ctx = EvalContext(
                    request=None,
                    user=user,
                    session={'user_id': user.user_id, 'email': user.email}
                )

                # Submit the vote
                vote_result = await nomination_award.submit_vote(
                    ctx=ctx,
                    env=env,
                    campaign_id=campaign_id,
                    nomination_id=nomination_id,
                    vote_comment=vote_comment
                )

                if vote_result:
                    # Get updated vote statistics
                    vote_stats = await nomination_award.get_real_time_vote_counts(
                        campaign_id=campaign_id,
                        env=env
                    )

                    return {
                        'success': True,
                        'campaign_name': campaign.campaign_name,
                        'vote_stats': vote_stats
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Failed to submit vote'
                    }

            except Exception as e:
                error_msg = str(e)
                # Parse common error messages
                if "not in voting phase" in error_msg:
                    return {
                        'success': False,
                        'error': 'This campaign is not currently accepting votes'
                    }
                elif "already voted" in error_msg or "Maximum votes" in error_msg:
                    return {
                        'success': False,
                        'error': 'You have already used all your votes for this campaign'
                    }
                elif "not eligible to vote" in error_msg:
                    return {
                        'success': False,
                        'error': 'You are not eligible to vote in this campaign'
                    }
                else:
                    self.logger.error(f"Error submitting vote: {e}")
                    return {
                        'success': False,
                        'error': 'An error occurred while processing your vote'
                    }

        except Exception as e:
            self.logger.error(f"Error handling vote submission: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_active_campaigns(self) -> List[Dict]:
        """Get list of active voting campaigns"""
        try:
            reward_engine = self.app['reward_engine']
            async with await reward_engine.connection.acquire() as conn:
                # Query for active voting campaigns
                query = """
                    SELECT nc.campaign_id, nc.campaign_name, nc.description,
                    nc.voting_end, nc.total_nominations,
                    r.reward, r.points
                    FROM rewards.nomination_campaigns nc
                    JOIN rewards.rewards r ON nc.reward_id = r.reward_id
                    WHERE nc.status = 'voting'
                    AND nc.voting_end > NOW()
                    ORDER BY nc.voting_end ASC
                """
                results = await conn.fetch_all(query)

                campaigns = []
                for row in results:
                    campaigns.append({
                        'campaign_id': row['campaign_id'],
                        'campaign_name': row['campaign_name'],
                        'description': row['description'],
                        'voting_end': row['voting_end'].isoformat() if row['voting_end'] else None,
                        'total_nominations': row['total_nominations'],
                        'reward_name': row['reward'],
                        'points': row['points']
                    })

                return campaigns

        except Exception as e:
            self.logger.error(f"Error getting active campaigns: {e}")
            return []

    async def get_campaign_nominees(self, campaign_id: int) -> List[Dict]:
        """Get list of nominees for a specific campaign"""
        try:
            reward_engine = self.app['reward_engine']
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT n.nomination_id, n.nominee_name, n.reason,
                    n.vote_count, u.display_name, u.department
                    FROM rewards.nominations n
                    LEFT JOIN auth.users u ON n.nominee_user_id = u.user_id
                    WHERE n.campaign_id = $1 AND n.is_active = true
                    ORDER BY n.vote_count DESC, n.nominated_at ASC
                """
                results = await conn.fetch_all(query, campaign_id)

                nominees = []
                for row in results:
                    nominees.append({
                        'nomination_id': row['nomination_id'],
                        'nominee_name': row['nominee_name'],
                        'display_name': row['display_name'],
                        'department': row['department'],
                        'reason': row['reason'],
                        'vote_count': row['vote_count']
                    })

                return nominees

        except Exception as e:
            self.logger.error(f"Error getting campaign nominees: {e}")
            return []

    # Placeholder methods for other commands
    async def handle_campaigns_command(self, turn_context: TurnContext):
        """Handle /campaigns command"""
        try:
            campaigns = await self.get_active_campaigns()

            if not campaigns:
                await turn_context.send_activity(
                    "📊 No active voting campaigns at the moment. Check back later!"
                )
                return

            # Create a simple list card
            card_data = {
                "type": "AdaptiveCard",
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.3",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "Active Voting Campaigns 🗳️",
                        "weight": "Bolder",
                        "size": "Large"
                    }
                ]
            }

            # Add each campaign
            for campaign in campaigns:
                card_data["body"].append({
                    "type": "Container",
                    "style": "emphasis",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": campaign['campaign_name'],
                            "weight": "Bolder"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Reward:** {campaign['reward_name']} ({campaign['points']} points)",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Candidates:** {campaign['total_nominations']}",
                            "wrap": True
                        }
                    ],
                    "spacing": "Medium"
                })

            card_data["body"].append({
                "type": "TextBlock",
                "text": "Use '/vote' to participate in any of these campaigns!",
                "wrap": True,
                "spacing": "Medium",
                "color": "Accent"
            })

            card = self.create_card(card_data)
            message = MessageFactory.attachment(card)
            await turn_context.send_activity(message)

        except Exception as e:
            self.logger.error(f"Error handling campaigns command: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error retrieving campaigns."
            )

    def create_card(self, card_data: dict) -> Any:
        """Create an adaptive card from card data"""
        return CardFactory.adaptive_card(card_data)

    async def handle_status_command(self, turn_context: TurnContext):
        """Handle /status command - show user's voting status"""
        try:
            # Get user info
            user_profile = await self.user_profile_accessor.get(
                turn_context,
                None
            )
            if not user_profile or not hasattr(user_profile, 'email'):
                await turn_context.send_activity(
                    "❌ Could not identify user. Please try again."
                )
                return

            # Find user in system
            reward_engine = self.app['reward_engine']
            async with await reward_engine.connection.acquire() as conn:
                User.Meta.connection = conn
                try:
                    user = await User.get(email=user_profile.email)
                except Exception:
                    await turn_context.send_activity(
                        "❌ User not found in system."
                    )
                    return

                # Get user's voting status for all active campaigns
                status_data = await self._get_user_voting_status(
                    conn,
                    user.user_id
                )

                if not status_data['active_campaigns']:
                    await turn_context.send_activity(
                        "📊 No active voting campaigns at the moment."
                    )
                    return

                # Create status card
                card = self._create_user_status_card(status_data, user)
                message = MessageFactory.attachment(card)
                await turn_context.send_activity(message)

        except Exception as e:
            self.logger.error(f"Error handling status command: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error retrieving your status."
            )

    async def handle_results_command(self, turn_context: TurnContext):
        """Handle /results command - show results of recent campaigns"""
        try:
            reward_engine = self.app['reward_engine']
            async with await reward_engine.connection.acquire() as conn:
                # Get recent closed campaigns
                recent_results = await self._get_recent_campaign_results(conn)

                if not recent_results:
                    await turn_context.send_activity(
                        "📊 No recent campaign results available."
                    )
                    return

                # Create results card
                card = self._create_results_card(recent_results)
                message = MessageFactory.attachment(card)
                await turn_context.send_activity(message)

        except Exception as e:
            self.logger.error(f"Error handling results command: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error retrieving results."
            )

    async def _get_user_voting_status(self, conn, user_id: int) -> dict:
        """Get comprehensive voting status for a user"""

        # Get active campaigns
        active_campaigns_query = """
            SELECT nc.campaign_id, nc.campaign_name, nc.voting_end,
                nc.max_votes_per_user, nc.total_nominations,
                r.reward, r.points,
                COUNT(nv.vote_id) as user_votes_in_campaign
            FROM rewards.nomination_campaigns nc
            JOIN rewards.rewards r ON nc.reward_id = r.reward_id
            LEFT JOIN rewards.nomination_votes nv ON nc.campaign_id = nv.campaign_id
                                                AND nv.voter_user_id = $1
            WHERE nc.status = 'voting' AND nc.voting_end > NOW()
            GROUP BY nc.campaign_id, nc.campaign_name, nc.voting_end,
                    nc.max_votes_per_user, nc.total_nominations, r.reward, r.points
            ORDER BY nc.voting_end ASC
        """  # noqa: E501

        active_campaigns = await conn.fetch_all(
            active_campaigns_query,
            user_id
        )

        # Get user's vote history
        vote_history_query = """
            SELECT nv.campaign_id, nc.campaign_name, nv.voted_at,
                n.nominee_name, nv.vote_comment
            FROM rewards.nomination_votes nv
            JOIN rewards.nomination_campaigns nc ON nv.campaign_id = nc.campaign_id
            JOIN rewards.nominations n ON nv.nomination_id = n.nomination_id
            WHERE nv.voter_user_id = $1
            ORDER BY nv.voted_at DESC
            LIMIT 10
        """  # noqa: E501

        vote_history = await conn.fetch_all(
            vote_history_query,
            user_id
        )

        # Calculate statistics
        total_votes_cast = len(vote_history)
        campaigns_participated = len(
            set(vote['campaign_id'] for vote in vote_history)
        )

        return {
            'active_campaigns': [
                dict(campaign) for campaign in active_campaigns
            ],
            'vote_history': [dict(vote) for vote in vote_history],
            'statistics': {
                'total_votes_cast': total_votes_cast,
                'campaigns_participated': campaigns_participated
            }
        }

    async def _get_recent_campaign_results(self, conn, limit: int = 5) -> list:
        """Get results of recent closed campaigns"""

        results_query = """
            SELECT nc.campaign_id, nc.campaign_name, nc.voting_end,
                nc.winner_email, nc.total_votes, nc.total_nominations,
                r.reward, r.points,
                -- Get winner details
                winner_n.nominee_name as winner_name,
                winner_n.vote_count as winner_votes,
                winner_n.reason as winner_reason
            FROM rewards.nomination_campaigns nc
            JOIN rewards.rewards r ON nc.reward_id = r.reward_id
            LEFT JOIN rewards.nominations winner_n ON nc.campaign_id = winner_n.campaign_id
                                                    AND winner_n.is_winner = true
            WHERE nc.status = 'closed'
            ORDER BY nc.voting_end DESC
            LIMIT $1
        """  # noqa: E501

        campaigns = await conn.fetch_all(results_query, limit)

        results = []
        for campaign in campaigns:
            campaign_dict = dict(campaign)

            # Get top candidates for this campaign
            top_candidates_query = """
                SELECT nominee_name, vote_count, reason
                FROM rewards.nominations
                WHERE campaign_id = $1 AND is_active = true
                ORDER BY vote_count DESC, nominated_at ASC
                LIMIT 5
            """

            top_candidates = await conn.fetch_all(
                top_candidates_query,
                campaign['campaign_id']
            )
            campaign_dict['top_candidates'] = [
                dict(candidate) for candidate in top_candidates
            ]

            results.append(campaign_dict)

        return results

    def _create_user_status_card(self, status_data: dict, user) -> Any:
        """Create adaptive card for user voting status"""

        # Build campaign status items
        campaign_items = []
        for campaign in status_data['active_campaigns']:
            votes_used = campaign['user_votes_in_campaign']
            votes_remaining = campaign['max_votes_per_user'] - votes_used

            # Time remaining calculation
            if campaign['voting_end']:
                try:
                    voting_end = campaign['voting_end']
                    now = datetime.now(voting_end.tzinfo)
                    time_remaining = voting_end - now

                    if time_remaining.total_seconds() > 0:
                        hours_remaining = int(
                            time_remaining.total_seconds() // 3600
                        )
                        time_text = f"Ends in {hours_remaining}h" if hours_remaining > 0 else "Ending soon"  # noqa: E501
                    else:
                        time_text = "Ended"
                except Exception:
                    time_text = "Unknown"
            else:
                time_text = "Unknown"

            status_color = "Good" if votes_remaining > 0 else "Warning"
            vote_status = f"{votes_used}/{campaign['max_votes_per_user']} votes used"  # noqa: E501

            campaign_items.append({
                "type": "Container",
                "style": "emphasis",
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": campaign['campaign_name'],
                                        "weight": "Bolder"
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": f"{campaign['reward']} • {campaign['total_nominations']} candidates",  # noqa: E501
                                        "size": "Small",
                                        "isSubtle": True
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": vote_status,
                                        "color": status_color,
                                        "weight": "Bolder",
                                        "horizontalAlignment": "Right"
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": time_text,
                                        "size": "Small",
                                        "isSubtle": True,
                                        "horizontalAlignment": "Right"
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "spacing": "Medium"
            })

        # Build recent votes section
        recent_votes_items = []
        if status_data['vote_history']:
            recent_votes_items.append({
                "type": "TextBlock",
                "text": "Recent Votes:",
                "weight": "Bolder",
                "spacing": "Medium"
            })

            for vote in status_data['vote_history'][:5]:
                vote_date = vote['voted_at'].strftime("%b %d, %Y") if vote['voted_at'] else "Unknown"  # noqa: E501

                recent_votes_items.append({
                    "type": "TextBlock",
                    "text": f"• **{vote['nominee_name']}** in {vote['campaign_name']} ({vote_date})",  # noqa: E501
                    "wrap": True,
                    "size": "Small"
                })

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"Voting Status for {user.display_name} 📊",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "Container",
                    "items": [
                        {
                            "type": "ColumnSet",
                            "columns": [
                                {
                                    "type": "Column",
                                    "width": "stretch",
                                    "items": [
                                        {
                                            "type": "TextBlock",
                                            "text": f"**Total Votes Cast:** {status_data['statistics']['total_votes_cast']}",  # noqa: E501
                                            "wrap": True
                                        }
                                    ]
                                },
                                {
                                    "type": "Column",
                                    "width": "stretch",
                                    "items": [
                                        {
                                            "type": "TextBlock",
                                            "text": f"**Campaigns Participated:** {status_data['statistics']['campaigns_participated']}",  # noqa: E501
                                            "wrap": True
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                    "style": "good",
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": "Active Campaigns:",
                    "weight": "Bolder",
                    "spacing": "Large"
                }
            ] + campaign_items + recent_votes_items + [
                {
                    "type": "TextBlock",
                    "text": "💡 Use '/vote' to participate in active campaigns!",  # noqa
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent",
                    "isSubtle": True
                }
            ]
        }

        return CardFactory.adaptive_card(card_data)

    def _create_results_card(self, recent_results: list) -> Any:
        """Create adaptive card for campaign results"""

        results_items = []

        for result in recent_results:
            # Winner section
            winner_section = []
            if result['winner_name']:
                winner_section = [
                    {
                        "type": "TextBlock",
                        "text": f"🏆 **Winner:** {result['winner_name']} ({result['winner_votes']} votes)",  # noqa
                        "wrap": True,
                        "weight": "Bolder",
                        "color": "Good"
                    },
                    {
                        "type": "TextBlock",
                        "text": f"**Reason:** {result['winner_reason']}",
                        "wrap": True,
                        "size": "Small"
                    }
                ]
            else:
                winner_section = [
                    {
                        "type": "TextBlock",
                        "text": "No winner selected",
                        "color": "Warning"
                    }
                ]

            # Top candidates
            top_candidates_text = ""
            if result['top_candidates']:
                standings = []
                for i, candidate in enumerate(result['top_candidates'][:3], 1):
                    emoji = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
                    standings.append(f"{emoji} {candidate['nominee_name']} - {candidate['vote_count']} votes")
                top_candidates_text = "\n".join(standings)

            # End date
            end_date = result['voting_end'].strftime("%B %d, %Y") if result['voting_end'] else "Unknown"

            results_items.append({
                "type": "Container",
                "style": "emphasis",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": result['campaign_name'],
                        "weight": "Bolder",
                        "size": "Medium"
                    },
                    {
                        "type": "TextBlock",
                        "text": f"**Reward:** {result['reward']} ({result['points']} points) • **Ended:** {end_date}",
                        "wrap": True,
                        "size": "Small",
                        "isSubtle": True
                    }
                ] + winner_section + [
                    {
                        "type": "TextBlock",
                        "text": "**Final Standings:**",
                        "weight": "Bolder",
                        "spacing": "Small"
                    },
                    {
                        "type": "TextBlock",
                        "text": top_candidates_text,
                        "wrap": True,
                        "fontType": "Monospace",
                        "size": "Small"
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Total Votes: {result['total_votes']} • Total Candidates: {result['total_nominations']}",  # noqa
                        "size": "Small",
                        "isSubtle": True
                    }
                ],
                "spacing": "Large"
            })

        card_data = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Recent Campaign Results 🏆",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": "Here are the results of recently completed campaigns:",
                    "wrap": True,
                    "spacing": "Medium"
                }
            ] + results_items + [
                {
                    "type": "TextBlock",
                    "text": "💡 Use '/campaigns' to see currently active campaigns!",
                    "wrap": True,
                    "spacing": "Medium",
                    "color": "Accent",
                    "isSubtle": True
                }
            ]
        }

        return CardFactory.adaptive_card(card_data)

    # === Additional Command: Nomination Submission ===
    async def handle_nominate_command(self, turn_context: TurnContext):
        """Handle /nominate command - submit nominations for open campaigns"""
        try:
            # Check for campaigns accepting nominations
            reward_engine = self.app['reward_engine']
            async with await reward_engine.connection.acquire() as conn:
                # Look for campaigns in nomination phase or
                # those allowing additional nominations
                nomination_campaigns_query = """
                    SELECT nc.campaign_id, nc.campaign_name, nc.nomination_end,
                        nc.allow_self_nomination, nc.max_nominations_per_user,
                        r.reward, r.points
                    FROM rewards.nomination_campaigns nc
                    JOIN rewards.rewards r ON nc.reward_id = r.reward_id
                    WHERE (nc.status = 'nomination' AND nc.nomination_end > NOW())
                    OR (nc.status = 'voting' AND nc.campaign_metadata->>'allow_additional_nominations' = 'true')
                    ORDER BY nc.nomination_end ASC
                """  # noqa: E501

                open_campaigns = await conn.fetch_all(
                    nomination_campaigns_query
                )

                if not open_campaigns:
                    await turn_context.send_activity(
                        "📝 No campaigns are currently accepting nominations. Check back later!"  # noqa
                    )
                    return

                # Create nomination selection card
                card = self._create_nomination_campaigns_card(
                    [dict(campaign) for campaign in open_campaigns]
                )
                message = MessageFactory.attachment(card)
                await turn_context.send_activity(message)

        except Exception as e:
            self.logger.error(f"Error handling nominate command: {e}")
            await turn_context.send_activity(
                "❌ Sorry, I encountered an error retrieving nomination opportunities."  # noqa
            )

    def _create_nomination_campaigns_card(self, campaigns: list) -> Any:
        """Create adaptive card for nomination campaign selection"""

        campaign_choices = []
        for campaign in campaigns:
            end_date = campaign['nomination_end'].strftime("%B %d") if campaign['nomination_end'] else "Unknown"
            choice_text = f"**{campaign['campaign_name']}**\n{campaign['reward']} • Nominations end {end_date}"

            campaign_choices.append({
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
                    "text": "Submit Nomination 📝",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": "Select a campaign to submit a nomination:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Input.ChoiceSet",
                    "id": "selected_campaign",
                    "style": "expanded",
                    "choices": campaign_choices,
                    "placeholder": "Select a campaign"
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Continue",
                    "style": "positive",
                    "data": {
                        "action": "start_nomination"
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
