import pandas as pd
from .computed import ComputedRule


class RandomUsers(ComputedRule):
    """RandomUsers.

    Description: Random Users.

    Args:
        ComputedRule (ComputedRule): ComputedRule.

    Returns:
        RandomUsers: a list of Random Users.
    """
    def __init__(
        self,
        conditions: dict = None,
        **kwargs
    ) -> None:
        super().__init__(conditions, **kwargs)
        self.name = "Random Users"
        self.count = kwargs.get('count', 1)
        self.filters = kwargs.get('filters', {})
        self.weights = kwargs.get('weights', {})
        self.exclude_recent_winners = kwargs.get(
            'exclude_recent_winners',
            False
        )
        self.recent_winner_days = kwargs.get(
            'recent_winner_days',
            7
        )
        self.current_reward_id = kwargs.get('current_reward_id', None)

    async def _get_candidates(
        self,
        env,
        dataset=None
    ) -> list:
        """
        Get random candidates with optional filtering and weighting.
        Check if the current context and environment match the rule.

        :param ctx: The evaluation context, containing user and session
            information.
        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        async with await env.connection.acquire() as conn:
            # Build base query
            where_conditions = ["u.is_active = true"]  # Only active users
            params = []
            param_count = 0

            # Apply filters
            if self.filters:
                if 'departments' in self.filters:
                    param_count += 1
                    where_conditions.append(
                        f"u.department = ANY(${param_count})"
                    )
                    params.append(self.filters['departments'])

                if 'job_codes' in self.filters:
                    param_count += 1
                    where_conditions.append(
                        f"u.job_code = ANY(${param_count})"
                    )
                    params.append(self.filters['job_codes'])

                if 'min_tenure_days' in self.filters:
                    param_count += 1
                    where_conditions.append(
                        f"(CURRENT_DATE - u.start_date) >= ${param_count}"
                    )
                    params.append(self.filters['min_tenure_days'])

            # Exclude recent winners if configured
            if self.exclude_recent_winners and self.current_reward_id:
                param_count += 1
                where_conditions.append(
                    f"""
                    u.user_id NOT IN (
                        SELECT DISTINCT receiver_user
                        FROM rewards.users_rewards
                        WHERE reward_id = ${param_count - 1}
                        AND awarded_at >= CURRENT_DATE - INTERVAL '${param_count} days'
                    )
                """  # noqa
                )
                params.extend(
                    [self.current_reward_id, self.recent_winner_days]
                )

            # Build final query
            where_clause = " AND ".join(where_conditions)
            # Add weighting logic

            weight_column = "1.0"  # Default equal weight
            if self.weights:
                weight_conditions = []
                if 'department_weights' in self.weights:
                    weight_conditions.extend(
                        f"WHEN u.department = '{dept}' THEN {weight}"
                        for dept, weight in self.weights[
                            'department_weights'
                        ].items()
                    )

                if 'tenure_weights' in self.weights:
                    # Weight by tenure: longer tenure = higher weight
                    tenure_weights = self.weights['tenure_weights']
                    weight_conditions.extend(
                        f"WHEN (CURRENT_DATE - u.start_date) >= {min_days} THEN {weight}"  # noqa
                        for min_days, weight in tenure_weights.items()
                    )

                if weight_conditions:
                    weight_column = f"""
                        CASE
                        {' '.join(weight_conditions)}
                        ELSE 1.0
                        END
                    """
            query = f"""
                WITH weighted_users AS (
                    SELECT u.user_id, {weight_column} as weight
                    FROM auth.users u
                    WHERE {where_clause}
                ),
                random_weights AS (
                    SELECT user_id, weight, random() * weight as random_weight
                    FROM weighted_users
                )
                SELECT user_id
                FROM random_weights
                ORDER BY random_weight DESC
                LIMIT {self.count}
            """
            try:
                result = await conn.fetch_all(query)
                df = self.get_dataframe(result)
                # Log exclusion information for debugging
                if self.exclude_recent_winners and self.current_reward_id:
                    excluded_count = await self._count_excluded_users(conn)
                    self.logger.info(
                        f"Excluded {excluded_count} recent winners of reward {self.current_reward_id} "  # noqa
                        f"from last {self.recent_winner_days} days"
                    )
                return df
            except Exception as exc:
                self.logger.error(
                    f"Error fetching random candidates: {exc}"
                )
                return pd.DataFrame()

    async def _count_excluded_users(self, conn) -> int:
        """Count how many users were excluded as recent winners."""
        if not self.exclude_recent_winners or not self.current_reward_id:
            return 0

        try:
            query = """
                SELECT COUNT(DISTINCT receiver_user)
                FROM rewards.users_rewards
                WHERE reward_id = $1
                AND awarded_at >= CURRENT_DATE - INTERVAL '%s days'
            """ % self.recent_winner_days

            count = await conn.fetchval(query, self.current_reward_id)
            return count or 0

        except Exception:
            return 0
