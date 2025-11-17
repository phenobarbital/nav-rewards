from typing import Optional, Any, Union
import importlib
import inspect
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import contextlib
from jinja2 import TemplateError
from datamodel.parsers.json import json_decoder
from datamodel.exceptions import ValidationError, ParserError
from asyncdb.exceptions import DriverError
from navconfig.logging import logging
from navconfig import config
from notify.providers.teams import Teams
from notify.providers.ses import Ses
from notify.models import Actor
from ..conf import (
    REWARDS_CLIENT_ID,
    REWARDS_CLIENT_SECRET,
    REWARDS_USER,
    REWARDS_PASSWORD,
    TIMEZONE,
)
from ..models import (
    RewardView,
    UserReward
)
from ..rules import (
    AbstractRule
)
from ..context import EvalContext
from ..env import Environment


try:
    LOCAL_TIMEZONE = ZoneInfo(TIMEZONE)
except Exception:
    LOCAL_TIMEZONE = timezone.utc

class RewardObject:
    def __init__(
        self,
        reward: RewardView,
        rules: Optional[list] = None,
        conditions: Optional[dict] = None,
        **kwargs
    ):
        self._id: int = reward.reward_id
        self.logger = logging.getLogger(
            f"Reward.{self._id}"
        )
        self._reward: RewardView = reward
        self._conditions = conditions
        self._rules: Optional[list[AbstractRule]] = []
        self._load_rules(rules)
        self.timeframe: str = reward.timeframe
        if reward.events:
            self._events: Optional[list] = [
                event for event in reward.events if event is not None
            ]
        else:
            self._events = []
        self._kwargs = kwargs
        self._template_engine = None

    def is_enabled(self) -> bool:
        return self._reward.is_enabled

    @property
    def template_engine(self):
        return self._template_engine

    @template_engine.setter
    def template_engine(self, engine):
        self._template_engine = engine

    def reward(self):
        return self._reward

    @property
    def id(self):
        return self._id

    @property
    def emoji(self):
        """Return the emoji associated with the reward."""
        return self._reward.emoji

    @property
    def name(self):
        return self._reward.reward

    @property
    def multiple(self) -> bool:
        return self._reward.multiple

    @property
    def conditions(self):
        return self._conditions

    @property
    def reward_type(self):
        return self._reward.reward_type

    def __str__(self):
        return f"{self._reward.reward}: {self._reward.description}"

    def __repr__(self):
        return f"{self._reward.reward}: {self._reward.description}"

    def get_user_context(self, user):
        # Emulate Session Context:
        session = {
            "username": user.email,
            "id": user.email,
            "user_id": user.user_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "name": user.display_name,
            "email": user.email,
            "birth_date": user.birth_date(),
            "associate_id": getattr(user, 'associate_id', user.email),
            "employment_duration": user.employment_duration(),
            "session": {
                "groups": user.groups,
                "programs": user.programs,
                "start_date": user.start_date,
                "birthday": user.birthday,
                "worker_type": user.worker_type,
                "job_code": user.job_code,
            }
        }
        ctx = EvalContext(
            request=None,
            user=user,
            session=session
        )
        return ctx, session

    def _load_rules(self, rules: Optional[list]):
        if rules:
            for rule in rules:
                self.add_rule(rule)

    def _load_rule(self, rule_obj: str) -> AbstractRule:
        """Load a Rule from a string."""
        try:
            args = {}
            rule = rule_obj.pop(0)
            if rule_obj:
                args = rule_obj[0]
            # Inject current reward_id for rules that need it
            if rule in ['ComputedRule']:
                args['current_reward_id'] = self._reward.reward_id
            self.logger.notice(
                f"Reward: Loading Rule: {rule}"
            )
            module_path = "rewards.rules"
            module = importlib.import_module(
                module_path, rule
            )
            rule_class = getattr(module, rule)
            return rule_class(
                conditions=self._conditions,
                **args
            )
        except (ValueError, ModuleNotFoundError, AttributeError) as exc:
            self.logger.error(
                f"Error loading Rule {rule_obj}: {exc}"
            )

    def add_rule(self, rule: Union[str, AbstractRule]):
        """Add a Rule to the Reward."""
        if not rule:
            return
        if isinstance(rule, list):
            if len(rule) == 0:
                self.logger.warning(
                    "Empty rule list, skipping"
                )
                return
            rule = self._load_rule(rule)
        elif isinstance(rule, dict):
            rule = self._load_rule_from_dict(rule)
        elif isinstance(rule, str):
            # Handle string rule names
            rule = self._load_rule([rule, {}])
        elif not isinstance(rule, AbstractRule):
            raise ValueError(
                f"Invalid Rule Type: {type(rule)}"
            )
        self._rules.append(rule)

    def _load_rule_from_dict(self, rule_dict: dict) -> AbstractRule:
        """Load a Rule from a dictionary format."""
        try:
            # Extract rule name from dictionary
            rule_name = rule_dict.pop(
                'rule_type',
                None
            ) or rule_dict.pop('type', None)
            if not rule_name:
                raise ValueError(
                    "Rule dictionary must contain 'rule_type' or 'type' field"
                )

            # Remaining dictionary items become the arguments
            args = rule_dict.copy()

            # Inject current reward_id for rules that need it
            if rule_name in ['ComputedRule']:
                args['current_reward_id'] = self._reward.reward_id

            self.logger.notice(
                f"Reward: Loading Rule from dict: {rule_name}"
            )

            module_path = "rewards.rules"
            module = importlib.import_module(module_path, rule_name)
            rule_class = getattr(module, rule_name)
            return rule_class(
                conditions=self._conditions,
                **args
            )
        except (ValueError, ModuleNotFoundError, AttributeError) as exc:
            self.logger.error(
                f"Error loading Rule from dict {rule_dict}: {exc}"
            )
            raise

    @staticmethod
    def _parse_time(time_str: str, format: str = "%H:%M:%S"):
        """Parse a string into a datetime.time object."""
        return datetime.strptime(time_str, format).time()

    @staticmethod
    def _parse_date(time_str: str, format: str = "%Y-%d-%m"):
        """Parse a string into a datetime.time object."""
        year = datetime.now().year
        try:
            return datetime.strptime(
                f"{year}-{time_str}",
                format
            ).date()
        except ValueError:
            return datetime.strptime(
                f"{time_str}/{year}",
                '%d/%m/%Y'
            ).date()

    async def _reward_message(
        self,
        ctx: EvalContext,
        env: Environment,
        user: Any,
        **kwargs
    ):
        msg = self._reward.message or kwargs.get('message', None)
        if not msg:
            return "Congratulations! You've received a Badge!"
        try:
            template = self._template_engine.from_string(msg)
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
            return msg

    def fits_event(self, event_name: str) -> bool:
        """Check if this Reward fits based on a triggered event."""
        try:
            return next(
                (
                    event[event_name]
                    for event in self._events
                    if event is not None and event_name in event
                ),
                None
            )
        except (KeyError, AttributeError):
            return False

    def evaluate_environment(self, current_environment: Environment) -> bool:
        availability = self._reward.availability_rule
        fit_time = True
        fit_date = True
        fit_matches = True

        # Check if there are start and end times in the availability rule
        if 'start_time' in availability and 'end_time' in availability:
            start_time = self._parse_time(
                availability.get('start_time')  # Use get() instead of pop()
            )
            end_time = self._parse_time(
                availability.get('end_time')    # Use get() instead of pop()
            )
            current_time = current_environment.timestamp.time()
            fit_time = start_time <= current_time <= end_time

        if 'start_date' in availability and 'end_date' in availability:
            start_date = self._parse_date(
                availability.get('start_date')  # Use get() instead of pop()
            )
            end_date = self._parse_date(
                availability.get('end_date')    # Use get() instead of pop()
            )
            current_date = current_environment.curdate
            fit_date = start_date <= current_date <= end_date

        # Check remaining attributes (excluding time/date keys)
        remaining_attrs = {
            k: v for k, v in availability.items()
            if k not in ('start_time', 'end_time', 'start_date', 'end_date')
        }

        matches = (
            # Check if the value in the policy environment is a range
            # If not, check for equality
            (isinstance(val, (range, list)) and current_environment[key] in val) or  # noqa
            (current_environment[key] == val)
            for key, val in remaining_attrs.items()
        )
        fit_matches = all(matches)

        return all([fit_time, fit_date, fit_matches])

    def _evaluate_as_json(self, text) -> Union[dict, list, str]:
        """Evaluate a string as JSON."""
        try:
            if text.startswith(('{', '[')):
                # replace single quotes with double quotes
                text = text.replace("'", '"')
            return json_decoder(text)
        except (ValueError, ParserError) as exc:
            self.logger.error(
                f"Error parsing *{text}* JSON: {exc}"
            )
            return text

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        # Check if the current environment matches the reward's requirements
        fit_results = {
            "fit_context": True,
            "fit_environment": self.evaluate_environment(env),
            "fit_programs": False,
            # by default there is no limitation by roles/jobs
            "fit_assigner": True,
            "fit_events": True,
            "fit_rules": True  # by default, there is no rules
        }
        self._failed_conditions = []
        programs = self._reward.programs
        if programs:
            ctx_programs = ctx.store.get('programs') or getattr(
                ctx.user, 'programs', []
            ) or []
            fit_results["fit_programs"] = not set(programs).isdisjoint(ctx_programs)  # noqa
        else:
            # by default, if no program constraint, then fits.
            fit_results["fit_programs"] = True
        # Check User/Session Context:
        if self._conditions:
            fit_results["fit_context"] = any(
                a in ctx.store['user_keys'] or a in ctx.store['session'].keys() or
                getattr(ctx, a, None) is not None
                for a in self._conditions.keys()
            )
        # Check of Assigner:
        if assigners := self._reward.assigner:
            for assigner in assigners:
                if assigner is None:
                    continue
                if isinstance(assigner, str):
                    assigner = self._evaluate_as_json(assigner)
                if isinstance(assigner, str):
                    # check by user_id or email
                    fit_results["fit_assigner"] = assigner in [
                        ctx.session.get('user_id', None),
                        ctx.session.get('email', None),
                    ]
                elif isinstance(assigner, dict):
                    # check by groups or by job_code
                    if 'job_code' in assigner:
                        job_code = ctx.session.get('job_code', None)
                        fit_results["fit_assigner"] = job_code in assigner.get('job_code', [])  # noqa
                    if 'groups' in assigner:
                        groups = assigner.get('groups', [])
                        ctx_groups = ctx.session.groups
                        fit_results["fit_assigner"] = not set(groups).isdisjoint(ctx_groups)  # noqa
                elif isinstance(assigner, int):
                    # check by user_id
                    fit_results["fit_assigner"] = assigner == ctx.session.get('user_id', None)  # noqa
                else:
                    self.logger.error(
                        f"Invalid assigner type: {type(assigner)}"
                    )
                    fit_results["fit_assigner"] = False
        # Fit by Rules:
        fit_rules = {}
        for rule in self._rules:
            print('RULE > ', rule)
            try:
                fit_results["fit_rules"] = rule.fits(ctx, env)
                fit_rules[f"{rule!s}"] = fit_results["fit_rules"]
            except Exception as exc:
                self.logger.error(
                    f"Error on Rule {rule}: {exc}"
                )
                fit_results["fit_rules"] = False
                fit_rules[f"{rule!s}"] = False
        # Determine overall fit
        overall_fit = all(fit_results.values())
        # If not all conditions are met, log or save the failed conditions
        if not overall_fit:
            failed_conditions = [
                key for key, value in fit_results.items() if not value
            ]
            self._failed_conditions = failed_conditions
            self._failed_conditions.append({
                "rules": fit_rules
            })
        return overall_fit

    def failed_conditions(self):
        failed = self._failed_conditions.copy()
        self._failed_conditions = []
        return failed

    async def check_awardee(self, ctx: EvalContext):
        """check_awardee.

        Args:
            ctx (EvalContext): Evaluation Context
        """
        # Check of Awardee, by default, there is no restrictions
        fit_awardee = True
        awardees = self._reward.awardee or []
        for awardee in awardees:
            if awardee is None:
                continue
            # check by groups or by job_code
            if 'job_code' in awardee:
                job_code = ctx.store.get('job_code', None)
                if isinstance(job_code, str):
                    job_code = [job_code]
                fit_awardee = job_code in awardee.get('job_code', [])
            if 'groups' in awardee:
                groups = awardee.get('groups', [])
                ctx_groups = ctx.store.get('groups', [])
                fit_awardee = not set(groups).isdisjoint(ctx_groups)
        return fit_awardee

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """
        Evaluates the Reward against the rules.

        :param ctx: The evaluation context, containing user and session
            information.
        :param environ: The environment information, such as the current time.
        :return: True if this Reward can be applied to User.
        """
        if await self.check_awardee(ctx):
            # Gather results of all rule evaluations
            results = await asyncio.gather(
                *(rule.evaluate(ctx, env) for rule in self._rules)
            )
            completed = all(results)
            if not completed:
                self._failed_conditions.append({
                    "rules": results
                })
            return completed
        else:
            self._failed_conditions.append({
                "awardee": False
            })
            return False

    @staticmethod
    def _timeframe_to_timedelta(timeframe: Optional[str]) -> Optional[timedelta]:
        """Convert a timeframe string into a timedelta.

        Supports legacy values like ``daily`` as well as the new
        ``minutes|hours|days`` formats, optionally with a quantity
        (e.g. ``hours:2``).
        """
        if not timeframe:
            return None

        raw_timeframe = timeframe.strip().lower()
        quantity = 1
        if ':' in raw_timeframe:
            unit, qty = raw_timeframe.split(':', 1)
            raw_timeframe = unit.strip()
            try:
                quantity = int(qty.strip())
            except ValueError:
                return None
            if quantity <= 0:
                return None

        aliases = {
            'minute': 'minutes',
            'minutes': 'minutes',
            'min': 'minutes',
            'hour': 'hours',
            'hours': 'hours',
            'hr': 'hours',
            'hourly': 'hours',
            'day': 'days',
            'days': 'days',
            'daily': 'days',
            'week': 'weeks',
            'weeks': 'weeks',
            'weekly': 'weeks',
            'biweekly': 'weeks',
            'month': 'months',
            'months': 'months',
            'monthly': 'months',
            'quarter': 'quarters',
            'quarters': 'quarters',
            'quarterly': 'quarters',
        }

        unit = aliases.get(raw_timeframe, raw_timeframe)
        if unit == 'minutes':
            return timedelta(minutes=quantity)
        if unit == 'hours':
            return timedelta(hours=quantity)
        if unit == 'days':
            return timedelta(days=quantity)
        if unit == 'weeks':
            return timedelta(weeks=quantity)
        if unit == 'months':
            # Approximate months as 30 days to maintain backward compatibility
            return timedelta(days=30 * quantity)
        return timedelta(days=90 * quantity) if unit == 'quarters' else None

    async def has_awarded(
        self,
        user: int,
        env: Environment,
        conn: Any,
        timeframe: Optional[str] = None,
        giver_user: Optional[int] = None,
        cooldown_minutes: int = 1
    ) -> bool:
        """
        Check if a user has already received this reward.

        Args:
            user: The user object
            env: Environment with current timestamp
            conn: Database connection
            timeframe: Optional timeframe for multiple rewards ('daily', 'weekly', 'monthly', 'hourly')
            cooldown_minutes: Minimum minutes between receiving same badge (default: 1)

        Returns:
            bool: True if user already has this reward (within constraints), False otherwise
        """
        query = """
SELECT awarded_at, giver_user FROM rewards.users_rewards
WHERE receiver_user = $1::int AND reward_id = $2::int
AND revoked = FALSE
AND deleted_at IS NULL
        """
        params = [user.user_id, self.id]
        use_giver_filter = giver_user is not None and self.multiple
        if use_giver_filter:
            query += " AND giver_user = $3::int"
            params.append(giver_user)
        query += " ORDER BY awarded_at DESC;"
        rewards = await conn.fetch_all(
            query,
            *params
        )

        if not rewards:
            # No rewards were awarded for this user.
            return False

        # check if this reward can be applied multiple times:
        if not self.multiple:
            return True  # Non-multiple rewards are awarded once

        def _to_utc(dt: datetime) -> datetime:
            """Return a timezone-aware UTC datetime for comparisons."""
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        def _to_local(dt: datetime) -> datetime:
            """Convert a timestamp to the configured project timezone."""
            return _to_utc(dt).astimezone(LOCAL_TIMEZONE)

        # SPAM PREVENTION: Check cooldown period
        most_recent_award = _to_utc(rewards[0]['awarded_at'])
        current_ts = _to_utc(env.timestamp)
        current_ts_local = _to_local(current_ts)

        effective_cooldown = self._reward.cooldown_minutes or cooldown_minutes
        time_since_last_award = current_ts - most_recent_award
        if time_since_last_award < timedelta(minutes=effective_cooldown):
            self.logger.debug(
                f"Cooldown active: Last award was {time_since_last_award.total_seconds():.0f}s ago "
            )
            return True  # Within cooldown period

        relevant_rewards = [
            {
                **rw,
                'awarded_at': _to_utc(rw['awarded_at'])
            }
            for rw in rewards
        ]

        effective_timeframe = timeframe or self._reward.timeframe
        timeframe_key = effective_timeframe.strip().lower() if effective_timeframe else None
        # Let's check if the reward can be awarded multiple times based on Time Frame
        allowed_timeframes = {
            'daily': lambda timestamp: timestamp.date(),
            'weekly': lambda timestamp: timestamp.strftime('%Y-%W'),
            'monthly': lambda timestamp: timestamp.strftime('%Y-%m'),
            'hourly': lambda timestamp: timestamp.replace(
                minute=0,
                second=0,
                microsecond=0
            ),
            'bihourly': lambda timestamp: (
                timestamp.replace(
                    minute=0 if timestamp.minute < 30 else 30,
                    second=0,
                    microsecond=0
                )
            ),
            'biweekly': lambda timestamp: (
                f"{timestamp.year}-W{((timestamp.isocalendar()[1] - 1) // 2) + 1}"
            ),
            'quarterly': lambda timestamp: (
                f"{timestamp.year}-Q{((timestamp.month - 1) // 3) + 1}"
            ),
        }

        if timeframe_key in allowed_timeframes:
            timeframe_check = allowed_timeframes[timeframe_key]
            return any(
                timeframe_check(current_ts_local) == timeframe_check(_to_local(rw['awarded_at']))
                for rw in relevant_rewards
            )

        if (timeframe_delta := self._timeframe_to_timedelta(effective_timeframe)):
            threshold = current_ts - timeframe_delta
            for rw in relevant_rewards:
                awarded_at = rw['awarded_at']
                if awarded_at >= threshold:
                    return True
            return False

        return any(
            current_ts.replace(second=0, microsecond=0) == rw['awarded_at'].replace(second=0, microsecond=0)  # noqa
            for rw in relevant_rewards
        )

    async def apply(
        self,
        ctx: EvalContext,
        env: Environment,
        conn: Any,
        **kwargs
    ) -> tuple[UserReward, dict]:
        """
        Apply the Reward to the User.

        :param ctx: The evaluation context, containing user and session
            information.
        :param environ: The environment information, such as the current time.
        :return: Tuple of (UserReward, error_dict)
        """
        # Reward Message:
        if kwargs.get('message', None) is None:
            kwargs['message'] = await self._reward_message(
                ctx, env, ctx.user, **kwargs
            )

        # Reward:
        giver = {}
        giver_user = kwargs.get('giver_user', None)
        if not giver_user and (
                ctx.session.user_id != ctx.user.user_id
        ):
            # Reward was given by someone else
            giver = {
                "giver_user": ctx.session.user_id,
                "giver_email": ctx.session.email,
                "giver_employee": ctx.session.get('associate_id', None),
                "giver_name": kwargs.get('giver_name', None)
            }
        # If the giver is the same as the user, reject the reward

        elif giver_user and giver_user == ctx.user.user_id:
            return None, "Cannot reward yourself."
        args = {
            # Core reward information
            "reward_id": self._reward.reward_id,
            "reward": self._reward.reward,

            # Receiver information
            "receiver_user": ctx.user.user_id,
            "receiver_email": ctx.user.email,
            "receiver_id": ctx.user.user_id,
            "receiver_name": ctx.user.display_name,
            "receiver_employee": getattr(ctx.user, 'associate_id', None),
            "display_name": ctx.user.display_name,

            # Reward details
            "points": self._reward.points,
            "awarded_at": env.timestamp,
            "reward_type": self._reward.reward_type,

            # Merge giver information
            **giver,

            # Merge any additional kwargs passed in
            **kwargs
        }
        print('ARGS > ', args)
        with contextlib.suppress(KeyError):
            # Remove user_id if it conflicts with receiver_user
            if 'user_id' in args and args['user_id'] == args['receiver_user']:
                del args['user_id']
        error = None
        try:
            UserReward.Meta.connection = conn
            reward = UserReward(**args)
            a = await reward.insert()
            self.logger.notice(
                f"User {ctx.user.email} has been "
                f"awarded with {self._reward.reward} at {a.awarded_at}"
            )
            ## Add the "Check Collective"
            await self.check_collectives(
                self._reward.reward_id,
                ctx.user.user_id,
                env
            )
            ## Using Notify to send Reward Notification to User.
            asyncio.create_task(
                self.send_notification(
                    ctx,
                    env,
                    self._reward,
                    a
                )
            )
            # Call awarded callbacks:
            asyncio.create_task(
                self._execute_awarded_callbacks(
                    ctx,
                    env,
                    a
                )
            )
            return a, error
        except ValidationError as err:
            error = {
                "message": "Error Validating Reward Payload",
                "error": err.payload,
            }
            return None, error
        except DriverError as err:
            error = {
                "message": "Error on Rewards Database",
                "error": str(err),
            }
            return None, error
        except Exception as err:
            error = {
                "message": "Error Creating Reward",
                "error": str(err),
            }
            return None, error

    async def check_collectives(
        self,
        reward_id: int,
        user_id: int,
        env: Environment
    ):
        """check_collectives.

            Check that the reward belongs to a
            collective and user can Unlock the Collective
        Args:
            reward_id (int): _description_
            user_id (int): _description_
        """
        async with await env.connection.acquire() as conn:
            # Step 1: Find if the reward belongs to any collective
            query = """
            SELECT collective_id FROM rewards.collectives_rewards
            WHERE reward_id = $1::integer;
            """
            collective_id = await conn.fetchval(query, reward_id)
            if collective_id is None:
                # Reward does not belong to any collective
                return
            # Step 2: Check if the user has all rewards from the collective
            query = """
            SELECT COUNT(DISTINCT cr.reward_id) as total_rewards,
                COUNT(DISTINCT ur.reward_id) as user_rewards
            FROM rewards.collectives_rewards cr
            LEFT JOIN rewards.users_rewards ur ON cr.reward_id = ur.reward_id
             AND ur.receiver_user = $1::integer
            WHERE cr.collective_id = $2::integer
            GROUP BY cr.collective_id;
            """
            record = await conn.fetch_one(query, user_id, collective_id)
            if record and record['total_rewards'] == record['user_rewards']:
                # Step 3: User has all rewards, unlock the collective
                query = """
                INSERT INTO rewards.collectives_unlocked
                (collective_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (collective_id, user_id) DO NOTHING;
                """
                await conn.execute(query, collective_id, user_id)
                self.logger.info(
                    f"User {user_id} has unlocked collective {collective_id}."
                )

    async def _execute_awarded_callbacks(
        self,
        ctx: EvalContext,
        env: Environment,
        award: UserReward
    ) -> None:
        """Execute optional callbacks when a reward has been awarded."""
        callbacks = getattr(self._reward, 'awarded_callbacks', None) or []
        if not callbacks:
            return
        for callback_path in callbacks:
            if not callback_path:
                continue
            try:
                module_path, func_name = callback_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                callback = getattr(module, func_name)
            except (ValueError, ImportError, AttributeError) as err:
                self.logger.error(
                    f"Unable to load awarded callback '{callback_path}': {err}"
                )
                continue

            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(ctx, env, award, self._reward)
                else:
                    callback(ctx, env, award, self._reward)
                self.logger.info(
                    f"Executed awarded callback: {callback_path}"
                )
            except Exception as err:  # noqa: BLE001
                self.logger.error(
                    f"Error executing awarded callback '{callback_path}': {err}"
                )

    async def send_notification(
        self,
        ctx: EvalContext,
        env: Environment,
        reward: RewardView,
        a: UserReward
    ):
        """send_notification.

        Send a notification to the user about the awarded reward.
        """
        # This method should be implemented in subclasses
        # Send first, a private message to the user using MS Teams:
        # use the JinjaEnvironment to load a template:
        reward_template = self._template_engine.get_template(
            "rewards/to_user.json"
        )
        giver_name = (
            a.giver_name
            or ctx.session.get('display_name')
            or ctx.session.get('name')
            or ctx.user.display_name
            or ctx.user.email
            or 'Rewards Team'
        )
        giver = {
            "name": giver_name,
            "email": (
                a.giver_email
                or ctx.session.get('email')
                or ctx.user.email
            ),
            "user_id": (
                a.giver_user
                or ctx.session.get('user_id')
                or ctx.user.user_id
            ),
            "employee": (
                a.giver_employee
                or ctx.session.get('associate_id')
            )
        }
        message = await reward_template.render_async(
            ctx=ctx,
            env=env,
            user=ctx.user,
            reward=reward.reward,
            reward_icon=reward.icon,
            reward_emoji=reward.emoji,
            reward_obj=reward,
            points=a.points,
            message=a.message,
            giver_name=giver_name,
            giver=giver,
            giver_email=giver.get('email'),
            awarded_at=a.awarded_at.strftime('%m/%d/%Y %H:%M:%S')
        )
        # Send the Teams message
        recipient = self.create_actor(a)
        await self.send_teams_message(
            to=recipient,
            message=message
        )
        # Send an email notification
        email_body = await self._reward_message(
            ctx, env, ctx.user, message=reward.message
        )
        args = {
            "reward": reward.reward,
            "reward_icon": reward.icon,
            "reward_emoji": reward.emoji,
            "user": ctx.user,
            "reward_obj": reward,
            "points": a.points,
            "message": a.message,
            "giver_name": giver_name,
            "giver": giver,
            "giver_email": giver.get('email'),
            "awarded_at": a.awarded_at.strftime('%m/%d/%Y %H:%M:%S')
        }
        await self.send_email_notification(
            to=recipient,
            subject=f"Congratulations! You've received a reward: {a.reward}",
            body=email_body,
            **args
        )
        # Log the notification
        self.logger.info(
            f"Notification sent to {ctx.user.email} for reward {a.reward}."
        )

    def create_actor(self, user: UserReward) -> Actor:
        """Create an Actor from UserReward."""
        return Actor(
            name=user.receiver_name or user.receiver_email,
            account={
                "address": user.receiver_email
            }
        )

    async def send_teams_message(self, to: Actor, message: str):
        try:
            tm = Teams(
                as_user=True,
                client_id=REWARDS_CLIENT_ID,
                client_secret=REWARDS_CLIENT_SECRET,
                username=REWARDS_USER,
                password=REWARDS_PASSWORD
            )
            async with tm as conn:
                result = await conn.send(
                    recipient=to,
                    message=message
                )
            print('Teams message sent successfully:')
        except Exception as e:
            print(f"Error sending Teams message: {e}")
            return

    async def send_email_notification(
        self,
        to: Actor,
        subject: str,
        body: str,
        **kwargs: Any
    ):
        """Send an email notification using SES."""
        # This method should be implemented in subclasses
        credentials = {
            "aws_access_key_id": config.get('AWS_ACCESS_KEY_ID'),
            "aws_secret_access_key": config.get('AWS_SECRET_ACCESS_KEY'),
            "aws_region_name": config.get('AWS_REGION_NAME'),
            "sender_email": config.get(
                'AWS_SENDER_EMAIL', fallback="rewards@trocglobal.com"
            )
        }
        try:
            ses = Ses(**credentials)
            async with ses as m:
                result = await m.send(
                    recipient=to,
                    subject=subject,
                    body=body,
                    template='rewards/email.html',
                    **kwargs
                )
                print('Email sent successfully:', result)
        except Exception as e:
            print(f"Error sending email notification: {e}")
            return
