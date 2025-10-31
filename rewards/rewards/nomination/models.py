from typing import Optional, List
from enum import Enum
from datetime import datetime
from datamodel import BaseModel, Field
from asyncdb.models import Model
from ...models import Reward


class CampaignStatus(Enum):
    DRAFT = "draft"
    NOMINATION_PHASE = "nomination"
    VOTING_PHASE = "voting"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class NominationCampaign(Model):
    """Campaign for nomination-based awards"""
    campaign_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )
    campaign_name: str = Field(required=True)
    description: str = Field(required=False)
    reward_id: Reward = Field(
        required=True,
        fk='reward_id|reward',
        api='rewards',
        label="Award"
    )

    # Phase management
    nomination_start: datetime = Field(required=True)
    nomination_end: datetime = Field(required=True)
    voting_start: datetime = Field(required=True)
    voting_end: datetime = Field(required=True)

    # Configuration
    allow_self_nomination: bool = Field(default=False)
    max_nominations_per_user: int = Field(default=1)
    max_votes_per_user: int = Field(default=1)
    min_nominations_to_proceed: int = Field(default=1)

    # Eligibility criteria (stored as JSON)
    eligible_nominators: Optional[dict] = Field(
        default_factory=dict,
        db_type="jsonb",
        comment="Criteria for who can nominate (job_codes, groups, etc.)"
    )
    eligible_nominees: Optional[dict] = Field(
        default_factory=dict,
        db_type="jsonb",
        comment="Criteria for who can be nominated"
    )
    eligible_voters: Optional[dict] = Field(
        default_factory=dict,
        db_type="jsonb",
        comment="Criteria for who can vote"
    )

    # Status and results
    status: CampaignStatus = Field(default=CampaignStatus.DRAFT)
    winner_user_id: int = Field(required=False)
    winner_email: str = Field(required=False)
    total_nominations: int = Field(default=0)
    total_votes: int = Field(default=0)

    # Audit fields
    created_by: int = Field(required=True)
    created_at: datetime = Field(default=datetime.now, readonly=True)
    updated_at: datetime = Field(required=False)

    class Meta:
        driver = "pg"
        name = "nomination_campaigns"
        schema = "rewards"
        endpoint = 'rewards/api/v1/nomination_campaigns'

class Nomination(Model):
    """Individual nominations within a campaign"""
    nomination_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    campaign_id: NominationCampaign = Field(
        required=True,
        fk='campaign_id|campaign_name',
        api='nomination_campaigns',
        label="Campaign"
    )

    # Nominee information
    nominee_user_id: int = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_users',
        label="Nominee"
    )
    nominee_email: str = Field(required=True)
    nominee_name: str = Field(required=False)

    # Nominator information
    nominator_user_id: int = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_users',
        label="Nominator"
    )
    nominator_email: str = Field(required=True)
    nominator_name: str = Field(required=False)

    # Nomination details
    reason: str = Field(
        required=True,
        ui_widget='textarea',
        label="Why does this person deserve this award?"
    )
    supporting_evidence: str = Field(
        required=False,
        ui_widget='textarea',
        label="Additional supporting information (optional)"
    )

    # Vote tracking
    vote_count: int = Field(default=0, readonly=True)

    # Status
    is_active: bool = Field(default=True)
    is_winner: bool = Field(default=False)
    nominated_at: datetime = Field(default=datetime.now, readonly=True)

    class Meta:
        driver = "pg"
        name = "nominations"
        schema = "rewards"
        endpoint = 'rewards/api/v1/nominations'

class NominationVote(Model):
    """Votes on nominations"""
    vote_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    nomination_id: Nomination = Field(
        required=True,
        fk='nomination_id|nomination_id',
        api='nominations',
        label="Nomination"
    )
    campaign_id: NominationCampaign = Field(
        required=True,
        fk='campaign_id|campaign_name',
        api='nomination_campaigns',
        label="Campaign"
    )

    # Voter information
    voter_user_id: int = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_users',
        label="Voter"
    )
    voter_email: str = Field(required=True)
    voter_name: str = Field(required=False)

    # Vote details
    voted_at: datetime = Field(default=datetime.now, readonly=True)
    vote_comment: str = Field(
        required=False,
        ui_widget='textarea',
        label="Comment (optional)"
    )

    class Meta:
        driver = "pg"
        name = "nomination_votes"
        schema = "rewards"
        endpoint = 'rewards/api/v1/nomination_votes'

class NominationComment(Model):
    """Comments on nominations (for public discussion)"""
    comment_id: int = Field(
        primary_key=True, required=False, db_default="auto", repr=False
    )
    nomination_id: Nomination = Field(
        required=True,
        fk='nomination_id|nomination_id',
        api='nominations',
        label="Nomination"
    )

    user_id: int = Field(
        required=True,
        fk='user_id|display_name',
        api='ad_users',
        label="User"
    )
    user_email: str = Field(required=True)

    comment: str = Field(required=True)
    commented_at: datetime = Field(default=datetime.now, readonly=True)
    is_enabled: bool = Field(default=True)

    class Meta:
        driver = "pg"
        name = "nomination_comments"
        schema = "rewards"
        endpoint = 'rewards/api/v1/nomination_comments'
