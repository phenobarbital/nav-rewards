"""Collection Computed Rule for NAV-Rewards.

This rule evaluates users who have completed (or are close to completing)
badge collections. It's designed to run as a scheduled ComputedRule via
APScheduler, checking collection progress and awarding bonus rewards.

Usage in rewards.json:
    {
        "reward_id": 9000,
        "reward": "Collection Master",
        "description": "Awarded when a collection is completed",
        "points": 0,
        "reward_type": "Computed Badge",
        "reward_category": "Collections",
        "reward_group": "Collection Rewards",
        "multiple": true,
        "timeframe": "daily",
        "rules": [
            ["CollectionRule", {
                "collective_id": 1,
                "award_bonus_badge": true
            }]
        ],
        "job": {
            "trigger": "cron",
            "cron": {"hour": 8, "minute": 0},
            "id": "collection_check_core_values",
            "name": "Core Values Collection Check"
        }
    }
"""
from typing import Iterable, Optional
from ..env import Environment
from ..models import get_user
from .computed import ComputedRule


class CollectionRule(ComputedRule):
    """CollectionRule.

    Computed rule that evaluates collection completion for users.
    Finds users who have completed all (or enough) badges in a collection
    but haven't yet received the collection bonus.

    Attributes:
    ----------
    collective_id: int: The collection to evaluate (None = evaluate all).
    award_bonus_badge: bool: Whether to also award the bonus_reward_id
        configured on the collection.
    check_seasonal: bool: Whether to include seasonal collections.
    notify_near_complete: bool: Whether to include users who are close
        to completion (>= 75% progress).
    near_complete_threshold: float: Progress percentage to consider
        'near complete' (default 0.75).
    """

    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "CollectionRule"
        self.description = "Evaluates collection completion for users"

        self.collective_id: Optional[int] = kwargs.get('collective_id', None)
        self.award_bonus_badge: bool = kwargs.get('award_bonus_badge', True)
        self.check_seasonal: bool = kwargs.get('check_seasonal', True)
        self.notify_near_complete: bool = kwargs.get(
            'notify_near_complete', False
        )
        self.near_complete_threshold: float = kwargs.get(
            'near_complete_threshold', 0.75
        )

    def fits_computed(self, env: Environment) -> bool:
        """Always fits - collections should be evaluated on schedule."""
        return True

    async def _get_candidates(
        self,
        env: Environment,
        dataset: Optional[Iterable] = None
    ) -> list:
        """
        Find users who have completed collections but haven't been
        awarded the unlock/bonus yet.

        Returns a list of EvalContext objects for each qualifying user,
        with collection metadata in ctx.args.
        """
        candidates = []
        async with await env.connection.acquire() as conn:
            # Build the query based on configuration
            where_clauses = [
                "cp.is_complete = TRUE",
                "cu.collective_id IS NULL",  # Not yet unlocked
                "c.is_active = TRUE"
            ]
            params = []
            param_idx = 0

            if self.collective_id is not None:
                param_idx += 1
                where_clauses.append(f"c.collective_id = ${param_idx}::int")
                params.append(self.collective_id)

            if not self.check_seasonal:
                where_clauses.append("c.is_seasonal = FALSE")

            # Check seasonal date bounds
            where_clauses.append(
                "(c.end_date IS NULL OR c.end_date > NOW())"
            )

            where_sql = " AND ".join(where_clauses)

            query = f"""
                SELECT
                    cp.user_id,
                    c.collective_id,
                    c.collective_name,
                    c.bonus_points,
                    c.bonus_reward_id,
                    c.tier,
                    c.message,
                    c.teams_webhook,
                    c.programs,
                    cp.badges_earned,
                    cp.badges_required,
                    cp.progress_pct,
                    cp.earned_reward_ids,
                    cp.completed_at
                FROM rewards.collectives_progress cp
                JOIN rewards.collectives c USING (collective_id)
                LEFT JOIN rewards.collectives_unlocked cu
                    ON cu.collective_id = cp.collective_id
                    AND cu.user_id = cp.user_id
                WHERE {where_sql}
                ORDER BY cp.completed_at ASC
            """

            rows = await conn.fetch_all(query, *params)
            if not rows:
                return candidates

            # Build EvalContext for each user/collection pair
            for row in rows:
                try:
                    user = await get_user(
                        env.connection,
                        user_id=row['user_id']
                    )
                    if not user:
                        continue

                    ctx = self._get_context_user(user)
                    # Attach collection metadata
                    ctx.args = {
                        'collective_id': row['collective_id'],
                        'collective_name': row['collective_name'],
                        'bonus_points': row['bonus_points'],
                        'bonus_reward_id': row['bonus_reward_id'],
                        'tier': row['tier'],
                        'message': row['message'],
                        'teams_webhook': row['teams_webhook'],
                        'programs': row['programs'],
                        'badges_earned': row['badges_earned'],
                        'badges_required': row['badges_required'],
                        'progress_pct': float(row['progress_pct']),
                        'earned_reward_ids': row['earned_reward_ids'],
                        'completed_at': row['completed_at'],
                    }
                    candidates.append(ctx)
                except Exception as err:
                    self.logger.error(
                        f"CollectionRule: Error building context for "
                        f"user {row['user_id']}: {err}"
                    )

            # Optionally include near-complete users
            if self.notify_near_complete:
                near_candidates = await self._get_near_complete_users(
                    conn, params, param_idx
                )
                candidates.extend(near_candidates)

        return candidates

    async def _get_near_complete_users(
        self,
        conn,
        params: list,
        param_idx: int
    ) -> list:
        """Find users who are close to completing a collection."""
        near_candidates = []
        threshold = self.near_complete_threshold * 100

        near_where = [
            "cp.is_complete = FALSE",
            f"cp.progress_pct >= {threshold}",
            "c.is_active = TRUE",
            "(c.end_date IS NULL OR c.end_date > NOW())"
        ]

        if self.collective_id is not None:
            param_idx += 1
            near_where.append(f"c.collective_id = ${param_idx}::int")

        near_sql = " AND ".join(near_where)

        query = f"""
            SELECT
                cp.user_id,
                c.collective_id,
                c.collective_name,
                cp.badges_earned,
                cp.badges_required,
                cp.progress_pct
            FROM rewards.collectives_progress cp
            JOIN rewards.collectives c USING (collective_id)
            WHERE {near_sql}
            ORDER BY cp.progress_pct DESC
        """

        rows = await conn.fetch_all(query, *params)
        for row in rows:
            try:
                user = await get_user(
                    conn,  # pass conn directly for near-complete
                    user_id=row['user_id']
                )
                if not user:
                    continue
                ctx = self._get_context_user(user)
                ctx.args = {
                    'collective_id': row['collective_id'],
                    'collective_name': row['collective_name'],
                    'badges_earned': row['badges_earned'],
                    'badges_required': row['badges_required'],
                    'progress_pct': float(row['progress_pct']),
                    'near_complete': True,
                }
                near_candidates.append(ctx)
            except Exception as err:
                self.logger.error(
                    f"CollectionRule: Error with near-complete user "
                    f"{row['user_id']}: {err}"
                )

        return near_candidates


class CollectionProgressRule(ComputedRule):
    """CollectionProgressRule.

    Lighter-weight rule that only checks and updates collection progress
    without awarding bonuses. Useful as a background maintenance task.

    Usage:
        ["CollectionProgressRule", {"rebuild": true}]
    """

    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "CollectionProgressRule"
        self.description = "Recalculates collection progress for all users"
        self.rebuild: bool = kwargs.get('rebuild', False)

    def fits_computed(self, env: Environment) -> bool:
        return True

    async def _get_candidates(
        self,
        env: Environment,
        dataset: Optional[Iterable] = None
    ) -> list:
        """
        Recalculate progress for all active collections.
        Returns empty list since this is a maintenance rule.
        """
        async with await env.connection.acquire() as conn:
            if self.rebuild:
                await self._rebuild_all_progress(conn)
            else:
                await self._update_stale_progress(conn)
        return []

    async def _rebuild_all_progress(self, conn) -> None:
        """Rebuild progress for all users across all active collections."""
        self.logger.info(
            "CollectionProgressRule: Rebuilding all collection progress"
        )
        query = """
            INSERT INTO rewards.collectives_progress (
                collective_id, user_id, badges_earned, badges_required,
                progress_pct, is_complete, earned_reward_ids,
                first_badge_at, last_badge_at, updated_at, completed_at
            )
            SELECT
                c.collective_id,
                ur.receiver_user AS user_id,
                COUNT(DISTINCT cr.reward_id) AS badges_earned,
                CASE c.completion_type
                    WHEN 'all' THEN total.cnt
                    ELSE COALESCE(c.required_count, total.cnt)
                END AS badges_required,
                LEAST(
                    (COUNT(DISTINCT cr.reward_id)::DECIMAL /
                     CASE c.completion_type
                         WHEN 'all' THEN total.cnt
                         ELSE COALESCE(c.required_count, total.cnt)
                     END::DECIMAL) * 100,
                    100
                ) AS progress_pct,
                COUNT(DISTINCT cr.reward_id) >=
                    CASE c.completion_type
                        WHEN 'all' THEN total.cnt
                        ELSE COALESCE(c.required_count, total.cnt)
                    END AS is_complete,
                ARRAY_AGG(DISTINCT cr.reward_id) AS earned_reward_ids,
                MIN(ur.awarded_at) AS first_badge_at,
                MAX(ur.awarded_at) AS last_badge_at,
                NOW() AS updated_at,
                CASE
                    WHEN COUNT(DISTINCT cr.reward_id) >=
                        CASE c.completion_type
                            WHEN 'all' THEN total.cnt
                            ELSE COALESCE(c.required_count, total.cnt)
                        END
                    THEN MAX(ur.awarded_at)
                    ELSE NULL
                END AS completed_at
            FROM rewards.collectives c
            JOIN rewards.collectives_rewards cr USING (collective_id)
            JOIN rewards.users_rewards ur
                ON ur.reward_id = cr.reward_id
                AND ur.revoked = FALSE
                AND ur.deleted_at IS NULL
            JOIN LATERAL (
                SELECT COUNT(*) AS cnt
                FROM rewards.collectives_rewards cr2
                WHERE cr2.collective_id = c.collective_id
            ) total ON TRUE
            WHERE c.is_active = TRUE
            GROUP BY c.collective_id, c.completion_type,
                     c.required_count, total.cnt, ur.receiver_user
            ON CONFLICT (collective_id, user_id)
            DO UPDATE SET
                badges_earned = EXCLUDED.badges_earned,
                badges_required = EXCLUDED.badges_required,
                progress_pct = EXCLUDED.progress_pct,
                is_complete = EXCLUDED.is_complete,
                earned_reward_ids = EXCLUDED.earned_reward_ids,
                first_badge_at = EXCLUDED.first_badge_at,
                last_badge_at = EXCLUDED.last_badge_at,
                updated_at = NOW(),
                completed_at = CASE
                    WHEN NOT rewards.collectives_progress.is_complete
                         AND EXCLUDED.is_complete
                    THEN NOW()
                    ELSE rewards.collectives_progress.completed_at
                END
        """
        try:
            await conn.execute(query)
            self.logger.info(
                "CollectionProgressRule: Progress rebuild complete"
            )
        except Exception as err:
            self.logger.error(
                f"CollectionProgressRule: Rebuild failed: {err}"
            )

    async def _update_stale_progress(self, conn) -> None:
        """Update only records that haven't been updated in 24h."""
        self.logger.info(
            "CollectionProgressRule: Updating stale progress records"
        )
        query = """
            UPDATE rewards.collectives_progress cp
            SET updated_at = NOW()
            WHERE cp.updated_at < NOW() - INTERVAL '24 hours'
              AND cp.is_complete = FALSE
        """
        try:
            await conn.execute(query)
        except Exception as err:
            self.logger.error(
                f"CollectionProgressRule: Stale update failed: {err}"
            )