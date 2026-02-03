"""
Feedback System Models for NAV-Rewards.

This module provides models for the Feedback System, allowing users to provide
structured feedback on badges, kudos, and nominations with point incentives.

Points Distribution:
    - Giver: 5 points (encourages engagement)
    - Receiver: 10 points (rewards quality recognition)

Target Types:
    - badge: Feedback on UserReward (users_rewards)
    - kudos: Feedback on UserKudos (users_kudos)
    - nomination: Feedback on Nomination awards
"""
from typing import Optional, List
from enum import Enum
from datetime import datetime
from datamodel import Field
from asyncdb.models import Model


# Configuration - can be overridden via environment
FEEDBACK_SCHEMA = "rewards"
POINTS_FOR_GIVER = 5
POINTS_FOR_RECEIVER = 10
MAX_FEEDBACK_PER_DAY = 20  # Anti-spam limit
COOLDOWN_MINUTES = 1  # Minimum time between feedback submissions


class TargetType(str, Enum):
    """Valid target types for feedback."""
    BADGE = "badge"
    KUDOS = "kudos"
    NOMINATION = "nomination"


class FeedbackCategory(str, Enum):
    """Categories for feedback types."""
    GRATITUDE = "gratitude"
    PERFORMANCE = "performance"
    MOTIVATION = "motivation"
    VALIDATION = "validation"
    COLLABORATION = "collaboration"
    DEVELOPMENT = "development"
    LEADERSHIP = "leadership"
    INNOVATION = "innovation"
    COMMITMENT = "commitment"
    QUALITY = "quality"


class FeedbackType(Model):
    """
    Predefined feedback categories.
    
    Similar to KudosTag, provides structured options for feedback
    with usage tracking for analytics and trending features.
    
    Attributes:
        feedback_type_id: Primary key
        type_name: Unique identifier (e.g., 'appreciation')
        display_name: Human-readable name (e.g., 'Appreciation')
        description: Detailed description of the feedback type
        emoji: Visual representation
        category: Grouping category
        usage_count: How many times this type has been used
        is_active: Whether this type is available for selection
    """
    feedback_type_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )
    type_name: str = Field(
        required=True,
        unique=True,
        label="Type Name",
        ui_help="Unique identifier for this feedback type"
    )
    display_name: str = Field(
        required=True,
        label="Display Name",
        ui_help="Human-readable name shown to users"
    )
    description: str = Field(
        required=False,
        label="Description",
        ui_help="Detailed description of this feedback type"
    )
    emoji: str = Field(
        required=False,
        ui_widget="EmojiPicker",
        label="Emoji",
        ui_help="Visual representation of this feedback type"
    )
    category: str = Field(
        required=False,
        label="Category",
        ui_help="Group similar feedback types together"
    )
    usage_count: int = Field(
        required=False,
        default=0,
        readonly=True,
        label="Usage Count",
        ui_help="Number of times this type has been used"
    )
    is_active: bool = Field(
        required=False,
        default=True,
        label="Active",
        ui_help="Whether this feedback type is available"
    )
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )

    class Meta:
        driver = "pg"
        name = "feedback_types"
        schema = FEEDBACK_SCHEMA
        endpoint: str = 'rewards/api/v1/feedback_types'
        strict = True

    def __str__(self) -> str:
        return f"{self.emoji} {self.display_name}" if self.emoji else self.display_name


class UserFeedback(Model):
    """
    User feedback on badges, kudos, or nominations.
    
    Polymorphic design allows feedback on multiple target types while
    maintaining referential integrity and enabling comprehensive analytics.
    
    Points System:
        - Giver receives points_given (default: 5) for providing feedback
        - Receiver receives points_received (default: 10) for quality recognition
    
    Attributes:
        feedback_id: Primary key
        target_type: Type of target ('badge', 'kudos', 'nomination')
        target_id: ID of the target record
        giver_user_id: User providing feedback
        receiver_user_id: User who received the original recognition
        feedback_type_id: Type of feedback (optional)
        rating: Optional 1-5 star rating
        message: Optional text message
        points_given: Points awarded to giver
        points_received: Points awarded to receiver
    """
    feedback_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )
    
    # Polymorphic target
    target_type: str = Field(
        required=True,
        label="Target Type",
        ui_help="Type of item being given feedback (badge, kudos, nomination)"
    )
    target_id: int = Field(
        required=True,
        label="Target ID",
        ui_help="ID of the badge, kudos, or nomination"
    )
    
    # Giver information
    giver_user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="Feedback Giver"
    )
    giver_email: str = Field(
        required=False,
        label="Giver Email"
    )
    giver_name: str = Field(
        required=False,
        label="Giver Name"
    )
    
    # Receiver information (person who received the original recognition)
    receiver_user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="Recognition Receiver"
    )
    receiver_email: str = Field(
        required=False,
        label="Receiver Email"
    )
    receiver_name: str = Field(
        required=False,
        label="Receiver Name"
    )
    
    # Feedback content
    feedback_type_id: Optional[int] = Field(
        required=False,
        fk='feedback_type_id|display_name',
        endpoint='rewards/api/v1/feedback_types',
        label="Feedback Type"
    )
    rating: Optional[int] = Field(
        required=False,
        label="Rating",
        ui_widget="StarRating",
        ui_help="Optional rating from 1 to 5 stars"
    )
    message: Optional[str] = Field(
        required=False,
        max_length=500,
        ui_widget='textarea',
        label="Message",
        ui_help="Optional message (max 500 characters)"
    )
    
    # Points (denormalized for performance and audit trail)
    points_given: int = Field(
        required=False,
        default=POINTS_FOR_GIVER,
        label="Points Given",
        ui_help="Points awarded to feedback giver"
    )
    points_received: int = Field(
        required=False,
        default=POINTS_FOR_RECEIVER,
        label="Points Received",
        ui_help="Points awarded to recognition receiver"
    )
    
    # Timestamps
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True,
        label="Created At"
    )
    updated_at: datetime = Field(
        required=False,
        readonly=True,
        label="Updated At"
    )
    is_active: bool = Field(
        required=False,
        default=True,
        label="Active"
    )

    class Meta:
        driver = "pg"
        name = "user_feedback"
        schema = FEEDBACK_SCHEMA
        endpoint: str = 'rewards/api/v1/user_feedback'
        strict = True

    def __post_init__(self):
        """Validate feedback data after initialization."""
        # Validate target type
        valid_types = [t.value for t in TargetType]
        if self.target_type and self.target_type not in valid_types:
            raise ValueError(
                f"Invalid target_type: {self.target_type}. "
                f"Must be one of: {valid_types}"
            )
        
        # Validate rating range
        if self.rating is not None and not (1 <= self.rating <= 5):
            raise ValueError("Rating must be between 1 and 5")
        
        # Ensure no self-feedback
        if self.giver_user_id and self.receiver_user_id:
            if self.giver_user_id == self.receiver_user_id:
                raise ValueError("Cannot give feedback to yourself")
        
        return super().__post_init__()

    def __str__(self) -> str:
        return f"Feedback #{self.feedback_id}: {self.target_type}/{self.target_id}"


class FeedbackCooldown(Model):
    """
    Track feedback cooldowns to prevent spam.
    
    Tracks the last feedback submission time and daily count
    per user per target type to enforce rate limits.
    """
    cooldown_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )
    user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="User"
    )
    target_type: str = Field(
        required=True,
        label="Target Type"
    )
    last_feedback_at: datetime = Field(
        required=False,
        default=datetime.now,
        label="Last Feedback At"
    )
    feedback_count_today: int = Field(
        required=False,
        default=1,
        label="Feedback Count Today"
    )

    class Meta:
        driver = "pg"
        name = "feedback_cooldowns"
        schema = FEEDBACK_SCHEMA
        endpoint: str = 'rewards/api/v1/feedback_cooldowns'
        strict = True


class FeedbackStats(Model):
    """
    User feedback statistics (read-only view model).
    
    Aggregated statistics for user feedback activity,
    mapped to the vw_user_feedback_stats view.
    """
    user_id: int = Field(primary_key=True)
    email: str = Field(required=False)
    display_name: str = Field(required=False)
    feedback_given: int = Field(default=0)
    points_earned_giving: int = Field(default=0)
    feedback_received: int = Field(default=0)
    points_earned_receiving: int = Field(default=0)
    avg_rating_received: float = Field(default=0.0)

    class Meta:
        driver = "pg"
        name = "vw_user_feedback_stats"
        schema = FEEDBACK_SCHEMA
        endpoint: str = 'rewards/api/v1/feedback_stats'
        strict = True
        readonly = True


class FeedbackByTarget(Model):
    """
    Feedback summary by target (read-only view model).
    
    Aggregated feedback data per target item,
    mapped to the vw_feedback_by_target view.
    """
    target_type: str = Field(primary_key=True)
    target_id: int = Field(primary_key=True)
    feedback_count: int = Field(default=0)
    avg_rating: float = Field(required=False)
    feedback_types: List[str] = Field(default_factory=list)
    first_feedback: datetime = Field(required=False)
    last_feedback: datetime = Field(required=False)

    class Meta:
        driver = "pg"
        name = "vw_feedback_by_target"
        schema = FEEDBACK_SCHEMA
        endpoint: str = 'rewards/api/v1/feedback_by_target'
        strict = True
        readonly = True


# Initial feedback types for database seeding
INITIAL_FEEDBACK_TYPES = [
    {
        "type_name": "appreciation",
        "display_name": "Appreciation",
        "description": "Grateful for this recognition",
        "emoji": "🙏",
        "category": "gratitude"
    },
    {
        "type_name": "impact",
        "display_name": "Great Impact",
        "description": "This had significant positive impact",
        "emoji": "💥",
        "category": "performance"
    },
    {
        "type_name": "inspiring",
        "display_name": "Inspiring",
        "description": "This inspired me or others",
        "emoji": "✨",
        "category": "motivation"
    },
    {
        "type_name": "well_deserved",
        "display_name": "Well Deserved",
        "description": "Completely earned this recognition",
        "emoji": "🏆",
        "category": "validation"
    },
    {
        "type_name": "teamwork",
        "display_name": "Team Player",
        "description": "Exemplifies great teamwork",
        "emoji": "🤝",
        "category": "collaboration"
    },
    {
        "type_name": "growth",
        "display_name": "Shows Growth",
        "description": "Demonstrates personal/professional growth",
        "emoji": "📈",
        "category": "development"
    },
    {
        "type_name": "leadership",
        "display_name": "Leadership",
        "description": "Shows excellent leadership qualities",
        "emoji": "👑",
        "category": "leadership"
    },
    {
        "type_name": "innovation",
        "display_name": "Innovative",
        "description": "Creative and innovative approach",
        "emoji": "💡",
        "category": "innovation"
    },
    {
        "type_name": "dedication",
        "display_name": "Dedication",
        "description": "Shows remarkable dedication",
        "emoji": "💪",
        "category": "commitment"
    },
    {
        "type_name": "excellence",
        "display_name": "Excellence",
        "description": "Exemplifies excellence in work",
        "emoji": "⭐",
        "category": "quality"
    }
]


# Export all models and constants
__all__ = [
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
]
