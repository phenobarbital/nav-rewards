"""
Prize Marketplace Models for NAV-Rewards.

This module defines the data models for:
- Prize Catalog (Marketplace)
- Prize Awards
- Prize Redemptions
- Mystery Box Events
"""
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
from datamodel import BaseModel, Field
from asyncdb.models import Model

# Schema configuration
REWARDS_SCHEMA = "rewards"


# ============================================================================
# ENUMS
# ============================================================================

class AwardStatus(str, Enum):
    """Status of a prize award."""
    PENDING = "pending"
    AVAILABLE = "available"
    RESERVED = "reserved"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AwardSource(str, Enum):
    """Source of how a prize was awarded."""
    BADGE = "badge"
    MYSTERY_BOX = "mystery_box"
    PURCHASE = "purchase"
    MANUAL = "manual"
    CAMPAIGN = "campaign"
    MILESTONE = "milestone"
    REFERRAL = "referral"
    LOTTERY = "lottery"


class RedemptionStatus(str, Enum):
    """Status of a prize redemption."""
    INITIATED = "initiated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FulfillmentType(str, Enum):
    """How a prize is fulfilled."""
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    EXTERNAL = "external"


class StockStatus(str, Enum):
    """Stock status for a prize."""
    UNLIMITED = "unlimited"
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


# ============================================================================
# PRIZE CATEGORY MODEL
# ============================================================================

class PrizeCategory(Model):
    """Prize category for organizing the marketplace."""

    category_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto"
    )
    category_name: str = Field(
        required=True,
        max_length=100,
        label="Category Name"
    )
    description: Optional[str] = Field(
        required=False,
        label="Description"
    )
    icon: Optional[str] = Field(
        required=False,
        max_length=500,
        label="Icon URL"
    )
    display_order: int = Field(
        required=False,
        default=0,
        label="Display Order"
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
    updated_at: datetime = Field(
        required=False,
        default=datetime.now
    )

    class Meta:
        driver = "pg"
        name = "prize_categories"
        schema = REWARDS_SCHEMA
        endpoint = "rewards/api/v1/prize_categories"
        strict = True


# ============================================================================
# PRIZE TIER MODEL
# ============================================================================

class PrizeTier(Model):
    """Prize tier/rarity level."""

    tier_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto"
    )
    tier_name: str = Field(
        required=True,
        max_length=50,
        label="Tier Name"
    )
    tier_level: int = Field(
        required=True,
        label="Tier Level",
        ui_help="1=Common, 5=Legendary"
    )
    description: Optional[str] = Field(
        required=False,
        label="Description"
    )
    color_code: Optional[str] = Field(
        required=False,
        max_length=7,
        label="Color Code",
        ui_help="Hex color for UI display"
    )
    drop_rate: Decimal = Field(
        required=False,
        default=Decimal("0.2000"),
        label="Drop Rate",
        ui_help="Probability for mystery boxes (0-1)"
    )
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )

    class Meta:
        driver = "pg"
        name = "prize_tiers"
        schema = REWARDS_SCHEMA
        endpoint = "rewards/api/v1/prize_tiers"
        strict = True


# ============================================================================
# PRIZE CATALOG MODEL
# ============================================================================

class PrizeCatalog(Model):
    """
    Main prize catalog model for the marketplace.

    Represents a prize that can be awarded to users and redeemed.
    """

    prize_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )

    # Basic Info
    prize_name: str = Field(
        required=True,
        max_length=255,
        label="Prize Name"
    )
    description: Optional[str] = Field(
        required=False,
        ui_widget="textarea",
        label="Full Description"
    )
    short_description: Optional[str] = Field(
        required=False,
        max_length=500,
        label="Short Description"
    )

    # Categorization
    category_id: Optional[int] = Field(
        required=False,
        fk="category_id|category_name",
        api="prize_categories",
        label="Category"
    )
    tier_id: Optional[int] = Field(
        required=False,
        fk="tier_id|tier_name",
        api="prize_tiers",
        label="Tier/Rarity"
    )

    # Value & Cost
    points_cost: int = Field(
        required=False,
        default=0,
        label="Points Cost",
        ui_help="Points required to purchase (0 = not purchasable)"
    )
    monetary_value: Optional[Decimal] = Field(
        required=False,
        label="Monetary Value",
        ui_help="Actual dollar value of the prize"
    )

    # Inventory
    total_quantity: Optional[int] = Field(
        required=False,
        label="Total Quantity",
        ui_help="Leave empty for unlimited"
    )
    available_quantity: Optional[int] = Field(
        required=False,
        label="Available Quantity"
    )
    reserved_quantity: int = Field(
        required=False,
        default=0,
        label="Reserved Quantity"
    )

    # Imagery
    image_url: Optional[str] = Field(
        required=False,
        max_length=500,
        ui_widget="ImageUploader",
        label="Main Image"
    )
    thumbnail_url: Optional[str] = Field(
        required=False,
        max_length=500,
        label="Thumbnail"
    )

    # Availability Rules
    availability_rule: Dict[str, Any] = Field(
        required=False,
        default_factory=dict,
        label="Availability Rules",
        ui_widget="JsonEditor"
    )

    # Eligibility Rules
    eligibility_rules: Dict[str, Any] = Field(
        required=False,
        default_factory=dict,
        label="Eligibility Rules",
        ui_widget="JsonEditor"
    )

    # Redemption Rules
    max_per_user: Optional[int] = Field(
        required=False,
        label="Max Per User",
        ui_help="Maximum times one user can receive this prize"
    )
    cooldown_days: int = Field(
        required=False,
        default=0,
        label="Cooldown Days"
    )
    requires_approval: bool = Field(
        required=False,
        default=False,
        label="Requires Approval"
    )

    # Mystery Box
    is_mystery_eligible: bool = Field(
        required=False,
        default=True,
        label="Mystery Box Eligible"
    )
    mystery_weight: int = Field(
        required=False,
        default=100,
        label="Mystery Weight",
        ui_help="Higher = more likely to drop within tier"
    )

    # Linked Badge
    linked_reward_id: Optional[int] = Field(
        required=False,
        fk="reward_id|reward",
        api="rewards",
        label="Linked Badge"
    )

    # Fulfillment
    fulfillment_type: str = Field(
        required=False,
        default="automatic",
        label="Fulfillment Type"
    )
    fulfillment_instructions: Optional[str] = Field(
        required=False,
        ui_widget="textarea",
        label="Fulfillment Instructions"
    )
    external_vendor: Optional[str] = Field(
        required=False,
        max_length=255,
        label="External Vendor"
    )
    vendor_sku: Optional[str] = Field(
        required=False,
        max_length=100,
        label="Vendor SKU"
    )

    # Metadata
    tags: Optional[List[str]] = Field(
        required=False,
        default_factory=list,
        label="Tags",
        db_type="text[]"
    )
    attributes: Dict[str, Any] = Field(
        required=False,
        default_factory=dict,
        label="Attributes",
        ui_widget="JsonEditor"
    )

    # Status
    is_active: bool = Field(
        required=False,
        default=True,
        label="Active"
    )
    is_featured: bool = Field(
        required=False,
        default=False,
        label="Featured"
    )

    # Audit
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )
    created_by: Optional[str] = Field(required=False, readonly=True)
    updated_at: datetime = Field(required=False, default=datetime.now)
    updated_by: Optional[str] = Field(required=False)
    deleted_at: Optional[datetime] = Field(required=False, readonly=True)
    deleted_by: Optional[str] = Field(required=False, readonly=True)

    class Meta:
        driver = "pg"
        name = "prize_catalog"
        schema = REWARDS_SCHEMA
        endpoint = "rewards/api/v1/prize_catalog"
        strict = True

    def is_available(self) -> bool:
        """Check if prize is available for awarding."""
        if not self.is_active:
            return False
        if self.total_quantity is not None:
            effective = (self.available_quantity or 0) - (self.reserved_quantity or 0)
            return effective > 0
        return True

    def get_effective_quantity(self) -> int:
        """Get the effective available quantity."""
        if self.total_quantity is None:
            return 999999  # Unlimited
        return (self.available_quantity or 0) - (self.reserved_quantity or 0)


# ============================================================================
# PRIZE AWARD MODEL
# ============================================================================

class PrizeAward(Model):
    """
    Prize award record - represents a prize given to a user.

    This tracks the full lifecycle from award to redemption.
    """

    award_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )

    # Prize Reference
    prize_id: int = Field(
        required=True,
        fk="prize_id|prize_name",
        api="prize_catalog",
        label="Prize"
    )

    # Recipient
    user_id: int = Field(
        required=True,
        fk="user_id|display_name",
        api="ad_users",
        label="Recipient"
    )
    user_email: str = Field(required=True, label="User Email")
    user_employee_id: Optional[str] = Field(
        required=False,
        max_length=100,
        label="Employee ID"
    )

    # Source & Attribution
    source: str = Field(
        required=False,
        default="manual",
        label="Award Source"
    )
    source_reference_id: Optional[int] = Field(
        required=False,
        label="Source Reference ID"
    )
    source_reference_type: Optional[str] = Field(
        required=False,
        max_length=50,
        label="Source Type"
    )

    # Linked Badge Award
    linked_award_id: Optional[int] = Field(
        required=False,
        fk="award_id|reward",
        api="users_rewards",
        label="Linked Badge Award"
    )

    # Award Details
    awarded_by_user_id: Optional[int] = Field(
        required=False,
        fk="user_id|display_name",
        api="ad_users",
        label="Awarded By"
    )
    awarded_by_email: Optional[str] = Field(required=False)
    awarded_at: datetime = Field(
        required=False,
        default=datetime.now,
        label="Awarded At"
    )
    award_message: Optional[str] = Field(
        required=False,
        ui_widget="textarea",
        label="Award Message"
    )

    # Status
    status: str = Field(
        required=False,
        default="available",
        label="Status"
    )
    status_changed_at: datetime = Field(
        required=False,
        default=datetime.now
    )
    status_changed_by: Optional[str] = Field(required=False)

    # Expiration
    expires_at: Optional[datetime] = Field(
        required=False,
        label="Expires At"
    )

    # Value snapshot
    points_value: int = Field(
        required=False,
        default=0,
        label="Points Value"
    )
    monetary_value: Optional[Decimal] = Field(
        required=False,
        label="Monetary Value"
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        required=False,
        default_factory=dict,
        label="Metadata"
    )

    # Audit
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )
    updated_at: datetime = Field(
        required=False,
        default=datetime.now
    )

    class Meta:
        driver = "pg"
        name = "prize_awards"
        schema = REWARDS_SCHEMA
        endpoint = "rewards/api/v1/prize_awards"
        strict = True

    def can_redeem(self) -> bool:
        """Check if this award can be redeemed."""
        if self.status != AwardStatus.AVAILABLE.value:
            return False
        if self.expires_at and self.expires_at < datetime.now():
            return False
        return True

    def is_expired(self) -> bool:
        """Check if the award has expired."""
        if self.expires_at is None:
            return False
        return self.expires_at < datetime.now()


# ============================================================================
# PRIZE REDEMPTION MODEL
# ============================================================================

class PrizeRedemption(Model):
    """
    Prize redemption record with full audit trail.

    Tracks the complete redemption lifecycle with metrics.
    """

    redemption_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto",
        repr=False
    )

    # References
    award_id: int = Field(
        required=True,
        fk="award_id|prize_id",
        api="prize_awards",
        label="Prize Award"
    )
    prize_id: int = Field(
        required=True,
        fk="prize_id|prize_name",
        api="prize_catalog",
        label="Prize"
    )
    user_id: int = Field(
        required=True,
        fk="user_id|display_name",
        api="ad_users",
        label="User"
    )

    # Redemption Code
    redemption_code: Optional[str] = Field(
        required=False,
        max_length=100,
        label="Redemption Code",
        readonly=True
    )

    # Status
    status: str = Field(
        required=False,
        default="initiated",
        label="Status"
    )

    # Timestamps
    initiated_at: datetime = Field(
        required=False,
        default=datetime.now,
        label="Initiated At"
    )
    approved_at: Optional[datetime] = Field(required=False, label="Approved At")
    approved_by: Optional[int] = Field(
        required=False,
        fk="user_id|display_name",
        api="ad_users",
        label="Approved By"
    )
    processing_started_at: Optional[datetime] = Field(required=False)
    completed_at: Optional[datetime] = Field(required=False, label="Completed At")
    cancelled_at: Optional[datetime] = Field(required=False)
    cancelled_by: Optional[int] = Field(required=False)
    cancelled_reason: Optional[str] = Field(required=False, ui_widget="textarea")

    # Fulfillment
    fulfillment_method: Optional[str] = Field(
        required=False,
        max_length=50,
        label="Fulfillment Method"
    )
    fulfillment_details: Dict[str, Any] = Field(
        required=False,
        default_factory=dict,
        label="Fulfillment Details"
    )

    # Shipping
    shipping_address: Optional[Dict[str, Any]] = Field(
        required=False,
        label="Shipping Address"
    )
    tracking_number: Optional[str] = Field(
        required=False,
        max_length=100,
        label="Tracking Number"
    )
    shipped_at: Optional[datetime] = Field(required=False)
    delivered_at: Optional[datetime] = Field(required=False)

    # User Feedback
    user_rating: Optional[int] = Field(
        required=False,
        label="User Rating",
        ui_help="1-5 stars"
    )
    user_feedback: Optional[str] = Field(
        required=False,
        ui_widget="textarea",
        label="User Feedback"
    )
    feedback_at: Optional[datetime] = Field(required=False)

    # Metrics (auto-calculated)
    time_to_approve_seconds: Optional[int] = Field(required=False, readonly=True)
    time_to_complete_seconds: Optional[int] = Field(required=False, readonly=True)
    total_processing_seconds: Optional[int] = Field(required=False, readonly=True)

    # Notes
    admin_notes: Optional[str] = Field(
        required=False,
        ui_widget="textarea",
        label="Admin Notes"
    )
    notification_sent_at: Optional[datetime] = Field(required=False)
    reminder_sent_at: Optional[datetime] = Field(required=False)

    # Metadata
    metadata: Dict[str, Any] = Field(
        required=False,
        default_factory=dict,
        label="Metadata"
    )

    # Audit
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        driver = "pg"
        name = "prize_redemptions"
        schema = REWARDS_SCHEMA
        endpoint = "rewards/api/v1/prize_redemptions"
        strict = True


# ============================================================================
# REDEMPTION STATUS HISTORY MODEL
# ============================================================================

class RedemptionStatusHistory(Model):
    """Audit trail for redemption status changes."""

    history_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto"
    )
    redemption_id: int = Field(
        required=True,
        fk="redemption_id",
        label="Redemption"
    )
    previous_status: Optional[str] = Field(required=False)
    new_status: str = Field(required=True)
    changed_at: datetime = Field(
        required=False,
        default=datetime.now
    )
    changed_by_user_id: Optional[int] = Field(required=False)
    changed_by_email: Optional[str] = Field(required=False)
    change_reason: Optional[str] = Field(required=False)
    metadata: Dict[str, Any] = Field(
        required=False,
        default_factory=dict
    )

    class Meta:
        driver = "pg"
        name = "redemption_status_history"
        schema = REWARDS_SCHEMA
        strict = True


# ============================================================================
# MYSTERY BOX EVENT MODEL
# ============================================================================

class MysteryBoxEvent(Model):
    """
    Mystery box event record.

    Tracks scheduled mystery box events and their results.
    """

    event_id: int = Field(
        primary_key=True,
        required=False,
        db_default="auto"
    )

    event_name: str = Field(
        required=True,
        max_length=255,
        label="Event Name"
    )
    description: Optional[str] = Field(
        required=False,
        ui_widget="textarea",
        label="Description"
    )

    # Scheduling
    scheduled_at: datetime = Field(
        required=True,
        label="Scheduled At"
    )
    executed_at: Optional[datetime] = Field(
        required=False,
        label="Executed At"
    )

    # Eligibility
    eligible_user_count: Optional[int] = Field(required=False)
    eligible_users: Optional[Dict[str, Any]] = Field(
        required=False,
        label="Eligibility Criteria"
    )

    # Results
    winners_count: int = Field(
        required=False,
        default=0,
        label="Winners Count"
    )
    prizes_awarded: List[Dict[str, Any]] = Field(
        required=False,
        default_factory=list,
        label="Prizes Awarded"
    )

    # Status
    status: str = Field(
        required=False,
        default="scheduled",
        label="Status"
    )
    error_message: Optional[str] = Field(required=False)

    # Linked Badge
    linked_reward_id: Optional[int] = Field(
        required=False,
        fk="reward_id|reward",
        api="rewards",
        label="Linked Badge"
    )

    # Audit
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        readonly=True
    )
    created_by: Optional[str] = Field(required=False)

    class Meta:
        driver = "pg"
        name = "mystery_box_events"
        schema = REWARDS_SCHEMA
        endpoint = "rewards/api/v1/mystery_box_events"
        strict = True


# ============================================================================
# VIEW MODELS (Read-only for API responses)
# ============================================================================

class UserPrizeWallet(BaseModel):
    """
    User's prize wallet view - combines award and redemption info.

    This is a read-only model for API responses.
    """
    award_id: int
    user_id: int
    user_email: str
    prize_id: int
    prize_name: str
    short_description: Optional[str]
    image_url: Optional[str]
    thumbnail_url: Optional[str]
    tier_name: Optional[str]
    tier_color: Optional[str]
    category_name: Optional[str]
    source: str
    status: str
    awarded_at: datetime
    expires_at: Optional[datetime]
    monetary_value: Optional[Decimal]
    points_value: int
    redemption_id: Optional[int]
    redemption_status: Optional[str]
    redemption_initiated_at: Optional[datetime]
    redemption_completed_at: Optional[datetime]
    redemption_code: Optional[str]
    is_expired: bool
    can_redeem: bool
    days_until_expiry: Optional[int]


class PrizeCatalogView(BaseModel):
    """
    Prize catalog view with computed fields.

    This is a read-only model for API responses.
    """
    prize_id: int
    prize_name: str
    description: Optional[str]
    short_description: Optional[str]
    category_name: Optional[str]
    tier_name: Optional[str]
    tier_level: Optional[int]
    tier_color: Optional[str]
    drop_rate: Optional[Decimal]
    points_cost: int
    monetary_value: Optional[Decimal]
    image_url: Optional[str]
    thumbnail_url: Optional[str]
    linked_badge_name: Optional[str]
    linked_badge_icon: Optional[str]
    stock_status: str
    effective_quantity: int
    is_active: bool
    is_featured: bool
    is_mystery_eligible: bool


class RedemptionMetrics(BaseModel):
    """
    Redemption metrics for analytics.
    """
    redemption_id: int
    award_id: int
    prize_id: int
    user_id: int
    prize_name: str
    status: str
    initiated_at: datetime
    completed_at: Optional[datetime]
    awarded_at: datetime
    seconds_to_initiate: Optional[int]
    seconds_to_complete: Optional[int]
    total_lifecycle_seconds: Optional[int]
