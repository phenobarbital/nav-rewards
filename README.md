# NAV-Rewards

**Engine for sending Kudos and Rewards to users, built on top of aiohttp + navigator-api.**

[![PyPI version](https://badge.fury.io/py/nav-rewards.svg)](https://badge.fury.io/py/nav-rewards)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

NAV-Rewards is a complete rewards and recognition system that integrates seamlessly with aiohttp applications. It includes:

- 🎖️ **Badge System** - User-assignable and automated badges
- 🏆 **Achievement Tracking** - Rule-based achievements with custom conditions
- 📊 **Attendance Rewards** - Time-based and performance-based rewards
- 🎲 **Lottery System** - Random user selection with configurable rules
- 🎯 **Workflow Badges** - Multi-step achievement tracking
- 🗳️ **Nomination System** - Employee of the month style voting
- 💬 **Kudos System** - Quick peer-to-peer recognition
- ⏰ **Scheduler** - APScheduler-based automated reward evaluation
- 📧 **Notifications** - Email, MS Teams, and Telegram integration
- 📊 **Event Manager** - RabbitMQ-based event dispatching

---

## 📦 Installation

### Via pip

```bash
pip install nav-rewards
```

### With all optional dependencies

```bash
# Install with event manager (RabbitMQ) support
pip install nav-rewards[events]

# Install everything
pip install nav-rewards[all]
```

### From source

```bash
git clone https://github.com/phenobarbital/nav-rewards.git
cd nav-rewards
pip install -e .
```

---

## 🗄️ Database Setup

### Prerequisites

- **PostgreSQL 12+** (required)
- **Redis** (required for caching and session management)
- **RabbitMQ** (optional, for event management)

### 1. Create Database Schema

NAV-Rewards requires a PostgreSQL database with specific schemas. Run the DDL script:

```bash
psql -U your_user -d your_database -f rewards/docs/ddl.sql
```

Or manually execute the schema creation from `rewards/docs/ddl.sql`:

```sql
-- Create the rewards schema
CREATE SCHEMA rewards AUTHORIZATION your_user;

-- Create base tables
CREATE TABLE rewards.reward_categories (...);
CREATE TABLE rewards.reward_groups (...);
CREATE TABLE rewards.reward_types (...);
CREATE TABLE rewards.rewards (...);
CREATE TABLE rewards.users_rewards (...);
CREATE TABLE rewards.points (...);
-- ... (see ddl.sql for complete schema)
```

### 2. Database Configuration

Create an environment configuration file at `env/.env`:

```bash
# env/.env

# ============================================
# Database Configuration
# ============================================
DBHOST=localhost
DBPORT=5432
DBNAME=navigator
DBUSER=your_database_user
DBPWD=your_database_password

# ============================================
# Redis Configuration
# ============================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=1
REDIS_SESSION_DB=0

# ============================================
# RabbitMQ Configuration (Optional)
# ============================================
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# ============================================
# Rewards System
# ============================================
ENABLE_REWARDS=true
REWARD_SCHEDULER=true
REWARD_MIDDLEWARE=true
ENABLE_EVENT_MANAGER=true

# Timezone for scheduling
TIMEZONE=America/New_York

# ============================================
# MS Teams Integration (Optional)
# ============================================
REWARDS_CLIENT_ID=your_ms_teams_client_id
REWARDS_CLIENT_SECRET=your_ms_teams_client_secret
REWARDS_TENANT_ID=your_ms_teams_tenant_id
BOT_REWARDS_ID=your_bot_app_id
BOT_REWARDS_SECRET=your_bot_app_secret

# ============================================
# Notification Services (Optional)
# ============================================
# Email via SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_email_password

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# ============================================
# Application Settings
# ============================================
ENVIRONMENT=production
PRODUCTION=true
DEBUG=false
```

### Directory Structure

```
your-project/
├── env/
│   └── .env                  # Environment variables
├── my_rewards/
│   └── rewards.json          # Your reward definitions
├── rewards/                  # NAV-Rewards package
└── app.py                    # Your application
```

---

## 🚀 Quick Start

### 1. Basic Integration

```python
from aiohttp import web
from rewards.engine import RewardsEngine

# Create your aiohttp app
app = web.Application()

# Initialize Rewards Engine
rewards_engine = RewardsEngine(app)

# Setup routes and middleware
rewards_engine.setup()

# Register startup/shutdown handlers
app.on_startup.append(rewards_engine.reward_startup)
app.on_shutdown.append(rewards_engine.reward_shutdown)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=8080)
```

### 2. Load Rewards from JSON

Create `my_rewards/rewards.json`:

```json
[
    {
        "reward_id": 1001,
        "reward": "Welcome Badge",
        "description": "Welcome to the platform!",
        "points": 10,
        "reward_type": "Automated Badge",
        "reward_category": "Recognition",
        "reward_group": "Core Badges",
        "multiple": true,
        "icon": "https://example.com/welcome-badge.png"
    }
]
```

Load rewards on startup:

```python
from rewards.storages import JsonStorage

# In your rewards_engine setup
json_storage = JsonStorage(
    json_file='my_rewards/rewards.json'
)
await rewards_engine.add_storage(json_storage)
```

---

## 📝 Writing Rewards

### Reward Structure

Every reward has this basic structure:

```json
{
    "reward_id": 1000,
    "reward": "Badge Name",
    "description": "Badge description",
    "points": 100,
    "reward_type": "Badge Type",
    "reward_category": "Category",
    "reward_group": "Group Name",
    "multiple": false,
    "timeframe": null,
    "icon": "https://example.com/icon.png",
    "rules": [],
    "conditions": {},
    "availability_rule": {},
    "assigner": [],
    "awardee": []
}
```

### Core Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reward_id` | int | ✅ | Unique identifier |
| `reward` | string | ✅ | Display name |
| `description` | string | ❌ | Detailed description |
| `points` | int | ❌ | Points awarded (default: 10) |
| `reward_type` | string | ❌ | Type of reward (see below) |
| `reward_category` | string | ✅ | Category (must exist in DB) |
| `reward_group` | string | ❌ | Grouping for organization |
| `multiple` | bool | ❌ | Can be awarded multiple times (default: false) |
| `timeframe` | string | ❌ | Frequency: `daily`, `weekly`, `monthly`, `quarterly` |
| `icon` | string | ❌ | URL or path to badge icon |

### Reward Types

#### 1. **User Badge**
Manual badges that users can assign to each other.

```json
{
    "reward_id": 1005,
    "reward": "Employee of the Month",
    "description": "Outstanding performance this month",
    "points": 200,
    "reward_type": "User Badge",
    "reward_category": "Recognition",
    "reward_group": "Monthly Awards",
    "assigner": [
        {
            "job_code": ["MANAGER", "DIRECTOR"]
        }
    ],
    "awardee": [
        {
            "job_code": ["EMPLOYEE", "ASSOCIATE"]
        }
    ]
}
```

**Permissions:**
- `assigner`: Who can give this badge (by job_code or groups)
- `awardee`: Who can receive this badge

#### 2. **Automated Badge**
Triggered automatically by system events (login, specific actions).

```json
{
    "reward_id": 1007,
    "reward": "Welcome to Navigator",
    "description": "10 points every time you log in",
    "multiple": true,
    "points": 10,
    "reward_type": "Automated Badge",
    "reward_category": "Recognition",
    "reward_group": "Daily Rewards"
}
```

#### 3. **Achievement Badge**
Rule-based badges that evaluate conditions and thresholds.

```json
{
    "reward_id": 3000,
    "reward": "Consistency King",
    "description": "Maintained 30-day login streak",
    "points": 1000,
    "reward_type": "Achievement Badge",
    "reward_category": "Engagement",
    "rules": [
        [
            "AchievementRule",
            {
                "function_path": "rewards.functions.engagement.get_login_streak",
                "threshold": 30,
                "operator": "gte"
            }
        ]
    ]
}
```

#### 4. **Computed Badge** (Lottery/Random)
Scheduled badges awarded to random users or based on computations.

```json
{
    "reward_id": 1010,
    "reward": "Daily Lottery Winner",
    "description": "Lucky winner of the daily lottery!",
    "points": 500,
    "reward_type": "Computed Badge",
    "reward_category": "Lottery",
    "multiple": true,
    "timeframe": "daily",
    "rules": [
        [
            "RandomUsers",
            {
                "count": 1,
                "exclude_recent_winners": true,
                "recent_winner_days": 7
            }
        ]
    ],
    "job": {
        "trigger": "cron",
        "cron": {
            "hour": 16,
            "minute": 0
        },
        "id": "daily_lottery"
    }
}
```

#### 5. **Workflow Badge**
Multi-step achievements that track user progress.

```json
{
    "reward_id": 7000,
    "reward": "Onboarding Champion",
    "description": "Complete the onboarding process",
    "points": 2000,
    "reward_type": "Workflow Badge",
    "reward_category": "Training",
    "multiple": false,
    "workflow": [
        {"step": "First Login"},
        {"step": "Complete Profile"},
        {"step": "Take Training"}
    ],
    "completion_callbacks": [
        "rewards.callbacks.send_completion_email"
    ]
}
```

#### 6. **Nomination Badge**
Voting-based awards (Employee of the Month style).

```json
{
    "reward_id": 8000,
    "reward": "Employee of the Month",
    "description": "Voted by peers as Employee of the Month",
    "points": 5000,
    "reward_type": "Nomination Badge",
    "reward_category": "Recognition",
    "nomination_config": {
        "nomination_duration_days": 7,
        "voting_duration_days": 5,
        "allow_self_nomination": false,
        "max_nominations_per_user": 2,
        "max_votes_per_user": 1
    }
}
```

---

## 🎯 Rules System

Rules define the conditions for awarding badges. They're specified in the `rules` array.

### Rule Format

```json
"rules": [
    ["RuleName", {"param1": "value1", "param2": "value2"}]
]
```

### Available Rules

#### 1. **AchievementRule**

Evaluates a custom function against a threshold.

```json
{
    "rules": [
        [
            "AchievementRule",
            {
                "function_path": "rewards.functions.engagement.get_login_streak",
                "threshold": 30,
                "operator": "gte"
            }
        ]
    ]
}
```

**Operators:**
- `gte`: greater than or equal
- `gt`: greater than
- `lte`: less than or equal
- `lt`: less than
- `eq`: equal
- `ne`: not equal

**Custom Achievement Functions:**

Create `rewards/functions/engagement.py`:

```python
async def get_login_streak(user, env, conn, **kwargs):
    """Calculate user's login streak in days."""
    query = """
    SELECT COUNT(DISTINCT DATE(login_date))
    FROM auth.user_logins
    WHERE user_id = $1
      AND login_date > NOW() - INTERVAL '30 days'
    """
    result = await conn.fetchval(query, user.user_id)
    return result or 0
```

#### 2. **AttendanceRule**

Evaluates attendance patterns.

```json
{
    "rules": [
        [
            "AttendanceRule",
            {
                "count": 30,
                "unit": "day",
                "dataset": "employee_attendance",
                "filter_by": "attendance_date",
                "match": "perfect",
                "only_weekdays": true
            }
        ]
    ]
}
```

**Parameters:**
- `count`: Number of time units
- `unit`: `day`, `week`, `month`
- `period_type`: `fixed` or `rolling` (default: fixed)
- `match`: `perfect` (100%) or `partial` (with deviation)
- `deviation`: Allowed missed days for partial match
- `only_weekdays`: Count only Monday-Friday

**Examples:**

```json
// Perfect monthly attendance
{
    "reward": "Perfect Attendance - Monthly",
    "rules": [
        [
            "AttendanceRule",
            {
                "count": 1,
                "unit": "month",
                "dataset": "employee_attendance",
                "match": "perfect",
                "only_weekdays": true
            }
        ]
    ]
}

// Good attendance (max 2 missed days in 30 days)
{
    "reward": "Excellent Attendance",
    "rules": [
        [
            "AttendanceRule",
            {
                "count": 30,
                "unit": "day",
                "dataset": "employee_attendance",
                "match": "partial",
                "deviation": 2,
                "only_weekdays": true
            }
        ]
    ]
}

// Rolling 30-day perfect attendance
{
    "reward": "Rolling 30-Day Streak",
    "rules": [
        [
            "AttendanceRule",
            {
                "count": 30,
                "unit": "day",
                "period_type": "rolling",
                "dataset": "employee_attendance",
                "match": "perfect",
                "only_weekdays": true
            }
        ]
    ]
}
```

#### 3. **RandomUsers**

Selects random users for lottery-style rewards.

```json
{
    "rules": [
        [
            "RandomUsers",
            {
                "count": 5,
                "filters": {
                    "departments": ["Sales", "Marketing"],
                    "job_codes": ["ASSOCIATE"],
                    "min_tenure_days": 90
                },
                "exclude_recent_winners": true,
                "recent_winner_days": 30
            }
        ]
    ]
}
```

#### 4. **Birthday**

Awards badge on user's birthday.

```json
{
    "reward": "Happy Birthday!",
    "rules": [["Birthday"]]
}
```

#### 5. **EmploymentDuration**

Awards badge on employment anniversary.

```json
{
    "reward": "1 Year Anniversary",
    "rules": [["EmploymentDuration"]]
}
```

#### 6. **WorkAnniversary**

Similar to EmploymentDuration but with more options.

```json
{
    "reward": "5 Year Milestone",
    "rules": [
        [
            "WorkAnniversary",
            {
                "years": 5
            }
        ]
    ]
}
```

---

## ⏰ Scheduling Rewards

Use the `job` field to schedule automatic reward evaluation.

### Cron-based Scheduling

```json
{
    "reward_id": 1010,
    "reward": "Daily Lottery",
    "reward_type": "Computed Badge",
    "rules": [["RandomUsers", {"count": 1}]],
    "job": {
        "trigger": "cron",
        "cron": {
            "hour": 16,
            "minute": 0
        },
        "id": "daily_lottery_4pm",
        "name": "Daily Lottery at 4 PM",
        "timezone": "America/New_York"
    }
}
```

### Interval-based Scheduling

```json
{
    "job": {
        "trigger": "interval",
        "interval": {
            "hours": 2
        },
        "id": "check_every_2_hours"
    }
}
```

### Date-based (One-time)

```json
{
    "job": {
        "trigger": "date",
        "run_date": "2025-12-25 10:00:00",
        "id": "christmas_special",
        "skip_past_dates": true
    }
}
```

### Advanced Cron Examples

```json
// Every Monday at 9 AM
{
    "cron": {
        "day_of_week": "mon",
        "hour": 9,
        "minute": 0
    }
}

// Last day of month at 4 PM
{
    "cron": {
        "day": "last",
        "hour": 16,
        "minute": 0
    }
}

// Every weekday at noon
{
    "cron": {
        "day_of_week": "mon-fri",
        "hour": 12,
        "minute": 0
    }
}
```

---

## 🎯 Availability Rules

Control when badges are available.

### Date-based Availability

```json
{
    "reward": "Holiday Special",
    "availability_rule": {
        "start_date": "12-01",
        "end_date": "12-31"
    }
}
```

### Time-based Availability

```json
{
    "reward": "Early Bird Special",
    "availability_rule": {
        "dow": [1, 2, 3, 4, 5],
        "start_time": "06:00:00",
        "end_time": "09:00:00"
    }
}
```

**dow**: Day of week (0=Monday, 6=Sunday)

---

## 📊 Complete Examples

### Example 1: Monthly Perfect Attendance

```json
{
    "reward_id": 5001,
    "reward": "Perfect Attendance - Monthly",
    "description": "Perfect weekday attendance for the entire month",
    "points": 1000,
    "reward_type": "Achievement Badge",
    "reward_category": "Attendance",
    "reward_group": "Monthly Badges",
    "multiple": true,
    "timeframe": "monthly",
    "icon": "https://example.com/perfect-attendance.png",
    "rules": [
        [
            "AttendanceRule",
            {
                "count": 1,
                "unit": "month",
                "dataset": "employee_attendance",
                "filter_by": "attendance_date",
                "match": "perfect",
                "only_weekdays": true
            }
        ]
    ]
}
```

### Example 2: Monthly Mega Lottery

```json
{
    "reward_id": 1013,
    "reward": "Monthly Mega Lottery",
    "description": "Big monthly lottery - 5 lucky winners!",
    "points": 5000,
    "reward_type": "Computed Badge",
    "reward_category": "Lottery",
    "reward_group": "Monthly Rewards",
    "multiple": true,
    "timeframe": "monthly",
    "icon": "https://example.com/lottery.png",
    "rules": [
        [
            "RandomUsers",
            {
                "count": 5,
                "exclude_recent_winners": true,
                "recent_winner_days": 30
            }
        ]
    ],
    "job": {
        "trigger": "cron",
        "cron": {
            "day": "last",
            "hour": 16,
            "minute": 0
        },
        "id": "monthly_mega_lottery",
        "name": "Monthly Mega Lottery"
    }
}
```

### Example 3: Login Streak Achievement

```json
{
    "reward_id": 3000,
    "reward": "Consistency King",
    "description": "Maintained 30-day login streak",
    "points": 1000,
    "reward_type": "Achievement Badge",
    "reward_category": "Engagement",
    "reward_group": "Streaks",
    "icon": "https://example.com/streak.png",
    "rules": [
        [
            "AchievementRule",
            {
                "function_path": "rewards.functions.engagement.get_login_streak",
                "threshold": 30,
                "operator": "gte"
            }
        ]
    ]
}
```

### Example 4: Onboarding Workflow

```json
{
    "reward_id": 7002,
    "reward": "Sales Mastery",
    "description": "Complete the sales training program",
    "points": 2000,
    "reward_type": "Workflow Badge",
    "reward_category": "Training",
    "reward_group": "Certifications",
    "multiple": true,
    "auto_enroll": true,
    "auto_evaluation": true,
    "workflow": [
        {
            "step": "Product Knowledge",
            "condition": {
                "function_path": "rewards.functions.training.check_product_knowledge",
                "threshold": 80,
                "operator": "gte"
            }
        },
        {
            "step": "Sales Techniques",
            "condition": {
                "function_path": "rewards.functions.training.check_sales_training",
                "threshold": 100,
                "operator": "eq"
            }
        },
        {
            "step": "First Sale",
            "condition": {
                "function_path": "rewards.functions.sales.check_first_sale",
                "threshold": 1,
                "operator": "gte"
            }
        }
    ],
    "completion_callbacks": [
        "rewards.callbacks.training.send_certificate"
    ]
}
```

### Example 5: Employee of the Month Nomination

```json
{
    "reward_id": 8001,
    "reward": "Employee of the Month - Sales",
    "description": "Voted by peers as top sales performer",
    "points": 5000,
    "reward_type": "Nomination Badge",
    "reward_category": "Recognition",
    "reward_group": "Monthly Awards",
    "multiple": true,
    "timeframe": "monthly",
    "nomination_config": {
        "nomination_duration_days": 7,
        "voting_duration_days": 5,
        "allow_self_nomination": false,
        "max_nominations_per_user": 3,
        "max_votes_per_user": 1,
        "eligible_nominators": {
            "job_codes": ["ASSOCIATE", "MANAGER"],
            "min_tenure_days": 90
        },
        "eligible_nominees": {
            "job_codes": ["ASSOCIATE"],
            "departments": ["Sales"]
        }
    },
    "job": {
        "trigger": "cron",
        "cron": {
            "day": 1,
            "hour": 9,
            "minute": 0
        },
        "id": "eotm_sales_start"
    }
}
```

---

## 🔧 Advanced Configuration

### Custom Achievement Functions

Create custom functions in `rewards/functions/`:

```python
# rewards/functions/custom.py

async def check_sales_target(user, env, conn, target=100, **kwargs):
    """Check if user met sales target."""
    query = """
    SELECT COUNT(*)
    FROM sales.transactions
    WHERE user_id = $1
      AND created_at >= $2
      AND created_at < $3
    """
    count = await conn.fetchval(
        query,
        user.user_id,
        env.start_date,
        env.end_date
    )
    return count >= target
```

Register in your reward:

```json
{
    "rules": [
        [
            "AchievementRule",
            {
                "function_path": "rewards.functions.custom.check_sales_target",
                "threshold": 100,
                "operator": "gte",
                "function_params": {
                    "target": 100
                }
            }
        ]
    ]
}
```

### Multiple Rules (AND Logic)

All rules must pass:

```json
{
    "reward": "Elite Performer",
    "rules": [
        [
            "AchievementRule",
            {
                "function_path": "rewards.functions.sales.get_sales_count",
                "threshold": 100,
                "operator": "gte"
            }
        ],
        [
            "AttendanceRule",
            {
                "count": 1,
                "unit": "month",
                "match": "perfect"
            }
        ]
    ]
}
```

### Message Templates

Use Jinja2 templates in messages:

```json
{
    "reward": "Top Seller",
    "message": "Congratulations {{user.display_name}}! You made {{args.sales_count}} sales this month and ranked #{{args.rank}}!",
    "rules": [
        ["BestSeller"]
    ]
}
```

---

## 📖 API Endpoints

NAV-Rewards automatically creates REST endpoints:

```
GET    /rewards/api/v1/rewards              # List all rewards
GET    /rewards/api/v1/rewards/{id}         # Get specific reward
POST   /rewards/api/v1/rewards              # Create reward
PUT    /rewards/api/v1/rewards/{id}         # Update reward
DELETE /rewards/api/v1/rewards/{id}         # Delete reward

GET    /rewards/api/v1/users_rewards        # List user rewards
POST   /api/v1/badge_assign                 # Assign a badge

GET    /rewards/api/v1/reward_categories    # List categories
GET    /rewards/api/v1/reward_groups        # List groups
GET    /rewards/api/v1/reward_types         # List types

GET    /kudos/api/v1/user_kudos             # List kudos
POST   /kudos/api/v1/user_kudos             # Send kudos
GET    /kudos/api/v1/kudos_tags             # List kudos tags
```

---

## 🤖 MS Teams Bot Integration

NAV-Rewards includes a Teams bot for badge assignment:

```python
from rewards.bot.badge import BadgeBot

# In your rewards engine setup
badge_bot = BadgeBot(
    bot_name="BadgeBot",
    id='badgebot',
    app=app,
    client_id=REWARDS_CLIENT_ID,
    client_secret=REWARDS_CLIENT_SECRET
)
badge_bot.setup(app)
```

**Bot Commands:**
- `/badge` - Award a badge to a user
- `/kudos` - Send kudos to a colleague

---

## 📚 Additional Resources

- **GitHub**: https://github.com/phenobarbital/nav-rewards
- **Documentation**: https://github.com/phenobarbital/nav-rewards/tree/main/rewards/docs
- **Issues**: https://github.com/phenobarbital/nav-rewards/issues
- **PyPI**: https://pypi.org/project/nav-rewards/

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## 💰 Support

If you find this project useful, please consider:

- ⭐ Starring the repository
- 🐛 Reporting bugs
- 💡 Suggesting new features
- 💵 Supporting via [PayPal](https://paypal.me/phenobarbital)
- 🙏 Saying thanks: https://saythanks.io/to/phenobarbital

---

## 👨‍💻 Author

**Jesus Lara Gimenez**
Email: jesuslarag@gmail.com
GitHub: [@phenobarbital](https://github.com/phenobarbital)

---

**Built with ❤️ using aiohttp and Navigator**
