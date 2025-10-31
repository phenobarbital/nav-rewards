# Kudos Recognition System - Integration Guide

## Overview

The Kudos system provides a lightweight recognition platform that complements your existing badge/reward system. It allows users to send quick recognition messages with hashtag-style tags to celebrate specific qualities and behaviors.

## Key Features

### ✅ Core Functionality
- **Quick Recognition**: Send kudos with message and quality tags
- **Predefined Tags**: Curated list of common recognition qualities
- **Custom Tags**: Users can create their own recognition tags
- **Tag Trending**: Track most popular recognition qualities
- **User Statistics**: Track kudos given/received per user
- **Bot Integration**: Seamless `/kudos` command in Teams

### ✅ Database Design
- **users_kudos**: Main kudos storage with user relationships
- **kudos_tags**: Predefined tags with usage tracking
- **Views**: Ready-made views for trending analysis and user stats

## Installation Steps

### 1. Database Setup

Run the SQL schema from the handlers artifact:

```sql
-- Copy and execute the CREATE_KUDOS_TABLES_SQL from kudos_handlers.py
```

### 2. Model Integration

Add to your `models.py`:

```python
# Add imports for new models
from .kudos_models import UserKudos, KudosTag, INITIAL_KUDOS_TAGS
```

### 3. Handler Registration

Add to your `engine.py` setup method:

```python
# Import handlers
from .kudos_handlers import UserKudosHandler, KudosTagHandler

# Register routes in setup method
UserKudosHandler.configure(
    self.app, '/rewards/api/v1/user_kudos'
)
KudosTagHandler.configure(
    self.app, '/rewards/api/v1/kudos_tags'
)
```

### 4. Bot Integration

Replace your existing `badge.py` with the updated version that includes:
- KudosDialog import and registration
- `/kudos` command handling
- Kudos submission processing

### 5. Dialog Registration

The updated BadgeBot automatically registers both dialogs:
- `BadgeDialog` for badge assignments
- `KudosDialog` for kudos recognition

## Usage Examples

### Sending Kudos via Bot

1. User types `/kudos` in Teams
2. Bot asks for recipient selection
3. User enters name/email
4. Bot shows kudos form with:
   - Message input
   - Predefined tag selection (multi-select)
   - Custom tag input
5. User submits kudos
6. System saves to database and updates tag usage

### Tag System

**Predefined Tags**: Helpful, Inspirational, Fair, Creative, Reliable, etc.
**Custom Tags**: Users can add their own (automatically get # prefix)
**Trending**: Most used tags appear first in selection

## API Endpoints

### Kudos Management
- `GET /rewards/api/v1/user_kudos` - List all kudos
- `POST /rewards/api/v1/user_kudos` - Create new kudos
- `GET /rewards/api/v1/user_kudos/{id}` - Get specific kudos

### Tag Management
- `GET /rewards/api/v1/kudos_tags` - List all tags
- `POST /rewards/api/v1/kudos_tags` - Create new tag
- `PUT /rewards/api/v1/kudos_tags/{id}` - Update tag

## Database Views

### Trending Tags View
```sql
-- Shows most popular tags in last 30 days
SELECT * FROM rewards.vw_trending_tags;
```

### User Statistics View
```sql
-- Shows kudos stats per user
SELECT * FROM rewards.vw_user_kudos_stats
WHERE user_id = 123;
```

## Customization Options

### Tag Categories
Modify the `category` field in `kudos_tags` to group tags:
- `support` - Helping behaviors
- `leadership` - Leadership qualities
- `innovation` - Creative/innovative actions
- `teamwork` - Collaboration behaviors
- `values` - Value-based recognition

### Message Templates
Add message templates or suggestions in the dialog card for common recognition scenarios.

### Privacy Controls
The `is_public` field allows for private kudos that only sender/receiver can see.

## Future Enhancements

### Analytics Dashboard
Create views showing:
- Most recognized users
- Trending recognition qualities
- Recognition patterns by department/team
- Recognition frequency over time

### Notifications
Integrate with your notification system to:
- Notify users when they receive kudos
- Send periodic "kudos digest" summaries
- Alert managers about team recognition patterns

### Recognition Campaigns
Create themed recognition campaigns:
- "Customer Service Week" - boost service-related tags
- "Innovation Month" - highlight creative contributions
- "Team Spirit" - focus on collaboration tags

### Mobile Support
The adaptive cards work in Teams mobile, providing full kudos functionality on mobile devices.

## Testing

### Manual Testing
1. Start bot conversation: `/kudos`
2. Try finding users by name and email
3. Test both predefined and custom tags
4. Verify database storage
5. Check tag usage count updates

### Database Validation
```sql
-- Check kudos creation
SELECT * FROM rewards.users_kudos ORDER BY sent_at DESC LIMIT 5;

-- Check tag usage updates
SELECT * FROM rewards.kudos_tags ORDER BY usage_count DESC;

-- Check user stats
SELECT * FROM rewards.vw_user_kudos_stats WHERE kudos_received > 0;
```

## Troubleshooting

### Common Issues

**Bot Not Responding to /kudos**
- Check KudosDialog is registered in BadgeBot setup
- Verify import paths for KudosDialog
- Check bot command list includes '/kudos'

**Database Errors**
- Ensure kudos tables are created
- Check foreign key constraints to auth.users
- Verify user_id fields match your user table

**Tag Usage Not Updating**
- Check update_tag_usage_counts function
- Verify tag name normalization
- Ensure database connection in submission handler

### Debug Logging
Enable debug logging in bot:
```python
self.logger.setLevel(logging.DEBUG)
```

## Performance Considerations

- Tag usage updates are async and won't block kudos sending
- GIN index on tags array enables fast tag searching
- Views are optimized for common query patterns
- Consider partitioning kudos table by date for large volumes

## Security

- All kudos require authenticated users (both sender and receiver)
- Self-kudos are prevented in submission handler
- Tags are sanitized to prevent injection
- Optional public/private flag for kudos visibility
