"""
Prize Marketplace Service for NAV-Rewards.

This module provides the core business logic for:
- Prize catalog management
- Prize awarding
- Prize redemption with validation
- Metrics and reporting
"""
import random
import secrets
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from dataclasses import dataclass, field
import asyncio

from navconfig.logging import logging
from asyncdb import AsyncDB

from .models import (
    PrizeCatalog,
    PrizeAward,
    PrizeRedemption,
    PrizeCategory,
    PrizeTier,
    MysteryBoxEvent,
    RedemptionStatusHistory,
    AwardStatus,
    AwardSource,
    RedemptionStatus,
    UserPrizeWallet,
)


@dataclass
class AwardResult:
    """Result of a prize award operation."""
    success: bool
    award_id: Optional[int] = None
    award: Optional[PrizeAward] = None
    message: str = ""
    error: Optional[str] = None


@dataclass
class RedemptionResult:
    """Result of a redemption operation."""
    success: bool
    redemption_id: Optional[int] = None
    redemption: Optional[PrizeRedemption] = None
    redemption_code: Optional[str] = None
    message: str = ""
    error: Optional[str] = None


@dataclass
class MysteryBoxResult:
    """Result of a mystery box event."""
    success: bool
    event_id: Optional[int] = None
    winners: List[Dict[str, Any]] = field(default_factory=list)
    total_prizes_awarded: int = 0
    message: str = ""
    error: Optional[str] = None


class MarketplaceService:
    """
    Core service for prize marketplace operations.

    Handles all prize-related business logic including:
    - Catalog queries and filtering
    - Prize awarding with validation
    - Redemption processing with audit trail
    - Mystery box prize selection
    - Metrics calculation
    """

    def __init__(self, connection: AsyncDB = None, logger=None):
        self.connection = connection
        self.logger = logger or logging.getLogger('Rewards.Marketplace')
        self._schema = "rewards"

    async def set_connection(self, connection: AsyncDB):
        """Set the database connection."""
        self.connection = connection

    # =========================================================================
    # CATALOG OPERATIONS
    # =========================================================================

    async def get_catalog(
        self,
        category_id: Optional[int] = None,
        tier_id: Optional[int] = None,
        is_active: bool = True,
        is_featured: Optional[bool] = None,
        in_stock_only: bool = False,
        mystery_eligible_only: bool = False,
        search_term: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get prizes from the catalog with filtering options.

        Args:
            category_id: Filter by category
            tier_id: Filter by tier/rarity
            is_active: Only active prizes (default True)
            is_featured: Filter by featured status
            in_stock_only: Only prizes with available stock
            mystery_eligible_only: Only mystery box eligible prizes
            search_term: Search in name/description
            limit: Max results
            offset: Pagination offset

        Returns:
            List of prize dictionaries with computed fields
        """
        query = """
            SELECT
                pc.*,
                pt.tier_name,
                pt.tier_level,
                pt.color_code AS tier_color,
                pt.drop_rate,
                pcat.category_name,
                r.reward AS linked_badge_name,
                r.icon AS linked_badge_icon,
                CASE
                    WHEN pc.total_quantity IS NULL THEN 'unlimited'
                    WHEN pc.available_quantity <= 0 THEN 'out_of_stock'
                    WHEN pc.available_quantity <= (pc.total_quantity * 0.1) THEN 'low_stock'
                    ELSE 'in_stock'
                END AS stock_status,
                COALESCE(pc.available_quantity, 999999) - COALESCE(pc.reserved_quantity, 0) AS effective_quantity
            FROM {schema}.prize_catalog pc
            LEFT JOIN {schema}.prize_tiers pt ON pc.tier_id = pt.tier_id
            LEFT JOIN {schema}.prize_categories pcat ON pc.category_id = pcat.category_id
            LEFT JOIN {schema}.rewards r ON pc.linked_reward_id = r.reward_id
            WHERE pc.deleted_at IS NULL
        """.format(schema=self._schema)

        params = []
        param_count = 0

        if is_active:
            param_count += 1
            query += f" AND pc.is_active = ${param_count}"
            params.append(True)

        if category_id is not None:
            param_count += 1
            query += f" AND pc.category_id = ${param_count}"
            params.append(category_id)

        if tier_id is not None:
            param_count += 1
            query += f" AND pc.tier_id = ${param_count}"
            params.append(tier_id)

        if is_featured is not None:
            param_count += 1
            query += f" AND pc.is_featured = ${param_count}"
            params.append(is_featured)

        if mystery_eligible_only:
            param_count += 1
            query += f" AND pc.is_mystery_eligible = ${param_count}"
            params.append(True)

        if in_stock_only:
            query += """ AND (
                pc.total_quantity IS NULL
                OR (pc.available_quantity - COALESCE(pc.reserved_quantity, 0)) > 0
            )"""

        if search_term:
            param_count += 1
            query += f" AND (pc.prize_name ILIKE ${param_count} OR pc.description ILIKE ${param_count})"
            params.append(f"%{search_term}%")

        query += f" ORDER BY pc.is_featured DESC, pt.tier_level DESC, pc.prize_name"
        query += f" LIMIT {limit} OFFSET {offset}"

        async with await self.connection.acquire() as conn:
            results = await conn.fetch_all(query, params)
            return [dict(r) for r in results]

    async def get_prize(self, prize_id: int) -> Optional[Dict[str, Any]]:
        """Get a single prize with all details."""
        query = """
            SELECT
                pc.*,
                pt.tier_name,
                pt.tier_level,
                pt.color_code AS tier_color,
                pcat.category_name,
                r.reward AS linked_badge_name
            FROM {schema}.prize_catalog pc
            LEFT JOIN {schema}.prize_tiers pt ON pc.tier_id = pt.tier_id
            LEFT JOIN {schema}.prize_categories pcat ON pc.category_id = pcat.category_id
            LEFT JOIN {schema}.rewards r ON pc.linked_reward_id = r.reward_id
            WHERE pc.prize_id = $1 AND pc.deleted_at IS NULL
        """.format(schema=self._schema)

        async with await self.connection.acquire() as conn:
            result = await conn.fetchrow(query, [prize_id])
            return dict(result) if result else None

    async def get_categories(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all prize categories."""
        query = f"""
            SELECT * FROM {self._schema}.prize_categories
            WHERE ($1 = FALSE OR is_active = TRUE)
            ORDER BY display_order, category_name
        """
        async with await self.connection.acquire() as conn:
            results = await conn.fetch_all(query, [active_only])
            return [dict(r) for r in results]

    async def get_tiers(self) -> List[Dict[str, Any]]:
        """Get all prize tiers."""
        query = f"""
            SELECT * FROM {self._schema}.prize_tiers
            ORDER BY tier_level
        """
        async with await self.connection.acquire() as conn:
            results = await conn.fetch_all(query)
            return [dict(r) for r in results]

    # =========================================================================
    # PRIZE AWARDING
    # =========================================================================

    async def award_prize(
        self,
        prize_id: int,
        user_id: int,
        user_email: str,
        source: AwardSource = AwardSource.MANUAL,
        source_reference_id: Optional[int] = None,
        source_reference_type: Optional[str] = None,
        linked_award_id: Optional[int] = None,
        awarded_by_user_id: Optional[int] = None,
        awarded_by_email: Optional[str] = None,
        award_message: Optional[str] = None,
        expires_in_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_employee_id: Optional[str] = None
    ) -> AwardResult:
        """
        Award a prize to a user.

        Args:
            prize_id: ID of the prize to award
            user_id: Recipient user ID
            user_email: Recipient email
            source: How the prize was awarded
            source_reference_id: Reference to source (e.g., badge award ID)
            source_reference_type: Type of source reference
            linked_award_id: Optional linked badge award
            awarded_by_user_id: User who awarded (for manual awards)
            awarded_by_email: Email of awarder
            award_message: Custom message
            expires_in_days: Days until award expires (None = never)
            metadata: Additional metadata
            user_employee_id: Employee ID if available

        Returns:
            AwardResult with success status and award details
        """
        try:
            # Get prize details
            prize = await self.get_prize(prize_id)
            if not prize:
                return AwardResult(
                    success=False,
                    error="Prize not found"
                )

            if not prize.get('is_active'):
                return AwardResult(
                    success=False,
                    error="Prize is not active"
                )

            # Check stock
            if prize.get('total_quantity') is not None:
                effective = (prize.get('available_quantity') or 0) - (prize.get('reserved_quantity') or 0)
                if effective <= 0:
                    return AwardResult(
                        success=False,
                        error="Prize is out of stock"
                    )

            # Check user eligibility (max per user, cooldown)
            if not await self._check_user_eligibility(prize_id, user_id, prize):
                return AwardResult(
                    success=False,
                    error="User is not eligible for this prize (max limit or cooldown)"
                )

            # Calculate expiration
            expires_at = None
            if expires_in_days:
                expires_at = datetime.now() + timedelta(days=expires_in_days)

            # Create the award
            insert_query = f"""
                INSERT INTO {self._schema}.prize_awards (
                    prize_id, user_id, user_email, user_employee_id,
                    source, source_reference_id, source_reference_type,
                    linked_award_id, awarded_by_user_id, awarded_by_email,
                    award_message, status, expires_at,
                    points_value, monetary_value, metadata
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
                )
                RETURNING award_id, awarded_at
            """

            params = [
                prize_id, user_id, user_email, user_employee_id,
                source.value, source_reference_id, source_reference_type,
                linked_award_id, awarded_by_user_id, awarded_by_email,
                award_message, AwardStatus.AVAILABLE.value, expires_at,
                prize.get('points_cost', 0), prize.get('monetary_value'),
                metadata or {}
            ]

            async with await self.connection.acquire() as conn:
                result = await conn.fetchrow(insert_query, params)

                if result:
                    self.logger.info(
                        f"Prize {prize_id} awarded to user {user_id} "
                        f"(award_id: {result['award_id']}, source: {source.value})"
                    )

                    return AwardResult(
                        success=True,
                        award_id=result['award_id'],
                        message=f"Prize '{prize['prize_name']}' successfully awarded"
                    )
                else:
                    return AwardResult(
                        success=False,
                        error="Failed to create award record"
                    )

        except Exception as err:
            self.logger.error(f"Error awarding prize: {err}")
            return AwardResult(
                success=False,
                error=str(err)
            )

    async def _check_user_eligibility(
        self,
        prize_id: int,
        user_id: int,
        prize: Dict[str, Any]
    ) -> bool:
        """Check if user is eligible for this prize."""
        max_per_user = prize.get('max_per_user')
        cooldown_days = prize.get('cooldown_days', 0)

        if not max_per_user and cooldown_days == 0:
            return True

        query = f"""
            SELECT COUNT(*) as total_awards,
                   MAX(awarded_at) as last_awarded
            FROM {self._schema}.prize_awards
            WHERE prize_id = $1
              AND user_id = $2
              AND status != 'cancelled'
        """

        async with await self.connection.acquire() as conn:
            result = await conn.fetchrow(query, [prize_id, user_id])

            if result:
                total_awards = result['total_awards']
                last_awarded = result['last_awarded']

                # Check max per user
                if max_per_user and total_awards >= max_per_user:
                    return False

                # Check cooldown
                if cooldown_days > 0 and last_awarded:
                    cooldown_end = last_awarded + timedelta(days=cooldown_days)
                    if datetime.now() < cooldown_end:
                        return False

            return True

    # =========================================================================
    # REDEMPTION OPERATIONS
    # =========================================================================

    async def initiate_redemption(
        self,
        award_id: int,
        user_id: int,
        fulfillment_method: Optional[str] = None,
        shipping_address: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RedemptionResult:
        """
        Initiate a prize redemption.

        This validates the award and creates a redemption record.
        The award status is updated to 'reserved' to prevent double redemption.

        Args:
            award_id: The prize award to redeem
            user_id: User initiating redemption (must match award recipient)
            fulfillment_method: How to fulfill (email, shipping, etc.)
            shipping_address: Address for physical items
            metadata: Additional redemption data

        Returns:
            RedemptionResult with redemption code if successful
        """
        try:
            # Verify the award exists and belongs to user
            award_query = f"""
                SELECT pa.*, pc.prize_name, pc.requires_approval,
                       pc.fulfillment_type, pc.fulfillment_instructions
                FROM {self._schema}.prize_awards pa
                JOIN {self._schema}.prize_catalog pc ON pa.prize_id = pc.prize_id
                WHERE pa.award_id = $1
            """

            async with await self.connection.acquire() as conn:
                award = await conn.fetchrow(award_query, [award_id])

                if not award:
                    return RedemptionResult(
                        success=False,
                        error="Award not found"
                    )

                # Validate ownership
                if award['user_id'] != user_id:
                    return RedemptionResult(
                        success=False,
                        error="Award does not belong to this user"
                    )

                # Check status
                if award['status'] != AwardStatus.AVAILABLE.value:
                    return RedemptionResult(
                        success=False,
                        error=f"Award cannot be redeemed (status: {award['status']})"
                    )

                # Check expiration
                if award['expires_at'] and award['expires_at'] < datetime.now():
                    # Update award to expired
                    await conn.execute(
                        f"""
                        UPDATE {self._schema}.prize_awards
                        SET status = 'expired', status_changed_at = NOW()
                        WHERE award_id = $1
                        """,
                        [award_id]
                    )
                    return RedemptionResult(
                        success=False,
                        error="Award has expired"
                    )

                # Determine initial status
                initial_status = RedemptionStatus.INITIATED.value
                if award['requires_approval']:
                    initial_status = RedemptionStatus.PENDING_APPROVAL.value

                # Create redemption record
                # Note: The trigger will generate the redemption code and update award status
                insert_query = f"""
                    INSERT INTO {self._schema}.prize_redemptions (
                        award_id, prize_id, user_id, status,
                        fulfillment_method, shipping_address, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING redemption_id, redemption_code
                """

                result = await conn.fetchrow(insert_query, [
                    award_id, award['prize_id'], user_id, initial_status,
                    fulfillment_method or award['fulfillment_type'],
                    shipping_address, metadata or {}
                ])

                if result:
                    self.logger.info(
                        f"Redemption initiated for award {award_id} "
                        f"(redemption_id: {result['redemption_id']}, "
                        f"code: {result['redemption_code']})"
                    )

                    return RedemptionResult(
                        success=True,
                        redemption_id=result['redemption_id'],
                        redemption_code=result['redemption_code'],
                        message=f"Redemption initiated for '{award['prize_name']}'"
                    )
                else:
                    return RedemptionResult(
                        success=False,
                        error="Failed to create redemption record"
                    )

        except Exception as err:
            self.logger.error(f"Error initiating redemption: {err}")
            return RedemptionResult(
                success=False,
                error=str(err)
            )

    async def update_redemption_status(
        self,
        redemption_id: int,
        new_status: RedemptionStatus,
        updated_by_user_id: Optional[int] = None,
        updated_by_email: Optional[str] = None,
        reason: Optional[str] = None,
        fulfillment_details: Optional[Dict[str, Any]] = None,
        tracking_number: Optional[str] = None,
        admin_notes: Optional[str] = None
    ) -> RedemptionResult:
        """
        Update a redemption's status.

        Args:
            redemption_id: The redemption to update
            new_status: New status value
            updated_by_user_id: User making the update
            updated_by_email: Email of updater
            reason: Reason for status change
            fulfillment_details: Additional fulfillment info (gift codes, etc.)
            tracking_number: Shipping tracking number
            admin_notes: Notes from admin

        Returns:
            RedemptionResult indicating success/failure
        """
        try:
            update_parts = ["status = $1"]
            params = [new_status.value]
            param_count = 1

            # Build dynamic update
            if fulfillment_details:
                param_count += 1
                update_parts.append(f"fulfillment_details = ${param_count}")
                params.append(fulfillment_details)

            if tracking_number:
                param_count += 1
                update_parts.append(f"tracking_number = ${param_count}")
                params.append(tracking_number)

                if new_status == RedemptionStatus.SHIPPED:
                    update_parts.append("shipped_at = NOW()")

            if admin_notes:
                param_count += 1
                update_parts.append(f"admin_notes = ${param_count}")
                params.append(admin_notes)

            if reason:
                param_count += 1
                update_parts.append(f"cancelled_reason = ${param_count}")
                params.append(reason)

            if updated_by_user_id:
                if new_status == RedemptionStatus.APPROVED:
                    param_count += 1
                    update_parts.append(f"approved_by = ${param_count}")
                    params.append(updated_by_user_id)
                elif new_status in [RedemptionStatus.CANCELLED, RedemptionStatus.REJECTED]:
                    param_count += 1
                    update_parts.append(f"cancelled_by = ${param_count}")
                    params.append(updated_by_user_id)

            # Add metadata for trigger to track who made the change
            param_count += 1
            update_parts.append(f"""
                metadata = metadata || jsonb_build_object(
                    'changed_by', ${param_count}::text
                )
            """)
            params.append(updated_by_email or str(updated_by_user_id))

            param_count += 1
            params.append(redemption_id)

            query = f"""
                UPDATE {self._schema}.prize_redemptions
                SET {', '.join(update_parts)}
                WHERE redemption_id = ${param_count}
                RETURNING redemption_id, status
            """

            async with await self.connection.acquire() as conn:
                result = await conn.fetchrow(query, params)

                if result:
                    self.logger.info(
                        f"Redemption {redemption_id} updated to {new_status.value}"
                    )
                    return RedemptionResult(
                        success=True,
                        redemption_id=redemption_id,
                        message=f"Redemption updated to {new_status.value}"
                    )
                else:
                    return RedemptionResult(
                        success=False,
                        error="Redemption not found"
                    )

        except Exception as err:
            self.logger.error(f"Error updating redemption: {err}")
            return RedemptionResult(
                success=False,
                error=str(err)
            )

    async def complete_redemption(
        self,
        redemption_id: int,
        fulfillment_details: Optional[Dict[str, Any]] = None,
        completed_by_email: Optional[str] = None
    ) -> RedemptionResult:
        """Shorthand to mark a redemption as completed."""
        return await self.update_redemption_status(
            redemption_id=redemption_id,
            new_status=RedemptionStatus.COMPLETED,
            updated_by_email=completed_by_email,
            fulfillment_details=fulfillment_details
        )

    async def cancel_redemption(
        self,
        redemption_id: int,
        cancelled_by_user_id: int,
        reason: str
    ) -> RedemptionResult:
        """Cancel a redemption and restore the award."""
        return await self.update_redemption_status(
            redemption_id=redemption_id,
            new_status=RedemptionStatus.CANCELLED,
            updated_by_user_id=cancelled_by_user_id,
            reason=reason
        )

    # =========================================================================
    # USER WALLET OPERATIONS
    # =========================================================================

    async def get_user_wallet(
        self,
        user_id: int,
        status_filter: Optional[List[str]] = None,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get a user's prize wallet (all their awards).

        Args:
            user_id: The user ID
            status_filter: Optional list of statuses to filter
            include_expired: Include expired awards

        Returns:
            List of prize awards with redemption info
        """
        query = f"""
            SELECT * FROM {self._schema}.vw_user_prize_wallet
            WHERE user_id = $1
        """
        params = [user_id]
        param_count = 1

        if status_filter:
            param_count += 1
            query += f" AND status = ANY(${param_count})"
            params.append(status_filter)

        if not include_expired:
            query += " AND is_expired = FALSE"

        query += " ORDER BY awarded_at DESC"

        async with await self.connection.acquire() as conn:
            results = await conn.fetch_all(query, params)
            return [dict(r) for r in results]

    async def get_user_wallet_stats(self, user_id: int) -> Dict[str, Any]:
        """Get statistics for a user's prize wallet."""
        query = f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'available' AND NOT is_expired) AS available_count,
                COUNT(*) FILTER (WHERE status = 'redeemed') AS redeemed_count,
                COUNT(*) FILTER (WHERE status = 'expired' OR is_expired) AS expired_count,
                COUNT(*) FILTER (WHERE status = 'reserved') AS pending_count,
                COALESCE(SUM(monetary_value) FILTER (WHERE status = 'available'), 0) AS available_value,
                COALESCE(SUM(monetary_value) FILTER (WHERE status = 'redeemed'), 0) AS redeemed_value,
                COUNT(*) FILTER (WHERE days_until_expiry BETWEEN 0 AND 7) AS expiring_soon
            FROM {self._schema}.vw_user_prize_wallet
            WHERE user_id = $1
        """

        async with await self.connection.acquire() as conn:
            result = await conn.fetchrow(query, [user_id])
            return dict(result) if result else {}

    # =========================================================================
    # MYSTERY BOX OPERATIONS
    # =========================================================================

    async def execute_mystery_box(
        self,
        event_name: str,
        winner_count: int = 1,
        eligible_user_ids: Optional[List[int]] = None,
        eligibility_criteria: Optional[Dict[str, Any]] = None,
        tier_overrides: Optional[Dict[int, float]] = None,
        expires_in_days: int = 30,
        linked_reward_id: Optional[int] = None,
        created_by: Optional[str] = None
    ) -> MysteryBoxResult:
        """
        Execute a mystery box event.

        Selects random winners and awards random prizes based on tier drop rates.

        Args:
            event_name: Name/description of the event
            winner_count: Number of winners to select
            eligible_user_ids: Specific users to consider (or None for all)
            eligibility_criteria: Query criteria for eligible users
            tier_overrides: Custom drop rates by tier_id
            expires_in_days: Days until awarded prizes expire
            linked_reward_id: Optional badge to link
            created_by: Who triggered the event

        Returns:
            MysteryBoxResult with winners and prizes
        """
        try:
            async with await self.connection.acquire() as conn:
                # Create event record
                event_query = f"""
                    INSERT INTO {self._schema}.mystery_box_events (
                        event_name, scheduled_at, status, eligible_users,
                        linked_reward_id, created_by
                    ) VALUES ($1, NOW(), 'running', $2, $3, $4)
                    RETURNING event_id
                """

                event_result = await conn.fetchrow(event_query, [
                    event_name, eligibility_criteria or {},
                    linked_reward_id, created_by
                ])
                event_id = event_result['event_id']

                # Get eligible users
                if eligible_user_ids:
                    users = eligible_user_ids
                else:
                    users = await self._get_eligible_users(conn, eligibility_criteria)

                if not users:
                    await self._update_event_status(
                        conn, event_id, 'completed',
                        error_message="No eligible users"
                    )
                    return MysteryBoxResult(
                        success=True,
                        event_id=event_id,
                        message="No eligible users for mystery box"
                    )

                # Get mystery-eligible prizes by tier
                tiers = await self._get_mystery_box_tiers(conn, tier_overrides)
                prizes_by_tier = await self._get_mystery_eligible_prizes(conn)

                if not prizes_by_tier:
                    await self._update_event_status(
                        conn, event_id, 'failed',
                        error_message="No prizes available for mystery box"
                    )
                    return MysteryBoxResult(
                        success=False,
                        event_id=event_id,
                        error="No prizes available"
                    )

                # Select winners
                winners = random.sample(users, min(winner_count, len(users)))

                # Award prizes to winners
                prizes_awarded = []
                for winner_user_id in winners:
                    # Roll for tier
                    tier = self._roll_tier(tiers)

                    # Get user email
                    user_info = await conn.fetchrow(
                        "SELECT email, associate_id FROM auth.users WHERE user_id = $1",
                        [winner_user_id]
                    )

                    if not user_info:
                        continue

                    # Select random prize from tier
                    tier_prizes = prizes_by_tier.get(tier['tier_id'], [])
                    if not tier_prizes:
                        # Fallback to common tier
                        tier_prizes = prizes_by_tier.get(1, [])

                    if tier_prizes:
                        # Weight selection by mystery_weight
                        prize = self._weighted_random_choice(tier_prizes)

                        # Award the prize
                        award_result = await self.award_prize(
                            prize_id=prize['prize_id'],
                            user_id=winner_user_id,
                            user_email=user_info['email'],
                            source=AwardSource.MYSTERY_BOX,
                            source_reference_id=event_id,
                            source_reference_type='mystery_box_event',
                            linked_award_id=linked_reward_id,
                            expires_in_days=expires_in_days,
                            metadata={
                                'mystery_box_event_id': event_id,
                                'tier_rolled': tier['tier_name'],
                                'event_name': event_name
                            },
                            user_employee_id=user_info.get('associate_id')
                        )

                        if award_result.success:
                            prizes_awarded.append({
                                'user_id': winner_user_id,
                                'user_email': user_info['email'],
                                'prize_id': prize['prize_id'],
                                'prize_name': prize['prize_name'],
                                'tier': tier['tier_name'],
                                'tier_color': tier.get('color_code'),
                                'award_id': award_result.award_id
                            })

                # Update event with results
                await conn.execute(f"""
                    UPDATE {self._schema}.mystery_box_events
                    SET status = 'completed',
                        executed_at = NOW(),
                        winners_count = $1,
                        prizes_awarded = $2,
                        eligible_user_count = $3
                    WHERE event_id = $4
                """, [
                    len(prizes_awarded),
                    prizes_awarded,
                    len(users),
                    event_id
                ])

                self.logger.info(
                    f"Mystery box event {event_id} completed: "
                    f"{len(prizes_awarded)} prizes awarded to {len(winners)} winners"
                )

                return MysteryBoxResult(
                    success=True,
                    event_id=event_id,
                    winners=prizes_awarded,
                    total_prizes_awarded=len(prizes_awarded),
                    message=f"Mystery box event completed: {len(prizes_awarded)} prizes awarded"
                )

        except Exception as err:
            self.logger.error(f"Error executing mystery box: {err}")
            return MysteryBoxResult(
                success=False,
                error=str(err)
            )

    async def _get_eligible_users(
        self,
        conn,
        criteria: Optional[Dict[str, Any]]
    ) -> List[int]:
        """Get eligible users based on criteria."""
        # Base query - active users
        query = """
            SELECT user_id FROM auth.users
            WHERE is_active = TRUE AND user_id > 0
        """
        params = []

        if criteria:
            # Add filters based on criteria
            if 'groups' in criteria:
                query += " AND EXISTS (SELECT 1 FROM auth.user_groups ug WHERE ug.user_id = users.user_id)"
            if 'min_tenure_days' in criteria:
                query += f" AND created_at <= NOW() - INTERVAL '{criteria['min_tenure_days']} days'"

        results = await conn.fetch_all(query, params)
        return [r['user_id'] for r in results]

    async def _get_mystery_box_tiers(
        self,
        conn,
        overrides: Optional[Dict[int, float]]
    ) -> List[Dict[str, Any]]:
        """Get tier drop rates."""
        tiers = await conn.fetch_all(f"""
            SELECT tier_id, tier_name, tier_level, drop_rate, color_code
            FROM {self._schema}.prize_tiers
            ORDER BY tier_level
        """)

        result = [dict(t) for t in tiers]

        if overrides:
            for tier in result:
                if tier['tier_id'] in overrides:
                    tier['drop_rate'] = Decimal(str(overrides[tier['tier_id']]))

        return result

    async def _get_mystery_eligible_prizes(self, conn) -> Dict[int, List[Dict]]:
        """Get all mystery-eligible prizes grouped by tier."""
        query = f"""
            SELECT prize_id, prize_name, tier_id, mystery_weight,
                   monetary_value, image_url
            FROM {self._schema}.prize_catalog
            WHERE is_mystery_eligible = TRUE
              AND is_active = TRUE
              AND deleted_at IS NULL
              AND (total_quantity IS NULL OR available_quantity > 0)
        """

        results = await conn.fetch_all(query)

        prizes_by_tier: Dict[int, List[Dict]] = {}
        for row in results:
            tier_id = row['tier_id'] or 1  # Default to common
            if tier_id not in prizes_by_tier:
                prizes_by_tier[tier_id] = []
            prizes_by_tier[tier_id].append(dict(row))

        return prizes_by_tier

    def _roll_tier(self, tiers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Roll for a tier based on drop rates."""
        roll = random.random()
        cumulative = 0

        for tier in tiers:
            cumulative += float(tier['drop_rate'])
            if roll <= cumulative:
                return tier

        return tiers[0]  # Fallback to first tier

    def _weighted_random_choice(self, prizes: List[Dict]) -> Dict:
        """Select a prize weighted by mystery_weight."""
        total_weight = sum(p.get('mystery_weight', 100) for p in prizes)
        roll = random.randint(1, total_weight)

        cumulative = 0
        for prize in prizes:
            cumulative += prize.get('mystery_weight', 100)
            if roll <= cumulative:
                return prize

        return prizes[0]

    async def _update_event_status(
        self,
        conn,
        event_id: int,
        status: str,
        error_message: Optional[str] = None
    ):
        """Update mystery box event status."""
        await conn.execute(f"""
            UPDATE {self._schema}.mystery_box_events
            SET status = $1, executed_at = NOW(), error_message = $2
            WHERE event_id = $3
        """, [status, error_message, event_id])

    # =========================================================================
    # METRICS & REPORTING
    # =========================================================================

    async def get_redemption_metrics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get redemption metrics for analytics."""
        query = f"""
            SELECT
                COUNT(*) AS total_redemptions,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE status IN ('initiated', 'pending_approval', 'processing')) AS in_progress,
                AVG(time_to_complete_seconds) FILTER (WHERE status = 'completed') AS avg_completion_seconds,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY time_to_complete_seconds)
                    FILTER (WHERE status = 'completed') AS median_completion_seconds,
                AVG(user_rating) FILTER (WHERE user_rating IS NOT NULL) AS avg_rating
            FROM {self._schema}.prize_redemptions
            WHERE ($1::timestamptz IS NULL OR initiated_at >= $1)
              AND ($2::timestamptz IS NULL OR initiated_at <= $2)
        """

        async with await self.connection.acquire() as conn:
            result = await conn.fetchrow(query, [start_date, end_date])
            return dict(result) if result else {}

    async def get_prize_popularity(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most popular prizes by award count."""
        query = f"""
            SELECT
                pc.prize_id,
                pc.prize_name,
                pc.image_url,
                pt.tier_name,
                COUNT(pa.award_id) AS award_count,
                COUNT(pr.redemption_id) FILTER (WHERE pr.status = 'completed') AS redemption_count,
                ROUND(
                    COUNT(pr.redemption_id) FILTER (WHERE pr.status = 'completed')::DECIMAL /
                    NULLIF(COUNT(pa.award_id), 0) * 100, 2
                ) AS redemption_rate
            FROM {self._schema}.prize_catalog pc
            LEFT JOIN {self._schema}.prize_awards pa ON pc.prize_id = pa.prize_id
            LEFT JOIN {self._schema}.prize_redemptions pr ON pa.award_id = pr.award_id
            LEFT JOIN {self._schema}.prize_tiers pt ON pc.tier_id = pt.tier_id
            WHERE pc.is_active = TRUE
            GROUP BY pc.prize_id, pc.prize_name, pc.image_url, pt.tier_name
            ORDER BY award_count DESC
            LIMIT $1
        """

        async with await self.connection.acquire() as conn:
            results = await conn.fetch_all(query, [limit])
            return [dict(r) for r in results]

    async def expire_old_awards(self) -> int:
        """
        Expire awards that have passed their expiration date.

        Returns:
            Number of awards expired
        """
        async with await self.connection.acquire() as conn:
            result = await conn.fetchval(
                f"SELECT {self._schema}.expire_old_awards()"
            )

            if result and result > 0:
                self.logger.info(f"Expired {result} old awards")

            return result or 0
