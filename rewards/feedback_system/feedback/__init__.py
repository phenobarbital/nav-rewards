"""
NAV-Rewards Feedback System.

A comprehensive feedback module for the NAV-Rewards recognition system,
allowing users to provide structured feedback on badges, kudos, and nominations
with point incentives.

Features:
    - Polymorphic feedback targets (badges, kudos, nominations)
    - Predefined feedback types with usage tracking
    - Optional star ratings (1-5)
    - Point system: 5 pts to giver, 10 pts to receiver
    - Anti-spam cooldowns and daily limits
    - MS Teams bot integration
    - Comprehensive statistics and analytics

Usage:
    from rewards.feedback import (
        FeedbackManager,
        setup_feedback_system,
        UserFeedback,
        FeedbackType
    )
    
    # Setup in your application
    feedback_manager = setup_feedback_system(app, reward_engine)

Points Distribution:
    - Feedback Giver: 5 points (encourages engagement)
    - Recognition Receiver: 10 points (rewards quality work)

API Endpoints:
    GET  /api/v1/feedback_types          - List feedback types
    GET  /api/v1/feedback_types/trending - Trending feedback types
    POST /api/v1/feedback_types          - Create feedback type (admin)
    
    GET  /api/v1/user_feedback           - List all feedback
    POST /api/v1/user_feedback           - Submit feedback
    GET  /api/v1/user_feedback/{id}      - Get specific feedback
    DELETE /api/v1/user_feedback/{id}    - Delete feedback
    
    GET  /api/v1/user_feedback/target/{type}/{id}  - Feedback for target
    GET  /api/v1/user_feedback/user/{id}/given     - User's given feedback
    GET  /api/v1/user_feedback/user/{id}/received  - User's received feedback
    
    GET  /api/v1/feedback_stats                    - Global statistics
    GET  /api/v1/feedback_stats/user/{id}          - User statistics
    GET  /api/v1/feedback_stats/leaderboard        - Feedback leaderboard
"""

# Version
__version__ = '1.0.0'

# Models
from .models import (
    FeedbackType,
    UserFeedback,
    FeedbackCooldown,
    FeedbackStats,
    FeedbackByTarget,
    TargetType,
    FeedbackCategory,
    INITIAL_FEEDBACK_TYPES,
    POINTS_FOR_GIVER,
    POINTS_FOR_RECEIVER,
    MAX_FEEDBACK_PER_DAY,
    COOLDOWN_MINUTES
)

# Handlers
from .handlers import (
    FeedbackTypeHandler,
    UserFeedbackHandler,
    FeedbackStatsHandler,
    update_feedback_type_usage,
    get_feedback_count_for_target,
    seed_feedback_types
)

# Manager
from .manager import (
    FeedbackManager,
    FeedbackEventHandler,
    setup_feedback_system
)

# Bot Dialog
from .dialogs.feedback import (
    FeedbackDialog,
    FeedbackBotMixin
)


__all__ = [
    # Version
    '__version__',
    
    # Models
    'FeedbackType',
    'UserFeedback',
    'FeedbackCooldown',
    'FeedbackStats',
    'FeedbackByTarget',
    'TargetType',
    'FeedbackCategory',
    'INITIAL_FEEDBACK_TYPES',
    'POINTS_FOR_GIVER',
    'POINTS_FOR_RECEIVER',
    'MAX_FEEDBACK_PER_DAY',
    'COOLDOWN_MINUTES',
    
    # Handlers
    'FeedbackTypeHandler',
    'UserFeedbackHandler',
    'FeedbackStatsHandler',
    'update_feedback_type_usage',
    'get_feedback_count_for_target',
    'seed_feedback_types',
    
    # Manager
    'FeedbackManager',
    'FeedbackEventHandler',
    'setup_feedback_system',
    
    # Bot
    'FeedbackDialog',
    'FeedbackBotMixin'
]
