from datetime import datetime
from typing import List
from datamodel import BaseModel, Field
from asyncdb.models import Model


class UserKudos(Model):
    """
    User Kudos Recognition System.

    Stores recognition messages between users with tags/qualities.
    """
    kudos_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )
    receiver_user_id: int = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_users',
        label="Receiver"
    )
    receiver_email: str = Field(required=True)
    receiver_name: str = Field(required=True)

    giver_user_id: int = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_users',
        label="Giver"
    )
    giver_email: str = Field(required=True)
    giver_name: str = Field(required=True)

    message: str = Field(
        required=True,
        ui_widget='textarea',
        ui_help='Recognition message',
        label="Recognition Message"
    )

    tags: List[str] = Field(
        required=False,
        default_factory=list,
        multiple=True,
        label="Recognition Tags",
        ui_help="Tags like #Helpful, #Inspirational, etc.",
        db_type="text[]"  # Explicitly specify PostgreSQL array type
    )

    sent_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )

    # Optional: Add visibility/privacy controls
    is_public: bool = Field(
        required=False,
        default=True,
        label="Public Recognition",
        ui_help="Make this recognition visible to others"
    )

    class Meta:
        driver = "pg"
        name = "users_kudos"
        schema = "rewards"
        endpoint: str = 'rewards/api/v1/users_kudos'
        strict = True


class KudosTag(Model):
    """
    Predefined tags for kudos system.

    Helps maintain consistency and enables trending analysis.
    """
    tag_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )
    tag_name: str = Field(
        required=True,
        unique=True,
        label="Tag Name",
        ui_help="Tag name without # symbol"
    )
    display_name: str = Field(
        required=True,
        label="Display Name",
        ui_help="How the tag appears to users"
    )
    description: str = Field(
        required=False,
        label="Description",
        ui_help="What this tag represents"
    )
    emoji: str = Field(
        required=False,
        ui_widget="EmojiPicker",
        label="Emoji"
    )
    category: str = Field(
        required=False,
        label="Category",
        ui_help="Group similar tags together"
    )
    usage_count: int = Field(
        required=False,
        default=0,
        readonly=True,
        label="Usage Count"
    )
    is_active: bool = Field(
        required=False,
        default=True,
        label="Active"
    )
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )

    class Meta:
        driver = "pg"
        name = "kudos_tags"
        schema = "rewards"
        endpoint: str = 'rewards/api/v1/kudos_tags'
        strict = True


# Sample data for initial tags
INITIAL_KUDOS_TAGS = [
    {
        "tag_name": "helpful",
        "display_name": "Helpful",
        "description": "Goes above and beyond to help others",
        "emoji": "🤝",
        "category": "support"
    },
    {
        "tag_name": "inspirational",
        "display_name": "Inspirational",
        "description": "Motivates and inspires others",
        "emoji": "✨",
        "category": "leadership"
    },
    {
        "tag_name": "fair",
        "display_name": "Fair",
        "description": "Always treats everyone fairly",
        "emoji": "⚖️",
        "category": "values"
    },
    {
        "tag_name": "creative",
        "display_name": "Creative",
        "description": "Brings innovative ideas and solutions",
        "emoji": "💡",
        "category": "innovation"
    },
    {
        "tag_name": "reliable",
        "display_name": "Reliable",
        "description": "Always delivers on commitments",
        "emoji": "🎯",
        "category": "performance"
    },
    {
        "tag_name": "collaborative",
        "display_name": "Collaborative",
        "description": "Excellent team player",
        "emoji": "👥",
        "category": "teamwork"
    },
    {
        "tag_name": "positive",
        "display_name": "Positive",
        "description": "Brings positive energy to the team",
        "emoji": "😊",
        "category": "attitude"
    },
    {
        "tag_name": "mentor",
        "display_name": "Great Mentor",
        "description": "Helps others learn and grow",
        "emoji": "🎓",
        "category": "leadership"
    },
    {
        "tag_name": "dedicated",
        "display_name": "Dedicated",
        "description": "Shows exceptional dedication to work",
        "emoji": "💪",
        "category": "performance"
    },
    {
        "tag_name": "innovative",
        "display_name": "Innovative",
        "description": "Consistently brings new ideas",
        "emoji": "🚀",
        "category": "innovation"
    },
    {
        "tag_name": "team_player",
        "display_name": "Team Player",
        "description": "Always supports team goals",
        "emoji": "👥",
        "category": "teamwork"
    },
    {
        "tag_name": "patient",
        "display_name": "Patient",
        "description": "Shows patience in challenging situations",
        "emoji": "🧘",
        "category": "values"
    },
    {
        "tag_name": "organized",
        "display_name": "Organized",
        "description": "Keeps things well organized",
        "emoji": "📅",
        "category": "performance"
    },
    {
        "tag_name": "supportive",
        "display_name": "Supportive",
        "description": "Always supports colleagues",
        "emoji": "🤗",
        "category": "teamwork"
    },
    {
        "tag_name": "respectful",
        "display_name": "Respectful",
        "description": "Treats everyone with respect",
        "emoji": "🙏",
        "category": "values"
    }
]
