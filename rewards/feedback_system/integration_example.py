"""
NAV-Rewards Feedback System Integration Example.

This file shows how to integrate the Feedback System into
the existing RewardsEngine and BadgeBot.

Copy the relevant sections into your existing files.
"""

# =============================================================================
# STEP 1: Add to rewards/engine/engine.py
# =============================================================================

# Add these imports at the top of engine.py
IMPORTS_FOR_ENGINE = """
# Feedback System imports
from ..feedback.handlers import (
    FeedbackTypeHandler,
    UserFeedbackHandler,
    FeedbackStatsHandler,
    seed_feedback_types
)
from ..feedback.manager import FeedbackManager
"""

# Add this in RewardsEngine.__init__
INIT_CODE = """
# Initialize feedback manager (add after other initializations)
self.feedback_manager: Optional[FeedbackManager] = None
"""

# Add this in RewardsEngine.setup() method
SETUP_CODE = """
# =====================================================
# Feedback System Handlers
# =====================================================
FeedbackTypeHandler.configure(
    self.app, '/rewards/api/v1/feedback_types'
)
UserFeedbackHandler.configure(
    self.app, '/rewards/api/v1/user_feedback'
)
FeedbackStatsHandler.configure(
    self.app, '/rewards/api/v1/feedback_stats'
)

# Initialize feedback manager
self.feedback_manager = FeedbackManager(
    self.app,
    reward_engine=self,
    base_path='/rewards/api/v1'
)
self.logger.info("Feedback System initialized")
"""

# Add this in RewardsEngine.reward_startup() method
STARTUP_CODE = """
# Initialize feedback types
async with await self.connection.acquire() as conn:
    await seed_feedback_types(conn)
    self.logger.info("Feedback types seeded")
"""


# =============================================================================
# STEP 2: Add to rewards/bot/badge.py (BadgeBot)
# =============================================================================

# Add these imports
IMPORTS_FOR_BOT = """
# Feedback dialog
from ..feedback.dialogs.feedback import FeedbackDialog
from ..feedback.models import UserFeedback, POINTS_FOR_GIVER, POINTS_FOR_RECEIVER
"""

# Add to BadgeBot.commands list
COMMANDS_UPDATE = """
self.commands = [
    '/badge',
    '/give',
    '/help',
    '/leaderboard',
    '/badges',
    '/kudos',
    '/feedback',  # Add this
]
"""

# Add in BadgeBot.__init__
INIT_DIALOG = """
# Initialize feedback dialog
self.feedback_dialog = FeedbackDialog(
    bot=self,
    submission_callback=self.handle_feedback_submission
)
"""

# Add in BadgeBot.setup
SETUP_DIALOG = """
# Add feedback dialog to dialog set
self.dialog_set.add(self.feedback_dialog)
"""

# Add command handling in BadgeBot.on_message_activity
MESSAGE_HANDLER = """
elif command == '/feedback':
    await self.start_feedback_dialog(turn_context)
    return
"""

# Add helper card command info
HELP_CARD_UPDATE = """
self._create_command_row(
    "/feedback",
    "Give feedback on badges, kudos, or nominations"
),
"""

# Add these new methods to BadgeBot class
NEW_METHODS = '''
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
    feedback_data: dict
) -> dict:
    """
    Handle feedback submission from the dialog.
    
    Args:
        turn_context: Bot turn context
        feedback_data: Feedback data from dialog
        
    Returns:
        Result dictionary with feedback_id and points
    """
    try:
        # Get user info
        user_id = turn_context.activity.from_property.id
        user_email = turn_context.activity.from_property.aad_object_id
        user_name = turn_context.activity.from_property.name
        
        reward_engine = self.app.get('reward_engine')
        if not reward_engine:
            raise Exception("Reward engine not available")
        
        async with await reward_engine.connection.acquire() as conn:
            # Get feedback type ID from type name
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
            
            # Validate target and get receiver info
            target_info = await self._validate_feedback_target(
                conn,
                feedback_data['target_type'],
                feedback_data['target_id']
            )
            
            if not target_info:
                raise ValueError(
                    f"Target {feedback_data['target_type']}/{feedback_data['target_id']} "
                    "not found"
                )
            
            # Create feedback using manager
            feedback = await reward_engine.feedback_manager.submit_feedback(
                conn=conn,
                giver_user_id=int(user_id) if user_id and user_id.isdigit() else 0,
                target_type=feedback_data['target_type'],
                target_id=feedback_data['target_id'],
                receiver_user_id=target_info['receiver_user_id'],
                feedback_type_id=feedback_type_id,
                rating=int(feedback_data['rating']) if feedback_data.get('rating') else None,
                message=feedback_data.get('message'),
                giver_email=user_email,
                giver_name=user_name,
                receiver_email=target_info.get('receiver_email'),
                receiver_name=target_info.get('receiver_name')
            )
            
            # Send notification to receiver (optional)
            await self._send_feedback_notification(feedback, target_info)
            
            return {
                'success': True,
                'feedback_id': feedback.feedback_id,
                'points_earned': POINTS_FOR_GIVER
            }
            
    except Exception as e:
        self.logger.error(f"Error submitting feedback: {e}")
        raise

async def _validate_feedback_target(
    self,
    conn,
    target_type: str,
    target_id: int
) -> dict:
    """Validate feedback target and return receiver info."""
    if target_type == 'badge':
        query = """
            SELECT receiver_user as receiver_user_id, 
                   receiver_email, receiver_name, display_name
            FROM rewards.users_rewards
            WHERE award_id = $1 AND revoked = FALSE
        """
    elif target_type == 'kudos':
        query = """
            SELECT receiver_user_id, receiver_email, receiver_name
            FROM rewards.users_kudos
            WHERE kudos_id = $1 AND is_active = TRUE
        """
    elif target_type == 'nomination':
        query = """
            SELECT nominee_user_id as receiver_user_id,
                   nominee_email as receiver_email,
                   nominee_name as receiver_name
            FROM rewards.nominations
            WHERE nomination_id = $1 AND is_active = TRUE
        """
    else:
        return None
    
    result = await conn.fetch_one(query, target_id)
    if result:
        return dict(result)
    return None

async def _send_feedback_notification(self, feedback, target_info: dict):
    """Send notification to feedback receiver."""
    try:
        # Implement notification logic similar to badge notifications
        # This is optional and can be customized
        pass
    except Exception as e:
        self.logger.warning(f"Failed to send feedback notification: {e}")
'''


# =============================================================================
# STEP 3: Add to rewards/models/__init__.py
# =============================================================================

MODELS_EXPORT = """
# Feedback models
from ..feedback.models import (
    FeedbackType,
    UserFeedback,
    FeedbackCooldown,
    FeedbackStats,
    FeedbackByTarget,
    TargetType,
    INITIAL_FEEDBACK_TYPES
)
"""


# =============================================================================
# COMPLETE EXAMPLE: Modified engine.py setup method
# =============================================================================

COMPLETE_SETUP_EXAMPLE = '''
def setup(self, **kwargs):
    """Setup the RewardsEngine with all handlers and routes."""
    
    # ... existing handler setup code ...
    
    # Badge/Reward Handlers
    BadgeAssignHandler.configure(self.app, '/rewards/api/v1/assign')
    EmployeeSearchHandler.configure(self.app, '/rewards/api/v1/employees')
    UserRewardHandler.configure(self.app, '/rewards/api/v1/users_rewards')
    RewardCategoryHandler.configure(self.app, '/rewards/api/v1/reward_categories')
    RewardGroupHandler.configure(self.app, '/rewards/api/v1/reward_groups')
    RewardTypeHandler.configure(self.app, '/rewards/api/v1/reward_types')
    RewardHandler.configure(self.app, '/rewards/api/v1/rewards')
    RewardViewHandler.configure(self.app, '/rewards/api/v1/vw_rewards')
    
    # Nomination Handlers
    NominationAwardHandler.configure(self.app, '/rewards/api/v1/nominations/campaigns')
    NominationHandler.configure(self.app, '/rewards/api/v1/nominations')
    NominationVoteHandler.configure(self.app, '/rewards/api/v1/nominations/votes')
    NominationCommentHandler.configure(self.app, '/rewards/api/v1/nominations/comments')
    
    # Kudos Handlers
    UserKudosHandler.configure(self.app, '/rewards/api/v1/user_kudos')
    KudosTagHandler.configure(self.app, '/rewards/api/v1/kudos_tags')
    
    # =====================================================
    # NEW: Feedback System Handlers
    # =====================================================
    FeedbackTypeHandler.configure(
        self.app, '/rewards/api/v1/feedback_types'
    )
    UserFeedbackHandler.configure(
        self.app, '/rewards/api/v1/user_feedback'
    )
    FeedbackStatsHandler.configure(
        self.app, '/rewards/api/v1/feedback_stats'
    )
    
    # Initialize feedback manager
    self.feedback_manager = FeedbackManager(
        self.app,
        reward_engine=self,
        base_path='/rewards/api/v1'
    )
    
    self.logger.info("Feedback System initialized")
    
    # ... rest of setup code ...
'''


# =============================================================================
# COMPLETE EXAMPLE: Modified BadgeBot class
# =============================================================================

COMPLETE_BADGE_BOT_EXAMPLE = '''
class BadgeBot(AbstractBot):
    """Bot that handles badge, kudos, and feedback through interactive dialogs."""
    
    info_message: str = (
        "I\'m the Badge Bot. 🏅\\n"
        "Use \'/help\' to see all available commands! 🏅\\n"
        "You can use \'/badge\' to award badges 🏅, "
        "\'/kudos\' to send recognition 🌟, "
        "or \'/feedback\' to give feedback! 💬"
    )

    def __init__(self, bot_name: str, app: web.Application, **kwargs):
        self.commands = [
            \'/badge\',
            \'/give\',
            \'/help\',
            \'/leaderboard\',
            \'/badges\',
            \'/kudos\',
            \'/feedback\',  # NEW
        ]
        super().__init__(
            bot_name=bot_name,
            app=app,
            welcome_message=self.info_message,
            **kwargs
        )
        
        # ... existing dialog initializations ...
        
        # NEW: Initialize feedback dialog
        self.feedback_dialog = FeedbackDialog(
            bot=self,
            submission_callback=self.handle_feedback_submission
        )

    def setup(self, app: web.Application):
        super().setup(app)
        self.dialog_set = DialogSet(self.dialog_state)
        self.dialog_set.add(self.badge_dialog)
        self.dialog_set.add(self.kudos_dialog)
        self.dialog_set.add(self.feedback_dialog)  # NEW
    
    async def on_message_activity(self, turn_context: TurnContext):
        text = turn_context.activity.text
        
        if text and text.lower().strip() in [cmd.lower() for cmd in self.commands]:
            command = text.lower().strip()
            
            if command in [\'/badge\', \'/give\']:
                await self.start_badge_dialog(turn_context)
                return
            elif command == \'/kudos\':
                await self.start_kudos_dialog(turn_context)
                return
            elif command == \'/feedback\':  # NEW
                await self.start_feedback_dialog(turn_context)
                return
            elif command == \'/leaderboard\':
                await self.handle_leaderboard_command(turn_context)
                return
            elif command == \'/badges\':
                await self.handle_mybadges_command(turn_context)
                return
            elif command == \'/help\':
                await self.send_help_card(turn_context)
                return
        
        # ... rest of method ...
'''


# =============================================================================
# Print integration instructions
# =============================================================================

if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    NAV-REWARDS FEEDBACK SYSTEM INTEGRATION                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  STEP 1: Run Database Migration                                              ║
║  ─────────────────────────────────                                           ║
║  psql -U your_user -d your_database -f ddl/feedback_schema.sql               ║
║                                                                              ║
║  STEP 2: Copy the feedback module to your project                            ║
║  ─────────────────────────────────────────────────                           ║
║  Copy the 'feedback' directory to: rewards/feedback/                         ║
║                                                                              ║
║  STEP 3: Update rewards/engine/engine.py                                     ║
║  ───────────────────────────────────────                                     ║
║  - Add imports (see IMPORTS_FOR_ENGINE)                                      ║
║  - Add initialization (see INIT_CODE)                                        ║
║  - Add setup code (see SETUP_CODE)                                           ║
║  - Add startup code (see STARTUP_CODE)                                       ║
║                                                                              ║
║  STEP 4: Update rewards/bot/badge.py (Optional - for bot integration)        ║
║  ─────────────────────────────────────────────────────────────────           ║
║  - Add imports (see IMPORTS_FOR_BOT)                                         ║
║  - Update commands list                                                      ║
║  - Add dialog initialization                                                 ║
║  - Add command handler                                                       ║
║  - Add helper methods                                                        ║
║                                                                              ║
║  STEP 5: Test the integration                                                ║
║  ────────────────────────────────                                            ║
║  pytest tests/test_feedback.py -v                                            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
