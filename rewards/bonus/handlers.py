"""
API Handlers for Prize Marketplace.

Provides REST endpoints for:
- Prize catalog management
- Prize awards
- Redemption operations
- User wallet
- Mystery box events
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.handlers import AuthHandler
from datamodel.exceptions import ValidationError

from .models import (
    PrizeCatalog,
    PrizeAward,
    PrizeRedemption,
    PrizeCategory,
    PrizeTier,
    MysteryBoxEvent,
    AwardSource,
    RedemptionStatus,
)
from .service import MarketplaceService, AwardResult, RedemptionResult


class PrizeCatalogHandler(BaseView):
    """
    Handler for prize catalog operations.

    Endpoints:
        GET /rewards/api/v1/prizes - List prizes
        GET /rewards/api/v1/prizes/{prize_id} - Get prize details
        POST /rewards/api/v1/prizes - Create prize (admin)
        PUT /rewards/api/v1/prizes/{prize_id} - Update prize (admin)
        DELETE /rewards/api/v1/prizes/{prize_id} - Soft delete (admin)
    """

    async def get(self):
        """List prizes or get single prize."""
        prize_id = self.request.match_info.get('prize_id')

        try:
            service = await self._get_service()

            if prize_id:
                # Single prize
                prize = await service.get_prize(int(prize_id))
                if not prize:
                    return self.not_found(
                        message=f"Prize {prize_id} not found"
                    )
                return self.json_response(prize)
            else:
                # List with filters
                params = self.request.rel_url.query

                prizes = await service.get_catalog(
                    category_id=params.get('category_id'),
                    tier_id=params.get('tier_id'),
                    is_active=params.get('is_active', 'true').lower() == 'true',
                    is_featured=params.get('is_featured'),
                    in_stock_only=params.get('in_stock_only', 'false').lower() == 'true',
                    mystery_eligible_only=params.get('mystery_eligible', 'false').lower() == 'true',
                    search_term=params.get('search'),
                    limit=int(params.get('limit', 50)),
                    offset=int(params.get('offset', 0))
                )

                return self.json_response({
                    'prizes': prizes,
                    'count': len(prizes)
                })

        except Exception as err:
            return self.error(
                message=f"Error fetching prizes: {err}",
                status=500
            )

    async def post(self):
        """Create a new prize (admin only)."""
        try:
            session = await self.get_session()
            if not self._is_admin(session):
                return self.not_authorized(
                    message="Admin privileges required"
                )

            data = await self.request.json()
            data['created_by'] = session.get('email')

            prize = PrizeCatalog(**data)
            result = await prize.insert()

            return self.json_response(
                {'prize_id': result.prize_id, 'message': 'Prize created'},
                status=201
            )

        except ValidationError as err:
            return self.error(message=str(err.payload), status=400)
        except Exception as err:
            return self.error(message=str(err), status=500)

    async def put(self):
        """Update a prize (admin only)."""
        prize_id = self.request.match_info.get('prize_id')

        try:
            session = await self.get_session()
            if not self._is_admin(session):
                return self.not_authorized()

            data = await self.request.json()
            data['updated_by'] = session.get('email')
            data['updated_at'] = datetime.now()

            prize = await PrizeCatalog.get(prize_id=int(prize_id))
            if not prize:
                return self.not_found()

            for key, value in data.items():
                if hasattr(prize, key):
                    setattr(prize, key, value)

            await prize.update()

            return self.json_response({'message': 'Prize updated'})

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def delete(self):
        """Soft delete a prize (admin only)."""
        prize_id = self.request.match_info.get('prize_id')

        try:
            session = await self.get_session()
            if not self._is_admin(session):
                return self.not_authorized()

            prize = await PrizeCatalog.get(prize_id=int(prize_id))
            if not prize:
                return self.not_found()

            prize.deleted_at = datetime.now()
            prize.deleted_by = session.get('email')
            prize.is_active = False
            await prize.update()

            return self.json_response({'message': 'Prize deleted'})

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        """Get the marketplace service."""
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)

    def _is_admin(self, session: dict) -> bool:
        """Check if user has admin privileges."""
        groups = session.get('groups', [])
        return 'admin' in groups or 'rewards_admin' in groups


class PrizeAwardHandler(BaseView):
    """
    Handler for prize award operations.

    Endpoints:
        POST /rewards/api/v1/awards - Award a prize
        GET /rewards/api/v1/awards/{award_id} - Get award details
        GET /rewards/api/v1/awards/user/{user_id} - Get user's awards
    """

    async def post(self):
        """Award a prize to a user."""
        try:
            session = await self.get_session()
            data = await self.request.json()

            # Validate required fields
            required = ['prize_id', 'user_id', 'user_email']
            for field in required:
                if field not in data:
                    return self.error(
                        message=f"Missing required field: {field}",
                        status=400
                    )

            service = await self._get_service()

            result = await service.award_prize(
                prize_id=data['prize_id'],
                user_id=data['user_id'],
                user_email=data['user_email'],
                source=AwardSource(data.get('source', 'manual')),
                source_reference_id=data.get('source_reference_id'),
                source_reference_type=data.get('source_reference_type'),
                linked_award_id=data.get('linked_award_id'),
                awarded_by_user_id=session.get('user_id'),
                awarded_by_email=session.get('email'),
                award_message=data.get('message'),
                expires_in_days=data.get('expires_in_days'),
                metadata=data.get('metadata'),
                user_employee_id=data.get('user_employee_id')
            )

            if result.success:
                return self.json_response(
                    {
                        'award_id': result.award_id,
                        'message': result.message
                    },
                    status=201
                )
            else:
                return self.error(message=result.error, status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def get(self):
        """Get award details or user's awards."""
        award_id = self.request.match_info.get('award_id')
        user_id = self.request.match_info.get('user_id')

        try:
            service = await self._get_service()

            if award_id:
                # Single award
                award = await PrizeAward.get(award_id=int(award_id))
                if not award:
                    return self.not_found()
                return self.json_response(award.to_dict())

            elif user_id:
                # User's wallet
                params = self.request.rel_url.query
                status_filter = params.get('status')

                wallet = await service.get_user_wallet(
                    user_id=int(user_id),
                    status_filter=[status_filter] if status_filter else None,
                    include_expired=params.get('include_expired', 'false').lower() == 'true'
                )

                stats = await service.get_user_wallet_stats(int(user_id))

                return self.json_response({
                    'awards': wallet,
                    'stats': stats
                })
            else:
                return self.error(message="Award ID or User ID required", status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)


class PrizeRedemptionHandler(BaseView):
    """
    Handler for prize redemption operations.

    Endpoints:
        POST /rewards/api/v1/redemptions - Initiate redemption
        GET /rewards/api/v1/redemptions/{redemption_id} - Get redemption details
        PUT /rewards/api/v1/redemptions/{redemption_id}/status - Update status
        POST /rewards/api/v1/redemptions/{redemption_id}/cancel - Cancel
        POST /rewards/api/v1/redemptions/{redemption_id}/complete - Complete
        POST /rewards/api/v1/redemptions/{redemption_id}/feedback - Submit feedback
    """

    async def post(self):
        """Initiate a new redemption."""
        try:
            session = await self.get_session()
            data = await self.request.json()

            if 'award_id' not in data:
                return self.error(
                    message="award_id is required",
                    status=400
                )

            service = await self._get_service()

            result = await service.initiate_redemption(
                award_id=data['award_id'],
                user_id=session.get('user_id'),
                fulfillment_method=data.get('fulfillment_method'),
                shipping_address=data.get('shipping_address'),
                metadata=data.get('metadata')
            )

            if result.success:
                return self.json_response(
                    {
                        'redemption_id': result.redemption_id,
                        'redemption_code': result.redemption_code,
                        'message': result.message
                    },
                    status=201
                )
            else:
                return self.error(message=result.error, status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def get(self):
        """Get redemption details."""
        redemption_id = self.request.match_info.get('redemption_id')

        try:
            redemption = await PrizeRedemption.get(
                redemption_id=int(redemption_id)
            )
            if not redemption:
                return self.not_found()

            return self.json_response(redemption.to_dict())

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def put_status(self):
        """Update redemption status (admin)."""
        redemption_id = self.request.match_info.get('redemption_id')

        try:
            session = await self.get_session()
            data = await self.request.json()

            if 'status' not in data:
                return self.error(message="status is required", status=400)

            service = await self._get_service()

            result = await service.update_redemption_status(
                redemption_id=int(redemption_id),
                new_status=RedemptionStatus(data['status']),
                updated_by_user_id=session.get('user_id'),
                updated_by_email=session.get('email'),
                reason=data.get('reason'),
                fulfillment_details=data.get('fulfillment_details'),
                tracking_number=data.get('tracking_number'),
                admin_notes=data.get('admin_notes')
            )

            if result.success:
                return self.json_response({'message': result.message})
            else:
                return self.error(message=result.error, status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def post_cancel(self):
        """Cancel a redemption."""
        redemption_id = self.request.match_info.get('redemption_id')

        try:
            session = await self.get_session()
            data = await self.request.json()

            service = await self._get_service()

            result = await service.cancel_redemption(
                redemption_id=int(redemption_id),
                cancelled_by_user_id=session.get('user_id'),
                reason=data.get('reason', 'User cancelled')
            )

            if result.success:
                return self.json_response({'message': 'Redemption cancelled'})
            else:
                return self.error(message=result.error, status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def post_complete(self):
        """Complete a redemption (admin)."""
        redemption_id = self.request.match_info.get('redemption_id')

        try:
            session = await self.get_session()
            data = await self.request.json()

            service = await self._get_service()

            result = await service.complete_redemption(
                redemption_id=int(redemption_id),
                fulfillment_details=data.get('fulfillment_details'),
                completed_by_email=session.get('email')
            )

            if result.success:
                return self.json_response({'message': 'Redemption completed'})
            else:
                return self.error(message=result.error, status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def post_feedback(self):
        """Submit feedback for a redemption."""
        redemption_id = self.request.match_info.get('redemption_id')

        try:
            data = await self.request.json()

            redemption = await PrizeRedemption.get(
                redemption_id=int(redemption_id)
            )
            if not redemption:
                return self.not_found()

            if redemption.status != RedemptionStatus.COMPLETED.value:
                return self.error(
                    message="Can only provide feedback for completed redemptions",
                    status=400
                )

            redemption.user_rating = data.get('rating')
            redemption.user_feedback = data.get('feedback')
            redemption.feedback_at = datetime.now()
            await redemption.update()

            return self.json_response({'message': 'Feedback submitted'})

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)


class MysteryBoxHandler(BaseView):
    """
    Handler for mystery box operations.

    Endpoints:
        POST /rewards/api/v1/mystery-box/trigger - Trigger mystery box event
        GET /rewards/api/v1/mystery-box/events - List events
        GET /rewards/api/v1/mystery-box/events/{event_id} - Get event details
    """

    async def post_trigger(self):
        """Trigger a mystery box event (admin)."""
        try:
            session = await self.get_session()

            if not self._is_admin(session):
                return self.not_authorized()

            data = await self.request.json()

            service = await self._get_service()

            result = await service.execute_mystery_box(
                event_name=data.get('event_name', 'Manual Mystery Box'),
                winner_count=data.get('winner_count', 1),
                eligible_user_ids=data.get('eligible_user_ids'),
                eligibility_criteria=data.get('eligibility_criteria'),
                tier_overrides=data.get('tier_overrides'),
                expires_in_days=data.get('expires_in_days', 30),
                linked_reward_id=data.get('linked_reward_id'),
                created_by=session.get('email')
            )

            if result.success:
                return self.json_response({
                    'event_id': result.event_id,
                    'winners': result.winners,
                    'total_prizes': result.total_prizes_awarded,
                    'message': result.message
                })
            else:
                return self.error(message=result.error, status=400)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def get_events(self):
        """List mystery box events."""
        try:
            params = self.request.rel_url.query
            limit = int(params.get('limit', 20))
            offset = int(params.get('offset', 0))
            status = params.get('status')

            db = self.request.app.get('database')

            query = """
                SELECT * FROM rewards.mystery_box_events
                WHERE ($1::text IS NULL OR status = $1)
                ORDER BY scheduled_at DESC
                LIMIT $2 OFFSET $3
            """

            async with await db.acquire() as conn:
                results = await conn.fetch_all(query, [status, limit, offset])

            return self.json_response({
                'events': [dict(r) for r in results],
                'count': len(results)
            })

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def get_event(self):
        """Get mystery box event details."""
        event_id = self.request.match_info.get('event_id')

        try:
            event = await MysteryBoxEvent.get(event_id=int(event_id))
            if not event:
                return self.not_found()

            return self.json_response(event.to_dict())

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)

    def _is_admin(self, session: dict) -> bool:
        groups = session.get('groups', [])
        return 'admin' in groups or 'rewards_admin' in groups


class UserWalletHandler(BaseView):
    """
    Handler for user prize wallet.

    Endpoints:
        GET /rewards/api/v1/wallet - Get current user's wallet
        GET /rewards/api/v1/wallet/stats - Get wallet statistics
    """

    async def get_wallet(self):
        """Get current user's prize wallet."""
        try:
            session = await self.get_session()
            user_id = session.get('user_id')

            params = self.request.rel_url.query

            service = await self._get_service()

            wallet = await service.get_user_wallet(
                user_id=user_id,
                status_filter=params.get('status'),
                include_expired=params.get('include_expired', 'false').lower() == 'true'
            )

            return self.json_response({
                'awards': wallet,
                'count': len(wallet)
            })

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def get_stats(self):
        """Get wallet statistics."""
        try:
            session = await self.get_session()
            user_id = session.get('user_id')

            service = await self._get_service()
            stats = await service.get_user_wallet_stats(user_id)

            return self.json_response(stats)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)


class PrizeCategoryHandler(BaseView):
    """Handler for prize categories."""

    async def get(self):
        """List prize categories."""
        try:
            service = await self._get_service()
            categories = await service.get_categories()
            return self.json_response({'categories': categories})
        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)


class PrizeTierHandler(BaseView):
    """Handler for prize tiers."""

    async def get(self):
        """List prize tiers."""
        try:
            service = await self._get_service()
            tiers = await service.get_tiers()
            return self.json_response({'tiers': tiers})
        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)


class RedemptionMetricsHandler(BaseView):
    """Handler for redemption metrics and analytics."""

    async def get(self):
        """Get redemption metrics."""
        try:
            params = self.request.rel_url.query

            start_date = None
            end_date = None

            if params.get('start_date'):
                start_date = datetime.fromisoformat(params['start_date'])
            if params.get('end_date'):
                end_date = datetime.fromisoformat(params['end_date'])

            service = await self._get_service()
            metrics = await service.get_redemption_metrics(start_date, end_date)

            return self.json_response(metrics)

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def get_popularity(self):
        """Get prize popularity rankings."""
        try:
            params = self.request.rel_url.query
            limit = int(params.get('limit', 10))

            service = await self._get_service()
            popularity = await service.get_prize_popularity(limit)

            return self.json_response({'prizes': popularity})

        except Exception as err:
            return self.error(message=str(err), status=500)

    async def _get_service(self) -> MarketplaceService:
        db = self.request.app.get('database')
        return MarketplaceService(connection=db)


def setup_marketplace_routes(app: web.Application):
    """
    Register all marketplace routes.

    Call this from your application setup:
        from rewards.marketplace.handlers import setup_marketplace_routes
        setup_marketplace_routes(app)
    """
    # Prize Catalog
    app.router.add_get(
        '/rewards/api/v1/prizes',
        PrizeCatalogHandler
    )
    app.router.add_get(
        '/rewards/api/v1/prizes/{prize_id}',
        PrizeCatalogHandler
    )
    app.router.add_post(
        '/rewards/api/v1/prizes',
        PrizeCatalogHandler
    )
    app.router.add_put(
        '/rewards/api/v1/prizes/{prize_id}',
        PrizeCatalogHandler
    )
    app.router.add_delete(
        '/rewards/api/v1/prizes/{prize_id}',
        PrizeCatalogHandler
    )

    # Categories & Tiers
    app.router.add_get(
        '/rewards/api/v1/prize-categories',
        PrizeCategoryHandler
    )
    app.router.add_get(
        '/rewards/api/v1/prize-tiers',
        PrizeTierHandler
    )

    # Awards
    app.router.add_post(
        '/rewards/api/v1/awards',
        PrizeAwardHandler
    )
    app.router.add_get(
        '/rewards/api/v1/awards/{award_id}',
        PrizeAwardHandler
    )
    app.router.add_get(
        '/rewards/api/v1/awards/user/{user_id}',
        PrizeAwardHandler
    )

    # Redemptions
    app.router.add_post(
        '/rewards/api/v1/redemptions',
        PrizeRedemptionHandler
    )
    app.router.add_get(
        '/rewards/api/v1/redemptions/{redemption_id}',
        PrizeRedemptionHandler
    )
    app.router.add_put(
        '/rewards/api/v1/redemptions/{redemption_id}/status',
        PrizeRedemptionHandler().put_status
    )
    app.router.add_post(
        '/rewards/api/v1/redemptions/{redemption_id}/cancel',
        PrizeRedemptionHandler().post_cancel
    )
    app.router.add_post(
        '/rewards/api/v1/redemptions/{redemption_id}/complete',
        PrizeRedemptionHandler().post_complete
    )
    app.router.add_post(
        '/rewards/api/v1/redemptions/{redemption_id}/feedback',
        PrizeRedemptionHandler().post_feedback
    )

    # User Wallet
    app.router.add_get(
        '/rewards/api/v1/wallet',
        UserWalletHandler().get_wallet
    )
    app.router.add_get(
        '/rewards/api/v1/wallet/stats',
        UserWalletHandler().get_stats
    )

    # Mystery Box
    app.router.add_post(
        '/rewards/api/v1/mystery-box/trigger',
        MysteryBoxHandler().post_trigger
    )
    app.router.add_get(
        '/rewards/api/v1/mystery-box/events',
        MysteryBoxHandler().get_events
    )
    app.router.add_get(
        '/rewards/api/v1/mystery-box/events/{event_id}',
        MysteryBoxHandler().get_event
    )

    # Metrics
    app.router.add_get(
        '/rewards/api/v1/metrics/redemptions',
        RedemptionMetricsHandler
    )
    app.router.add_get(
        '/rewards/api/v1/metrics/popularity',
        RedemptionMetricsHandler().get_popularity
    )
