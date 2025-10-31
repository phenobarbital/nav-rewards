"""
Main configuration for Rewards.
"""
import sys
from navconfig import config, BASE_DIR, DEBUG
from navconfig.logging import logging


# Environment
ENVIRONMENT = config.get("ENVIRONMENT", fallback="development")
PRODUCTION = config.getboolean("PRODUCTION", fallback=(not DEBUG))
LOCAL_DEVELOPMENT = DEBUG is True and sys.argv[0] == "run.py"


# DB Default (database used for interaction (rw))
DBHOST = config.get("DBHOST", fallback="localhost")
DBUSER = config.get("DBUSER")
DBPWD = config.get("DBPWD")
DBNAME = config.get("DBNAME", fallback="navigator")
DBPORT = config.get("DBPORT", fallback=5432)
if not DBUSER:
    raise RuntimeError("Missing PostgreSQL Default Settings.")
# database for changes (admin)
default_dsn = f"postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}"
default_pg = f"postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}"

# sqlalchemy+asyncpg connector:
default_sqlalchemy_pg = f"postgresql+asyncpg://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}"

# Redis Server:
REDIS_HOST = config.get('REDIS_HOST', fallback='localhost')
REDIS_PORT = config.get('REDIS_PORT', fallback=6379)
REDIS_DB = config.get('REDIS_DB', fallback=1)
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
REDIS_SESSION_DB = config.get("REDIS_SESSION_DB", fallback=0)

# Azure Bot:
MS_TENANT_ID = config.get('MS_TENANT_ID')
MS_CLIENT_ID = config.get('MS_CLIENT_ID')
MS_CLIENT_SECRET = config.get('MS_CLIENT_SECRET')

## Rewards System:
ENABLE_EVENT_MANAGER = config.getboolean("ENABLE_EVENT_MANAGER", fallback=True)
EVENT_MANAGER_QUEUE_SIZE = config.getint(
    "EVENT_MANAGER_QUEUE_SIZE",
    fallback=3
)

ENABLE_REWARDS = config.getboolean("ENABLE_REWARDS", fallback=True)
REWARD_SCHEDULER = config.getboolean("REWARD_SCHEDULER", fallback=True)
REWARD_MIDDLEWARE = config.getboolean("REWARD_MIDDLEWARE", fallback=True)

# MS Teams Configuration
REWARDS_CLIENT_ID = config.get('REWARDS_CLIENT_ID')
REWARDS_CLIENT_SECRET = config.get('REWARDS_CLIENT_SECRET')
REWARDS_USER = config.get('REWARDS_USER')
REWARDS_PASSWORD = config.get('REWARDS_PASSWORD')
REWARDS_TENANT_ID = config.get('REWARDS_TENANT_ID')

#### Microsoft Teams Bot
BOT_REWARDS_ID = config.get("BOT_REWARDS_ID")
BOT_REWARDS_SECRET = config.get("BOT_REWARDS_SECRET")

"""
Notification System
"""
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID")

"""
RabbitMQ Configuration.
"""
RABBITMQ_HOST = config.get("RABBITMQ_HOST", fallback="localhost")
RABBITMQ_PORT = config.get("RABBITMQ_PORT", fallback=5672)
RABBITMQ_USER = config.get("RABBITMQ_USER", fallback="guest")
RABBITMQ_PASS = config.get("RABBITMQ_PASS", fallback="guest")
RABBITMQ_VHOST = config.get("RABBITMQ_VHOST", fallback="navigator")
# DSN
rabbitmq_dsn = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/{RABBITMQ_VHOST}"


## Tables:
# System table to find people
PEOPLE_LIST = config.get('PEOPLE_LIST', fallback='vw_people')
PEOPLE_SCHEMA = config.get('PEOPLE_SCHEMA', fallback='troc')

REWARDS_SCHEMA = config.get('REWARDS_SCHEMA', fallback='rewards')
REWARDS_VIEW = config.get('REWARDS_VIEW', fallback='vw_rewards')
USER_REWARDS = config.get('USER_REWARDS', fallback="users_rewards")
