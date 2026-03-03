"""Collection Handlers for NAV-Rewards.

REST API handlers for the Collections system, following the established
BaseHandler / FormModel patterns from the existing codebase.

Endpoints:
    GET  /collections/api/v1/collections          - List all active collections
    GET  /collections/api/v1/collections/{id}      - Get collection details
    GET  /collections/api/v1/collections/{id}/badges - Badges in a collection
    GET  /collections/api/v1/progress/user/{id}    - User's collection progress
    GET  /collections/api/v1/progress/user/{id}/{cid} - Progress for specific collection
    GET  /collections/api/v1/leaderboard           - Collection completion leaderboard
    GET  /collections/api/v1/leaderboard/{id}      - Leaderboard for specific collection
    GET  /collections/api/v1/completions/recent     - Recent collection completions
"""
from aiohttp import web
from navigator.views import BaseHandler
from ..models.rewards import (
    Collective
)
from .service import CollectiveService


class CollectiveListHandler(BaseHandler):
    """Handler for listing and retrieving collections."""

    model = Collective

    async def get_collections(self, request: web.Request) -> web.Response:
        """List all active collections with badge counts and details."""
        try:
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            # Optional program filter from query params
            programs = request.query.getall('program', None)

            async with await reward_engine.connection.acquire() as conn:
                collections = await CollectiveService.get_available_collections(
                    conn, programs=programs
                )
                return self.json_response(
                    [dict(c) for c in collections]
                )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_collection(self, request: web.Request) -> web.Response:
        """Get a specific collection with full details."""
        try:
            collection_id = int(request.match_info['id'])
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_collectives
                    WHERE collective_id = $1
                """
                collection = await conn.fetch_one(query, collection_id)
                if not collection:
                    return self.json_response(
                        {'error': 'Collection not found'}, status=404
                    )
                return self.json_response(dict(collection))
        except ValueError:
            return self.json_response(
                {'error': 'Invalid collection ID'}, status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_collection_badges(
        self, request: web.Request
    ) -> web.Response:
        """Get all badges in a collection with their details."""
        try:
            collection_id = int(request.match_info['id'])
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT r.reward_id, r.reward, r.description,
                           r.points, r.icon, r.reward_type,
                           r.reward_category, r.reward_group
                    FROM rewards.collectives_rewards cr
                    JOIN rewards.rewards r USING (reward_id)
                    WHERE cr.collective_id = $1
                    ORDER BY r.reward
                """
                badges = await conn.fetch_all(query, collection_id)
                return self.json_response(
                    [dict(b) for b in badges]
                )
        except ValueError:
            return self.json_response(
                {'error': 'Invalid collection ID'}, status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)


class CollectionProgressHandler(BaseHandler):
    """Handler for user collection progress."""

    async def get_user_progress(
        self, request: web.Request
    ) -> web.Response:
        """Get all collection progress for a user."""
        try:
            user_id = int(request.match_info['user_id'])
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                progress = await CollectiveService.get_user_progress(
                    conn, user_id
                )
                result = []
                for p in progress:
                    row = dict(p)
                    # Add missing badges info
                    if not row.get('is_complete'):
                        missing = await self._get_missing_badges(
                            conn, row['collective_id'], user_id
                        )
                        row['missing_badges'] = missing
                    result.append(row)
                return self.json_response(result)
        except ValueError:
            return self.json_response(
                {'error': 'Invalid user ID'}, status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_user_collection_progress(
        self, request: web.Request
    ) -> web.Response:
        """Get progress for a specific collection and user."""
        try:
            user_id = int(request.match_info['user_id'])
            collection_id = int(request.match_info['collection_id'])
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                progress = await CollectiveService.get_user_progress(
                    conn, user_id, collection_id
                )
                if not progress:
                    # Return empty progress for collections not started
                    collection = await conn.fetch_one(
                        "SELECT * FROM rewards.vw_collectives WHERE collective_id = $1",
                        collection_id
                    )
                    if not collection:
                        return self.json_response(
                            {'error': 'Collection not found'}, status=404
                        )
                    return self.json_response({
                        'collective_id': collection_id,
                        'collective_name': collection['collective_name'],
                        'badges_earned': 0,
                        'badges_required': collection['badges_to_complete'],
                        'progress_pct': 0.0,
                        'is_complete': False,
                        'missing_badges': await self._get_missing_badges(
                            conn, collection_id, user_id
                        )
                    })

                row = dict(progress[0])
                if not row.get('is_complete'):
                    row['missing_badges'] = await self._get_missing_badges(
                        conn, collection_id, user_id
                    )
                return self.json_response(row)
        except ValueError:
            return self.json_response(
                {'error': 'Invalid ID parameter'}, status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    @staticmethod
    async def _get_missing_badges(
        conn, collective_id: int, user_id: int
    ) -> list:
        """Get badges the user is missing from a collection."""
        query = """
            SELECT r.reward_id, r.reward, r.description, r.icon, r.points
            FROM rewards.collectives_rewards cr
            JOIN rewards.rewards r USING (reward_id)
            WHERE cr.collective_id = $1
              AND cr.reward_id NOT IN (
                  SELECT ur.reward_id
                  FROM rewards.users_rewards ur
                  WHERE ur.receiver_user = $2
                    AND ur.revoked = FALSE
                    AND ur.deleted_at IS NULL
                    AND ur.reward_id IN (
                        SELECT reward_id
                        FROM rewards.collectives_rewards
                        WHERE collective_id = $1
                    )
              )
            ORDER BY r.reward
        """
        rows = await conn.fetch_all(query, collective_id, user_id)
        return [dict(r) for r in rows]


class CollectionLeaderboardHandler(BaseHandler):
    """Handler for collection leaderboard."""

    async def get_leaderboard(self, request: web.Request) -> web.Response:
        """Get leaderboard of users with most completed collections."""
        try:
            limit = int(request.query.get('limit', 20))
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT
                        cu.user_id,
                        u.email,
                        u.display_name,
                        COUNT(cu.collective_id) AS collections_completed,
                        SUM(COALESCE(cu.bonus_points_awarded, 0))
                            AS total_bonus_points,
                        MAX(cu.unlocked_at) AS last_completed_at,
                        ARRAY_AGG(c.collective_name
                            ORDER BY cu.unlocked_at DESC) AS collection_names
                    FROM rewards.collectives_unlocked cu
                    JOIN auth.users u USING (user_id)
                    JOIN rewards.collectives c USING (collective_id)
                    WHERE c.is_active = TRUE
                    GROUP BY cu.user_id, u.email, u.display_name
                    ORDER BY collections_completed DESC,
                             total_bonus_points DESC
                    LIMIT $1
                """
                leaderboard = await conn.fetch_all(query, limit)
                return self.json_response(
                    [dict(r) for r in leaderboard]
                )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_collection_leaderboard(
        self, request: web.Request
    ) -> web.Response:
        """Get completion times for a specific collection."""
        try:
            collection_id = int(request.match_info['id'])
            limit = int(request.query.get('limit', 20))
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT
                        cu.user_id,
                        u.email,
                        u.display_name,
                        cu.unlocked_at,
                        cu.bonus_points_awarded,
                        cp.first_badge_at,
                        cp.last_badge_at,
                        EXTRACT(EPOCH FROM (cp.last_badge_at - cp.first_badge_at))
                            AS completion_seconds
                    FROM rewards.collectives_unlocked cu
                    JOIN auth.users u USING (user_id)
                    LEFT JOIN rewards.collectives_progress cp
                        ON cp.collective_id = cu.collective_id
                        AND cp.user_id = cu.user_id
                    WHERE cu.collective_id = $1
                    ORDER BY cu.unlocked_at ASC
                    LIMIT $2
                """
                results = await conn.fetch_all(query, collection_id, limit)
                return self.json_response(
                    [dict(r) for r in results]
                )
        except ValueError:
            return self.json_response(
                {'error': 'Invalid collection ID'}, status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)


class CollectionCompletionHandler(BaseHandler):
    """Handler for recent collection completions (activity feed)."""

    async def get_recent_completions(
        self, request: web.Request
    ) -> web.Response:
        """Get recent collection completions across all users."""
        try:
            days = int(request.query.get('days', 30))
            limit = int(request.query.get('limit', 50))
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'}, status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                query = f"""
SELECT
    cl.log_id,
    cl.collective_id,
    c.collective_name,
    c.tier,
    c.icon,
    cl.user_id,
    u.email,
    u.display_name,
    cl.bonus_points_awarded,
    cl.completed_at
FROM rewards.collectives_completion_log cl
JOIN rewards.collectives c USING (collective_id)
JOIN auth.users u USING (user_id)
WHERE cl.completed_at > NOW() - INTERVAL '{days} days'
ORDER BY cl.completed_at DESC
LIMIT {days}
                """
                results = await conn.fetch_all(query, limit)
                return self.json_response(
                    [dict(r) for r in results]
                )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)


def setup_collection(app: web.Application):
    """Register collection API routes with the aiohttp app.

    Call this from your RewardsEngine setup or app configuration.

    Example:
        from rewards.collections.handlers import setup_collection
        setup_collection(app)
    """
    # Collection listings
    collection_list = CollectiveListHandler()
    app.router.add_get(
        '/collections/api/v1/collections',
        collection_list.get_collections
    )
    app.router.add_get(
        '/collections/api/v1/collections/{id}',
        collection_list.get_collection
    )
    app.router.add_get(
        '/collections/api/v1/collections/{id}/badges',
        collection_list.get_collection_badges
    )

    # User progress
    progress = CollectionProgressHandler()
    app.router.add_get(
        '/collections/api/v1/progress/user/{user_id}',
        progress.get_user_progress
    )
    app.router.add_get(
        '/collections/api/v1/progress/user/{user_id}/{collection_id}',
        progress.get_user_collection_progress
    )

    # Leaderboard
    leaderboard = CollectionLeaderboardHandler()
    app.router.add_get(
        '/collections/api/v1/leaderboard',
        leaderboard.get_leaderboard
    )
    app.router.add_get(
        '/collections/api/v1/leaderboard/{id}',
        leaderboard.get_collection_leaderboard
    )

    # Activity feed
    completions = CollectionCompletionHandler()
    app.router.add_get(
        '/collections/api/v1/completions/recent',
        completions.get_recent_completions
    )