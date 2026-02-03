"""
Feedback System Engine Integration for NAV-Rewards.

This module provides the integration layer between the Feedback System
and the existing RewardsEngine. It handles initialization, route registration,
and event management for feedback operations.

Usage:
    from rewards.feedback import FeedbackManager
    
    # In your engine setup
    feedback_manager = FeedbackManager(app, reward_engine)
    feedback_manager.setup()
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from aiohttp import web
from navconfig.logging import logging
from .models import (
    FeedbackType,
    UserFeedback,
    FeedbackCooldown,
    INITIAL_FEEDBACK_TYPES,
    POINTS_FOR_GIVER,
    POINTS_FOR_RECEIVER,
    MAX_FEEDBACK_PER_DAY,
    TargetType
)
from .handlers import (
    FeedbackTypeHandler,
    UserFeedbackHandler,
    FeedbackStatsHandler,
    seed_feedback_types
)


class FeedbackManager:
    """
    Manager class for the Feedback System.
    
    Handles:
        - Handler registration
        - Route configuration
        - Event integration
        - Statistics and analytics
    """
    
    def __init__(
        self,
        app: web.Application,
        reward_engine: Any = None,
        base_path: str = '/rewards/api/v1'
    ):
        """
        Initialize the Feedback Manager.
        
        Args:
            app: aiohttp Application instance
            reward_engine: RewardsEngine instance (optional, can be set later)
            base_path: Base URL path for API endpoints
        """
        self.app = app
        self.reward_engine = reward_engine
        self.base_path = base_path
        self.logger = logging.getLogger('feedback_manager')
        
        # Store reference in app
        self.app['feedback_manager'] = self
    
    def setup(self):
        """
        Setup the Feedback System.
        
        Registers all handlers and routes.
        """
        self.logger.info("Setting up Feedback System...")
        
        # Register handlers
        FeedbackTypeHandler.configure(
            self.app,
            f'{self.base_path}/feedback_types'
        )
        
        UserFeedbackHandler.configure(
            self.app,
            f'{self.base_path}/user_feedback'
        )
        
        FeedbackStatsHandler.configure(
            self.app,
            f'{self.base_path}/feedback_stats'
        )
        
        self.logger.info(
            f"Feedback System routes registered at {self.base_path}"
        )
    
    async def initialize_database(self, conn):
        """
        Initialize database with feedback types.
        
        Should be called during app startup.
        
        Args:
            conn: Database connection
        """
        try:
            await seed_feedback_types(conn)
            self.logger.info("Feedback types initialized")
        except Exception as e:
            self.logger.error(f"Error initializing feedback types: {e}")
    
    async def submit_feedback(
        self,
        conn,
        giver_user_id: int,
        target_type: str,
        target_id: int,
        receiver_user_id: int,
        feedback_type_id: Optional[int] = None,
        rating: Optional[int] = None,
        message: Optional[str] = None,
        giver_email: Optional[str] = None,
        giver_name: Optional[str] = None,
        receiver_email: Optional[str] = None,
        receiver_name: Optional[str] = None
    ) -> UserFeedback:
        """
        Submit feedback programmatically.
        
        This method can be called from other parts of the system
        (e.g., event handlers, scheduled jobs) to submit feedback.
        
        Args:
            conn: Database connection
            giver_user_id: User giving feedback
            target_type: Type of target ('badge', 'kudos', 'nomination')
            target_id: ID of the target
            receiver_user_id: User who received the original recognition
            feedback_type_id: Optional feedback type
            rating: Optional 1-5 rating
            message: Optional message
            giver_email: Optional giver email
            giver_name: Optional giver name
            receiver_email: Optional receiver email
            receiver_name: Optional receiver name
            
        Returns:
            Created UserFeedback instance
            
        Raises:
            ValueError: If validation fails
        """
        # Validate no self-feedback
        if giver_user_id == receiver_user_id:
            raise ValueError("Cannot give feedback on your own recognition")
        
        # Validate target type
        valid_types = [t.value for t in TargetType]
        if target_type not in valid_types:
            raise ValueError(f"Invalid target_type: {target_type}")
        
        # Validate rating
        if rating is not None and not (1 <= rating <= 5):
            raise ValueError("Rating must be between 1 and 5")
        
        # Check for duplicate
        dup_query = """
            SELECT 1 FROM rewards.user_feedback
            WHERE target_type = $1 AND target_id = $2 
            AND giver_user_id = $3 AND is_active = TRUE
        """
        existing = await conn.fetch_one(dup_query, target_type, target_id, giver_user_id)
        if existing:
            raise ValueError("Feedback already submitted for this target")
        
        # Create feedback
        UserFeedback.Meta.connection = conn
        
        feedback = UserFeedback(
            target_type=target_type,
            target_id=target_id,
            giver_user_id=giver_user_id,
            giver_email=giver_email,
            giver_name=giver_name,
            receiver_user_id=receiver_user_id,
            receiver_email=receiver_email,
            receiver_name=receiver_name,
            feedback_type_id=feedback_type_id,
            rating=rating,
            message=message[:500] if message else None,
            points_given=POINTS_FOR_GIVER,
            points_received=POINTS_FOR_RECEIVER
        )
        
        await feedback.insert()
        
        self.logger.info(
            f"Feedback #{feedback.feedback_id} submitted: "
            f"{target_type}/{target_id} by user {giver_user_id}"
        )
        
        return feedback
    
    async def get_feedback_summary(
        self,
        conn,
        target_type: str,
        target_id: int
    ) -> Dict[str, Any]:
        """
        Get feedback summary for a target.
        
        Args:
            conn: Database connection
            target_type: Type of target
            target_id: ID of the target
            
        Returns:
            Dictionary with feedback summary
        """
        query = """
            SELECT 
                COUNT(*) as feedback_count,
                AVG(rating) FILTER (WHERE rating IS NOT NULL) as avg_rating,
                array_agg(DISTINCT ft.display_name) FILTER (WHERE ft.display_name IS NOT NULL) as feedback_types
            FROM rewards.user_feedback f
            LEFT JOIN rewards.feedback_types ft ON f.feedback_type_id = ft.feedback_type_id
            WHERE f.target_type = $1 AND f.target_id = $2 AND f.is_active = TRUE
        """
        result = await conn.fetch_one(query, target_type, target_id)
        
        return {
            'target_type': target_type,
            'target_id': target_id,
            'feedback_count': result['feedback_count'] or 0,
            'avg_rating': float(result['avg_rating']) if result['avg_rating'] else None,
            'feedback_types': result['feedback_types'] or []
        }
    
    async def get_user_feedback_stats(
        self,
        conn,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Get feedback statistics for a user.
        
        Args:
            conn: Database connection
            user_id: User ID
            
        Returns:
            Dictionary with user feedback stats
        """
        query = """
            SELECT * FROM rewards.vw_user_feedback_stats
            WHERE user_id = $1
        """
        result = await conn.fetch_one(query, user_id)
        
        if result:
            return dict(result)
        
        return {
            'user_id': user_id,
            'feedback_given': 0,
            'points_earned_giving': 0,
            'feedback_received': 0,
            'points_earned_receiving': 0,
            'avg_rating_received': 0
        }


class FeedbackEventHandler:
    """
    Event handler for feedback-related events.
    
    Integrates with the RabbitMQ event system to handle
    feedback events asynchronously.
    """
    
    def __init__(self, feedback_manager: FeedbackManager):
        self.feedback_manager = feedback_manager
        self.logger = logging.getLogger('feedback_events')
    
    async def on_badge_awarded(self, event_data: Dict[str, Any]):
        """
        Handle badge awarded event.
        
        Can be used to prompt for feedback or send notifications.
        """
        award_id = event_data.get('award_id')
        receiver_user_id = event_data.get('receiver_user_id')
        
        self.logger.info(
            f"Badge awarded event received: award_id={award_id}"
        )
        
        # Could trigger feedback reminders, notifications, etc.
    
    async def on_kudos_sent(self, event_data: Dict[str, Any]):
        """Handle kudos sent event."""
        kudos_id = event_data.get('kudos_id')
        
        self.logger.info(
            f"Kudos sent event received: kudos_id={kudos_id}"
        )
    
    async def on_feedback_submitted(self, event_data: Dict[str, Any]):
        """
        Handle feedback submitted event.
        
        Can be used to send notifications to the receiver.
        """
        feedback_id = event_data.get('feedback_id')
        receiver_user_id = event_data.get('receiver_user_id')
        points_received = event_data.get('points_received', POINTS_FOR_RECEIVER)
        
        self.logger.info(
            f"Feedback submitted event: feedback_id={feedback_id}, "
            f"receiver={receiver_user_id}, points={points_received}"
        )
        
        # Could send notification to receiver about feedback and points


def setup_feedback_system(
    app: web.Application,
    reward_engine: Any,
    base_path: str = '/rewards/api/v1'
) -> FeedbackManager:
    """
    Convenience function to setup the complete Feedback System.
    
    Args:
        app: aiohttp Application
        reward_engine: RewardsEngine instance
        base_path: Base URL path for API endpoints
        
    Returns:
        Configured FeedbackManager instance
    """
    manager = FeedbackManager(app, reward_engine, base_path)
    manager.setup()
    return manager


# Integration code for RewardsEngine
REWARDS_ENGINE_INTEGRATION = """
# Add to rewards/engine/engine.py

# Import feedback handlers
from ..feedback.handlers import (
    FeedbackTypeHandler,
    UserFeedbackHandler,
    FeedbackStatsHandler
)
from ..feedback.manager import FeedbackManager

# In RewardsEngine.__init__:
self.feedback_manager = None

# In RewardsEngine.setup():
# ... existing handler registrations ...

# Feedback System handlers
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

# In RewardsEngine.reward_startup():
# Initialize feedback types
async with await self.connection.acquire() as conn:
    await self.feedback_manager.initialize_database(conn)
"""


# Export all components
__all__ = [
    'FeedbackManager',
    'FeedbackEventHandler',
    'setup_feedback_system',
    'REWARDS_ENGINE_INTEGRATION'
]
