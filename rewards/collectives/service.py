"""Collection Service for NAV-Rewards.

Provides the business logic for collection completion, bonus awarding,
and notification dispatching. This service is called from the enhanced
`check_collectives` method in RewardObject.

Integration:
    Replace the existing `check_collectives` method in
    `rewards/rewards/base.py` with the enhanced version below.
"""
import asyncio
from typing import Optional
from navconfig.logging import logging
from ..env import Environment
from ..context import EvalContext


class CollectiveService:
    """Service layer for collection (collectives) management.

    Handles:
    - Checking collection completion after a badge is awarded
    - Awarding bonus badges/points on collection completion
    - Dispatching notifications (Teams, Email)
    - Logging completion events
    """

    def __init__(self, env: Environment):
        self.env = env
        self.logger = logging.getLogger('rewards.collections')

    async def check_and_complete(
        self,
        reward_id: int,
        user_id: int,
        award_id: Optional[int] = None,
        ctx: Optional[EvalContext] = None
    ) -> list:
        """Check if awarding this badge completes any collections.

        This is the main entry point called after every badge award.

        Args:
            reward_id: The badge that was just awarded.
            user_id: The user who received the badge.
            award_id: The award_id from users_rewards (for audit).
            ctx: Optional evaluation context.

        Returns:
            List of completed collective_ids.
        """
        completed = []
        async with await self.env.connection.acquire() as conn:
            # Step 1: Find collections containing this badge that the user
            # has now completed (using the progress table updated by trigger)
            query = """
                SELECT
                    cp.collective_id,
                    c.collective_name,
                    c.bonus_points,
                    c.bonus_reward_id,
                    c.message,
                    c.teams_webhook,
                    c.tier,
                    cp.badges_earned,
                    cp.badges_required,
                    cp.earned_reward_ids,
                    cp.completed_at
                FROM rewards.collectives_progress cp
                JOIN rewards.collectives c USING (collective_id)
                LEFT JOIN rewards.collectives_unlocked cu
                    ON cu.collective_id = cp.collective_id
                    AND cu.user_id = cp.user_id
                WHERE cp.user_id = $1::bigint
                  AND cp.is_complete = TRUE
                  AND cu.collective_id IS NULL
                  AND c.is_active = TRUE
                  AND (c.end_date IS NULL OR c.end_date > NOW())
            """
            rows = await conn.fetch_all(query, user_id)

            for row in (rows or []):
                collective_id = row['collective_id']
                try:
                    result = await self._complete_collection(
                        conn=conn,
                        user_id=user_id,
                        collective_id=collective_id,
                        row=row,
                        triggering_reward_id=reward_id,
                        triggering_award_id=award_id,
                        ctx=ctx
                    )
                    if result:
                        completed.append(collective_id)
                except Exception as err:
                    self.logger.error(
                        f"Error completing collection {collective_id} "
                        f"for user {user_id}: {err}"
                    )

        return completed

    async def _complete_collection(
        self,
        conn,
        user_id: int,
        collective_id: int,
        row: dict,
        triggering_reward_id: int,
        triggering_award_id: Optional[int],
        ctx: Optional[EvalContext]
    ) -> bool:
        """Process a single collection completion.

        Steps:
        1. Insert into collectives_unlocked
        2. Award bonus badge if configured
        3. Award bonus points if configured
        4. Log the completion
        5. Dispatch notifications
        """
        bonus_award_id = None

        # Step 1: Unlock the collection
        unlock_query = """
            INSERT INTO rewards.collectives_unlocked
                (collective_id, user_id, bonus_points_awarded)
            VALUES ($1, $2, $3)
            ON CONFLICT (collective_id, user_id) DO NOTHING
            RETURNING unlocked_at
        """
        unlock_result = await conn.fetchval(
            unlock_query,
            collective_id,
            user_id,
            row['bonus_points'] or 0
        )
        if unlock_result is None:
            # Already unlocked (race condition), skip
            return False

        # Step 2: Award bonus badge if configured
        if row['bonus_reward_id']:
            bonus_award_id = await self._award_bonus_badge(
                conn=conn,
                user_id=user_id,
                bonus_reward_id=row['bonus_reward_id'],
                collective_name=row['collective_name'],
                ctx=ctx
            )
            if bonus_award_id:
                # Update the unlock record with bonus_award_id
                await conn.execute(
                    """UPDATE rewards.collectives_unlocked
                    SET bonus_award_id = $1
                    WHERE collective_id = $2 AND user_id = $3""",
                    bonus_award_id, collective_id, user_id
                )

        # Step 3: Award bonus points
        if row['bonus_points'] and row['bonus_points'] > 0:
            await self._award_bonus_points(
                conn=conn,
                user_id=user_id,
                bonus_points=row['bonus_points']
            )

        # Step 4: Log completion
        badges_snapshot = [
            {'reward_id': rid}
            for rid in (row['earned_reward_ids'] or [])
        ]
        await conn.execute(
            """INSERT INTO rewards.collectives_completion_log
            (collective_id, user_id, bonus_points_awarded,
             bonus_reward_id, bonus_award_id,
             completing_badge_id, completing_award_id,
             badges_snapshot)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)""",
            collective_id,
            user_id,
            row['bonus_points'] or 0,
            row['bonus_reward_id'],
            bonus_award_id,
            triggering_reward_id,
            triggering_award_id,
            str(badges_snapshot).replace("'", '"')
        )

        self.logger.info(
            f"User {user_id} completed collection "
            f"'{row['collective_name']}' (ID: {collective_id}). "
            f"Bonus: {row['bonus_points']} points"
            + (f", badge {row['bonus_reward_id']}" if row['bonus_reward_id'] else "")
        )

        # Step 5: Dispatch notification (fire-and-forget)
        asyncio.create_task(
            self._send_collection_notification(
                user_id=user_id,
                collective_name=row['collective_name'],
                tier=row['tier'],
                bonus_points=row['bonus_points'],
                message=row['message'],
                teams_webhook=row['teams_webhook'],
                ctx=ctx
            )
        )

        return True

    async def _award_bonus_badge(
        self,
        conn,
        user_id: int,
        bonus_reward_id: int,
        collective_name: str,
        ctx: Optional[EvalContext]
    ) -> Optional[int]:
        """Award the bonus badge for completing a collection."""
        try:
            # Check if user already has this bonus badge
            existing = await conn.fetchval(
                """SELECT award_id FROM rewards.users_rewards
                WHERE receiver_user = $1 AND reward_id = $2
                AND revoked = FALSE AND deleted_at IS NULL
                LIMIT 1""",
                user_id, bonus_reward_id
            )
            if existing:
                return existing

            # Get reward details
            reward_info = await conn.fetch_one(
                """SELECT reward, points FROM rewards.rewards
                WHERE reward_id = $1""",
                bonus_reward_id
            )
            if not reward_info:
                self.logger.warning(
                    f"Bonus reward {bonus_reward_id} not found"
                )
                return None

            # Get user email for the insert
            user_email = await conn.fetchval(
                "SELECT email FROM auth.users WHERE user_id = $1",
                user_id
            )

            # Insert the bonus badge award
            award_id = await conn.fetchval(
                """INSERT INTO rewards.users_rewards
                (reward_id, reward, receiver_user, receiver_email,
                 points, message, awarded_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                RETURNING award_id""",
                bonus_reward_id,
                reward_info['reward'],
                user_id,
                user_email,
                reward_info['points'],
                f"Bonus badge for completing the '{collective_name}' collection!"
            )
            self.logger.info(
                f"Awarded bonus badge {bonus_reward_id} to user {user_id} "
                f"for collection '{collective_name}'"
            )
            return award_id
        except Exception as err:
            self.logger.error(
                f"Error awarding bonus badge {bonus_reward_id} "
                f"to user {user_id}: {err}"
            )
            return None

    async def _award_bonus_points(
        self,
        conn,
        user_id: int,
        bonus_points: int
    ) -> None:
        """Award bonus points for completing a collection."""
        try:
            await conn.execute(
                """INSERT INTO rewards.points (user_id, points)
                VALUES ($1, $2)""",
                user_id, bonus_points
            )
        except Exception as err:
            self.logger.error(
                f"Error awarding {bonus_points} bonus points "
                f"to user {user_id}: {err}"
            )

    async def _send_collection_notification(
        self,
        user_id: int,
        collective_name: str,
        tier: str,
        bonus_points: int,
        message: Optional[str],
        teams_webhook: Optional[str],
        ctx: Optional[EvalContext]
    ) -> None:
        """Send notification about collection completion."""
        if not teams_webhook:
            return

        try:
            from ..notifications.teams_webhook import TeamsWebhook
            webhook = TeamsWebhook(teams_webhook)

            display_name = 'User'
            email = ''
            if ctx and ctx.user:
                display_name = getattr(
                    ctx.user, 'display_name', ctx.user.email
                )
                email = ctx.user.email

            # Build notification payload
            tier_emoji = {
                'bronze': '🥉',
                'silver': '🥈',
                'gold': '🥇',
                'platinum': '💎',
                'diamond': '💠'
            }.get(tier, '🏆')

            notification_text = (
                f"{tier_emoji} **Collection Unlocked!** {tier_emoji}\n\n"
                f"**{display_name}** has completed the "
                f"**{collective_name}** collection!\n\n"
            )
            if bonus_points:
                notification_text += (
                    f"🎁 Bonus: **{bonus_points} points** awarded\n\n"
                )
            if message:
                # Simple template rendering
                rendered = message.replace(
                    '{{user.display_name}}', display_name
                ).replace(
                    '{{collective_name}}', collective_name
                )
                notification_text += f"_{rendered}_\n"

            await webhook.send_text_notification(notification_text)
            self.logger.info(
                f"Collection notification sent for user {user_id}: "
                f"{collective_name}"
            )
        except ImportError:
            self.logger.debug(
                "Teams webhook not available for collection notification"
            )
        except Exception as err:
            self.logger.error(
                f"Error sending collection notification: {err}"
            )

    # ---- Static helper for progress queries ----

    @staticmethod
    async def get_user_progress(
        conn,
        user_id: int,
        collective_id: Optional[int] = None
    ) -> list:
        """Get collection progress for a user.

        Args:
            conn: Database connection.
            user_id: The user to query.
            collective_id: Optional specific collection.

        Returns:
            List of progress records.
        """
        query = """
            SELECT * FROM rewards.vw_user_collection_progress
            WHERE user_id = $1
        """
        params = [user_id]
        if collective_id is not None:
            query += " AND collective_id = $2"
            params.append(collective_id)

        query += " ORDER BY progress_pct DESC"
        return await conn.fetch_all(query, *params)

    @staticmethod
    async def get_available_collections(
        conn,
        programs: Optional[list] = None
    ) -> list:
        """Get all active collections, optionally filtered by programs."""
        query = """
            SELECT * FROM rewards.vw_collectives
            WHERE is_active = TRUE
              AND (end_date IS NULL OR end_date > NOW())
        """
        params = []
        if programs:
            query += " AND (programs IS NULL OR programs && $1::varchar[])"
            params.append(programs)

        query += " ORDER BY sort_order, tier DESC, collective_name"
        return await conn.fetch_all(query, *params)