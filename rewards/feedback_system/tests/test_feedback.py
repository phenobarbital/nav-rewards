"""
Tests for NAV-Rewards Feedback System.

Run with: pytest tests/test_feedback.py -v
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

# Import feedback components
from rewards.feedback.models import (
    FeedbackType,
    UserFeedback,
    FeedbackCooldown,
    TargetType,
    POINTS_FOR_GIVER,
    POINTS_FOR_RECEIVER,
    MAX_FEEDBACK_PER_DAY,
    COOLDOWN_MINUTES,
    INITIAL_FEEDBACK_TYPES
)
from rewards.feedback.handlers import (
    FeedbackTypeHandler,
    UserFeedbackHandler,
    FeedbackStatsHandler,
    seed_feedback_types
)
from rewards.feedback.manager import (
    FeedbackManager,
    FeedbackEventHandler,
    setup_feedback_system
)


# =============================================================================
# MODEL TESTS
# =============================================================================

class TestFeedbackModels:
    """Tests for feedback models."""
    
    def test_target_type_enum(self):
        """Test TargetType enum values."""
        assert TargetType.BADGE.value == "badge"
        assert TargetType.KUDOS.value == "kudos"
        assert TargetType.NOMINATION.value == "nomination"
    
    def test_feedback_type_creation(self):
        """Test FeedbackType model creation."""
        ft = FeedbackType(
            type_name="test_type",
            display_name="Test Type",
            description="A test feedback type",
            emoji="🧪",
            category="testing"
        )
        assert ft.type_name == "test_type"
        assert ft.display_name == "Test Type"
        assert ft.emoji == "🧪"
        assert ft.usage_count == 0
        assert ft.is_active == True
    
    def test_user_feedback_creation(self):
        """Test UserFeedback model creation."""
        feedback = UserFeedback(
            target_type="badge",
            target_id=123,
            giver_user_id=1,
            receiver_user_id=2,
            feedback_type_id=1,
            rating=5,
            message="Great work!"
        )
        assert feedback.target_type == "badge"
        assert feedback.target_id == 123
        assert feedback.points_given == POINTS_FOR_GIVER
        assert feedback.points_received == POINTS_FOR_RECEIVER
    
    def test_user_feedback_no_self_feedback(self):
        """Test that self-feedback is prevented."""
        with pytest.raises(ValueError, match="Cannot give feedback to yourself"):
            UserFeedback(
                target_type="badge",
                target_id=123,
                giver_user_id=42,
                receiver_user_id=42  # Same as giver
            )
    
    def test_user_feedback_invalid_target_type(self):
        """Test that invalid target types are rejected."""
        with pytest.raises(ValueError, match="Invalid target_type"):
            UserFeedback(
                target_type="invalid_type",
                target_id=123,
                giver_user_id=1,
                receiver_user_id=2
            )
    
    def test_user_feedback_rating_validation(self):
        """Test rating validation."""
        # Valid rating
        feedback = UserFeedback(
            target_type="badge",
            target_id=123,
            giver_user_id=1,
            receiver_user_id=2,
            rating=5
        )
        assert feedback.rating == 5
        
        # Invalid rating - too high
        with pytest.raises(ValueError, match="Rating must be between 1 and 5"):
            UserFeedback(
                target_type="badge",
                target_id=123,
                giver_user_id=1,
                receiver_user_id=2,
                rating=6
            )
        
        # Invalid rating - too low
        with pytest.raises(ValueError, match="Rating must be between 1 and 5"):
            UserFeedback(
                target_type="badge",
                target_id=123,
                giver_user_id=1,
                receiver_user_id=2,
                rating=0
            )
    
    def test_user_feedback_optional_rating(self):
        """Test that rating is optional."""
        feedback = UserFeedback(
            target_type="kudos",
            target_id=456,
            giver_user_id=1,
            receiver_user_id=2
        )
        assert feedback.rating is None
    
    def test_initial_feedback_types(self):
        """Test initial feedback types configuration."""
        assert len(INITIAL_FEEDBACK_TYPES) >= 10
        
        # Check required fields
        for ft in INITIAL_FEEDBACK_TYPES:
            assert 'type_name' in ft
            assert 'display_name' in ft
            assert 'emoji' in ft
            assert 'category' in ft
    
    def test_points_constants(self):
        """Test point constants are properly defined."""
        assert POINTS_FOR_GIVER == 5
        assert POINTS_FOR_RECEIVER == 10
        assert MAX_FEEDBACK_PER_DAY == 20
        assert COOLDOWN_MINUTES == 1


# =============================================================================
# HANDLER TESTS
# =============================================================================

class TestFeedbackHandlers:
    """Tests for feedback handlers."""
    
    @pytest.fixture
    def mock_request(self):
        """Create a mock request object."""
        request = MagicMock()
        request.app = {'reward_engine': MagicMock()}
        return request
    
    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = AsyncMock()
        return conn
    
    @pytest.mark.asyncio
    async def test_validate_target_badge(self, mock_connection):
        """Test target validation for badges."""
        handler = UserFeedbackHandler()
        
        # Mock the database response
        mock_connection.fetch_one = AsyncMock(return_value={
            'award_id': 123,
            'receiver_user': 42,
            'receiver_email': 'test@example.com',
            'receiver_name': 'Test User',
            'display_name': 'Test User'
        })
        
        result = await handler._validate_target(
            mock_connection,
            'badge',
            123
        )
        
        assert result is not None
        assert result['receiver_user_id'] == 42
        assert result['receiver_email'] == 'test@example.com'
    
    @pytest.mark.asyncio
    async def test_validate_target_not_found(self, mock_connection):
        """Test target validation when target doesn't exist."""
        handler = UserFeedbackHandler()
        
        mock_connection.fetch_one = AsyncMock(return_value=None)
        
        result = await handler._validate_target(
            mock_connection,
            'badge',
            999  # Non-existent ID
        )
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_check_cooldown_allowed(self, mock_connection):
        """Test cooldown check when allowed."""
        handler = UserFeedbackHandler()
        
        # No previous feedback - should be allowed
        mock_connection.fetch_one = AsyncMock(return_value=None)
        
        allowed, error = await handler._check_cooldown(
            mock_connection,
            user_id=1,
            target_type='badge'
        )
        
        assert allowed == True
        assert error == ""
    
    @pytest.mark.asyncio
    async def test_check_cooldown_rate_limited(self, mock_connection):
        """Test cooldown check when rate limited."""
        handler = UserFeedbackHandler()
        
        # Recent feedback - should be rate limited
        import pytz
        now = datetime.now(pytz.UTC)
        mock_connection.fetch_one = AsyncMock(return_value={
            'last_feedback_at': now - timedelta(seconds=30),  # 30 seconds ago
            'feedback_count_today': 1
        })
        
        allowed, error = await handler._check_cooldown(
            mock_connection,
            user_id=1,
            target_type='badge'
        )
        
        assert allowed == False
        assert "wait" in error.lower()
    
    @pytest.mark.asyncio
    async def test_check_duplicate(self, mock_connection):
        """Test duplicate feedback check."""
        handler = UserFeedbackHandler()
        
        # No existing feedback
        mock_connection.fetch_one = AsyncMock(return_value=None)
        
        is_duplicate = await handler._check_duplicate(
            mock_connection,
            'badge',
            123,
            1
        )
        
        assert is_duplicate == False
        
        # Existing feedback
        mock_connection.fetch_one = AsyncMock(return_value={'exists': True})
        
        is_duplicate = await handler._check_duplicate(
            mock_connection,
            'badge',
            123,
            1
        )
        
        assert is_duplicate == True


# =============================================================================
# MANAGER TESTS
# =============================================================================

class TestFeedbackManager:
    """Tests for FeedbackManager."""
    
    @pytest.fixture
    def app(self):
        """Create a test application."""
        return web.Application()
    
    @pytest.fixture
    def manager(self, app):
        """Create a FeedbackManager instance."""
        return FeedbackManager(app)
    
    def test_manager_initialization(self, app, manager):
        """Test manager initialization."""
        assert manager.app == app
        assert 'feedback_manager' in app
        assert app['feedback_manager'] == manager
    
    def test_manager_setup(self, app, manager):
        """Test manager setup registers routes."""
        manager.setup()
        
        # Check routes are registered
        routes = [r.resource.canonical for r in app.router.routes()]
        assert '/rewards/api/v1/feedback_types' in routes
        assert '/rewards/api/v1/user_feedback' in routes
        assert '/rewards/api/v1/feedback_stats' in routes
    
    @pytest.mark.asyncio
    async def test_submit_feedback_validation(self, manager):
        """Test feedback submission validation."""
        mock_conn = AsyncMock()
        
        # Test self-feedback rejection
        with pytest.raises(ValueError, match="Cannot give feedback"):
            await manager.submit_feedback(
                mock_conn,
                giver_user_id=42,
                target_type='badge',
                target_id=123,
                receiver_user_id=42  # Same as giver
            )
        
        # Test invalid target type
        with pytest.raises(ValueError, match="Invalid target_type"):
            await manager.submit_feedback(
                mock_conn,
                giver_user_id=1,
                target_type='invalid',
                target_id=123,
                receiver_user_id=2
            )
        
        # Test invalid rating
        with pytest.raises(ValueError, match="Rating must be"):
            await manager.submit_feedback(
                mock_conn,
                giver_user_id=1,
                target_type='badge',
                target_id=123,
                receiver_user_id=2,
                rating=10
            )


# =============================================================================
# EVENT HANDLER TESTS
# =============================================================================

class TestFeedbackEventHandler:
    """Tests for FeedbackEventHandler."""
    
    @pytest.fixture
    def event_handler(self):
        """Create event handler with mock manager."""
        manager = MagicMock()
        return FeedbackEventHandler(manager)
    
    @pytest.mark.asyncio
    async def test_on_badge_awarded(self, event_handler):
        """Test badge awarded event handling."""
        event_data = {
            'award_id': 123,
            'receiver_user_id': 42
        }
        
        # Should not raise any exceptions
        await event_handler.on_badge_awarded(event_data)
    
    @pytest.mark.asyncio
    async def test_on_feedback_submitted(self, event_handler):
        """Test feedback submitted event handling."""
        event_data = {
            'feedback_id': 100,
            'receiver_user_id': 42,
            'points_received': 10
        }
        
        await event_handler.on_feedback_submitted(event_data)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestFeedbackIntegration(AioHTTPTestCase):
    """Integration tests for feedback API endpoints."""
    
    async def get_application(self):
        """Create test application with feedback routes."""
        app = web.Application()
        
        # Mock reward engine
        mock_engine = MagicMock()
        mock_engine.connection = AsyncMock()
        app['reward_engine'] = mock_engine
        
        # Setup feedback routes
        manager = FeedbackManager(app, mock_engine)
        manager.setup()
        
        return app
    
    @unittest_run_loop
    async def test_list_feedback_types(self):
        """Test listing feedback types endpoint."""
        # Mock the database response
        self.app['reward_engine'].connection.acquire = AsyncMock()
        
        mock_conn = AsyncMock()
        mock_conn.fetch_all = AsyncMock(return_value=[
            {
                'feedback_type_id': 1,
                'type_name': 'appreciation',
                'display_name': 'Appreciation',
                'emoji': '🙏',
                'category': 'gratitude',
                'usage_count': 100
            }
        ])
        
        self.app['reward_engine'].connection.acquire.return_value.__aenter__ = \
            AsyncMock(return_value=mock_conn)
        self.app['reward_engine'].connection.acquire.return_value.__aexit__ = \
            AsyncMock(return_value=None)
        
        async with self.client.get('/rewards/api/v1/feedback_types') as resp:
            # Note: This will fail without proper mock setup
            # This is a template for integration tests
            pass


# =============================================================================
# UTILITY FUNCTION TESTS
# =============================================================================

class TestUtilityFunctions:
    """Tests for utility functions."""
    
    @pytest.mark.asyncio
    async def test_seed_feedback_types_empty_table(self):
        """Test seeding feedback types when table is empty."""
        mock_conn = AsyncMock()
        
        # Table is empty
        mock_conn.fetch_one = AsyncMock(return_value={'count': 0})
        mock_conn.execute = AsyncMock()
        
        await seed_feedback_types(mock_conn)
        
        # Should have inserted all initial types
        assert mock_conn.execute.call_count == len(INITIAL_FEEDBACK_TYPES)
    
    @pytest.mark.asyncio
    async def test_seed_feedback_types_existing_data(self):
        """Test seeding feedback types when table has data."""
        mock_conn = AsyncMock()
        
        # Table has data
        mock_conn.fetch_one = AsyncMock(return_value={'count': 10})
        mock_conn.execute = AsyncMock()
        
        await seed_feedback_types(mock_conn)
        
        # Should not insert anything
        mock_conn.execute.assert_not_called()


# =============================================================================
# DIALOG TESTS
# =============================================================================

class TestFeedbackDialog:
    """Tests for FeedbackDialog."""
    
    def test_dialog_initialization(self):
        """Test dialog initialization."""
        from rewards.feedback.dialogs.feedback import FeedbackDialog
        
        mock_bot = MagicMock()
        dialog = FeedbackDialog(bot=mock_bot)
        
        assert dialog.bot == mock_bot
        assert dialog.initial_dialog_id == "FeedbackWaterfall"
    
    def test_create_feedback_form_card(self):
        """Test feedback form card creation."""
        from rewards.feedback.dialogs.feedback import FeedbackDialog
        
        mock_bot = MagicMock()
        dialog = FeedbackDialog(bot=mock_bot)
        
        card = dialog._create_feedback_form_card('badge', 123)
        
        assert card['type'] == 'AdaptiveCard'
        assert 'body' in card
        assert 'actions' in card
    
    def test_create_confirmation_card(self):
        """Test confirmation card creation."""
        from rewards.feedback.dialogs.feedback import FeedbackDialog
        
        mock_bot = MagicMock()
        dialog = FeedbackDialog(bot=mock_bot)
        
        feedback_data = {
            'target_type': 'badge',
            'target_id': 123,
            'feedback_type': 'appreciation',
            'rating': 5
        }
        
        card = dialog._create_confirmation_card(feedback_data)
        
        assert card['type'] == 'AdaptiveCard'
        assert 'Feedback Submitted' in str(card)


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
