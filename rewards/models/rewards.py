from typing import Optional, List
from enum import Enum
from uuid import UUID, uuid4
from datetime import datetime
from datamodel import BaseModel, Field
from asyncdb.models import Model
from navigator_auth.models import Group
from ..conf import (
    REWARDS_SCHEMA,
    REWARDS_VIEW,
    USER_REWARDS,
)
from .user import User


class RewardType(Model):
    """Type of Rewards/Badges
    """
    reward_type: str = Field(primary_key=True, required=True)
    description: str = Field(required=False)

    class Meta:
        name = "reward_types"
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/reward_types'
        strict = True

class RewardCategory(Model):
    """Reward Categories."""
    reward_category: str = Field(primary_key=True, required=True)

    class Meta:
        name = "reward_categories"
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/reward_categories'
        strict = True


class RewardGroup(Model):
    """Groups of Rewards.
    """
    reward_group: str = Field(primary_key=True, required=True)

    class Meta:
        name = "reward_groups"
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/reward_groups'
        strict = True

class Reward(Model):
    """
    Rewards and Badges Management.
    """
    reward_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    reward: str = Field(required=True, nullable=False)
    description: str = Field(required=False)
    message: str = Field(
        required=False,
        default='Congratulations! \
            You have earned a badge sent by {{session.display_name}}.'
    )
    points: int = Field(required=False, default=10)
    multiple: bool = Field(
        required=False,
        default=False,
        label="If True, This Reward can be applied multiple times"
    )
    reward_type: RewardType = Field(
        required=False,
        fk="reward_type|reward_type",
        api="reward_types",
        label="Badge Type"
    )
    reward_group: RewardGroup = Field(
        required=False,
        fk="reward_group|reward_group",
        api="reward_groups",
        label="Reward Group"
    )
    reward_category: RewardCategory = Field(
        required=True,
        fk="reward_category|reward_category",
        api="reward_categories",
        label="Badge Category"
    )
    programs: Optional[list] = Field(
        required=False,
        fk="program_slug|program_name",
        api="programs",
        label="Programs",
        nullable=True,
        multiple=True,
        default_factory=list
    )
    icon: str = Field(
        required=False,
        default="",
        ui_widget="ImageUploader",
        ui_help="Badge Icon, Hint: please use a transparent PNG."
    )
    emoji: str = Field(
        required=False,
        ui_widget="EmojiPicker",
        ui_help="Emoji to represent the badge",
        label="Emoji"
    )
    attributes: Optional[dict] = Field(
        required=False, default_factory=dict, db_type="jsonb", repr=False
    )
    availability_rule: dict = Field(
        required=False, default_factory=dict, db_type="jsonb"
    )
    rules: dict = Field(
        required=False, default_factory=dict, db_type="jsonb"
    )
    conditions: dict = Field(
        required=False, default_factory=dict, db_type="jsonb"
    )
    events: List[str] = Field(
        required=False, default_factory=list, multiple=True
    )
    effective_date: datetime = Field(required=False, default=datetime.now)
    timeframe: str = Field(required=False)
    cooldown_minutes: Optional[int] = Field(default=1)
    is_enabled: bool = Field(required=False, default=True)
    inserted_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )
    inserted_by: int = Field(
        required=False,
        label="Inserted By",
        readonly=True
    )
    updated_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )
    updated_by: int = Field(
        required=False,
        label="Updated By",
        readonly=True
    )
    deleted_at: datetime = Field(
        required=False,
        readonly=True
    )
    deleted_by: int = Field(
        required=False,
        label="Deleted By",
        readonly=True
    )
    completion_callbacks: List[str] = Field(
        required=False,
        default_factory=list,
    )
    step_callbacks: List[str] = Field(
        required=False,
        default_factory=list,
    )
    awarded_callbacks: List[str] = Field(
        required=False,
        default_factory=list,
    )

    class Meta:
        name = "rewards"
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/rewards'
        strict = True

class RewardRule(Model):
    """Rules that can be used to assign a reward to an employee."""
    rule_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    reward_id: Reward = Field(
        required=True, fk='reward_id|reward', api='rewards', label="Badge"
    )
    description: str = Field(required=False)
    rule_name: str = Field(required=True)
    rule_type: str = Field(required=True)
    conditions: Optional[dict] = Field(
        required=False,
        db_type="jsonb",
        comment="Stores the conditions for the rule in a structured format"
    )
    active: bool = Field(required=False, default=True)
    inserted_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        name = "reward_rules"
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/reward_rules'
        strict = True


class PermissionType(Enum):
    """Types of Permissions for Rewards."""
    ASSIGNER = (0, "Assigner")
    AWARDEE = (1, "Awardee")
    OBSERVER = (3, "Observer")

    def __init__(self, value, label):
        self._value_ = value
        self._label = label

    @property
    def label(self):
        return self._label

    def __int__(self):
        return self._value_

class RewardPermission(Model):
    """Permissions for Rewards."""
    permission_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    group_id: Group = Field(
        required=True, fk='group_id|group_name', api='groups', label="Group"
    )
    reward_id: Reward = Field(
        required=True, fk='reward_id|reward', api='rewards', label="Badge"
    )
    permission_type: PermissionType = Field(
        required=True, default=PermissionType.ASSIGNER
    )

    class Meta:
        name = "reward_permissions"
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/reward_permissions'
        strict = True


class UserReward(Model):
    """
    Assign a Badge to an Employee.
    """
    award_id: int = Field(primary_key=True, required=False, db_default="auto")
    reward_id: Reward = Field(
        required=True, fk='reward_id|reward', api='rewards', label="Badge"
    )
    reward: str = Field(repr=False)
    reward_type: str = Field(
        required=False,
        fk='reward_type|reward_type',
        api='reward_types',
        label="Badge Type"
    )
    receiver_email: str = Field(
        required=True,
        fk='email|display_name',
        api='ad_users',
        label="Receiver Email"
    )
    user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="Receiver User"
    )
    display_name: str
    receiver_user: int = Field(required=True)
    receiver_employee: str = Field(required=False)
    receiver_id: str = Field(required=False)
    receiver_name: str
    giver_user: int = Field(required=False)
    giver_name: str
    giver_email: str = Field(required=False)
    giver_employee: str = Field(required=False)
    original_email: str = Field(required=False)
    points: int = Field(required=False, default=1)
    message: str = Field(
        required=False,
        ui_widget='textarea',
        ui_help='Message to the receiver',
        label="Your Message"
    )
    awarded_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )
    revoked: bool = Field(required=False, default=False)
    revoked_at: datetime = Field(
        required=False, readonly=True
    )
    revoked_by: int = Field(required=False)
    deleted_at: datetime = Field(
        required=False
    )

    class Meta:
        name = 'users_rewards'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/users_rewards'
        strict = True

    def __post_init__(self):
        if self.receiver_user and not self.user_id:
            self.user_id = self.receiver_user
        self.receiver_id = self.receiver_user or self.user_id
        return super().__post_init__()


class RewardLike(Model):
    like_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    award_id: UserReward = Field(
        required=True,
        fk='award_id|award_id',
        endpoint='rewards/api/v1/users_rewards',
        label="Award"
    )
    user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="User"
    )
    username: str = Field(required=False)
    liked_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )

    class Meta:
        name = 'rewards_likes'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/rewards_likes'
        strict = True


class RewardComment(Model):
    """Comments on Rewards."""
    comment_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    award_id: UserReward = Field(
        required=True,
        fk='award_id|award_id',
        endpoint='rewards/api/v1/users_rewards',
        label="Award"
    )
    user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="User"
    )
    username: str = Field(required=False)
    comment: str = Field(required=True)
    commented_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )
    enabled: bool = Field(required=False, default=True)

    class Meta:
        name = 'rewards_comments'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/rewards_comments'
        strict = True

class RewardCommentReport(Model):
    """Reports on Reward Comments."""
    comment_id: RewardComment = Field(
        required=True,
        fk='comment_id|comment_id',
        endpoint='rewards/api/v1/rewards_comments',
        label="Comment"
    )
    reported_by: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="User"
    )
    comment: str = Field(required=False)
    username: str = Field(required=False)
    reported_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )

    class Meta:
        name = 'rewards_comments_reports'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/rewards_comments_reports'
        strict = True

class RewardPoint(Model):
    """User Reward Points."""
    point_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="User"
    )
    points: int = Field(required=True)
    karma: int = Field(required=False, default=0)
    previous_karma: int = Field(required=False, default=0)
    awarded_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )

    class Meta:
        name = 'rewards_points'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/rewards_points'
        strict = True


class Collective(Model):
    """Collectives of Rewards."""
    collective_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    collective_name: str = Field(required=True)
    description: str = Field(required=False)
    points: int = Field(required=True, default=50)
    icon: str = Field(required=False, default="")
    attributes: Optional[dict] = Field(required=False, default_factory=dict)
    created_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )

    class Meta:
        name = 'collectives'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/collectives'
        strict = True

class CollectiveReward(Model):
    """Collective Rewards."""
    collective_id: Collective = Field(
        required=True,
        fk='collective_id|collective_name',
        endpoint='rewards/api/v1/collectives',
        label="Collective"
    )
    reward_id: Reward = Field(
        required=True,
        fk='reward_id|reward',
        endpoint='rewards/api/v1/rewards',
        label="Badge"
    )
    created_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )

    class Meta:
        name = 'collectives_rewards'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/collectives_rewards'
        strict = True

class CollectiveUnlocked(Model):
    """Collective Unlocked by User."""
    collective_id: Collective = Field(
        required=True,
        fk='collective_id|collective_name',
        endpoint='rewards/api/v1/collectives',
        label="Collective"
    )
    user_id: int = Field(
        required=True,
        fk='user_id|email',
        endpoint='ad_users',
        label="User"
    )
    unlocked_at: datetime = Field(
        required=False, default=datetime.now, readonly=True
    )

    class Meta:
        name = 'collectives_unlocked'
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/collectives_unlocked'
        strict = True


class RewardView(Model):
    """
    Rewards Management.
    """
    reward_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    reward: str = Field(required=True, nullable=False)
    description: str = Field(required=False)
    auto_enroll: bool = Field(
        required=False,
        default=False,
        label="Auto Enroll",
        ui_help="If True, users will be automatically enrolled in this reward."
    )
    message: str = Field(
        required=False,
        default='Congratulations! You have earned a badge.'
    )
    points: int = Field(required=False, default=10)
    multiple: bool = Field(
        required=False,
        default=False,
        label="If True, This Reward can be applied multiple times"
    )
    reward_type: RewardType = Field(
        required=False,
        fk="reward_type|reward_type",
        api="reward_types",
        label="Badge Type"
    )
    reward_group: RewardGroup = Field(
        required=False,
        fk="reward_group|reward_group",
        api="reward_groups",
        label="Reward Group"
    )
    reward_category: RewardCategory = Field(
        required=True,
        fk="reward_category|reward_category",
        api="reward_categories",
        label="Badge Category"
    )
    programs: Optional[list] = Field(
        required=False,
        fk="program_slug|program_name",
        api="programs",
        label="Programs",
        nullable=True,
        multiple=True,
        default_factory=list
    )
    icon: str = Field(
        required=False,
        default="",
        ui_widget="ImageUploader",
        ui_help="Badge Icon, Hint: please use a transparent PNG."
    )
    emoji: str = Field(
        required=False,
        ui_widget="EmojiPicker",
        ui_help="Emoji to represent the badge",
        label="Emoji",
        default="🏆"
    )
    attributes: Optional[dict] = Field(
        required=False, default_factory=dict, db_type="jsonb", repr=False
    )
    availability_rule: dict = Field(
        required=False, default_factory=dict, db_type="jsonb", repr=False
    )
    rules: list = Field(
        required=False, default_factory=dict, db_type="jsonb"
    )
    conditions: dict = Field(
        required=False, default_factory=dict, db_type="jsonb"
    )
    assigner: List[str] = Field(
        required=False, default_factory=list, multiple=True
    )
    awardee: List[str] = Field(
        required=False, default_factory=list, multiple=True
    )
    events: list = Field(
        required=False, default_factory=list, multiple=True
    )
    timeframe: str = Field(required=False)
    cooldown_minutes: Optional[int] = Field(default=1)
    is_enabled: bool = Field(required=False, default=True)
    completion_callbacks: List[str] = Field(
        required=False,
        default_factory=list,
    )
    step_callbacks: List[str] = Field(
        required=False,
        default_factory=list,
    )
    awarded_callbacks: List[str] = Field(
        required=False,
        default_factory=list,
    )
    auto_evaluation: bool = Field(
        required=False,
        default=True,
        label="Auto Evaluation",
        ui_help="If True, reward will be automatically evaluated based on the defined rules."  # noqa: E501
    )
    effective_date: Optional[datetime] = Field(
        ui_help="When this Reward is effective."
    )

    class Meta:
        name = REWARDS_VIEW
        schema = REWARDS_SCHEMA
        endpoint: str = 'rewards/api/v1/rewards_views'
        strict = True

class BadgeAssign(BaseModel):
    """
    Assign a Badge to an Employee.
    """
    reward_id: RewardView = Field(
        required=True,
        fk='reward_id|reward',
        endpoint='rewards/api/v1/rewards_list',
        label="Badge"
    )
    reward: str
    reward_type: str = Field(
        required=False,
    )
    user_id: User = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_people',
        ui_widget='adv-search',
        label="Receiver Name",
        ui_widget_filterby=['email', 'display_name', 'given_name', 'last_name']
    )
    display_name: str
    receiver_user: int
    receiver_email: str = Field(
        required=False, repr=False
    )
    receiver_employee: str = Field(required=False)
    receiver_id: str = Field(required=False)
    giver_user: int = Field(required=False, repr=False)
    giver_email: str = Field(required=False, repr=False)
    giver_employee: str = Field(required=False, repr=False)
    giver_name: str = Field(
        required=False,
        repr=False,
        default="",
        label="Giver Name"
    )
    points: int = Field(default=0)
    message: str = Field(
        required=True,
        ui_widget='textarea',
        ui_help='Message to the receiver',
        label="Your Message",
        placeholder="Describe why you're giving this person a shoutout"
    )

    class Meta:
        name = USER_REWARDS
        schema = REWARDS_SCHEMA
        endpoint: str = 'api/v1/badge_assign'
        strict = True
        settings: dict = {
            "showSubmit": True,
            "SubmitLabel": "Assign Badge",
            "showCancel": True,
        }

    def __post_init__(self):
        if self.user_id and not self.receiver_user:
            self.receiver_user = self.user_id
        if self.receiver_user and not self.user_id:
            self.user_id = self.receiver_user
        return super().__post_init__()


class WorkflowState(BaseModel):
    """
    Reward Workflow States.
    """
    state_id: UUID = Field(
        required=False,
        primary_key=True,
        db_default="auto",
        default=uuid4(),
        repr=False
    )
    reward_id: int = Field(
        required=True
    )
