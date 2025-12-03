from typing import List, Optional, Union, Any
import asyncio
from asyncio import Semaphore
from datetime import datetime, timedelta
import zoneinfo
import importlib
import contextlib
import aiormq
from redis import asyncio as aioredis
from aiohttp import web
from jinja2 import (
    TemplateError,
    FileSystemLoader,
    Environment as JinjaEnvironment
)
from navconfig.logging import logging
from datamodel import BaseModel
from datamodel.exceptions import ValidationError  # pylint: disable=E0611
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611
from asyncdb import AsyncPool
## APscheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
## Navigator
from navigator_session import get_session
from navigator.applications.base import BaseApplication  # pylint: disable=E0611
from navigator.types import WebApp  # pylint: disable=E0611
from ..models import (
    User,
    all_users,
    filter_users,
    get_user
)
from ..conf import (
    REWARDS_CLIENT_ID,
    REWARDS_CLIENT_SECRET,
    BASE_DIR,
    default_dsn,
    TIMEZONE,
    REWARD_SCHEDULER,
    REDIS_URL
)
from ..registry import AchievementLoader
from ..context import EvalContext, achievement_registry
from ..env import Environment
from ..rewards import RewardObject
from ..rewards.nomination import NominationAward
from ..rewards.nomination.models import (
    NominationCampaign,
    CampaignStatus
)
from ..storages import AbstractStorage
from ..handlers import (
    BadgeAssignHandler,
    EmployeeSearchHandler,
    UserRewardHandler,
    RewardCategoryHandler,
    RewardGroupHandler,
    RewardTypeHandler,
    RewardHandler,
    RewardViewHandler
)
# Award System Handlers:
from ..rewards.nomination.handlers import (
    NominationAwardHandler,
    NominationHandler,
    NominationVoteHandler,
    NominationCommentHandler
)
# Loading BadgeBot:
from ..bot.badge import BadgeBot
from ..bot.vote import NominationBot
# Kudos Handlers:
from ..kudos.handlers import (
    UserKudosHandler,
    KudosTagHandler
)


# disable logging of APScheduler
logging.getLogger("apscheduler").setLevel(logging.WARNING)


class RewardError(Exception):
    """RewardError.
    """
    pass

class RewardsEngine:
    """RewardsEngine.
    """
    def __init__(
        self,
        app: web.Application,
        **kwargs
    ):
        self.storages = []
        self._rewards: list[RewardObject] = []
        self.logger = logging.getLogger(
            'rewards'
        )
        # Rewards non usable by users.
        self._not_returned = [
            'Automated Badge',
            'Challenge',
            'Computed Badge'
        ]
        self._timezone = zoneinfo.ZoneInfo(TIMEZONE)
        # Limit the number of concurrent connections
        self._semaphore = Semaphore(50)
        self._user_semaphore = Semaphore(10)
        self._batch_size: int = 50
        self.scheduler = AsyncIOScheduler(
            executors={
                "default": AsyncIOExecutor(),
            },
            timezone=self._timezone,
            job_defaults={
                "coalesce": False,
                "max_instances": 3,
                "misfire_grace_time": 60
            }
        )
        # Event Manager:
        self._reward_exchange = kwargs.get('exchange', 'navigator')
        # Template Manager:
        jinja_config = {
            "enable_async": True,
            "extensions": [
                "jinja2.ext.i18n",
                "jinja2.ext.loopcontrols",
                "jinja2.ext.do",
            ],
        }
        self.loader = FileSystemLoader(
            str(BASE_DIR.joinpath("templates")),
            encoding='utf-8'
        )
        self.env = JinjaEnvironment(
            loader=self.loader,
            **jinja_config
        )

    @property
    def connection(self):
        return self._pool

    def add_storage(self, storage: Union[AbstractStorage, str], **kwargs):
        """add_storage.
        """
        if isinstance(storage, AbstractStorage):
            self.storages.append(storage)
        elif isinstance(storage, str):
            storage = self.get_storage(storage, **kwargs)
            self.storages.append(storage)

    def get_storage(self, name: str, **kwargs):
        """get_storage.
        """
        classpath = f'rewards.storages.{name}'
        classname = f'{name.capitalize()}Storage'
        try:
            module = importlib.import_module(
                classpath
            )
            storage = getattr(module, classname)
            return storage(**kwargs)
        except ModuleNotFoundError as err:
            self.logger.error(str(err))
            raise err

    async def load_rewards(self):
        """load_rewards.

        Load rewards and register scheduled jobs for Computed Badges.
        """
        rewards = []
        # Generate the list of rewards from all storages
        for storage in self.storages:
            async with storage as st:
                rewards = await st.load_rewards()
                self._rewards += rewards
        for reward in self._rewards:
            # sharing the Jinja Template Environment with Rewards
            if reward:
                reward.template_engine = self.env
                if reward.reward_type == 'Computed Badge' and \
                        reward.job is not None:
                    # Register the job for computed badges
                    try:
                        await self._register_computed_badge_job(reward)
                    except Exception as err:
                        self.logger.error(
                            f"Error registering job for computed badge '{reward._reward.reward}': {err}"  # noqa
                        )

    async def _register_computed_badge_job(self, reward):
        """
        Register a scheduled job for a computed badge with
            APScheduler configuration.

        Args:
            reward: The reward object with job configuration
        """
        try:
            job_config = reward.job

            # Extract core scheduling parameters
            trigger = job_config.get('trigger', 'interval')
            # Build base job arguments (without trigger-specific parameters)
            job_args = {
                'func': reward.call_reward,
                'trigger': trigger,
                'args': [self.app]
            }
            scheduled_next_run = None

            # Add trigger-specific parameters based on trigger type
            if trigger == 'interval':
                schedule = job_config.get('schedule', {"hours": 6})
                job_args |= schedule

                # Only set next_run_time for interval triggers
                if next_run_time := self._calculate_next_run_time(job_config):
                    job_args['next_run_time'] = next_run_time
                    scheduled_next_run = next_run_time

            elif trigger == 'cron':
                cron_config = job_config.get('cron', {})
                if not cron_config:
                    raise ValueError(
                        "Cron trigger requires 'cron' configuration"
                    )

                cron_params = [
                    'year', 'month', 'day', 'week', 'day_of_week',
                    'hour', 'minute', 'second', 'start_date', 'end_date'
                ]

                for param in cron_params:
                    if param in cron_config:
                        job_args[param] = cron_config[param]

            elif trigger == 'date':
                date_config = job_config.get('date', {})
                if 'run_date' not in date_config:
                    raise ValueError(
                        "Date trigger requires 'run_date' in 'date' configuration"  # noqa
                    )

                run_date_str = date_config['run_date']

                # Parse and validate the run date
                try:
                    run_date = datetime.fromisoformat(run_date_str)

                    # Check if the date is in the past
                    now = datetime.now()
                    if run_date < now:
                        self.logger.warning(
                            f"Date trigger for '{reward._reward.reward}' has past date: {run_date_str}. "  # noqa
                            "Job will either execute immediately or be skipped"
                        )
                        if skip := job_config.get('skip_past_dates', False):
                            # Skip past dates (recommended)
                            self.logger.info(
                                f"Skipping job registration for past date: {run_date_str}"  # noqa
                            )
                            return
                        else:
                            # Update to next year (alternative)
                            run_date = run_date.replace(year=now.year + 1)
                            self.logger.info(
                                f"Updated past date to next year: {run_date}"
                            )

                    job_args['run_date'] = run_date
                    scheduled_next_run = run_date

                except ValueError as e:
                    raise ValueError(
                        f"Invalid run_date format '{run_date_str}': {e}"
                    ) from e

            # Add optional APScheduler parameters
            optional_params = {
                'id': job_config.get(
                    'id',
                    f'computed_badge_{reward._reward.reward_id}'
                ),
                'name': job_config.get(
                    'name',
                    f'Computed Badge: {reward._reward.reward}'
                ),
                'replace_existing': job_config.get('replace_existing', True),
                'max_instances': job_config.get('max_instances', 1),
                'coalesce': job_config.get('coalesce', True),
                'misfire_grace_time': job_config.get('misfire_grace_time', 60),
                'jitter': job_config.get('jitter', None),
            }

            # Add non-None optional parameters
            for key, value in optional_params.items():
                if value is not None:
                    job_args[key] = value

            # Handle timezone
            if timezone := job_config.get('timezone'):
                job_args['timezone'] = zoneinfo.ZoneInfo(timezone)
            else:
                job_args['timezone'] = self._timezone

            # Register the job
            job = self.scheduler.add_job(**job_args)
            # Proper logging without accessing non-existent attributes
            job_id = getattr(job, 'id', 'unknown_job_id')

            self.logger.info(
                f"Registered job '{job_id}' for Reward '{reward._reward.reward}' "  # noqa
                f"(trigger: {trigger}, next run: {scheduled_next_run!r})"
            )

        except Exception as err:
            self.logger.error(
                f"Error registering job for computed badge '{reward._reward.reward}': {err}"  # noqa
            )

    def _calculate_next_run_time(self, job_config: dict):
        """Calculate next run time based on configuration."""
        next_run_config = job_config.get('next_run_time')

        if not next_run_config:
            # Default: start immediately
            return datetime.now(tz=self._timezone)

        if isinstance(next_run_config, str):
            # Handle special cases for next_run_time
            _now = datetime.now(tz=self._timezone)
            if next_run_config == 'now':
                return _now
            elif next_run_config == 'delayed':
                # Start after a delay (useful for system startup)
                delay_minutes = job_config.get('delay_minutes', 5)
                return _now + timedelta(minutes=delay_minutes)
            elif next_run_config.startswith('offset:'):
                # Custom offset: "offset:30m", "offset:2h", "offset:1d"
                offset_str = next_run_config.split(':', 1)[1]
                offset = self._parse_time_offset(offset_str)
                return _now + offset
            else:
                # Try to parse as ISO datetime
                try:
                    return datetime.fromisoformat(next_run_config)
                except ValueError:
                    self.logger.warning(
                        f"Invalid next_run_time format: {next_run_config}"
                    )
                    return datetime.now(tz=self._timezone)

        elif isinstance(next_run_config, dict):
            # Relative time configuration
            return datetime.now(tz=self._timezone) + timedelta(
                **next_run_config
            )

        return None

    def _parse_time_offset(self, offset_str: str) -> timedelta:
        """Parse time offset string like '30m', '2h', '1d'."""
        import re

        pattern = r'(\d+)([smhd])'
        match = re.match(pattern, offset_str.lower())

        if not match:
            raise ValueError(f"Invalid time offset format: {offset_str}")

        value, unit = match.groups()
        value = int(value)

        units = {
            's': 'seconds',
            'm': 'minutes',
            'h': 'hours',
            'd': 'days'
        }

        return timedelta(**{units[unit]: value})

    def _apply_cron_config(self, job_args: dict, job_config: dict):
        """Apply cron-specific configuration."""
        cron_config = job_config.get('cron', {})

        # Remove schedule from job_args as cron uses different parameters
        job_args.pop('schedule', None)

        # Add cron-specific parameters
        cron_params = [
            'year', 'month', 'day', 'week', 'day_of_week',
            'hour', 'minute', 'second', 'start_date', 'end_date'
        ]

        for param in cron_params:
            if param in cron_config:
                job_args[param] = cron_config[param]

    def _apply_date_config(self, job_args: dict, job_config: dict):
        """Apply date-specific configuration."""
        date_config = job_config.get('date', {})

        # Remove schedule from job_args
        job_args.pop('schedule', None)

        # Add date-specific parameters
        if 'run_date' in date_config:
            job_args['run_date'] = date_config['run_date']

    def AccessDenied(
        self,
        reason: Union[str, dict],
        headers: dict = None,
        exception: Exception = None,
        content_type: str = 'application/json',
        status: int = 403,
        **kwargs
    ) -> web.HTTPError:
        response_obj = {
            "status": status
        }
        if exception:
            response_obj["error"] = str(exception)
        args = {
            "content_type": content_type,
            "headers": headers,
            **kwargs
        }
        if isinstance(reason, dict):
            response_obj = {**response_obj, **reason}
            args["content_type"] = "application/json"
        elif isinstance(reason, str):
            response_obj['reason'] = reason
        else:
            response_obj['reason'] = {
                "error": reason
            }
        try:
            args["body"] = json_encoder(response_obj)
        except TypeError:
            self.logger.error(
                f"Error encoding response body: {response_obj}"
            )
            args["body"] = json_encoder(
                {"error": "Invalid response format"}
            )
        if status == 401:  # unauthorized
            return web.HTTPUnauthorized(**args)
        elif status == 403:  # forbidden
            return web.HTTPForbidden(**args)
        elif status == 404:  # not found
            return web.HTTPNotFound(**args)
        elif status == 406:  # Not acceptable
            return web.HTTPNotAcceptable(**args)
        elif status == 412:
            return web.HTTPPreconditionFailed(**args)
        elif status == 428:
            return web.HTTPPreconditionRequired(**args)
        else:
            return web.HTTPBadRequest(**args)

    def is_authenticated(self, request: web.Request):
        if request.get("authenticated", False) is False:
            # check credentials:
            raise self.AccessDenied(
                reason="User Not Authenticated",
                status=403
            )

    async def get_user(self, request: web.Request) -> tuple:
        try:
            session = await get_session(request, new=False)
        except (AttributeError, RuntimeError) as ex:
            self.logger.error(
                'NAV User Session system is not installed.'
            )
            raise self.AccessDenied(
                reason="Missing User session for validating Access.",
                exception=ex,
                status=412
            ) from ex
        try:
            user = session.decode('user')
        except (AttributeError, KeyError) as ex:
            self.logger.error(
                f"User is not authenticated: {ex}"
            )
            user = None
        return (session, user)

    async def get_reward(self, reward_id: int) -> RewardObject:
        """get_reward.
        """
        return next(
            (
                None if reward.reward_type in self._not_returned else reward
                for reward in self._rewards
                if reward.id == reward_id
            ),
            None,
        )

    async def get_rewards(self, request):
        """get_rewards.
        TODO: Filter Rewards by User, Availability, etc.
        """
        self.is_authenticated(request=request)
        session, user = await self.get_user(request)
        env = Environment()
        ctx = EvalContext(
            request=request,
            user=user,
            session=session
        )
        return web.json_response(
            [
                {
                    "reward_id": reward._reward.reward_id,
                    "reward": reward._reward.reward,
                    "description": reward._reward.description,
                    "type": reward._reward.reward_type,
                    "icon": reward._reward.icon,
                    "availability": reward._reward.availability_rule
                }
                for reward in self._rewards if reward.fits(
                    ctx, env
                ) and reward.reward_type not in self._not_returned
            ]
        )

    async def get_rewards_for_user(
        self,
        ctx: EvalContext
    ) -> List[RewardObject]:
        """get_rewards_for_user.

        Get all rewards available for a specific user.
        """
        env = Environment()
        return [
            reward for reward in self._rewards if reward.fits(
                ctx, env
            ) and reward.reward_type not in self._not_returned
        ]

    async def get_badges_for_user(
        self,
        ctx: EvalContext
    ) -> List[RewardObject]:
        """get_badges_for_user.

        Get all User-assigned Badges available for a specific user.
        """
        env = Environment()
        _allowed = ['User Badge', 'Test Badge']
        return [
            reward for reward in self._rewards if reward.reward_type in _allowed and reward.fits(  # noqa
                ctx, env
            )
        ]

    async def process_event(
        self,
        event: aiormq.abc.DeliveredMessage,
        event_body: str
    ):
        """Process the event.

        This method is called when an event is received from the Event Manager.
        It processes the event and applies rewards based on the event data.
        """
        # Process the event and apply rewards as necessary
        # Extract the routing key (event name)
        event_name = event.delivery.routing_key

        # Handle nomination-specific events
        if event_name.startswith('nomination.'):
            await self._process_nomination_event(
                event_name,
                event_body
            )
            return

        with contextlib.suppress(Exception):
            event_body = json_decoder(event_body)
        self.logger.debug(
            f"::: Received event: {event_name} with body: {event_body}"
        )
        _filtered = [
            reward for reward in self._rewards if reward.fits_event(event_name)
        ]
        print('FILTERED > ', _filtered)
        if not _filtered:
            self.logger.debug(
                f"No rewards match event: {event_name}"
            )
            return

        # Create the Environment for the Rewards
        try:
            env = Environment(
                connection=self.connection,
                cache=self.get_cache()
            )
        except ValidationError as err:
            self.logger.error(
                f"Error on Environment: {err.payload}"
            )
            return
        except Exception as err:
            self.logger.error(
                f"Unexpected error creating Environment: {err}"
            )
            return

        # Task evaluation
        tasks = []
        for reward in _filtered:
            try:
                if not reward.is_enabled():
                    continue
                # Step 1: evaluate_event return a list of potential users
                potential_users = await reward.evaluate_event(
                    event_body,
                    event,
                    env
                )
                if not potential_users:
                    continue
                # Step 2: Iterate over all users:
                for user_ctx in potential_users:
                    task = asyncio.create_task(
                        self._process_user_batch(user_ctx, env, reward)
                    )
                    tasks.append(task)
            except Exception as err:
                self.logger.error(
                    f"Error processing reward {reward.name} for event {event_name}: {err}"  # noqa
                )
                continue
        # Step 3: Execute all tasks
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.exceptions.CancelledError:
                pass  # ignore cancelled errors
            except Exception as err:
                self.logger.error(
                    f"Error executing event processing tasks: {err}"
                )

    async def set_connection(self):
        kwargs = {
            "server_settings": {
                'client_min_messages': 'notice',
                'max_parallel_workers': '24',
                'tcp_keepalives_idle': '30'
            }
        }
        try:
            self._pool = AsyncPool(
                "pg",
                dsn=default_dsn,
                **kwargs
            )
            await self._pool.connect()  # pylint: disable=E1101
            self.logger.notice('Rewards: Connected.')
        except Exception as err:
            self.logger.error(str(err))

    async def start_redis(self, dsn: str, **kwargs):
        self._redis = aioredis.ConnectionPool.from_url(
            dsn,
            encoding='utf-8',
            decode_responses=True,
            max_connections=600,
            health_check_interval=60.0,
            **kwargs,
        )
        return self._redis

    def get_cache(self):
        """get_cache.

        Return a Redis Connection from Pool.
        Returns:
            redis.Redis: Redis Object.
        """
        if self._redis:
            return aioredis.Redis(
                connection_pool=self._redis
            )

    def setup(self, app: web.Application) -> web.Application:
        if isinstance(app, BaseApplication):
            self.app = app.get_app()
        elif isinstance(app, WebApp):
            self.app = app  # register the app into the Extension
        ### Startup Event
        self.app.on_startup.append(
            self.reward_startup
        )
        # Shutdown Process
        self.app.on_shutdown.append(
            self.reward_shutdown
        )
        # Saving into the Application
        self.app['reward_engine'] = self

        # Configure Routes:
        self.app.router.add_get(
            '/rewards/api/v1/rewards_list',
            self.get_rewards
        )
        BadgeAssignHandler.configure(
            self.app,
            '/rewards/api/v1/badge_assign'
        )
        EmployeeSearchHandler.configure(
            self.app,
            '/rewards/api/v1/employee_search'
        )
        RewardGroupHandler.configure(
            self.app, '/rewards/api/v1/reward_groups'
        )
        RewardTypeHandler.configure(
            self.app, '/rewards/api/v1/reward_types'
        )
        RewardCategoryHandler.configure(
            self.app, '/rewards/api/v1/reward_categories'
        )
        UserRewardHandler.configure(
            self.app, '/rewards/api/v1/user_rewards'
        )
        RewardHandler.configure(
            self.app, '/rewards/api/v1/rewards'
        )
        # Reward View:
        RewardViewHandler.configure(
            self.app, '/rewards/api/v1/reward_views'

        )
        # Adding the Reward Evaluator:
        runtime_now = datetime.now(tz=self._timezone)
        self.scheduler.add_job(
            self._evaluate_rewards,
            'interval',
            hours=2,
            args=[self.app],
            # Start 1 min after startup
            next_run_time=runtime_now + timedelta(minutes=1),
        )
        # Auto-workflow evaluation every 4 hours
        self.scheduler.add_job(
            self._evaluate_auto_workflows,
            'interval',
            hours=4,  # Every 4 hours
            args=[self.app],
            # Start 30 min after startup
            next_run_time=runtime_now + timedelta(minutes=30),
            id='auto_workflow_evaluation',
            replace_existing=True
        )
        # Daily evaluation for onboarding workflows
        # (more frequent for new employees)
        self.scheduler.add_job(
            self._evaluate_single_workflow_type,
            'interval',
            hours=24,
            args=['Workflow Badge', self.app],
            next_run_time=runtime_now + timedelta(hours=1),
            id='onboarding_workflow_evaluation',
            replace_existing=True
        )
        # Event Manager:
        self.event_manager = app['event_manager']
        # Reward Bot:
        badge_bot = BadgeBot(
            bot_name="BadgeBot",
            id='badgebot',
            app=self.app,
            client_id=REWARDS_CLIENT_ID,
            client_secret=REWARDS_CLIENT_SECRET,
            debug_mode=True
        )
        badge_bot.setup(self.app)
        # Nomination Bot:
        # nomination_bot = NominationBot(
        #     bot_name="NominationBot",
        #     id='voting',
        #     app=self.app,
        #     client_id=REWARDS_CLIENT_ID,
        #     client_secret=REWARDS_CLIENT_SECRET,
        #     debug_mode=True
        # )
        # nomination_bot.setup(self.app)
        # Achievement Loader:
        loader = AchievementLoader(
            registry=achievement_registry,
            base_path='rewards.functions'
        )
        loader.preload_modules(
            ['engagement', 'rewards']
        )
        # we can also validate critical achievement functions
        critical_functions = [
            'rewards.functions.engagement.get_login_streak'
        ]
        for func_path in critical_functions:
            if not loader.validate_function_path(func_path):
                self.logger.warning(
                    f"Critical achievement function not available: {func_path}"
                )
        # Register Nomination Handlers:
        self._setup_award_endpoints()
        # Register Kudos Handlers:
        UserKudosHandler.configure(
            self.app, '/kudos/api/v1/user_kudos'
        )
        KudosTagHandler.configure(
            self.app, '/kudos/api/v1/kudos_tags'
        )

    async def reward_startup(self, app: web.Application):
        """reward_startup.
        """
        # Create a Pool-based Database Connection
        await self.load_rewards()
        await self.set_connection()
        await self.start_redis(REDIS_URL)
        try:
            # starting scheduler
            self.scheduler.start()
            self.logger.info(
                f"Reward Scheduler Started at {datetime.now()}"
            )
        except Exception as err:
            raise RuntimeError(
                f"Error Starting Scheduler {err!r}"
            ) from err
        # Subscribe to the Event Manager
        await self.event_manager.create_exchange(
            self._reward_exchange
        )
        await self.event_manager.subscribe_to_events(
            exchange=self._reward_exchange,
            queue_name='reward_processing_queue',
            routing_key='#',
            callback=self.process_event
        )

    async def reward_shutdown(self, app: web.Application):
        """reward_shutdown.
        """
        await self._pool.wait_close(timeout=5)  # pylint: disable=E1101
        try:
            for storage in self.storages:
                await storage.close()
        except Exception as err:
            self.logger.error(str(err))
        try:
            await self._redis.disconnect(
                inuse_connections=True
            )
        except Exception as err:
            self.logger.error(str(err))
        self.logger.notice(
            'Rewards: Closing Connections.'
        )
        # Stopping the Scheduler:
        self.scheduler.shutdown(wait=True)

    async def _evaluate_rewards(self, app: web.Application):
        """
        Evaluate Rewards for all users.
        """
        _allowed = ['Recognition Badge']
        env = Environment()
        ctx = EvalContext(
            request=None,
            user=None,
            session=None
        )
        _filtered = [
            p for p in self._rewards if p.fits(
                ctx, env
            ) and p.reward_type in _allowed
        ]
        if not _filtered:
            self.logger.info("No rewards to evaluate")
            return
        try:
            users = await all_users(self.connection)
        except Exception as err:
            self.logger.error(f"Error fetching users: {err}")
            return

        if not users:
            self.logger.info("No users found for reward evaluation")
            return

        # Split users into batches
        self.logger.info(f"Evaluating rewards for {len(users)} users")
        # Split users into batches
        for i in range(0, len(users), self._batch_size):
            batch = users[i:i + self._batch_size]
            try:
                await self.process_batch(batch, env, _filtered)
            except Exception as err:
                self.logger.error(
                    f"Error processing batch {i // self._batch_size + 1}: {err}"
                )
                continue

    def _get_context_user(
        self,
        user: User,
        session: dict = None
    ) -> EvalContext:
        """
        Return the user context for the rule.

        :param user: The user to be evaluated.
        :param session: The User's session information.
        :return: tuple with the user context.
        """
        # Emulate Session Context:
        if not session:
            try:
                bd = user.birth_date() or None
            except (ValueError, AttributeError, TypeError) as err:
                self.logger.warning(
                    f"Invalid birth date for user {user.email}: {err}."
                )
                bd = None
            try:
                ed = user.employment_duration() or None
            except (ValueError, AttributeError, TypeError) as err:
                self.logger.warning(
                    f"Invalid employment duration for {user.email}: {err}."
                )
                ed = None
            session = {
                "username": user.email,
                "id": user.email,
                "user_id": user.user_id,
                "name": user.display_name,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": user.display_name,
                "email": user.email,
                "associate_id": getattr(user, 'associate_id', user.email),
                "associate_oid": user.associate_oid,
                "department": user.department_code,
                "job_code": user.job_code,
                "worker_type": user.worker_type,
                "start_date": user.start_date,
                "birth_date": bd,
                "employment_duration": ed,
                "session": {
                    "groups": getattr(user, 'groups', []),
                    "programs": getattr(user, 'programs', []),
                    "start_date": getattr(user, 'start_date', None),
                    "birthday": getattr(user, 'birthday', None),
                    "worker_type": getattr(user, 'worker_type', None),
                    "job_code": getattr(user, 'job_code', None),
                }
            }
        return EvalContext(
            request=None,
            user=user,
            session=session
        )

    async def process_batch(self, batch, env, rewards):
        ### Create the Context for each User
        tasks = []
        for user in batch:
            try:
                # Create context safely
                ctx = self._get_context_user(user)
                # Create the async task
                task = asyncio.create_task(
                    self._process_user_batch(ctx, env, rewards)
                )
                tasks.append(task)
            except Exception as err:
                usr = getattr(user, 'email', 'unknown')
                self.logger.error(
                    f"Error creating context for user {usr}: {err}"
                )
                continue
        # Execute all tasks
        if tasks:
            with contextlib.suppress(asyncio.exceptions.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_user_batch(
        self,
        ctx,
        env,
        reward: Union[RewardObject, list]
    ):
        """Process rewards for a single user context."""
        try:
            if isinstance(reward, list):
                # Process multiple rewards
                tasks = []
                for r in reward:
                    task = asyncio.create_task(
                        self._evaluate_user_reward(r, ctx, env)
                    )
                    tasks.append(task)

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            else:
                # Process single reward
                await self._evaluate_user_reward(reward, ctx, env)

        except Exception as err:
            user_email = getattr(ctx.user, 'email', 'unknown') if ctx.user else 'unknown'  # noqa
            self.logger.error(
                f"Error processing user batch for {user_email}: {err}"
            )

    async def _custom_message(
        self,
        reward: RewardObject,
        ctx: EvalContext,
        env: Environment,
        user: User,
        **kwargs
    ):
        msg = reward.reward().message
        try:
            template = self.env.from_string(msg)
            try:
                args = ctx.args
            except AttributeError:
                args = {}
            jinja_params = {
                "ctx": ctx,
                "user": user,
                "env": env,
                "args": args,
                "session": ctx.session,
                **kwargs
            }
            message = await template.render_async(**jinja_params)
            return message
        except TemplateError as ex:
            raise ValueError(
                f"Template parsing error: {ex}"
            ) from ex
        except Exception as err:
            self.logger.error(
                f"Error rendering Message: {err}"
            )

    async def _evaluate_user_reward(
        self,
        reward: RewardObject,
        ctx: EvalContext,
        env: Environment
    ):
        """Evaluate and potentially apply a reward for a user."""
        try:
            # Wait to acquire the semaphore before getting a connection
            async with self._semaphore:
                user = ctx.user
                if not user:
                    self.logger.warning(
                        "No user in context for reward evaluation"
                    )
                    return False

                async with await self.connection.acquire() as conn:  # pylint: disable=E1101
                    # Evaluate Reward for this User:
                    if not reward.fits(ctx=ctx, env=env):
                        # Reward does not fit the user
                        return False

                    session_user_id = None
                    try:
                        session_user_id = ctx.session.get('user_id')
                    except AttributeError:
                        session_user_id = getattr(ctx.session, 'user_id', None)

                    if await reward.has_awarded(
                        user,
                        env,
                        conn,
                        reward.timeframe,
                        giver_user=session_user_id
                    ):
                        # User already has this reward
                        return False

                    if await reward.evaluate(ctx=ctx, env=env):
                        # Evaluate and Apply the Reward
                        try:
                            message = await self._custom_message(
                                reward, ctx, env, user
                            )
                            self.logger.info(
                                f'EVALUATING for {user.email}: {reward.name}'
                            )
                            # Here you would apply the reward
                            # await reward.apply(ctx, env, conn, message=message)  # noqa
                            return True
                        except Exception as msg_err:
                            self.logger.error(
                                f"Error generating reward message: {msg_err}"
                            )
                            return False

        except Exception as err:
            user_email = getattr(ctx.user, 'email', 'unknown') if ctx.user else 'unknown'  # noqa
            self.logger.error(
                f"Error evaluating reward for user {user_email}: {err}"
            )
            return False

    async def check_user(
        self,
        data: BaseModel,
        env: Environment
    ) -> BaseModel:
        """check_user.
        """
        try:
            return await get_user(self.connection, user_id=data.user_id)
        except Exception as err:
            raise RuntimeError(
                f"Error on Fetch User: {err}"
            ) from err

    async def _evaluate_reward(
        self,
        reward: RewardObject,
        ctx: EvalContext,
        env: Environment
    ):
        try:
            async with self._user_semaphore:
                async with await self.connection.acquire() as conn:  # pylint: disable=E1101
                    # Evaluate Reward for this User:
                    session_user_id = None
                    try:
                        session_user_id = ctx.session.get('user_id')
                    except AttributeError:
                        session_user_id = getattr(ctx.session, 'user_id', None)

                    if await reward.has_awarded(
                        ctx.user,
                        env,
                        conn,
                        reward.reward().timeframe,
                        giver_user=session_user_id
                    ):
                        # User already has this reward
                        return False
                    if await reward.evaluate(
                        ctx=ctx, environ=env
                    ):
                        # Apply Reward to User:
                        try:
                            # Using Apply method from reward itself
                            print('APPLYING REWARD  > ', reward)
                            error = None
                            # r, error = await reward.apply(ctx, env, conn)
                            if error := None:
                                self.logger.error(
                                    str(error)
                                )
                                raise RuntimeError(
                                    str(error)
                                )
                        except Exception:
                            raise
        except Exception as err:
            logging.error(
                f"Error applying reward: {err}"
            )

    async def evaluate(
        self,
        request: web.Request,
        session: Any,
        user: BaseModel
    ):
        """Evaluate Rewards for a specific User.
        """
        with contextlib.suppress(Exception):
            user = await get_user(self.connection, user_id=user.user_id)
        env = Environment()
        ctx = EvalContext(
            request=request,
            user=user,
            session=session
        )
        # Filter Rewards that fit Inquiry by its attributes.
        # only evaluate non-user badges:
        _allowed = ['Automated Badge', 'Recognition Badge']
        _filtered = [
            p for p in self._rewards if p.fits(
                ctx, env
            ) and p.reward_type in _allowed
        ]
        for reward in _filtered:
            print('EVALUATING REWARD > ', reward)
            asyncio.create_task(
                self._evaluate_reward(
                    reward, ctx, env
                )
            )
        return True

    # Aditional methods for scheduling different rewards evaluation:
    async def _evaluate_auto_workflows(self, app: web.Application):
        """
        Evaluate all workflow-based rewards for all users.
        This method runs every 4 hours to check workflow progression.
        """
        self.logger.info("Starting auto-workflow evaluation cycle")
        # Filter for workflow-type rewards
        workflow_types = ['Workflow Badge', 'Auto Workflow Badge', 'Challenge']
        workflow_rewards = [
            reward for reward in self._rewards
            if (reward.reward_type in workflow_types and
                reward.is_enabled() and hasattr(reward, 'workflow_steps')
                )
        ]
        if not workflow_rewards:
            self.logger.info(
                "No workflow rewards found for evaluation"
            )
            return

        try:
            users = []
            # Get all active users
            try:
                users = await filter_users(self.connection, is_active=True)
            except Exception as err:
                self.logger.error(
                    f"Error fetching users for workflow evaluation: {err}"
                )
                return

            if not users:
                self.logger.info(
                    "No users found for workflow evaluation"
                )
                return

            self.logger.info(
                f"Evaluating workflows for {len(users)} users"
            )

            # Create environment for evaluation
            env = Environment(
                connection=self.connection,
                cache=self.get_cache()
            )

            # Process users in batches
            _evaluations = 0
            _completions = 0

            for i in range(0, len(users), self._batch_size):
                batch = users[i:i + self._batch_size]
                bte, btc = await self._process_workflow_batch(
                    batch, env, workflow_rewards
                )
                _evaluations += bte
                _completions += btc

                # Log progress every few batches
                if (i // self._batch_size) % 5 == 0:
                    self.logger.info(
                        f"Processed {i + len(batch)}/{len(users)} users. "
                        f"Evaluations: {_evaluations}, Completions: {_completions}"  # noqa
                    )

            self.logger.info(
                f"Auto-workflow evaluation completed. "
                f"Total evaluations: {_evaluations}, "
                f"Total completions: {_completions}"
            )

        except Exception as err:
            self.logger.error(
                f"Error in auto-workflow evaluation: {err}"
            )

    async def _process_workflow_batch(
        self,
        user_batch: list,
        env: Environment,
        workflow_rewards: list
    ) -> tuple:
        """
        Process a batch of users for workflow evaluation.

        Returns:
            Tuple of (total_evaluations, total_completions)
        """
        tasks = []

        # Create evaluation tasks for each user-workflow combination
        for user in user_batch:
            for workflow_reward in workflow_rewards:
                task = asyncio.create_task(
                    self._evaluate_user_workflow(user, workflow_reward, env)
                )
                tasks.append(task)

        # Execute all tasks and collect results
        if tasks:
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Count successes and completions
                total_evaluations = len(
                    [r for r in results if not isinstance(r, Exception)]
                )
                total_completions = len(
                    [r for r in results if r is True]
                )

                # Log any exceptions
                if exceptions := [
                    r for r in results if isinstance(r, Exception)
                ]:
                    self.logger.warning(
                        f"Workflow evaluation exceptions: {len(exceptions)}"
                    )
                    for exc in exceptions[:5]:  # Log first 5 exceptions
                        self.logger.debug(
                            f"Workflow evaluation exception: {exc}"
                        )

                return total_evaluations, total_completions

            except Exception as err:
                self.logger.error(f"Error processing workflow batch: {err}")
                return 0, 0

        return 0, 0

    async def _evaluate_user_workflow(
        self,
        user: User,
        reward: RewardObject,
        env: Environment
    ) -> bool:
        """
        Evaluate a single workflow for a single user.

        Args:
            user: The user to evaluate
            workflow_reward: The workflow reward object
            env: Environment context

        Returns:
            True if workflow was completed and reward awarded
        """
        try:
            # Create user context
            ctx = self._get_context_user(user)

            # Check if this workflow fits the user (program restrictions, etc.)
            if not reward.fits(ctx=ctx, env=env):
                return False

            # Evaluate the workflow
            if completed := await reward.evaluate(ctx=ctx, env=env):
                # Workflow was completed - award the reward
                try:
                    async with await self.connection.acquire() as conn:  # pylint: disable=E1101
                        reward_awarded, error = await reward.apply(
                            ctx=ctx,
                            env=env,
                            conn=conn
                        )

                        if reward_awarded:
                            self.logger.info(
                                f"Awarded workflow reward '{reward.name}' "
                                f"to user {user.email} (ID: {user.user_id})"
                            )
                            return True
                        elif error:
                            self.logger.error(
                                f"Error awarding workflow reward to {user.email}: {error}"  # noqa
                            )

                except Exception as err:
                    self.logger.error(
                        f"Error applying workflow reward for user {user.email}: {err}"  # noqa
                    )

            return False

        except Exception as err:
            self.logger.error(
                f"Error evaluating workflow for user {getattr(user, 'email', 'unknown')}: {err}"  # noqa
            )
            return False

    async def _evaluate_single_workflow_type(
        self,
        workflow_type: str,
        app: web.Application
    ):
        """
        Evaluate workflows of a specific type (useful for targeted evaluations)

        Args:
            workflow_type: Type of workflow to evaluate
                (e.g., 'Workflow Badge')
            app: Application instance
        """
        try:
            self.logger.info(
                f"Evaluating workflows of type: {workflow_type}"
            )

            # Filter for specific workflow type
            workflow_rewards = [
                reward for reward in self._rewards
                if (reward.reward_type == workflow_type and
                    reward.is_enabled() and hasattr(reward, 'workflow_steps')
                    )
            ]

            if not workflow_rewards:
                self.logger.info(f"No {workflow_type} rewards found")
                return

            # Get users and evaluate
            users = await filter_users(self.connection, is_active=True)
            env = Environment(
                connection=self.connection,
                cache=self.get_cache()
            )

            # Process in batches
            for i in range(0, len(users), self._batch_size):
                batch = users[i:i + self._batch_size]
                await self._process_workflow_batch(
                    batch,
                    env,
                    workflow_rewards
                )

            self.logger.info(
                f"Completed evaluation of {workflow_type} workflows"
            )

        except Exception as err:
            self.logger.error(
                f"Error evaluating {workflow_type} workflows: {err}"
            )

    async def _get_draft_campaigns(
        self,
        env: Environment,
        campaign: NominationCampaign
    ) -> Optional[NominationAward]:
        current_time = env.timestamp
        if current_time >= campaign.nomination_start:
            try:
                nomination_reward = await self.get_nomination_reward(  # noqa
                    campaign.reward_id
                )
                if nomination_reward:
                    await nomination_reward.start_nomination_phase(
                        campaign.campaign_id,
                        env
                    )
                    self.logger.info(
                        f"Auto-started nomination phase for campaign {campaign.campaign_id}"  # noqa
                    )
            except Exception as err:
                self.logger.error(
                    f"Error auto-starting nomination phase: {err}"
                )

    async def _get_nomination_campaigns(
        self,
        env: Environment,
        campaign: NominationCampaign
    ) -> None:

        current_time = env.timestamp
        if current_time >= campaign.nomination_end:
            try:
                nomination_reward = await self.get_nomination_reward(   # noqa
                    campaign.reward_id
                )
                if nomination_reward and campaign.total_nominations >= campaign.min_nominations_to_proceed:   # noqa
                    await nomination_reward.start_voting_phase(
                        campaign.campaign_id,
                        env
                    )
                    self.logger.info(
                        f"Auto-started voting phase for campaign {campaign.campaign_id}"  # noqa
                    )
                elif nomination_reward:
                    # Not enough nominations, cancel campaign
                    campaign.status = CampaignStatus.CANCELLED.value
                    await campaign.save()
                    self.logger.info(
                        f"Cancelled campaign {campaign.campaign_id} - insufficient nominations"  # noqa
                    )
            except Exception as err:
                self.logger.error(
                    f"Error auto-starting voting phase: {err}"
                )

    async def _get_voting_campaigns(
        self,
        env: Environment,
        campaign: NominationCampaign
    ) -> None:

        current_time = env.timestamp
        if current_time >= campaign.voting_end:
            try:
                if _nomination := await self.get_nomination_reward(
                    campaign.reward_id
                ):
                    winner = await _nomination.close_campaign_and_select_winner(  # noqa
                        campaign.campaign_id,
                        env
                    )
                    if winner:
                        self.logger.info(
                            f"Auto-closed campaign {campaign.campaign_id} with winner {winner.nominee_email}"  # noqa
                        )
                    else:
                        self.logger.info(
                            f"Auto-closed campaign {campaign.campaign_id} with no winner"  # noqa
                        )
            except Exception as err:
                self.logger.error(
                    f"Error auto-closing campaign: {err}"
                )

    async def _check_nomination_phases(self, app):
        """Check and transition nomination campaign phases automatically."""
        try:
            env = Environment(
                connection=self.connection,
                cache=self.get_cache()
            )
            async with await self.connection.acquire() as conn:  # pylint: disable=E1101
                NominationCampaign.Meta.connection = conn

                # Check campaigns that should transition to nomination phase
                draft_campaigns = await NominationCampaign.filter(
                    status=CampaignStatus.DRAFT.value
                )

                for campaign in draft_campaigns:
                    await self._get_draft_campaigns(env, campaign)

                # Check campaigns that should transition to voting phase
                nomination_campaigns = await NominationCampaign.filter(
                    status=CampaignStatus.NOMINATION_PHASE.value
                )

                for campaign in nomination_campaigns:
                    await self._get_nomination_campaigns(env, campaign)

                # Check campaigns that should close and select winners
                voting_campaigns = await NominationCampaign.filter(
                    status=CampaignStatus.VOTING_PHASE.value
                )

                for campaign in voting_campaigns:
                    await self._get_voting_campaigns(
                        env, campaign
                    )

        except Exception as err:
            self.logger.error(
                f"Error in nomination phase checker: {err}"
            )

    async def get_nomination_reward(
        self,
        reward_id: int
    ) -> Optional[NominationAward]:
        """Get a nomination reward by ID."""
        reward = await self.get_reward(reward_id)
        return reward if reward and isinstance(
            reward, NominationAward
        ) else None

    async def create_nomination_campaign(
        self,
        request,
        reward_id: int,
        campaign_name: str,
        description: str = "",
        start_date: datetime = None
    ):
        """Helper method to create nomination campaigns."""
        try:
            session, user = await self.get_user(request)

            nomination_reward = await self.get_nomination_reward(reward_id)
            if not nomination_reward:
                raise ValueError("Reward is not a nomination type")

            env = Environment(
                connection=self.connection,
                cache=self.get_cache()
            )

            ctx = EvalContext(
                request=request,
                user=user,
                session=session
            )

            return await nomination_reward.create_campaign(
                ctx=ctx,
                env=env,
                campaign_name=campaign_name,
                description=description,
                start_date=start_date
            )

        except Exception as err:
            self.logger.error(
                f"Error creating nomination campaign: {err}"
            )
            raise

    async def _process_nomination_event(
        self,
        event_name: str,
        event_body: dict
    ):
        """Process nomination-specific events."""
        try:
            if event_name == 'nomination.campaign_created':
                # Handle campaign creation notifications
                await self._notify_campaign_created(event_body)

            elif event_name == 'nomination.phase_started':
                # Handle phase transition notifications
                await self._notify_phase_started(event_body)

            elif event_name == 'nomination.nomination_submitted':
                # Handle new nomination notifications
                await self._notify_nomination_submitted(event_body)

            elif event_name == 'nomination.voting_started':
                # Handle voting phase notifications
                await self._notify_voting_started(event_body)

            elif event_name == 'nomination.winner_selected':
                # Handle winner selection notifications
                await self._notify_winner_selected(event_body)

        except Exception as err:
            self.logger.error(
                f"Error processing nomination event {event_name}: {err}"
            )

    async def _notify_campaign_created(self, event_data: dict):
        """Send notifications when nomination campaign is created."""
        # Implementation for notifying eligible users about new campaign
        pass

    async def _notify_phase_started(self, event_data: dict):
        """Send notifications when campaign phase changes."""
        # Implementation for notifying users about phase transitions
        pass

    async def _notify_nomination_submitted(self, event_data: dict):
        """Send notifications when someone is nominated."""
        # Implementation for notifying nominees and relevant users
        pass

    async def _notify_voting_started(self, event_data: dict):
        """Send notifications when voting starts."""
        # Implementation for notifying eligible voters
        pass

    async def _notify_winner_selected(self, event_data: dict):
        """Send notifications when winner is selected."""
        # Implementation for announcing the winner
        pass

    def _setup_award_endpoints(
        self
    ):
        # nomination award endpoints
        # Campaign with Nomination:
        self.app.router.add_post(
            '/rewards/api/v1/nomination_campaigns/create',
            NominationAwardHandler().create_campaign
        )
        self.app.router.add_post(
            '/rewards/api/v1/nomination_campaigns/{campaign_id}/start_nomination',  # noqa
            NominationAwardHandler().start_nomination_phase
        )
        self.app.router.add_post(
            '/rewards/api/v1/nomination_campaigns/{campaign_id}/start_voting',
            NominationAwardHandler().start_voting_phase
        )
        self.app.router.add_post(
            '/rewards/api/v1/nomination_campaigns/{campaign_id}/close',
            NominationAwardHandler().close_campaign
        )
        self.app.router.add_get(
            '/rewards/api/v1/nomination_campaigns/{campaign_id}/status',
            NominationAwardHandler().get_campaign_status
        )
        # with pre-candidates
        self.app.router.add_post(
            '/rewards/api/v1/nomination_awards/create_with_candidates',
            NominationAwardHandler().create_campaign_with_candidates
        )

        self.app.router.add_post(
            '/rewards/api/v1/nomination_awards/{campaign_id}/add_candidate',
            NominationAwardHandler().add_candidate_to_campaign
        )

        self.app.router.add_post(
            '/rewards/api/v1/nomination_awards/{campaign_id}/start_voting',
            NominationAwardHandler().start_voting_direct
        )

        # Vote statistics endpoints
        self.app.router.add_get(
            '/rewards/api/v1/nomination_awards/{campaign_id}/vote_statistics',
            NominationAwardHandler().get_vote_statistics
        )

        self.app.router.add_get(
            '/rewards/api/v1/nomination_awards/{campaign_id}/vote_counts',
            NominationAwardHandler().get_real_time_vote_counts
        )

        self.app.router.add_get(
            '/rewards/api/v1/nomination_awards/{campaign_id}/leaderboard',
            NominationAwardHandler().get_candidate_leaderboard
        )

        self.app.router.add_get(
            '/rewards/api/v1/nomination_awards/{campaign_id}/user_status',
            NominationAwardHandler().get_user_voting_status
        )

        self.app.router.add_get(
            '/rewards/api/v1/nomination_awards/{campaign_id}/summary',
            NominationAwardHandler().get_campaign_summary
        )
        # Nomination management
        self.app.router.add_post(
            '/rewards/api/v1/nominations/submit',
            NominationHandler().submit_nomination
        )
        self.app.router.add_get(
            '/rewards/api/v1/nominations/campaign/{campaign_id}',
            NominationHandler().get_campaign_nominations
        )
        # Voting management
        self.app.router.add_post(
            '/rewards/api/v1/nomination_votes/submit',
            NominationVoteHandler().submit_vote
        )
        self.app.router.add_get(
            '/rewards/api/v1/nomination_votes/nomination/{nomination_id}',
            NominationVoteHandler().get_nomination_votes
        )

        # Comment management
        self.app.router.add_post(
            '/rewards/api/v1/nomination_comments/nomination/{nomination_id}',
            NominationCommentHandler().add_comment
        )
        self.app.router.add_get(
            '/rewards/api/v1/nomination_comments/nomination/{nomination_id}',
            NominationCommentHandler().get_nomination_comments
        )

        # Schedule automatic phase transitions
        self.scheduler.add_job(
            self._check_nomination_phases,
            'interval',
            minutes=15,  # Check every 15 minutes
            args=[self.app],
            id='nomination_phase_checker',
            replace_existing=True
        )
