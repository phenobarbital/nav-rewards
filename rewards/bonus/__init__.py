"""
NAV-Rewards Prize Marketplace Module.

This module provides a complete prize marketplace system for NAV-Rewards including:
- Prize Catalog (Marketplace) with categories and tiers
- Prize Awards with lifecycle tracking
- Prize Redemptions with full audit trail
- Mystery Box events with random prize distribution

Quick Start:
    from rewards.marketplace import MarketplaceService, setup_marketplace_routes

    # Setup routes
    setup_marketplace_routes(app)

    # Use the service
    service = MarketplaceService(connection=db)

    # Award a prize
    result = await service.award_prize(
        prize_id=1,
        user_id=123,
        user_email="user@example.com",
        source=AwardSource.MANUAL
    )

    # Initiate redemption
    redemption = await service.initiate_redemption(
        award_id=result.award_id,
        user_id=123
    )

    # Execute mystery box
    mystery_result = await service.execute_mystery_box(
        event_name="Daily Mystery Box",
        winner_count=5
    )
"""
from .models import (
    # Core Models
    PrizeCatalog,
    PrizeAward,
    PrizeRedemption,
    PrizeCategory,
    PrizeTier,
    MysteryBoxEvent,
    RedemptionStatusHistory,

    # Enums
    AwardStatus,
    AwardSource,
    RedemptionStatus,
    FulfillmentType,
    StockStatus,

    # View Models
    UserPrizeWallet,
    PrizeCatalogView,
    RedemptionMetrics,
)

from .service import (
    MarketplaceService,
    AwardResult,
    RedemptionResult,
    MysteryBoxResult,
)

from .handlers import (
    PrizeCatalogHandler,
    PrizeAwardHandler,
    PrizeRedemptionHandler,
    MysteryBoxHandler,
    UserWalletHandler,
    PrizeCategoryHandler,
    PrizeTierHandler,
    RedemptionMetricsHandler,
    setup_marketplace_routes,
)

from .mystery import (
    MysteryBoxRule,
    MysteryBoxReward,
    random_mystery_box_event,
    expire_old_prizes,
    register_mystery_box_jobs,
)


__all__ = [
    # Models
    'PrizeCatalog',
    'PrizeAward',
    'PrizeRedemption',
    'PrizeCategory',
    'PrizeTier',
    'MysteryBoxEvent',
    'RedemptionStatusHistory',

    # Enums
    'AwardStatus',
    'AwardSource',
    'RedemptionStatus',
    'FulfillmentType',
    'StockStatus',

    # View Models
    'UserPrizeWallet',
    'PrizeCatalogView',
    'RedemptionMetrics',

    # Service
    'MarketplaceService',
    'AwardResult',
    'RedemptionResult',
    'MysteryBoxResult',

    # Handlers
    'PrizeCatalogHandler',
    'PrizeAwardHandler',
    'PrizeRedemptionHandler',
    'MysteryBoxHandler',
    'UserWalletHandler',
    'PrizeCategoryHandler',
    'PrizeTierHandler',
    'RedemptionMetricsHandler',
    'setup_marketplace_routes',

    # Mystery Box
    'MysteryBoxRule',
    'MysteryBoxReward',
    'random_mystery_box_event',
    'expire_old_prizes',
    'register_mystery_box_jobs',
]

__version__ = '1.0.0'
