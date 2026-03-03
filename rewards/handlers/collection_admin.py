"""
Collection Admin Handler for NAV-Rewards.

Administrative REST API handlers for managing Collections (collectives) and their
badge associations. All endpoints require admin authorization.

Endpoints:
    POST   /rewards/api/v1/admin/collections           - Create collection with badges
    GET    /rewards/api/v1/admin/collections           - List all collections (admin view)
    PUT    /rewards/api/v1/admin/collections/{id}      - Update collection
    DELETE /rewards/api/v1/admin/collections/{id}      - Soft-delete collection
    POST   /rewards/api/v1/admin/collections/{id}/badges     - Add badges
    DELETE /rewards/api/v1/admin/collections/{id}/badges     - Remove badges
    POST   /rewards/api/v1/admin/collections/{id}/recalculate - Force progress recalculation
"""
from typing import Optional, List, Any
from datetime import datetime
from aiohttp import web
from navigator_session import get_session
from navigator.views import BaseHandler
from navconfig.logging import logging

from ..models.rewards import Collective


# Valid tier values
VALID_TIERS = ('bronze', 'silver', 'gold', 'platinum', 'diamond')

# Valid completion types
VALID_COMPLETION_TYPES = ('all', 'n_of_m', 'any_n')


class CollectionAdminHandler(BaseHandler):
    """Handler for administrative collection (collective) management.

    All endpoints require admin authorization (admin or rewards_admin group).
    """

    model = Collective

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def _is_admin(self, user: dict) -> bool:
        """Check if user has admin privileges.

        Args:
            user: User dict from session containing 'groups' list.

        Returns:
            True if user is in 'admin' or 'rewards_admin' group.
        """
        groups = user.get('groups', [])
        return 'admin' in groups or 'rewards_admin' in groups

    async def _get_user_session(self, request: web.Request) -> tuple:
        """Get user session and validate admin access.

        Args:
            request: aiohttp request object.

        Returns:
            Tuple of (session, user_dict).

        Raises:
            web.HTTPForbidden: If user is not an admin.
        """
        session = await get_session(request, new=False)
        user = session.decode('user')

        if not self._is_admin(user):
            raise web.HTTPForbidden(
                text='{"error": "Admin access required"}',
                content_type='application/json'
            )

        return session, user

    async def _validate_badge_ids(
        self,
        conn,
        badge_ids: List[int]
    ) -> tuple[bool, str, List[dict]]:
        """Validate that all badge_ids exist in rewards table.

        Args:
            conn: Database connection.
            badge_ids: List of reward IDs to validate.

        Returns:
            Tuple of (is_valid, error_message, badge_details).
        """
        if not badge_ids:
            return False, "badge_ids is required and must be non-empty", []

        # Check all badges exist
        query = """
            SELECT reward_id, reward FROM rewards.rewards
            WHERE reward_id = ANY($1::int[])
        """
        found_badges = await conn.fetch_all(query, badge_ids)
        found_ids = {b['reward_id'] for b in found_badges}

        missing = set(badge_ids) - found_ids
        if missing:
            return False, f"Badge IDs not found: {sorted(missing)}", []

        return True, "", [dict(b) for b in found_badges]

    async def _validate_bonus_reward(
        self,
        conn,
        bonus_reward_id: Optional[int]
    ) -> tuple[bool, str]:
        """Validate bonus_reward_id exists if provided.

        Args:
            conn: Database connection.
            bonus_reward_id: Optional reward ID for bonus.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if bonus_reward_id is None:
            return True, ""

        query = "SELECT 1 FROM rewards.rewards WHERE reward_id = $1"
        exists = await conn.fetch_one(query, bonus_reward_id)
        if not exists:
            return False, f"bonus_reward_id {bonus_reward_id} not found"

        return True, ""

    def _validate_completion_type(
        self,
        completion_type: str,
        required_count: Optional[int],
        badge_count: int
    ) -> tuple[bool, str]:
        """Validate completion_type and required_count relationship.

        Args:
            completion_type: Type of completion ('all', 'n_of_m', 'any_n').
            required_count: Required badge count for n_of_m/any_n.
            badge_count: Total number of badges in collection.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if completion_type not in VALID_COMPLETION_TYPES:
            return False, f"completion_type must be one of: {VALID_COMPLETION_TYPES}"

        if completion_type in ('n_of_m', 'any_n'):
            if required_count is None or required_count <= 0:
                return False, f"required_count is required for completion_type '{completion_type}'"
            if required_count > badge_count:
                return False, f"required_count ({required_count}) cannot exceed badge count ({badge_count})"

        return True, ""

    def _validate_seasonal(
        self,
        is_seasonal: bool,
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> tuple[bool, str]:
        """Validate seasonal date requirements.

        Args:
            is_seasonal: Whether collection is seasonal.
            start_date: Start date string (ISO format).
            end_date: End date string (ISO format).

        Returns:
            Tuple of (is_valid, error_message).
        """
        if not is_seasonal:
            return True, ""

        if not start_date or not end_date:
            return False, "start_date and end_date required when is_seasonal is true"

        try:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if end <= start:
                return False, "end_date must be after start_date"
        except (ValueError, AttributeError) as e:
            return False, f"Invalid date format: {e}"

        return True, ""

    def _validate_tier(self, tier: str) -> tuple[bool, str]:
        """Validate tier value.

        Args:
            tier: Tier string to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if tier not in VALID_TIERS:
            return False, f"tier must be one of: {VALID_TIERS}"
        return True, ""

    async def create_collection(self, request: web.Request) -> web.Response:
        """Create a new collection with badges in a single transaction.

        POST /rewards/api/v1/admin/collections

        Request Body:
            collective_name: str (required) - Collection name
            badge_ids: List[int] (required) - Badge IDs to include
            description: str - Collection description
            points: int - Base points (default 50)
            bonus_points: int - Bonus points on completion (default 0)
            completion_type: str - 'all', 'n_of_m', 'any_n' (default 'all')
            required_count: int - Required for n_of_m/any_n
            bonus_reward_id: int - Bonus badge on completion
            tier: str - bronze/silver/gold/platinum/diamond (default 'bronze')
            icon: str - Icon URL
            message: str - Completion message
            is_seasonal: bool - Seasonal collection flag
            start_date: str - Season start (ISO format)
            end_date: str - Season end (ISO format)
            programs: List[str] - Associated programs
            teams_webhook: str - MS Teams webhook URL
            sort_order: int - Display order

        Returns:
            201: Created collection with badge details
            400: Validation error
            403: Not authorized
        """
        try:
            await self._get_user_session(request)
            data = await request.json()

            # Required fields
            collective_name = data.get('collective_name')
            badge_ids = data.get('badge_ids', [])

            if not collective_name:
                return self.json_response(
                    {'error': 'collective_name is required'},
                    status=400
                )

            if not badge_ids or not isinstance(badge_ids, list):
                return self.json_response(
                    {'error': 'badge_ids is required and must be a non-empty list'},
                    status=400
                )

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Validate badge_ids
                valid, error, badge_details = await self._validate_badge_ids(
                    conn, badge_ids
                )
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Validate bonus_reward_id
                bonus_reward_id = data.get('bonus_reward_id')
                valid, error = await self._validate_bonus_reward(conn, bonus_reward_id)
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Validate completion_type
                completion_type = data.get('completion_type', 'all')
                required_count = data.get('required_count')
                valid, error = self._validate_completion_type(
                    completion_type, required_count, len(badge_ids)
                )
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Validate tier
                tier = data.get('tier', 'bronze')
                valid, error = self._validate_tier(tier)
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Validate seasonal dates
                is_seasonal = data.get('is_seasonal', False)
                valid, error = self._validate_seasonal(
                    is_seasonal, data.get('start_date'), data.get('end_date')
                )
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Check unique name
                name_check = await conn.fetch_one(
                    "SELECT 1 FROM rewards.collectives WHERE collective_name = $1",
                    collective_name
                )
                if name_check:
                    return self.json_response(
                        {'error': f"Collection name '{collective_name}' already exists"},
                        status=400
                    )

                # Begin transaction
                async with conn.transaction():
                    # Insert collective
                    insert_query = """
                        INSERT INTO rewards.collectives (
                            collective_name, description, points, bonus_points,
                            completion_type, required_count, bonus_reward_id,
                            tier, icon, message, is_seasonal, start_date, end_date,
                            programs, teams_webhook, sort_order, is_active, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, $15, $16, TRUE, NOW()
                        )
                        RETURNING collective_id
                    """

                    # Parse dates if provided
                    start_date = None
                    end_date = None
                    if data.get('start_date'):
                        start_date = datetime.fromisoformat(
                            data['start_date'].replace('Z', '+00:00')
                        )
                    if data.get('end_date'):
                        end_date = datetime.fromisoformat(
                            data['end_date'].replace('Z', '+00:00')
                        )

                    result = await conn.fetch_one(
                        insert_query,
                        collective_name,
                        data.get('description', ''),
                        data.get('points', 50),
                        data.get('bonus_points', 0),
                        completion_type,
                        required_count if completion_type != 'all' else None,
                        bonus_reward_id,
                        tier,
                        data.get('icon', ''),
                        data.get('message', ''),
                        is_seasonal,
                        start_date,
                        end_date,
                        data.get('programs', []),
                        data.get('teams_webhook', ''),
                        data.get('sort_order', 0)
                    )

                    collective_id = result['collective_id']

                    # Insert badge associations
                    badge_insert = """
                        INSERT INTO rewards.collectives_rewards (
                            collective_id, reward_id, created_at
                        ) VALUES ($1, $2, NOW())
                    """
                    for badge_id in badge_ids:
                        await conn.execute(badge_insert, collective_id, badge_id)

                # Calculate badges_to_complete
                badges_to_complete = (
                    required_count if completion_type != 'all' else len(badge_ids)
                )

                return self.json_response({
                    'collective_id': collective_id,
                    'collective_name': collective_name,
                    'completion_type': completion_type,
                    'tier': tier,
                    'badges': badge_details,
                    'total_badges': len(badge_ids),
                    'badges_to_complete': badges_to_complete,
                    'message': 'Collection created successfully'
                }, status=201)

        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error creating collection: {err}")
            return self.json_response({'error': str(err)}, status=500)

    async def update_collection(self, request: web.Request) -> web.Response:
        """Update an existing collection's metadata and/or badges.

        PUT /rewards/api/v1/admin/collections/{id}

        Request Body (all optional):
            collective_name: str - New name
            description: str - New description
            points: int - Base points
            bonus_points: int - Bonus points
            completion_type: str - Completion type
            required_count: int - Required badges
            tier: str - Collection tier
            icon: str - Icon URL
            message: str - Completion message
            is_active: bool - Active status
            is_seasonal: bool - Seasonal flag
            start_date: str - Season start
            end_date: str - Season end
            programs: List[str] - Programs
            teams_webhook: str - Webhook URL
            sort_order: int - Display order
            badge_ids: List[int] - Replace all badges

        Returns:
            200: Updated collection
            400: Validation error
            404: Collection not found
            403: Not authorized
        """
        try:
            await self._get_user_session(request)
            collection_id = int(request.match_info['id'])
            data = await request.json()

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Check collection exists
                existing = await conn.fetch_one(
                    "SELECT * FROM rewards.collectives WHERE collective_id = $1",
                    collection_id
                )
                if not existing:
                    return self.json_response(
                        {'error': 'Collection not found'},
                        status=404
                    )

                # Validate badge_ids if provided
                badge_ids = data.get('badge_ids')
                badge_details = []
                if badge_ids is not None:
                    if not isinstance(badge_ids, list) or len(badge_ids) == 0:
                        return self.json_response(
                            {'error': 'badge_ids must be a non-empty list'},
                            status=400
                        )
                    valid, error, badge_details = await self._validate_badge_ids(
                        conn, badge_ids
                    )
                    if not valid:
                        return self.json_response({'error': error}, status=400)

                # Validate completion_type if provided or if badges change
                completion_type = data.get('completion_type', existing['completion_type'])
                required_count = data.get('required_count', existing['required_count'])
                badge_count = len(badge_ids) if badge_ids else await self._get_badge_count(
                    conn, collection_id
                )
                valid, error = self._validate_completion_type(
                    completion_type, required_count, badge_count
                )
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Validate tier if provided
                if 'tier' in data:
                    valid, error = self._validate_tier(data['tier'])
                    if not valid:
                        return self.json_response({'error': error}, status=400)

                # Validate seasonal if provided
                is_seasonal = data.get('is_seasonal', existing['is_seasonal'])
                if is_seasonal:
                    start = data.get('start_date') or (
                        existing['start_date'].isoformat() if existing['start_date'] else None
                    )
                    end = data.get('end_date') or (
                        existing['end_date'].isoformat() if existing['end_date'] else None
                    )
                    valid, error = self._validate_seasonal(is_seasonal, start, end)
                    if not valid:
                        return self.json_response({'error': error}, status=400)

                # Validate unique name if changing
                if 'collective_name' in data and data['collective_name'] != existing['collective_name']:
                    name_check = await conn.fetch_one(
                        "SELECT 1 FROM rewards.collectives WHERE collective_name = $1 AND collective_id != $2",
                        data['collective_name'], collection_id
                    )
                    if name_check:
                        return self.json_response(
                            {'error': f"Collection name '{data['collective_name']}' already exists"},
                            status=400
                        )

                # Build update query dynamically
                update_fields = []
                params = []
                param_idx = 1

                updateable_fields = [
                    'collective_name', 'description', 'points', 'bonus_points',
                    'completion_type', 'required_count', 'bonus_reward_id',
                    'tier', 'icon', 'message', 'is_active', 'is_seasonal',
                    'programs', 'teams_webhook', 'sort_order'
                ]

                for field in updateable_fields:
                    if field in data:
                        update_fields.append(f"{field} = ${param_idx}")
                        params.append(data[field])
                        param_idx += 1

                # Handle date fields
                if 'start_date' in data:
                    start_date = datetime.fromisoformat(
                        data['start_date'].replace('Z', '+00:00')
                    ) if data['start_date'] else None
                    update_fields.append(f"start_date = ${param_idx}")
                    params.append(start_date)
                    param_idx += 1

                if 'end_date' in data:
                    end_date = datetime.fromisoformat(
                        data['end_date'].replace('Z', '+00:00')
                    ) if data['end_date'] else None
                    update_fields.append(f"end_date = ${param_idx}")
                    params.append(end_date)
                    param_idx += 1

                # Always update updated_at
                update_fields.append(f"updated_at = ${param_idx}")
                params.append(datetime.now())
                param_idx += 1

                params.append(collection_id)

                async with conn.transaction():
                    # Update collection metadata
                    if update_fields:
                        update_query = f"""
                            UPDATE rewards.collectives
                            SET {', '.join(update_fields)}
                            WHERE collective_id = ${param_idx}
                        """
                        await conn.execute(update_query, *params)

                    # Replace badges if provided
                    if badge_ids is not None:
                        # Log warning if users have progress
                        progress_check = await conn.fetch_one(
                            """SELECT COUNT(*) as cnt FROM rewards.collectives_progress
                               WHERE collective_id = $1 AND badges_earned > 0""",
                            collection_id
                        )
                        if progress_check and progress_check['cnt'] > 0:
                            self.logger.warning(
                                f"Updating badges for collection {collection_id} "
                                f"which has {progress_check['cnt']} users with progress"
                            )

                        # Delete existing badge associations
                        await conn.execute(
                            "DELETE FROM rewards.collectives_rewards WHERE collective_id = $1",
                            collection_id
                        )

                        # Insert new badges
                        for badge_id in badge_ids:
                            await conn.execute(
                                """INSERT INTO rewards.collectives_rewards
                                   (collective_id, reward_id, created_at)
                                   VALUES ($1, $2, NOW())""",
                                collection_id, badge_id
                            )

                # Get updated collection
                updated = await conn.fetch_one(
                    "SELECT * FROM rewards.vw_collectives WHERE collective_id = $1",
                    collection_id
                )

                return self.json_response({
                    **dict(updated),
                    'message': 'Collection updated successfully'
                })

        except ValueError:
            return self.json_response({'error': 'Invalid collection ID'}, status=400)
        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error updating collection: {err}")
            return self.json_response({'error': str(err)}, status=500)

    async def _get_badge_count(self, conn, collection_id: int) -> int:
        """Get count of badges in a collection."""
        result = await conn.fetch_one(
            "SELECT COUNT(*) as cnt FROM rewards.collectives_rewards WHERE collective_id = $1",
            collection_id
        )
        return result['cnt'] if result else 0

    async def delete_collection(self, request: web.Request) -> web.Response:
        """Soft-delete a collection by setting is_active=False.

        DELETE /rewards/api/v1/admin/collections/{id}

        Returns:
            200: Collection deactivated
            404: Collection not found
            403: Not authorized
        """
        try:
            await self._get_user_session(request)
            collection_id = int(request.match_info['id'])

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Check collection exists
                existing = await conn.fetch_one(
                    "SELECT collective_name FROM rewards.collectives WHERE collective_id = $1",
                    collection_id
                )
                if not existing:
                    return self.json_response(
                        {'error': 'Collection not found'},
                        status=404
                    )

                # Get count of users with progress
                progress_count = await conn.fetch_one(
                    """SELECT COUNT(DISTINCT user_id) as cnt
                       FROM rewards.collectives_progress
                       WHERE collective_id = $1 AND badges_earned > 0""",
                    collection_id
                )

                # Soft delete
                await conn.execute(
                    """UPDATE rewards.collectives
                       SET is_active = FALSE, updated_at = NOW()
                       WHERE collective_id = $1""",
                    collection_id
                )

                return self.json_response({
                    'collective_id': collection_id,
                    'message': 'Collection deactivated',
                    'users_with_progress': progress_count['cnt'] if progress_count else 0
                })

        except ValueError:
            return self.json_response({'error': 'Invalid collection ID'}, status=400)
        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error deleting collection: {err}")
            return self.json_response({'error': str(err)}, status=500)

    async def add_badges(self, request: web.Request) -> web.Response:
        """Add badges to an existing collection without replacing existing ones.

        POST /rewards/api/v1/admin/collections/{id}/badges

        Request Body:
            badge_ids: List[int] - Badge IDs to add

        Returns:
            200: Updated badge list
            400: Validation error
            404: Collection not found
            403: Not authorized
        """
        try:
            await self._get_user_session(request)
            collection_id = int(request.match_info['id'])
            data = await request.json()

            badge_ids = data.get('badge_ids', [])
            if not badge_ids or not isinstance(badge_ids, list):
                return self.json_response(
                    {'error': 'badge_ids is required and must be a non-empty list'},
                    status=400
                )

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Check collection exists
                existing = await conn.fetch_one(
                    "SELECT collective_id FROM rewards.collectives WHERE collective_id = $1",
                    collection_id
                )
                if not existing:
                    return self.json_response(
                        {'error': 'Collection not found'},
                        status=404
                    )

                # Validate badge_ids
                valid, error, _ = await self._validate_badge_ids(conn, badge_ids)
                if not valid:
                    return self.json_response({'error': error}, status=400)

                # Insert badges with ON CONFLICT DO NOTHING
                added_count = 0
                for badge_id in badge_ids:
                    result = await conn.execute(
                        """INSERT INTO rewards.collectives_rewards
                           (collective_id, reward_id, created_at)
                           VALUES ($1, $2, NOW())
                           ON CONFLICT (collective_id, reward_id) DO NOTHING""",
                        collection_id, badge_id
                    )
                    if result and 'INSERT' in str(result):
                        added_count += 1

                # Update badges_required in progress records
                new_badge_count = await self._get_badge_count(conn, collection_id)
                await conn.execute(
                    """UPDATE rewards.collectives_progress
                       SET badges_required = $2
                       WHERE collective_id = $1
                         AND is_complete = FALSE""",
                    collection_id, new_badge_count
                )

                # Get updated badge list
                badges = await conn.fetch_all(
                    """SELECT r.reward_id, r.reward, r.description, r.icon
                       FROM rewards.collectives_rewards cr
                       JOIN rewards.rewards r USING (reward_id)
                       WHERE cr.collective_id = $1
                       ORDER BY r.reward""",
                    collection_id
                )

                return self.json_response({
                    'collective_id': collection_id,
                    'badges_added': added_count,
                    'total_badges': len(badges),
                    'badges': [dict(b) for b in badges],
                    'message': f'{added_count} badge(s) added to collection'
                })

        except ValueError:
            return self.json_response({'error': 'Invalid collection ID'}, status=400)
        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error adding badges: {err}")
            return self.json_response({'error': str(err)}, status=500)

    async def remove_badges(self, request: web.Request) -> web.Response:
        """Remove badges from a collection.

        DELETE /rewards/api/v1/admin/collections/{id}/badges

        Request Body:
            badge_ids: List[int] - Badge IDs to remove

        Returns:
            200: Updated badge list
            400: Validation error / Would leave collection empty
            404: Collection not found
            403: Not authorized
        """
        try:
            await self._get_user_session(request)
            collection_id = int(request.match_info['id'])
            data = await request.json()

            badge_ids = data.get('badge_ids', [])
            if not badge_ids or not isinstance(badge_ids, list):
                return self.json_response(
                    {'error': 'badge_ids is required and must be a non-empty list'},
                    status=400
                )

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Check collection exists
                existing = await conn.fetch_one(
                    "SELECT collective_id FROM rewards.collectives WHERE collective_id = $1",
                    collection_id
                )
                if not existing:
                    return self.json_response(
                        {'error': 'Collection not found'},
                        status=404
                    )

                # Check if removal would leave collection empty
                current_count = await self._get_badge_count(conn, collection_id)
                if current_count <= len(badge_ids):
                    # Verify which badges actually exist in collection
                    existing_badges = await conn.fetch_all(
                        """SELECT reward_id FROM rewards.collectives_rewards
                           WHERE collective_id = $1 AND reward_id = ANY($2::int[])""",
                        collection_id, badge_ids
                    )
                    if len(existing_badges) >= current_count:
                        return self.json_response(
                            {'error': 'Cannot remove all badges from collection'},
                            status=400
                        )

                # Remove badges
                result = await conn.execute(
                    """DELETE FROM rewards.collectives_rewards
                       WHERE collective_id = $1 AND reward_id = ANY($2::int[])""",
                    collection_id, badge_ids
                )

                # Update badges_required and recalculate progress
                new_badge_count = await self._get_badge_count(conn, collection_id)

                # Get collection completion type
                collection = await conn.fetch_one(
                    "SELECT completion_type, required_count FROM rewards.collectives WHERE collective_id = $1",
                    collection_id
                )

                # Calculate new badges_required
                badges_required = (
                    collection['required_count']
                    if collection['completion_type'] != 'all' and collection['required_count']
                    else new_badge_count
                )

                # Recalculate progress for affected users
                await conn.execute(
                    """UPDATE rewards.collectives_progress cp
                       SET badges_required = $2,
                           badges_earned = (
                               SELECT COUNT(DISTINCT ur.reward_id)
                               FROM rewards.users_rewards ur
                               JOIN rewards.collectives_rewards cr
                                   ON ur.reward_id = cr.reward_id
                               WHERE cr.collective_id = $1
                                 AND ur.receiver_user = cp.user_id
                                 AND ur.revoked = FALSE
                                 AND ur.deleted_at IS NULL
                           ),
                           progress_pct = CASE
                               WHEN $2 > 0 THEN ROUND(
                                   (SELECT COUNT(DISTINCT ur.reward_id)
                                    FROM rewards.users_rewards ur
                                    JOIN rewards.collectives_rewards cr
                                        ON ur.reward_id = cr.reward_id
                                    WHERE cr.collective_id = $1
                                      AND ur.receiver_user = cp.user_id
                                      AND ur.revoked = FALSE
                                      AND ur.deleted_at IS NULL
                                   )::DECIMAL / $2 * 100, 2
                               )
                               ELSE 0
                           END
                       WHERE collective_id = $1""",
                    collection_id, badges_required
                )

                # Get updated badge list
                badges = await conn.fetch_all(
                    """SELECT r.reward_id, r.reward, r.description, r.icon
                       FROM rewards.collectives_rewards cr
                       JOIN rewards.rewards r USING (reward_id)
                       WHERE cr.collective_id = $1
                       ORDER BY r.reward""",
                    collection_id
                )

                return self.json_response({
                    'collective_id': collection_id,
                    'total_badges': len(badges),
                    'badges': [dict(b) for b in badges],
                    'message': 'Badges removed from collection'
                })

        except ValueError:
            return self.json_response({'error': 'Invalid collection ID'}, status=400)
        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error removing badges: {err}")
            return self.json_response({'error': str(err)}, status=500)

    async def list_collections(self, request: web.Request) -> web.Response:
        """List all collections with admin statistics.

        GET /rewards/api/v1/admin/collections

        Query Params:
            include_inactive: bool - Include deactivated collections (default true)
            tier: str - Filter by tier
            program: str - Filter by program

        Returns:
            200: List of collections with stats
            403: Not authorized
        """
        try:
            await self._get_user_session(request)

            # Query params
            include_inactive = request.query.get('include_inactive', 'true').lower() == 'true'
            tier_filter = request.query.get('tier')
            program_filter = request.query.get('program')

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Build query with stats
                conditions = []
                params = []
                param_idx = 1

                if not include_inactive:
                    conditions.append("c.is_active = TRUE")

                if tier_filter:
                    conditions.append(f"c.tier = ${param_idx}")
                    params.append(tier_filter)
                    param_idx += 1

                if program_filter:
                    conditions.append(f"${param_idx} = ANY(c.programs)")
                    params.append(program_filter)
                    param_idx += 1

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                query = f"""
                    SELECT
                        c.collective_id,
                        c.collective_name,
                        c.description,
                        c.points,
                        c.bonus_points,
                        c.completion_type,
                        c.required_count,
                        c.tier,
                        c.icon,
                        c.is_active,
                        c.is_seasonal,
                        c.start_date,
                        c.end_date,
                        c.programs,
                        c.sort_order,
                        c.created_at,
                        (SELECT COUNT(*) FROM rewards.collectives_rewards cr
                         WHERE cr.collective_id = c.collective_id) AS total_badges,
                        COUNT(DISTINCT cp.user_id) FILTER (WHERE cp.badges_earned > 0)
                            AS users_started,
                        COUNT(DISTINCT cu.user_id) AS users_completed,
                        CASE
                            WHEN COUNT(DISTINCT cp.user_id) FILTER (WHERE cp.badges_earned > 0) > 0
                            THEN ROUND(
                                COUNT(DISTINCT cu.user_id)::DECIMAL /
                                COUNT(DISTINCT cp.user_id) FILTER (WHERE cp.badges_earned > 0) * 100, 1
                            )
                            ELSE 0
                        END AS completion_rate
                    FROM rewards.collectives c
                    LEFT JOIN rewards.collectives_progress cp USING (collective_id)
                    LEFT JOIN rewards.collectives_unlocked cu USING (collective_id)
                    {where_clause}
                    GROUP BY c.collective_id
                    ORDER BY c.sort_order, c.collective_name
                """

                collections = await conn.fetch_all(query, *params)

                return self.json_response([dict(c) for c in collections])

        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error listing collections: {err}")
            return self.json_response({'error': str(err)}, status=500)

    async def recalculate_progress(self, request: web.Request) -> web.Response:
        """Force full progress recalculation for a collection.

        POST /rewards/api/v1/admin/collections/{id}/recalculate

        Returns:
            200: Recalculation summary
            404: Collection not found
            403: Not authorized
        """
        try:
            await self._get_user_session(request)
            collection_id = int(request.match_info['id'])

            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )

            async with await reward_engine.connection.acquire() as conn:
                # Check collection exists
                collection = await conn.fetch_one(
                    """SELECT collective_id, collective_name, completion_type, required_count
                       FROM rewards.collectives WHERE collective_id = $1""",
                    collection_id
                )
                if not collection:
                    return self.json_response(
                        {'error': 'Collection not found'},
                        status=404
                    )

                # Get badge count for this collection
                badge_count = await self._get_badge_count(conn, collection_id)

                # Determine badges_required
                badges_required = (
                    collection['required_count']
                    if collection['completion_type'] != 'all' and collection['required_count']
                    else badge_count
                )

                # Rebuild progress for all users who have any of the collection's badges
                rebuild_query = """
                    INSERT INTO rewards.collectives_progress (
                        collective_id, user_id, badges_earned, badges_required,
                        progress_pct, is_complete, earned_reward_ids
                    )
                    SELECT
                        $1 AS collective_id,
                        ur.receiver_user AS user_id,
                        COUNT(DISTINCT ur.reward_id) AS badges_earned,
                        $2 AS badges_required,
                        ROUND(COUNT(DISTINCT ur.reward_id)::DECIMAL / $2 * 100, 2) AS progress_pct,
                        COUNT(DISTINCT ur.reward_id) >= $2 AS is_complete,
                        ARRAY_AGG(DISTINCT ur.reward_id) AS earned_reward_ids
                    FROM rewards.users_rewards ur
                    JOIN rewards.collectives_rewards cr ON ur.reward_id = cr.reward_id
                    WHERE cr.collective_id = $1
                      AND ur.revoked = FALSE
                      AND ur.deleted_at IS NULL
                    GROUP BY ur.receiver_user
                    ON CONFLICT (collective_id, user_id) DO UPDATE SET
                        badges_earned = EXCLUDED.badges_earned,
                        badges_required = EXCLUDED.badges_required,
                        progress_pct = EXCLUDED.progress_pct,
                        is_complete = EXCLUDED.is_complete,
                        earned_reward_ids = EXCLUDED.earned_reward_ids,
                        completed_at = CASE
                            WHEN EXCLUDED.is_complete AND rewards.collectives_progress.completed_at IS NULL
                            THEN NOW()
                            ELSE rewards.collectives_progress.completed_at
                        END
                """
                await conn.execute(rebuild_query, collection_id, badges_required)

                # Get stats
                stats = await conn.fetch_one(
                    """SELECT
                           COUNT(*) AS total_users,
                           COUNT(*) FILTER (WHERE is_complete) AS completed_users
                       FROM rewards.collectives_progress
                       WHERE collective_id = $1""",
                    collection_id
                )

                return self.json_response({
                    'collective_id': collection_id,
                    'collective_name': collection['collective_name'],
                    'users_recalculated': stats['total_users'] if stats else 0,
                    'users_completed': stats['completed_users'] if stats else 0,
                    'message': 'Progress recalculated successfully'
                })

        except ValueError:
            return self.json_response({'error': 'Invalid collection ID'}, status=400)
        except web.HTTPForbidden:
            return self.json_response({'error': 'Admin access required'}, status=403)
        except Exception as err:
            self.logger.error(f"Error recalculating progress: {err}")
            return self.json_response({'error': str(err)}, status=500)


def setup_collection_admin_routes(app: web.Application):
    """Register collection admin API routes with the aiohttp app.

    Call this from RewardsEngine.setup() or app configuration.

    Example:
        from rewards.handlers.collection_admin import setup_collection_admin_routes
        setup_collection_admin_routes(app)
    """
    handler = CollectionAdminHandler()
    base_path = '/rewards/api/v1/admin/collections'

    # Collection CRUD
    app.router.add_post(base_path, handler.create_collection)
    app.router.add_get(base_path, handler.list_collections)
    app.router.add_put(f'{base_path}/{{id}}', handler.update_collection)
    app.router.add_delete(f'{base_path}/{{id}}', handler.delete_collection)

    # Badge management
    app.router.add_post(f'{base_path}/{{id}}/badges', handler.add_badges)
    app.router.add_delete(f'{base_path}/{{id}}/badges', handler.remove_badges)

    # Progress management
    app.router.add_post(f'{base_path}/{{id}}/recalculate', handler.recalculate_progress)


# Export public API
__all__ = [
    'CollectionAdminHandler',
    'setup_collection_admin_routes',
    'VALID_TIERS',
    'VALID_COMPLETION_TYPES'
]
