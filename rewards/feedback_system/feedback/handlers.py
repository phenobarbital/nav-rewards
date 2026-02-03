"""
Feedback System Handlers for NAV-Rewards.

This module provides REST API handlers for the Feedback System,
including endpoints for creating, retrieving, and managing feedback
on badges, kudos, and nominations.

Endpoints:
    - GET /feedback_types - List all feedback types
    - POST /feedback_types - Create a new feedback type
    - GET /user_feedback - List all feedback
    - POST /user_feedback - Submit new feedback
    - GET /user_feedback/{id} - Get specific feedback
    - GET /user_feedback/target/{type}/{id} - Get feedback for a target
    - GET /user_feedback/user/{id}/given - Feedback given by user
    - GET /user_feedback/user/{id}/received - Feedback received by user
    - GET /feedback_stats - Get feedback statistics
    - GET /feedback_stats/user/{id} - Get user feedback stats
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from aiohttp import web
from navigator_session import get_session
from datamodel.exceptions import ValidationError
from navigator.views import BaseHandler
from .models import (
    FeedbackType,
    UserFeedback,
    FeedbackCooldown,
    FeedbackStats,
    FeedbackByTarget,
    TargetType,
    POINTS_FOR_GIVER,
    POINTS_FOR_RECEIVER,
    MAX_FEEDBACK_PER_DAY,
    COOLDOWN_MINUTES,
    INITIAL_FEEDBACK_TYPES
)


# SQL for creating tables (for reference/migration)
CREATE_FEEDBACK_TABLES_SQL = """
-- See ddl/feedback_schema.sql for complete schema
"""


class FeedbackTypeHandler(BaseHandler):
    """Handler for feedback types management."""
    
    model = FeedbackType
    
    async def get_all_types(self, request: web.Request) -> web.Response:
        """Get all active feedback types."""
        try:
            reward_engine = request.app.get('reward_engine')
            if not reward_engine:
                return self.json_response(
                    {'error': 'Reward engine not initialized'},
                    status=500
                )
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT feedback_type_id, type_name, display_name, 
                           description, emoji, category, usage_count
                    FROM rewards.feedback_types
                    WHERE is_active = TRUE
                    ORDER BY usage_count DESC, display_name ASC
                """
                types = await conn.fetch_all(query)
                return self.json_response([dict(t) for t in types])
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_trending_types(self, request: web.Request) -> web.Response:
        """Get trending feedback types from the last 30 days."""
        try:
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_trending_feedback_types
                    LIMIT 10
                """
                types = await conn.fetch_all(query)
                return self.json_response([dict(t) for t in types])
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def create_type(self, request: web.Request) -> web.Response:
        """Create a new feedback type (admin only)."""
        try:
            session = await get_session(request, new=False)
            user = session.decode('user')
            
            # Check admin permission (implement your own logic)
            # if not user.get('is_admin'):
            #     return self.json_response({'error': 'Unauthorized'}, status=403)
            
            data = await request.json()
            required_fields = ['type_name', 'display_name']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                FeedbackType.Meta.connection = conn
                
                feedback_type = FeedbackType(**data)
                await feedback_type.insert()
                
                return self.json_response(feedback_type.to_dict(), status=201)
                
        except ValidationError as err:
            return self.json_response(
                {'error': 'Validation error', 'details': str(err)},
                status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    @classmethod
    def configure(cls, app: web.Application, path: str):
        """Configure routes for feedback types."""
        handler = cls()
        
        app.router.add_get(f'{path}', handler.get_all_types)
        app.router.add_get(f'{path}/trending', handler.get_trending_types)
        app.router.add_post(f'{path}', handler.create_type)


class UserFeedbackHandler(BaseHandler):
    """Handler for user feedback operations."""
    
    model = UserFeedback
    
    async def _get_user_session(self, request: web.Request):
        """Get user session information."""
        session = await get_session(request, new=False)
        user = session.decode('user')
        return session, user
    
    async def _validate_target(
        self,
        conn,
        target_type: str,
        target_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Validate that the target exists and get receiver info.
        
        Returns target info with receiver_user_id if valid, None otherwise.
        """
        if target_type == TargetType.BADGE.value:
            query = """
                SELECT award_id, receiver_user, receiver_email, receiver_name,
                       display_name, reward, points
                FROM rewards.users_rewards
                WHERE award_id = $1 AND revoked = FALSE
            """
            result = await conn.fetch_one(query, target_id)
            if result:
                return {
                    'receiver_user_id': result['receiver_user'],
                    'receiver_email': result['receiver_email'],
                    'receiver_name': result.get('receiver_name') or result.get('display_name'),
                    'target_info': dict(result)
                }
                
        elif target_type == TargetType.KUDOS.value:
            query = """
                SELECT kudos_id, receiver_user_id, receiver_email, receiver_name
                FROM rewards.users_kudos
                WHERE kudos_id = $1 AND is_active = TRUE
            """
            result = await conn.fetch_one(query, target_id)
            if result:
                return {
                    'receiver_user_id': result['receiver_user_id'],
                    'receiver_email': result['receiver_email'],
                    'receiver_name': result['receiver_name'],
                    'target_info': dict(result)
                }
                
        elif target_type == TargetType.NOMINATION.value:
            query = """
                SELECT nomination_id, nominee_user_id, nominee_email, nominee_name
                FROM rewards.nominations
                WHERE nomination_id = $1 AND is_active = TRUE
            """
            result = await conn.fetch_one(query, target_id)
            if result:
                return {
                    'receiver_user_id': result['nominee_user_id'],
                    'receiver_email': result.get('nominee_email'),
                    'receiver_name': result.get('nominee_name'),
                    'target_info': dict(result)
                }
        
        return None
    
    async def _check_cooldown(
        self,
        conn,
        user_id: int,
        target_type: str
    ) -> tuple[bool, str]:
        """
        Check if user is within cooldown period.
        
        Returns (is_allowed, error_message).
        """
        query = """
            SELECT last_feedback_at, feedback_count_today
            FROM rewards.feedback_cooldowns
            WHERE user_id = $1 AND target_type = $2
        """
        cooldown = await conn.fetch_one(query, user_id, target_type)
        
        if cooldown:
            last_feedback = cooldown['last_feedback_at']
            count_today = cooldown['feedback_count_today']
            
            # Check minimum time between feedback
            min_interval = timedelta(minutes=COOLDOWN_MINUTES)
            if datetime.now(last_feedback.tzinfo) - last_feedback < min_interval:
                return False, f"Please wait {COOLDOWN_MINUTES} minute(s) between feedback"
            
            # Check daily limit
            if (last_feedback.date() == datetime.now().date() and 
                count_today >= MAX_FEEDBACK_PER_DAY):
                return False, f"Daily feedback limit ({MAX_FEEDBACK_PER_DAY}) reached"
        
        return True, ""
    
    async def _check_duplicate(
        self,
        conn,
        target_type: str,
        target_id: int,
        giver_user_id: int
    ) -> bool:
        """Check if user has already given feedback on this target."""
        query = """
            SELECT 1 FROM rewards.user_feedback
            WHERE target_type = $1 AND target_id = $2 
            AND giver_user_id = $3 AND is_active = TRUE
        """
        result = await conn.fetch_one(query, target_type, target_id, giver_user_id)
        return result is not None
    
    async def submit_feedback(self, request: web.Request) -> web.Response:
        """
        Submit feedback on a badge, kudos, or nomination.
        
        Required fields:
            - target_type: 'badge', 'kudos', or 'nomination'
            - target_id: ID of the target item
            
        Optional fields:
            - feedback_type_id: Predefined feedback type
            - rating: 1-5 star rating
            - message: Text message (max 500 chars)
        """
        try:
            session, user = await self._get_user_session(request)
            data = await request.json()
            
            # Validate required fields
            required_fields = ['target_type', 'target_id']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )
            
            target_type = data['target_type']
            target_id = int(data['target_id'])
            
            # Validate target type
            valid_types = [t.value for t in TargetType]
            if target_type not in valid_types:
                return self.json_response(
                    {'error': f'Invalid target_type. Must be one of: {valid_types}'},
                    status=400
                )
            
            # Validate rating if provided
            rating = data.get('rating')
            if rating is not None:
                rating = int(rating)
                if not (1 <= rating <= 5):
                    return self.json_response(
                        {'error': 'Rating must be between 1 and 5'},
                        status=400
                    )
            
            # Get user info
            giver_user_id = user.get('user_id')
            giver_email = user.get('email')
            giver_name = user.get('display_name') or user.get('name')
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                # Validate target and get receiver info
                target_info = await self._validate_target(conn, target_type, target_id)
                if not target_info:
                    return self.json_response(
                        {'error': f'Target {target_type}/{target_id} not found or inactive'},
                        status=404
                    )
                
                receiver_user_id = target_info['receiver_user_id']
                
                # Check no self-feedback
                if giver_user_id == receiver_user_id:
                    return self.json_response(
                        {'error': 'Cannot give feedback on your own recognition'},
                        status=400
                    )
                
                # Check cooldown
                allowed, error_msg = await self._check_cooldown(
                    conn, giver_user_id, target_type
                )
                if not allowed:
                    return self.json_response({'error': error_msg}, status=429)
                
                # Check duplicate
                if await self._check_duplicate(conn, target_type, target_id, giver_user_id):
                    return self.json_response(
                        {'error': 'You have already given feedback on this item'},
                        status=409
                    )
                
                # Create feedback
                UserFeedback.Meta.connection = conn
                
                feedback = UserFeedback(
                    target_type=target_type,
                    target_id=target_id,
                    giver_user_id=giver_user_id,
                    giver_email=giver_email,
                    giver_name=giver_name,
                    receiver_user_id=receiver_user_id,
                    receiver_email=target_info.get('receiver_email'),
                    receiver_name=target_info.get('receiver_name'),
                    feedback_type_id=data.get('feedback_type_id'),
                    rating=rating,
                    message=data.get('message', '')[:500] if data.get('message') else None,
                    points_given=POINTS_FOR_GIVER,
                    points_received=POINTS_FOR_RECEIVER
                )
                
                await feedback.insert()
                
                # Return success with points info
                return self.json_response({
                    'feedback': feedback.to_dict(),
                    'points_awarded': {
                        'giver': POINTS_FOR_GIVER,
                        'receiver': POINTS_FOR_RECEIVER
                    },
                    'message': f'Feedback submitted! You earned {POINTS_FOR_GIVER} points.'
                }, status=201)
                
        except ValidationError as err:
            return self.json_response(
                {'error': 'Validation error', 'details': str(err)},
                status=400
            )
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_feedback(self, request: web.Request) -> web.Response:
        """Get a specific feedback by ID."""
        try:
            feedback_id = int(request.match_info['feedback_id'])
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_user_feedback
                    WHERE feedback_id = $1
                """
                feedback = await conn.fetch_one(query, feedback_id)
                
                if not feedback:
                    return self.json_response(
                        {'error': 'Feedback not found'},
                        status=404
                    )
                
                return self.json_response(dict(feedback))
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_feedback_for_target(self, request: web.Request) -> web.Response:
        """Get all feedback for a specific target."""
        try:
            target_type = request.match_info['target_type']
            target_id = int(request.match_info['target_id'])
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_user_feedback
                    WHERE target_type = $1 AND target_id = $2
                    ORDER BY created_at DESC
                """
                feedback_list = await conn.fetch_all(query, target_type, target_id)
                
                # Also get summary
                summary_query = """
                    SELECT * FROM rewards.vw_feedback_by_target
                    WHERE target_type = $1 AND target_id = $2
                """
                summary = await conn.fetch_one(summary_query, target_type, target_id)
                
                return self.json_response({
                    'feedback': [dict(f) for f in feedback_list],
                    'summary': dict(summary) if summary else None
                })
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_user_given_feedback(self, request: web.Request) -> web.Response:
        """Get all feedback given by a user."""
        try:
            user_id = int(request.match_info['user_id'])
            
            # Pagination
            limit = int(request.query.get('limit', 20))
            offset = int(request.query.get('offset', 0))
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_user_feedback
                    WHERE giver_user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                """
                feedback_list = await conn.fetch_all(query, user_id, limit, offset)
                
                # Get total count
                count_query = """
                    SELECT COUNT(*) as total FROM rewards.user_feedback
                    WHERE giver_user_id = $1 AND is_active = TRUE
                """
                count_result = await conn.fetch_one(count_query, user_id)
                
                return self.json_response({
                    'feedback': [dict(f) for f in feedback_list],
                    'total': count_result['total'],
                    'limit': limit,
                    'offset': offset
                })
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_user_received_feedback(self, request: web.Request) -> web.Response:
        """Get all feedback received by a user."""
        try:
            user_id = int(request.match_info['user_id'])
            
            # Pagination
            limit = int(request.query.get('limit', 20))
            offset = int(request.query.get('offset', 0))
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_user_feedback
                    WHERE receiver_user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                """
                feedback_list = await conn.fetch_all(query, user_id, limit, offset)
                
                # Get total count
                count_query = """
                    SELECT COUNT(*) as total FROM rewards.user_feedback
                    WHERE receiver_user_id = $1 AND is_active = TRUE
                """
                count_result = await conn.fetch_one(count_query, user_id)
                
                return self.json_response({
                    'feedback': [dict(f) for f in feedback_list],
                    'total': count_result['total'],
                    'limit': limit,
                    'offset': offset
                })
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def list_feedback(self, request: web.Request) -> web.Response:
        """List all feedback with optional filters."""
        try:
            # Query parameters
            target_type = request.query.get('target_type')
            feedback_type_id = request.query.get('feedback_type_id')
            limit = int(request.query.get('limit', 50))
            offset = int(request.query.get('offset', 0))
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                # Build query with filters
                conditions = ["is_active = TRUE"]
                params = []
                param_idx = 1
                
                if target_type:
                    conditions.append(f"target_type = ${param_idx}")
                    params.append(target_type)
                    param_idx += 1
                
                if feedback_type_id:
                    conditions.append(f"feedback_type_id = ${param_idx}")
                    params.append(int(feedback_type_id))
                    param_idx += 1
                
                where_clause = " AND ".join(conditions)
                
                query = f"""
                    SELECT * FROM rewards.vw_user_feedback
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ${param_idx} OFFSET ${param_idx + 1}
                """
                params.extend([limit, offset])
                
                feedback_list = await conn.fetch_all(query, *params)
                
                return self.json_response({
                    'feedback': [dict(f) for f in feedback_list],
                    'limit': limit,
                    'offset': offset
                })
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def delete_feedback(self, request: web.Request) -> web.Response:
        """Soft delete feedback (mark as inactive)."""
        try:
            session, user = await self._get_user_session(request)
            feedback_id = int(request.match_info['feedback_id'])
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                # Check ownership
                query = """
                    SELECT giver_user_id FROM rewards.user_feedback
                    WHERE feedback_id = $1 AND is_active = TRUE
                """
                feedback = await conn.fetch_one(query, feedback_id)
                
                if not feedback:
                    return self.json_response(
                        {'error': 'Feedback not found'},
                        status=404
                    )
                
                if feedback['giver_user_id'] != user.get('user_id'):
                    return self.json_response(
                        {'error': 'Not authorized to delete this feedback'},
                        status=403
                    )
                
                # Soft delete
                update_query = """
                    UPDATE rewards.user_feedback
                    SET is_active = FALSE, updated_at = $1
                    WHERE feedback_id = $2
                """
                await conn.execute(update_query, datetime.now(), feedback_id)
                
                return self.json_response({'message': 'Feedback deleted successfully'})
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    @classmethod
    def configure(cls, app: web.Application, path: str):
        """Configure routes for user feedback."""
        handler = cls()
        
        # Main CRUD
        app.router.add_get(f'{path}', handler.list_feedback)
        app.router.add_post(f'{path}', handler.submit_feedback)
        app.router.add_get(f'{path}/{{feedback_id}}', handler.get_feedback)
        app.router.add_delete(f'{path}/{{feedback_id}}', handler.delete_feedback)
        
        # Target-based queries
        app.router.add_get(
            f'{path}/target/{{target_type}}/{{target_id}}',
            handler.get_feedback_for_target
        )
        
        # User-based queries
        app.router.add_get(
            f'{path}/user/{{user_id}}/given',
            handler.get_user_given_feedback
        )
        app.router.add_get(
            f'{path}/user/{{user_id}}/received',
            handler.get_user_received_feedback
        )


class FeedbackStatsHandler(BaseHandler):
    """Handler for feedback statistics."""
    
    model = FeedbackStats
    
    async def get_global_stats(self, request: web.Request) -> web.Response:
        """Get global feedback statistics."""
        try:
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT 
                        COUNT(*) as total_feedback,
                        COUNT(DISTINCT giver_user_id) as unique_givers,
                        COUNT(DISTINCT receiver_user_id) as unique_receivers,
                        SUM(points_given) as total_points_given,
                        SUM(points_received) as total_points_received,
                        AVG(rating) FILTER (WHERE rating IS NOT NULL) as avg_rating,
                        COUNT(*) FILTER (WHERE target_type = 'badge') as badge_feedback,
                        COUNT(*) FILTER (WHERE target_type = 'kudos') as kudos_feedback,
                        COUNT(*) FILTER (WHERE target_type = 'nomination') as nomination_feedback
                    FROM rewards.user_feedback
                    WHERE is_active = TRUE
                """
                stats = await conn.fetch_one(query)
                
                return self.json_response(dict(stats))
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_user_stats(self, request: web.Request) -> web.Response:
        """Get feedback statistics for a specific user."""
        try:
            user_id = int(request.match_info['user_id'])
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT * FROM rewards.vw_user_feedback_stats
                    WHERE user_id = $1
                """
                stats = await conn.fetch_one(query, user_id)
                
                if not stats:
                    return self.json_response({
                        'user_id': user_id,
                        'feedback_given': 0,
                        'points_earned_giving': 0,
                        'feedback_received': 0,
                        'points_earned_receiving': 0,
                        'avg_rating_received': 0
                    })
                
                return self.json_response(dict(stats))
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    async def get_leaderboard(self, request: web.Request) -> web.Response:
        """Get feedback leaderboard."""
        try:
            board_type = request.query.get('type', 'received')  # 'given' or 'received'
            limit = int(request.query.get('limit', 10))
            
            reward_engine = request.app.get('reward_engine')
            
            async with await reward_engine.connection.acquire() as conn:
                if board_type == 'given':
                    query = """
                        SELECT user_id, email, display_name, 
                               feedback_given, points_earned_giving
                        FROM rewards.vw_user_feedback_stats
                        ORDER BY feedback_given DESC
                        LIMIT $1
                    """
                else:
                    query = """
                        SELECT user_id, email, display_name,
                               feedback_received, points_earned_receiving, avg_rating_received
                        FROM rewards.vw_user_feedback_stats
                        ORDER BY feedback_received DESC
                        LIMIT $1
                    """
                
                leaderboard = await conn.fetch_all(query, limit)
                
                return self.json_response({
                    'type': board_type,
                    'leaderboard': [dict(row) for row in leaderboard]
                })
                
        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)
    
    @classmethod
    def configure(cls, app: web.Application, path: str):
        """Configure routes for feedback statistics."""
        handler = cls()
        
        app.router.add_get(f'{path}', handler.get_global_stats)
        app.router.add_get(f'{path}/user/{{user_id}}', handler.get_user_stats)
        app.router.add_get(f'{path}/leaderboard', handler.get_leaderboard)


# Helper functions for integration
async def update_feedback_type_usage(conn, feedback_type_id: int):
    """Increment usage count for a feedback type."""
    if feedback_type_id:
        query = """
            UPDATE rewards.feedback_types
            SET usage_count = usage_count + 1
            WHERE feedback_type_id = $1
        """
        await conn.execute(query, feedback_type_id)


async def get_feedback_count_for_target(
    conn,
    target_type: str,
    target_id: int
) -> int:
    """Get the number of feedback items for a target."""
    query = """
        SELECT COUNT(*) as count FROM rewards.user_feedback
        WHERE target_type = $1 AND target_id = $2 AND is_active = TRUE
    """
    result = await conn.fetch_one(query, target_type, target_id)
    return result['count'] if result else 0


async def seed_feedback_types(conn):
    """Seed initial feedback types if table is empty."""
    check_query = "SELECT COUNT(*) as count FROM rewards.feedback_types"
    result = await conn.fetch_one(check_query)
    
    if result['count'] == 0:
        for ft in INITIAL_FEEDBACK_TYPES:
            insert_query = """
                INSERT INTO rewards.feedback_types 
                (type_name, display_name, description, emoji, category)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (type_name) DO NOTHING
            """
            await conn.execute(
                insert_query,
                ft['type_name'],
                ft['display_name'],
                ft['description'],
                ft['emoji'],
                ft['category']
            )


# Export all handlers and utilities
__all__ = [
    'FeedbackTypeHandler',
    'UserFeedbackHandler',
    'FeedbackStatsHandler',
    'update_feedback_type_usage',
    'get_feedback_count_for_target',
    'seed_feedback_types',
    'CREATE_FEEDBACK_TABLES_SQL'
]
