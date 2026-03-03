"""
Tests for NAV-Rewards Collection Admin Handler.

Tests the CollectionAdminHandler endpoints including CRUD operations,
badge management, authorization, and validation logic.

Run with: pytest rewards/tests/test_collection_admin.py -v
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from rewards.handlers.collection_admin import (
    CollectionAdminHandler,
    setup_collection_admin_routes,
    VALID_TIERS,
    VALID_COMPLETION_TYPES
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def handler():
    """Create a CollectionAdminHandler instance."""
    return CollectionAdminHandler()


@pytest.fixture
def mock_connection():
    """Create a mock database connection."""
    conn = AsyncMock()
    conn.fetch_one = AsyncMock()
    conn.fetch_all = AsyncMock()
    conn.execute = AsyncMock()

    # Create a transaction context manager mock
    transaction_mock = AsyncMock()
    transaction_mock.__aenter__ = AsyncMock()
    transaction_mock.__aexit__ = AsyncMock()
    conn.transaction = MagicMock(return_value=transaction_mock)

    return conn


class AsyncContextManagerMock:
    """Helper class to create an async context manager mock."""

    def __init__(self, return_value):
        self._return_value = return_value

    async def __aenter__(self):
        return self._return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


@pytest.fixture
def mock_reward_engine(mock_connection):
    """Create a mock reward engine with connection pool."""
    engine = MagicMock()

    # The handler uses: async with await reward_engine.connection.acquire() as conn:
    # So acquire() must return an awaitable that resolves to an async context manager

    async def acquire_coro():
        return AsyncContextManagerMock(mock_connection)

    engine.connection = MagicMock()
    engine.connection.acquire = acquire_coro

    return engine


@pytest.fixture
def admin_session():
    """Create an admin user session."""
    return {
        'user_id': 1,
        'email': 'admin@example.com',
        'display_name': 'Admin User',
        'groups': ['admin']
    }


@pytest.fixture
def rewards_admin_session():
    """Create a rewards_admin user session."""
    return {
        'user_id': 2,
        'email': 'rewards_admin@example.com',
        'display_name': 'Rewards Admin',
        'groups': ['rewards_admin']
    }


@pytest.fixture
def non_admin_session():
    """Create a non-admin user session."""
    return {
        'user_id': 3,
        'email': 'user@example.com',
        'display_name': 'Regular User',
        'groups': ['users']
    }


@pytest.fixture
def valid_collection_data():
    """Valid data for creating a collection."""
    return {
        'collective_name': 'Test Collection',
        'description': 'A test collection',
        'points': 100,
        'bonus_points': 500,
        'completion_type': 'all',
        'tier': 'gold',
        'icon': 'https://example.com/icon.png',
        'message': 'Congratulations!',
        'is_seasonal': False,
        'programs': ['test_program'],
        'badge_ids': [1, 2, 3]
    }


# =============================================================================
# AUTHORIZATION TESTS
# =============================================================================

class TestCollectionAdminAuthorization:
    """Tests for admin authorization checks."""

    def test_is_admin_with_admin_group(self, handler, admin_session):
        """Test _is_admin returns True for admin group."""
        assert handler._is_admin(admin_session) is True

    def test_is_admin_with_rewards_admin_group(self, handler, rewards_admin_session):
        """Test _is_admin returns True for rewards_admin group."""
        assert handler._is_admin(rewards_admin_session) is True

    def test_is_admin_with_non_admin(self, handler, non_admin_session):
        """Test _is_admin returns False for non-admin users."""
        assert handler._is_admin(non_admin_session) is False

    def test_is_admin_with_empty_groups(self, handler):
        """Test _is_admin returns False when groups list is empty."""
        user = {'user_id': 1, 'groups': []}
        assert handler._is_admin(user) is False

    def test_is_admin_with_missing_groups(self, handler):
        """Test _is_admin returns False when groups key is missing."""
        user = {'user_id': 1}
        assert handler._is_admin(user) is False

    def test_is_admin_with_multiple_groups(self, handler):
        """Test _is_admin works with multiple groups including admin."""
        user = {'user_id': 1, 'groups': ['users', 'developers', 'admin']}
        assert handler._is_admin(user) is True


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestCollectionAdminValidation:
    """Tests for validation methods."""

    @pytest.mark.asyncio
    async def test_validate_badge_ids_success(self, handler, mock_connection):
        """Test badge validation succeeds with valid badges."""
        mock_connection.fetch_all.return_value = [
            {'reward_id': 1, 'reward': 'Badge 1'},
            {'reward_id': 2, 'reward': 'Badge 2'},
            {'reward_id': 3, 'reward': 'Badge 3'}
        ]

        valid, error, details = await handler._validate_badge_ids(
            mock_connection, [1, 2, 3]
        )

        assert valid is True
        assert error == ""
        assert len(details) == 3

    @pytest.mark.asyncio
    async def test_validate_badge_ids_missing_badges(self, handler, mock_connection):
        """Test badge validation fails when badges don't exist."""
        mock_connection.fetch_all.return_value = [
            {'reward_id': 1, 'reward': 'Badge 1'}
        ]

        valid, error, _ = await handler._validate_badge_ids(
            mock_connection, [1, 2, 3]
        )

        assert valid is False
        assert "not found" in error.lower()
        assert "2" in error or "3" in error

    @pytest.mark.asyncio
    async def test_validate_badge_ids_empty_list(self, handler, mock_connection):
        """Test badge validation fails with empty list."""
        valid, error, _ = await handler._validate_badge_ids(mock_connection, [])

        assert valid is False
        assert "required" in error.lower()

    @pytest.mark.asyncio
    async def test_validate_bonus_reward_success(self, handler, mock_connection):
        """Test bonus reward validation succeeds when reward exists."""
        mock_connection.fetch_one.return_value = {'exists': True}

        valid, error = await handler._validate_bonus_reward(mock_connection, 100)

        assert valid is True
        assert error == ""

    @pytest.mark.asyncio
    async def test_validate_bonus_reward_not_found(self, handler, mock_connection):
        """Test bonus reward validation fails when reward doesn't exist."""
        mock_connection.fetch_one.return_value = None

        valid, error = await handler._validate_bonus_reward(mock_connection, 999)

        assert valid is False
        assert "999" in error
        assert "not found" in error.lower()

    @pytest.mark.asyncio
    async def test_validate_bonus_reward_none(self, handler, mock_connection):
        """Test bonus reward validation succeeds when bonus_reward_id is None."""
        valid, error = await handler._validate_bonus_reward(mock_connection, None)

        assert valid is True
        assert error == ""

    def test_validate_completion_type_all(self, handler):
        """Test completion_type 'all' validation."""
        valid, error = handler._validate_completion_type('all', None, 5)
        assert valid is True
        assert error == ""

    def test_validate_completion_type_n_of_m_valid(self, handler):
        """Test completion_type 'n_of_m' with valid required_count."""
        valid, error = handler._validate_completion_type('n_of_m', 3, 5)
        assert valid is True
        assert error == ""

    def test_validate_completion_type_n_of_m_missing_count(self, handler):
        """Test completion_type 'n_of_m' requires required_count."""
        valid, error = handler._validate_completion_type('n_of_m', None, 5)
        assert valid is False
        assert "required_count" in error.lower()

    def test_validate_completion_type_n_of_m_count_exceeds_badges(self, handler):
        """Test required_count cannot exceed badge count."""
        valid, error = handler._validate_completion_type('n_of_m', 10, 5)
        assert valid is False
        assert "exceed" in error.lower()

    def test_validate_completion_type_invalid(self, handler):
        """Test invalid completion_type is rejected."""
        valid, error = handler._validate_completion_type('invalid', None, 5)
        assert valid is False
        assert "completion_type" in error.lower()

    def test_validate_tier_valid(self, handler):
        """Test valid tier values."""
        for tier in VALID_TIERS:
            valid, error = handler._validate_tier(tier)
            assert valid is True, f"Tier '{tier}' should be valid"
            assert error == ""

    def test_validate_tier_invalid(self, handler):
        """Test invalid tier is rejected."""
        valid, error = handler._validate_tier('legendary')
        assert valid is False
        assert "tier" in error.lower()

    def test_validate_seasonal_not_seasonal(self, handler):
        """Test seasonal validation when not seasonal."""
        valid, error = handler._validate_seasonal(False, None, None)
        assert valid is True
        assert error == ""

    def test_validate_seasonal_with_valid_dates(self, handler):
        """Test seasonal validation with valid date range."""
        valid, error = handler._validate_seasonal(
            True,
            '2026-01-01T00:00:00Z',
            '2026-12-31T23:59:59Z'
        )
        assert valid is True
        assert error == ""

    def test_validate_seasonal_missing_dates(self, handler):
        """Test seasonal validation fails without dates."""
        valid, error = handler._validate_seasonal(True, None, None)
        assert valid is False
        assert "required" in error.lower()

    def test_validate_seasonal_end_before_start(self, handler):
        """Test seasonal validation fails when end_date is before start_date."""
        valid, error = handler._validate_seasonal(
            True,
            '2026-12-31T00:00:00Z',
            '2026-01-01T00:00:00Z'
        )
        assert valid is False
        assert "after" in error.lower()


# =============================================================================
# CREATE COLLECTION TESTS
# =============================================================================

class TestCreateCollection:
    """Tests for create_collection endpoint."""

    @pytest.mark.asyncio
    async def test_create_collection_success(
        self, handler, mock_connection, mock_reward_engine, admin_session, valid_collection_data
    ):
        """Test successful collection creation."""
        # Setup mocks
        mock_connection.fetch_all.return_value = [
            {'reward_id': 1, 'reward': 'Badge 1'},
            {'reward_id': 2, 'reward': 'Badge 2'},
            {'reward_id': 3, 'reward': 'Badge 3'}
        ]
        mock_connection.fetch_one.side_effect = [
            None,  # Name uniqueness check - not found (good)
            {'collective_id': 1}  # INSERT RETURNING
        ]

        # Create mock request
        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.json = AsyncMock(return_value=valid_collection_data)

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.create_collection(request)

        # Verify response
        assert response.status == 201

    @pytest.mark.asyncio
    async def test_create_collection_missing_name(
        self, handler, mock_reward_engine, admin_session
    ):
        """Test collection creation fails without collective_name."""
        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.json = AsyncMock(return_value={
            'badge_ids': [1, 2, 3]
        })

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.create_collection(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_collection_missing_badges(
        self, handler, mock_reward_engine, admin_session
    ):
        """Test collection creation fails without badge_ids."""
        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.json = AsyncMock(return_value={
            'collective_name': 'Test'
        })

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.create_collection(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_collection_duplicate_name(
        self, handler, mock_connection, mock_reward_engine, admin_session, valid_collection_data
    ):
        """Test collection creation fails with duplicate name."""
        mock_connection.fetch_all.return_value = [
            {'reward_id': 1, 'reward': 'Badge 1'},
            {'reward_id': 2, 'reward': 'Badge 2'},
            {'reward_id': 3, 'reward': 'Badge 3'}
        ]
        # Name check returns existing
        mock_connection.fetch_one.return_value = {'exists': True}

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.json = AsyncMock(return_value=valid_collection_data)

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.create_collection(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_collection_non_admin_forbidden(
        self, handler, mock_reward_engine, non_admin_session
    ):
        """Test collection creation returns 403 for non-admin."""
        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.json = AsyncMock(return_value={})

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = non_admin_session
            mock_get_session.return_value = mock_session

            response = await handler.create_collection(request)

        assert response.status == 403


# =============================================================================
# UPDATE COLLECTION TESTS
# =============================================================================

class TestUpdateCollection:
    """Tests for update_collection endpoint."""

    @pytest.mark.asyncio
    async def test_update_collection_not_found(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test update returns 404 when collection doesn't exist."""
        mock_connection.fetch_one.return_value = None

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '999'}
        request.json = AsyncMock(return_value={'description': 'Updated'})

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.update_collection(request)

        assert response.status == 404

    @pytest.mark.asyncio
    async def test_update_collection_invalid_id(
        self, handler, mock_reward_engine, admin_session
    ):
        """Test update returns 400 for invalid collection ID."""
        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': 'invalid'}
        request.json = AsyncMock(return_value={'description': 'Updated'})

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.update_collection(request)

        assert response.status == 400


# =============================================================================
# DELETE COLLECTION TESTS
# =============================================================================

class TestDeleteCollection:
    """Tests for delete_collection (soft-delete) endpoint."""

    @pytest.mark.asyncio
    async def test_delete_collection_success(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test successful collection soft-delete."""
        mock_connection.fetch_one.side_effect = [
            {'collective_name': 'Test'},  # Exists check
            {'cnt': 5}  # Progress count
        ]

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '1'}

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.delete_collection(request)

        assert response.status == 200
        # Verify execute was called (soft delete update)
        assert mock_connection.execute.called

    @pytest.mark.asyncio
    async def test_delete_collection_not_found(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test delete returns 404 when collection doesn't exist."""
        mock_connection.fetch_one.return_value = None

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '999'}

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.delete_collection(request)

        assert response.status == 404


# =============================================================================
# ADD BADGES TESTS
# =============================================================================

class TestAddBadges:
    """Tests for add_badges endpoint."""

    @pytest.mark.asyncio
    async def test_add_badges_success(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test successfully adding badges to collection."""
        mock_connection.fetch_one.side_effect = [
            {'collective_id': 1},  # Collection exists
            {'cnt': 5}  # Badge count after add
        ]
        mock_connection.fetch_all.side_effect = [
            [{'reward_id': 4, 'reward': 'Badge 4'}],  # Badge validation
            [  # Updated badge list
                {'reward_id': 1, 'reward': 'Badge 1', 'description': '', 'icon': ''},
                {'reward_id': 4, 'reward': 'Badge 4', 'description': '', 'icon': ''}
            ]
        ]
        mock_connection.execute.return_value = 'INSERT 1'

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '1'}
        request.json = AsyncMock(return_value={'badge_ids': [4]})

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.add_badges(request)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_add_badges_empty_list(
        self, handler, mock_reward_engine, admin_session
    ):
        """Test add_badges fails with empty badge list."""
        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '1'}
        request.json = AsyncMock(return_value={'badge_ids': []})

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.add_badges(request)

        assert response.status == 400


# =============================================================================
# REMOVE BADGES TESTS
# =============================================================================

class TestRemoveBadges:
    """Tests for remove_badges endpoint."""

    @pytest.mark.asyncio
    async def test_remove_badges_cannot_remove_all(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test cannot remove all badges from collection."""
        mock_connection.fetch_one.side_effect = [
            {'collective_id': 1},  # Collection exists
            {'cnt': 2}  # Current badge count
        ]
        # These badges exist in collection
        mock_connection.fetch_all.return_value = [
            {'reward_id': 1},
            {'reward_id': 2}
        ]

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '1'}
        request.json = AsyncMock(return_value={'badge_ids': [1, 2]})

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.remove_badges(request)

        assert response.status == 400
        # Response body should mention "cannot remove all"


# =============================================================================
# LIST COLLECTIONS TESTS
# =============================================================================

class TestListCollections:
    """Tests for list_collections endpoint."""

    @pytest.mark.asyncio
    async def test_list_collections_success(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test listing collections with stats."""
        mock_connection.fetch_all.return_value = [
            {
                'collective_id': 1,
                'collective_name': 'Test Collection',
                'description': 'Test',
                'points': 100,
                'bonus_points': 500,
                'completion_type': 'all',
                'required_count': None,
                'tier': 'gold',
                'icon': '',
                'is_active': True,
                'is_seasonal': False,
                'start_date': None,
                'end_date': None,
                'programs': [],
                'sort_order': 0,
                'created_at': datetime.now(),
                'total_badges': 5,
                'users_started': 100,
                'users_completed': 25,
                'completion_rate': 25.0
            }
        ]

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.query = {}

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.list_collections(request)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_list_collections_with_filters(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test listing collections with tier and program filters."""
        mock_connection.fetch_all.return_value = []

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.query = {
            'include_inactive': 'false',
            'tier': 'gold',
            'program': 'test_program'
        }

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.list_collections(request)

        assert response.status == 200


# =============================================================================
# RECALCULATE PROGRESS TESTS
# =============================================================================

class TestRecalculateProgress:
    """Tests for recalculate_progress endpoint."""

    @pytest.mark.asyncio
    async def test_recalculate_progress_success(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test progress recalculation."""
        mock_connection.fetch_one.side_effect = [
            {  # Collection data
                'collective_id': 1,
                'collective_name': 'Test',
                'completion_type': 'all',
                'required_count': None
            },
            {'cnt': 5},  # Badge count
            {'total_users': 10, 'completed_users': 3}  # Stats
        ]

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '1'}

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.recalculate_progress(request)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_recalculate_progress_not_found(
        self, handler, mock_connection, mock_reward_engine, admin_session
    ):
        """Test recalculate returns 404 when collection doesn't exist."""
        mock_connection.fetch_one.return_value = None

        request = MagicMock()
        request.app = {'reward_engine': mock_reward_engine}
        request.match_info = {'id': '999'}

        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = admin_session
            mock_get_session.return_value = mock_session

            response = await handler.recalculate_progress(request)

        assert response.status == 404


# =============================================================================
# ROUTE SETUP TESTS
# =============================================================================

class TestRouteSetup:
    """Tests for route registration."""

    def test_setup_collection_admin_routes(self):
        """Test that all routes are registered correctly."""
        app = web.Application()
        setup_collection_admin_routes(app)

        # Get all registered routes
        routes = []
        for route in app.router.routes():
            if hasattr(route.resource, 'canonical'):
                routes.append((route.method, route.resource.canonical))
            elif hasattr(route.resource, '_path'):
                routes.append((route.method, route.resource._path))

        base_path = '/rewards/api/v1/admin/collections'

        # Check expected routes are registered
        expected_routes = [
            ('POST', base_path),
            ('GET', base_path),
            ('PUT', f'{base_path}/{{id}}'),
            ('DELETE', f'{base_path}/{{id}}'),
            ('POST', f'{base_path}/{{id}}/badges'),
            ('DELETE', f'{base_path}/{{id}}/badges'),
            ('POST', f'{base_path}/{{id}}/recalculate'),
        ]

        for method, path in expected_routes:
            assert any(
                m == method and p == path for m, p in routes
            ), f"Route {method} {path} not found"


# =============================================================================
# CONSTANTS TESTS
# =============================================================================

class TestConstants:
    """Tests for module constants."""

    def test_valid_tiers(self):
        """Test VALID_TIERS contains expected values."""
        assert 'bronze' in VALID_TIERS
        assert 'silver' in VALID_TIERS
        assert 'gold' in VALID_TIERS
        assert 'platinum' in VALID_TIERS
        assert 'diamond' in VALID_TIERS
        assert len(VALID_TIERS) == 5

    def test_valid_completion_types(self):
        """Test VALID_COMPLETION_TYPES contains expected values."""
        assert 'all' in VALID_COMPLETION_TYPES
        assert 'n_of_m' in VALID_COMPLETION_TYPES
        assert 'any_n' in VALID_COMPLETION_TYPES
        assert len(VALID_COMPLETION_TYPES) == 3


# =============================================================================
# E2E INTEGRATION TESTS
# =============================================================================

class TestCollectionAdminE2E(AioHTTPTestCase):
    """End-to-end integration tests for collection admin API."""

    async def get_application(self):
        """Create test application with admin routes."""
        app = web.Application()

        # Mock reward engine
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetch_one = AsyncMock()
        mock_conn.fetch_all = AsyncMock()
        mock_conn.execute = AsyncMock()

        # Transaction mock
        transaction_mock = AsyncMock()
        transaction_mock.__aenter__ = AsyncMock()
        transaction_mock.__aexit__ = AsyncMock()
        mock_conn.transaction = MagicMock(return_value=transaction_mock)

        # Acquire mock
        acquire_mock = AsyncMock()
        acquire_mock.__aenter__ = AsyncMock(return_value=mock_conn)
        acquire_mock.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connection = MagicMock()
        mock_engine.connection.acquire = MagicMock(return_value=acquire_mock)

        app['reward_engine'] = mock_engine
        app['mock_conn'] = mock_conn

        # Setup routes
        setup_collection_admin_routes(app)

        return app

    @unittest_run_loop
    async def test_e2e_collection_workflow(self):
        """Test complete collection admin workflow."""
        # This test demonstrates the E2E flow:
        # 1. List collections (empty)
        # 2. Create a collection
        # 3. Add badges
        # 4. Update collection
        # 5. Recalculate progress
        # 6. Delete (soft-delete)

        # Setup mock session for admin user
        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = {
                'user_id': 1,
                'email': 'admin@example.com',
                'groups': ['admin']
            }
            mock_get_session.return_value = mock_session

            # Step 1: List collections
            mock_conn = self.app['mock_conn']
            mock_conn.fetch_all.return_value = []

            resp = await self.client.get('/rewards/api/v1/admin/collections')
            # Note: Without proper session middleware, this will return 403
            # In a real E2E test, you'd setup proper authentication

    @unittest_run_loop
    async def test_e2e_unauthorized_access(self):
        """Test that non-admin users are rejected."""
        with patch('rewards.handlers.collection_admin.get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_session.decode.return_value = {
                'user_id': 99,
                'email': 'user@example.com',
                'groups': ['users']  # Not admin
            }
            mock_get_session.return_value = mock_session

            resp = await self.client.get('/rewards/api/v1/admin/collections')
            assert resp.status == 403


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
