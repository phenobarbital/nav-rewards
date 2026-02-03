# NAV-Rewards Feedback System

## Overview

The Feedback System is a comprehensive module for NAV-Rewards that allows users to provide structured feedback on recognition they've received or witnessed. Unlike simple likes or comments, feedback includes point incentives that encourage meaningful engagement.

### Key Features

- **Polymorphic Targets**: Feedback on badges, kudos, and nominations
- **Structured Feedback Types**: Predefined categories with usage tracking
- **Point Incentives**: 5 pts to giver, 10 pts to receiver
- **Optional Ratings**: 1-5 star rating system
- **Anti-Spam Protection**: Cooldowns and daily limits
- **MS Teams Integration**: Full bot dialog support
- **Comprehensive Analytics**: Stats, trends, and leaderboards

---

## Quick Start

### 1. Run Database Migration

```bash
psql -U your_user -d your_database -f feedback_schema.sql
```

### 2. Add to RewardsEngine

```python
# In rewards/engine/engine.py

from ..feedback import (
    FeedbackTypeHandler,
    UserFeedbackHandler,
    FeedbackStatsHandler,
    FeedbackManager
)

# In setup() method:
FeedbackTypeHandler.configure(self.app, '/rewards/api/v1/feedback_types')
UserFeedbackHandler.configure(self.app, '/rewards/api/v1/user_feedback')
FeedbackStatsHandler.configure(self.app, '/rewards/api/v1/feedback_stats')

# Initialize manager
self.feedback_manager = FeedbackManager(self.app, self)
```

### 3. Initialize on Startup

```python
# In reward_startup() method:
async with await self.connection.acquire() as conn:
    await self.feedback_manager.initialize_database(conn)
```

---

## Points System

| Action | Giver Points | Receiver Points |
|--------|--------------|-----------------|
| Submit Feedback | +5 | +10 |

The point distribution encourages:
- **Engagement**: Users earn points for providing feedback
- **Quality Recognition**: Receivers benefit from positive feedback

Points are automatically awarded via database trigger when feedback is created.

---

## Database Schema

### Tables

#### `rewards.feedback_types`
Predefined feedback categories.

| Column | Type | Description |
|--------|------|-------------|
| feedback_type_id | SERIAL | Primary key |
| type_name | VARCHAR(50) | Unique identifier |
| display_name | VARCHAR(100) | Human-readable name |
| description | TEXT | Detailed description |
| emoji | VARCHAR(10) | Visual representation |
| category | VARCHAR(50) | Grouping category |
| usage_count | INT | Times used |
| is_active | BOOLEAN | Available for selection |

#### `rewards.user_feedback`
Main feedback storage.

| Column | Type | Description |
|--------|------|-------------|
| feedback_id | BIGSERIAL | Primary key |
| target_type | VARCHAR(20) | 'badge', 'kudos', 'nomination' |
| target_id | BIGINT | ID of target item |
| giver_user_id | BIGINT | User giving feedback |
| receiver_user_id | BIGINT | User who received recognition |
| feedback_type_id | INT | FK to feedback_types |
| rating | SMALLINT | 1-5 star rating (optional) |
| message | TEXT | Optional message (max 500) |
| points_given | INT | Points to giver (default 5) |
| points_received | INT | Points to receiver (default 10) |
| created_at | TIMESTAMPTZ | Creation timestamp |

#### `rewards.feedback_cooldowns`
Anti-spam tracking.

| Column | Type | Description |
|--------|------|-------------|
| cooldown_id | BIGSERIAL | Primary key |
| user_id | BIGINT | User ID |
| target_type | VARCHAR(20) | Target type |
| last_feedback_at | TIMESTAMPTZ | Last submission time |
| feedback_count_today | INT | Daily count |

### Views

- `vw_user_feedback` - Full feedback details with user names
- `vw_trending_feedback_types` - Trending types (last 30 days)
- `vw_user_feedback_stats` - User statistics
- `vw_feedback_by_target` - Summary per target

---

## API Reference

### Feedback Types

#### List Feedback Types
```
GET /rewards/api/v1/feedback_types
```

Response:
```json
[
    {
        "feedback_type_id": 1,
        "type_name": "appreciation",
        "display_name": "Appreciation",
        "emoji": "🙏",
        "category": "gratitude",
        "usage_count": 150
    }
]
```

#### Get Trending Types
```
GET /rewards/api/v1/feedback_types/trending
```

### User Feedback

#### Submit Feedback
```
POST /rewards/api/v1/user_feedback
Content-Type: application/json

{
    "target_type": "badge",
    "target_id": 12345,
    "feedback_type_id": 1,
    "rating": 5,
    "message": "This recognition was well deserved!"
}
```

Response:
```json
{
    "feedback": {
        "feedback_id": 100,
        "target_type": "badge",
        "target_id": 12345,
        "giver_user_id": 42,
        "receiver_user_id": 87,
        "feedback_type_id": 1,
        "rating": 5,
        "message": "This recognition was well deserved!",
        "points_given": 5,
        "points_received": 10,
        "created_at": "2026-01-16T10:30:00Z"
    },
    "points_awarded": {
        "giver": 5,
        "receiver": 10
    },
    "message": "Feedback submitted! You earned 5 points."
}
```

#### Get Feedback for Target
```
GET /rewards/api/v1/user_feedback/target/badge/12345
```

Response:
```json
{
    "feedback": [
        {
            "feedback_id": 100,
            "giver_display_name": "John Doe",
            "feedback_type_display": "Appreciation",
            "feedback_emoji": "🙏",
            "rating": 5,
            "message": "Great work!",
            "created_at": "2026-01-16T10:30:00Z"
        }
    ],
    "summary": {
        "feedback_count": 5,
        "avg_rating": 4.6,
        "feedback_types": ["appreciation", "impact", "teamwork"]
    }
}
```

#### Get User's Given Feedback
```
GET /rewards/api/v1/user_feedback/user/42/given?limit=20&offset=0
```

#### Get User's Received Feedback
```
GET /rewards/api/v1/user_feedback/user/42/received?limit=20&offset=0
```

### Statistics

#### Global Stats
```
GET /rewards/api/v1/feedback_stats
```

Response:
```json
{
    "total_feedback": 1500,
    "unique_givers": 250,
    "unique_receivers": 300,
    "total_points_given": 7500,
    "total_points_received": 15000,
    "avg_rating": 4.3,
    "badge_feedback": 800,
    "kudos_feedback": 500,
    "nomination_feedback": 200
}
```

#### User Stats
```
GET /rewards/api/v1/feedback_stats/user/42
```

#### Leaderboard
```
GET /rewards/api/v1/feedback_stats/leaderboard?type=received&limit=10
```

---

## Predefined Feedback Types

| Type | Display | Emoji | Category |
|------|---------|-------|----------|
| appreciation | Appreciation | 🙏 | gratitude |
| impact | Great Impact | 💥 | performance |
| inspiring | Inspiring | ✨ | motivation |
| well_deserved | Well Deserved | 🏆 | validation |
| teamwork | Team Player | 🤝 | collaboration |
| growth | Shows Growth | 📈 | development |
| leadership | Leadership | 👑 | leadership |
| innovation | Innovative | 💡 | innovation |
| dedication | Dedication | 💪 | commitment |
| excellence | Excellence | ⭐ | quality |

---

## MS Teams Bot Integration

### Add to BadgeBot

```python
# In rewards/bot/badge.py

from ..feedback.dialogs import FeedbackDialog

class BadgeBot(AbstractBot):
    def __init__(self, ...):
        # ... existing code ...
        
        # Add feedback dialog
        self.feedback_dialog = FeedbackDialog(
            bot=self,
            submission_callback=self.handle_feedback_submission
        )
    
    def setup(self, app):
        super().setup(app)
        self.dialog_set.add(self.feedback_dialog)
    
    async def on_message_activity(self, turn_context):
        text = turn_context.activity.text
        
        if text and text.lower().strip() == '/feedback':
            await self.start_feedback_dialog(turn_context)
            return
        
        # ... existing code ...
    
    async def start_feedback_dialog(self, turn_context):
        dialog_context = await self.dialog_set.create_context(turn_context)
        if dialog_context.active_dialog is None:
            await dialog_context.begin_dialog(self.feedback_dialog.id)
        await self.save_state_changes(turn_context)
    
    async def handle_feedback_submission(self, turn_context, feedback_data):
        # Process feedback submission
        pass
```

### Bot Commands

| Command | Description |
|---------|-------------|
| `/feedback` | Start feedback dialog |
| `/help` | Show all commands including feedback |

---

## Validation Rules

### Anti-Spam Protection

1. **No Self-Feedback**: Users cannot give feedback on their own recognition
2. **One Per Target**: Only one feedback per user per target
3. **Cooldown Period**: Minimum 1 minute between submissions
4. **Daily Limit**: Maximum 20 feedback submissions per day

### Input Validation

- `target_type`: Must be 'badge', 'kudos', or 'nomination'
- `rating`: If provided, must be between 1 and 5
- `message`: Maximum 500 characters

---

## Configuration

### Environment Variables

```bash
# Points configuration (optional - defaults shown)
FEEDBACK_POINTS_GIVER=5
FEEDBACK_POINTS_RECEIVER=10
FEEDBACK_MAX_PER_DAY=20
FEEDBACK_COOLDOWN_MINUTES=1
```

### Programmatic Configuration

```python
from rewards.feedback.models import (
    POINTS_FOR_GIVER,
    POINTS_FOR_RECEIVER,
    MAX_FEEDBACK_PER_DAY,
    COOLDOWN_MINUTES
)

# Override in your configuration
POINTS_FOR_GIVER = 10
POINTS_FOR_RECEIVER = 20
```

---

## Error Handling

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Validation error |
| 403 | Not authorized |
| 404 | Not found |
| 409 | Duplicate feedback |
| 429 | Rate limited (cooldown) |
| 500 | Server error |

### Error Response Format

```json
{
    "error": "You have already given feedback on this item"
}
```

---

## Analytics & Reporting

### SQL Queries for Reports

#### Top Feedback Givers
```sql
SELECT * FROM rewards.vw_user_feedback_stats
ORDER BY feedback_given DESC
LIMIT 10;
```

#### Most Appreciated Badges
```sql
SELECT target_id, feedback_count, avg_rating
FROM rewards.vw_feedback_by_target
WHERE target_type = 'badge'
ORDER BY feedback_count DESC
LIMIT 10;
```

#### Feedback Trends (Last 7 Days)
```sql
SELECT 
    DATE(created_at) as date,
    COUNT(*) as feedback_count,
    AVG(rating) as avg_rating
FROM rewards.user_feedback
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
    AND is_active = TRUE
GROUP BY DATE(created_at)
ORDER BY date;
```

---

## Testing

### Unit Test Example

```python
import pytest
from rewards.feedback.models import UserFeedback, TargetType

def test_feedback_validation():
    # Test self-feedback prevention
    with pytest.raises(ValueError, match="Cannot give feedback"):
        UserFeedback(
            target_type="badge",
            target_id=1,
            giver_user_id=42,
            receiver_user_id=42  # Same as giver
        )

def test_rating_validation():
    # Test rating range
    with pytest.raises(ValueError, match="Rating must be"):
        UserFeedback(
            target_type="badge",
            target_id=1,
            giver_user_id=1,
            receiver_user_id=2,
            rating=6  # Invalid
        )
```

### API Test Example

```python
async def test_submit_feedback(client):
    response = await client.post(
        '/rewards/api/v1/user_feedback',
        json={
            'target_type': 'badge',
            'target_id': 123,
            'feedback_type_id': 1,
            'rating': 5
        }
    )
    assert response.status == 201
    data = await response.json()
    assert data['points_awarded']['giver'] == 5
```

---

## Migration from Existing System

If you're adding feedback to an existing nav-rewards installation:

1. **Backup Database**: Always backup before migrations
2. **Run DDL**: Execute `feedback_schema.sql`
3. **Update Engine**: Add handler registrations
4. **Update Bot**: Add feedback dialog
5. **Test**: Verify all endpoints work
6. **Deploy**: Roll out to production

---

## Support

For issues or feature requests, please contact the nav-rewards team or open an issue in the repository.
