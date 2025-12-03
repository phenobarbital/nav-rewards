from collections.abc import Iterable
from typing import Optional, Dict, Callable
from datetime import datetime
import contextlib
import importlib
import inspect
import aiormq
from transitions import Machine, State
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611,E0401
from .event import EventReward
from ..env import Environment
from ..context import EvalContext, achievement_registry
from ..rules.achievement import AchievementRule
from ..models import (
    RewardView,
    User,
    filter_users
)


class WorkflowCallbackRegistry:
    """Registry for workflow completion callbacks."""

    def __init__(self):
        self._callbacks: Dict[str, Callable] = {}
        self.logger = logging.getLogger('workflow.callbacks')

    def register_callback(self, name: str, callback: Callable):
        """Register a callback function."""
        # Validate callback signature
        self._validate_function_signature(callback)

        self._callbacks[name] = callback
        self.logger.info(f"Registered workflow callback: {name}")

    def _load_function_from_path(self, function_path):
        # Split module path and function name
        module_path, function_name = function_path.rsplit('.', 1)
        # Import the module
        module = importlib.import_module(module_path)
        # Get the function
        func = getattr(module, function_name)
        # Validate function signature
        self._validate_function_signature(func)
        # Cache the function
        self._callbacks[function_path] = func
        self.logger.info(
            f"Loaded workflow callback: {function_path}"
        )
        return func

    def _validate_function_signature(self, func: Callable):
        """Validate that the function has the expected signature."""
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Expected: (user, env, conn, **kwargs) or async version
        if len(params) < 3:
            raise ValueError(
                f"Callback {func!r} must accept at least (user, env, conn) args"  # noqa: E501
            )

        if not inspect.iscoroutinefunction(func):
            raise ValueError(
                f"Callback function {func!r} must be async"
            )

    def load_callback(self, callback_path: str) -> Optional[Callable]:
        """Dynamically load a callback from string path."""
        if callback_path in self._callbacks:
            return self._callbacks[callback_path]

        try:
            # Attempt to load the function from the path
            return self._load_function_from_path(callback_path)

        except (ImportError, AttributeError, ValueError) as err:
            self.logger.error(
                f"Failed to load Callback function '{callback_path}': {err}"
            )
            return None

# Global callback registry
workflow_callback_registry = WorkflowCallbackRegistry()


class WorkflowModel:
    """Model for the state machine."""

    def __init__(self, reward_id: int, user_id: int):
        self.reward_id = reward_id
        self.user_id = user_id
        self.completed_at = None
        self.logger = logging.getLogger(
            f'workflow.{reward_id}.{user_id}'
        )

class WorkflowReward(EventReward):
    """WorkflowReward.

    WorkflowReward uses state machines to evaluate multi-step rewards.

    A workflow reward requires users to complete multiple steps in sequence
    before earning the reward. Each step transition is tracked and persisted.

    Args:
        RewardObject (RewardObject): RewardObject.

    Returns:
        WorkflowReward: a WorkflowReward.
    """
    type: str = 'workflow'

    def __init__(
        self,
        reward: RewardView,
        rules: Optional[list] = None,
        conditions: Optional[dict] = None,
        workflow: Optional[list] = None,
        completion_callbacks: Optional[list] = None,
        step_callbacks: Optional[dict] = None,
        auto_evaluation: bool = True,
        auto_enroll: bool = False,
        **kwargs
    ) -> None:
        self.states: list = []
        # Evaluate the workflow
        self.workflow_steps: list = workflow or []
        self.completion_callbacks: list = completion_callbacks or []
        self.step_callbacks: dict = step_callbacks or {}
        self.auto_evaluation: bool = auto_evaluation
        self.auto_enroll: bool = auto_enroll  # Control auto-enrollment
        super().__init__(reward, rules, conditions, **kwargs)
        # Parse and setup the workflow
        if not self.workflow_steps:
            raise ValueError(
                "WorkflowReward requires a workflow configuration"
            )

        self.states, self.transitions, self.step_conditions = self._parse_workflow(  # noqa: E501
            self.workflow_steps
        )
        self.logger.info(
            f"Initialized workflow for reward {self._reward.reward_id} "
            f"with {len(self.states)-1} steps (auto: {auto_evaluation}, "
            f"auto_enroll: {auto_enroll})"
        )

    def _parse_workflow(self, workflow: list) -> tuple:
        """
        Parse workflow configuration into states,
            transitions and step conditions.

        Args:
            workflow: List of workflow steps

        Returns:
            Tuple of (states, transitions, step_conditions)
        """
        if not workflow:
            raise ValueError("Workflow cannot be empty")

        # Create states from workflow steps
        states = []
        step_conditions = {}

        if self.auto_enroll:
            # Add an initial "not_started" state for proper enrollment flow
            states.append(State(
                name='not_started',
                on_enter='_on_enter_not_started',
                on_exit='_on_exit_not_started'
            ))

        for i, step in enumerate(workflow):
            step_name = step.get('step')
            if not step_name:
                raise ValueError(
                    f"Step {i} missing 'step' name"
                )

            step_condition = None
            if 'condition' in step:
                step_condition = self._parse_step_condition(
                    step['condition']
                )

            step_conditions[step_name] = step_condition
            state = State(
                name=step_name,
                on_enter=f'_on_enter_{step_name.lower().replace(" ", "_")}',
                on_exit=f'_on_exit_{step_name.lower().replace(" ", "_")}'
            )
            states.append(state)

        # Add completion state
        states.append(
            State(
                name='completed',
                on_enter='_on_workflow_completed'
            )
        )

        # Create transitions between consecutive states
        transitions = []
        # Transition from not_started to first workflow step
        if len(states) > 2:  # not_started + workflow_steps + completed
            transitions.append({
                'trigger': 'start_workflow',
                'source': 'not_started',
                'dest': states[1].name,  # First workflow step
                'after': '_after_step_transition'
            })

            # Transitions between workflow steps
            for i in range(1, len(states) - 1):
                transition = {
                    'trigger': 'next_step',
                    'source': states[i].name,
                    'dest': states[i + 1].name,
                    'after': '_after_step_transition'
                }
                transitions.append(transition)

        return states, transitions, step_conditions

    def _parse_step_condition(self, condition_config: dict) -> dict:
        """
        Parse step condition configuration.

        Args:
            condition_config: Step condition configuration

        Returns:
            Parsed condition configuration
        """
        if 'function_path' in condition_config:
            # Achievement function condition
            return {
                'type': 'achievement_function',
                'function_path': condition_config['function_path'],
                'function_params': condition_config.get('function_params', {}),
                'threshold': condition_config.get('threshold'),
                'operator': condition_config.get('operator', 'gte')
            }
        elif 'rule' in condition_config:
            # Rule-based condition
            return {
                'type': 'rule',
                'rule_class': condition_config['rule'],
                'rule_params': condition_config.get('rule_params', {})
            }
        elif 'custom_check' in condition_config:
            # Custom check function
            return {
                'type': 'custom_check',
                'function_path': condition_config['custom_check'],
                'function_params': condition_config.get('function_params', {})
            }
        else:
            raise ValueError(
                f"Invalid step condition configuration: {condition_config}"
            )

    def _add_callback_methods(self, model: WorkflowModel):
        """Add callback methods to the state machine model."""

        def _on_enter_not_started(self):
            """Called when entering not_started state."""
            self.logger.info(f"User {self.user_id} initialized in workflow")

        def _on_exit_not_started(self):
            """Called when leaving not_started state."""
            self.logger.info(f"User {self.user_id} starting workflow")

        def _after_step_transition(self):
            """Called after each step transition."""
            self.logger.info(
                f"User {self.user_id} transitioned to: {self.state}"
            )

        def _on_workflow_completed(self):
            """Called when workflow is completed."""
            self.completed_at = datetime.now()
            self.logger.info(
                f"User {self.user_id} completed workflow at {self.completed_at}"  # noqa: E501
            )

        # Bind methods to model
        model._on_enter_not_started = _on_enter_not_started.__get__(model)
        model._on_exit_not_started = _on_exit_not_started.__get__(model)
        model._after_step_transition = _after_step_transition.__get__(model)
        model._on_workflow_completed = _on_workflow_completed.__get__(model)

        return model

    async def _evaluate_step_condition(
        self,
        step_name: str,
        ctx: EvalContext,
        env: Environment
    ) -> bool:
        """
        Evaluate whether a step's condition is met.

        Args:
            step_name: Name of the workflow step
            ctx: Evaluation context
            env: Environment

        Returns:
            True if step condition is met
        """
        condition = self.step_conditions.get(step_name)
        if not condition:
            # No condition means step is always considered completed
            return True

        try:
            if condition['type'] == 'achievement_function':
                return await self._evaluate_achievement_condition(
                    condition, ctx, env
                )
            elif condition['type'] == 'rule':
                return await self._evaluate_rule_condition(
                    condition, ctx, env
                )
            elif condition['type'] == 'custom_check':
                return await self._evaluate_custom_condition(
                    condition, ctx, env
                )
            else:
                self.logger.error(
                    f"Unknown condition type: {condition['type']}"
                )
                return False

        except Exception as err:
            self.logger.error(
                f"Error evaluating step condition for '{step_name}': {err}"
            )
            return False

    async def _evaluate_achievement_condition(
        self,
        condition: dict,
        ctx: EvalContext,
        env: Environment
    ) -> bool:
        """Evaluate achievement function condition."""
        function_path = condition['function_path']
        threshold = condition.get('threshold')
        operator = condition.get('operator', 'gte')
        function_params = condition.get('function_params', {})

        # Use the achievement registry to get the function
        func = achievement_registry.get_function(function_path)
        if not func:
            self.logger.error(
                f"Achievement function not found: {function_path}"
            )
            return False

        # Calculate the value
        try:
            if env.connection:
                async with await env.connection.acquire() as conn:
                    value = await func(ctx.user, env, conn, **function_params)
            else:
                value = await func(ctx.user, env, None, **function_params)

            # If no threshold, just check if value is truthy
            if threshold is None:
                return bool(value)

            # Compare against threshold
            operators = {
                'gte': lambda v, t: v >= t,
                'gt': lambda v, t: v > t,
                'lte': lambda v, t: v <= t,
                'lt': lambda v, t: v < t,
                'eq': lambda v, t: v == t,
                'ne': lambda v, t: v != t,
            }

            if operator not in operators:
                raise ValueError(
                    f"Invalid operator: {operator}"
                )

            result = operators[operator](value, threshold)

            self.logger.debug(
                f"Achievement condition: {function_path}() = {value} {operator} {threshold} = {result}"  # noqa: E501
            )

            return result

        except Exception as err:
            self.logger.error(
                f"Error executing achievement function {function_path}: {err}"
            )
            return False

    async def _evaluate_rule_condition(
        self,
        condition: dict,
        ctx: EvalContext,
        env: Environment
    ) -> bool:
        """Evaluate rule-based condition."""
        rule_class = condition['rule_class']
        rule_params = condition.get('rule_params', {})

        try:
            # Dynamically create the rule
            if rule_class == 'AchievementRule':
                rule = AchievementRule(**rule_params)
            else:
                # Load other rule types
                module_path = f"rewards.rules.{rule_class.lower()}"
                module = importlib.import_module(module_path)
                rule_cls = getattr(module, rule_class)
                rule = rule_cls(**rule_params)

            # Evaluate the rule
            return await rule.evaluate(ctx, env) if rule.fits(ctx, env) else False  # noqa: E501

        except Exception as err:
            self.logger.error(
                f"Error evaluating rule condition {rule_class}: {err}"
            )
            return False

    async def _evaluate_custom_condition(
        self,
        condition: dict,
        ctx: EvalContext,
        env: Environment
    ) -> bool:
        """Evaluate custom check function condition."""
        function_path = condition['function_path']
        function_params = condition.get('function_params', {})

        try:
            # Load the custom function
            module_path, function_name = function_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            func = getattr(module, function_name)

            # Execute the function
            if inspect.iscoroutinefunction(func):
                return await func(ctx, env, **function_params)
            else:
                return func(ctx, env, **function_params)

        except Exception as err:
            self.logger.error(
                f"Error evaluating custom condition {function_path}: {err}"
            )
            return False

    def _create_machine(self, user_id: int) -> Machine:
        """Create a state machine instance for a user."""
        model = WorkflowModel(
            reward_id=self._reward.reward_id,
            user_id=user_id
        )

        machine = Machine(
            model=model,
            states=self.states,
            transitions=self.transitions,
            initial=self.states[0].name,
            ignore_invalid_triggers=True,
            auto_transitions=False,
        )

        # Add callback methods to the model
        self._add_callback_methods(model)

        return machine

    def is_complete(self, model):
        return model.state == 'completed'

    def get_redis_key(self, ctx: EvalContext) -> str:
        """Generate Redis key for user workflow data."""
        return f"workflow:{ctx.user.user_id}:{ctx.user.username}"

    async def get_user_workflow_data(
        self,
        ctx: EvalContext,
        env: Environment
    ) -> dict:
        """
        Load user's workflow state from Redis.

        Returns:
            Dictionary with workflow state data
        """
        key = self.get_redis_key(ctx)
        reward_id_str = str(self._reward.reward_id)

        try:
            # Check if user data exists
            if await env.cache.exists(key):
                # Get existing rewards data
                rewards_data = await env.cache.hget(key, 'rewards')
                if rewards_data:
                    rewards = json_decoder(rewards_data)

                    # Get or create this reward's data
                    if reward_id_str in rewards:
                        workflow_data = rewards[reward_id_str]
                        # Ensure all required fields exist
                        if self.auto_enroll is True:
                            workflow_data.setdefault(
                                'state',
                                'not_started'
                            )
                            workflow_data.setdefault(
                                'steps',
                                len(self.states) - 2
                            )
                            workflow_data.setdefault('enrolled_at', None)
                        else:
                            workflow_data.setdefault(
                                'state',
                                self.states[0].name
                            )
                            workflow_data.setdefault(
                                'steps',
                                len(self.states) - 1
                            )
                        workflow_data.setdefault('progress', 0)
                        workflow_data.setdefault('started_at', None)
                        workflow_data.setdefault('completed_at', None)
                        if (
                            self.auto_enroll and  workflow_data['state'] == 'not_started' and workflow_data['enrolled_at'] is None  # noqa
                        ):
                            # Auto-enroll if enabled and user is
                            # in not_started state
                            # Check if user fits the workflow requirements
                            if self.fits(ctx, env):
                                await self._auto_enroll_user(
                                    ctx,
                                    env,
                                    workflow_data
                                )
                        return workflow_data

            # Create new workflow data
            if self.auto_enroll:
                workflow_data = {
                    'state': 'not_started',
                    'steps': len(self.states) - 2,
                }
            else:
                workflow_data = {
                    'state': self.states[0].name,
                    'steps': len(self.states) - 1,
                    'started_at': env.timestamp.isoformat(),
                }
            workflow_data |= {
                'progress': 0,
                'completed_at': None,
                'enrolled_at': None
            }

            # Auto-enroll if enabled
            if self.auto_enroll and self.fits(ctx, env):
                await self._auto_enroll_user(ctx, env, workflow_data)

            # Save to Redis
            await self._save_user_workflow_data(ctx, env, workflow_data)

            return workflow_data

        except Exception as err:
            self.logger.error(
                f"Error loading workflow data: {err}"
            )
            # Return safe default
            return {
                'state': self.states[0].name,
                'progress': 0,
                'steps': len(self.states) - 1,
                'started_at': env.timestamp.isoformat(),
                'completed_at': None,
                'enrolled_at': None
            }

    async def _auto_enroll_user(
        self,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ):
        """Automatically enroll user in the first workflow step."""
        try:
            # Create state machine
            machine = self._create_machine(ctx.user.user_id)

            # Set current state
            machine.set_state(workflow_data['state'])

            # Start the workflow (transition from not_started to first step)
            if hasattr(machine.model, 'start_workflow'):
                machine.model.start_workflow()

                # Update workflow data
                workflow_data['state'] = machine.model.state
                workflow_data['enrolled_at'] = env.timestamp.isoformat()
                workflow_data['started_at'] = env.timestamp.isoformat()
                workflow_data['progress'] = 1  # Now in first step

                self.logger.info(
                    f"Auto-enrolled user {ctx.user.user_id} in workflow "
                    f"{self._reward.reward_id} - moved to step: {machine.model.state}"  # noqa
                )

                # Execute step callbacks for the first step
                await self._execute_step_callbacks(
                    machine.model.state,
                    ctx,
                    env,
                    workflow_data
                )

        except Exception as err:
            self.logger.error(
                f"Error auto-enrolling user: {err}"
            )

    async def _save_user_workflow_data(
        self,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ):
        """Save user's workflow state to Redis."""
        key = self.get_redis_key(ctx)
        reward_id_str = str(self._reward.reward_id)

        try:
            # Get existing user data or create new
            user_data = {}
            if await env.cache.exists(key):
                existing_data = await env.cache.hgetall(key)
                user_data |= existing_data

            # Update user metadata
            user_data.update({
                'user_id': str(ctx.user.user_id),
                'username': ctx.user.username,
                'email': getattr(ctx.user, 'email', ''),
                'last_updated': env.timestamp.isoformat()
            })

            # Get existing rewards or create new dict
            rewards = json_decoder(
                user_data['rewards']
            ) if 'rewards' in user_data else {}

            # Update this reward's data
            rewards[reward_id_str] = workflow_data

            # Save back to Redis
            user_data['rewards'] = json_encoder(rewards)

            await env.cache.hset(key, mapping=user_data)

        except Exception as err:
            self.logger.error(
                f"Error saving workflow data: {err}"
            )
            raise

    async def reset_user_workflow(self, ctx: EvalContext, env: Environment):
        """Reset user's workflow to initial state."""
        if self.auto_enroll:
            # Reset to not_started state
            workflow_data = {
                'state': 'not_started',
                'steps': len(self.states) - 2,
                'enrolled_at': None,
                'started_at': None,
                'completed_at': None,
                'progress': 0
            }
            if self.fits(ctx, env):
                # Auto-enroll if user fits the workflow requirements
                await self._auto_enroll_user(ctx, env, workflow_data)
        else:
            workflow_data = {
                'state': self.states[0].name,
                'progress': 0,
                'steps': len(self.states) - 1,
                'started_at': env.timestamp.isoformat(),
                'completed_at': None
            }
        await self._save_user_workflow_data(ctx, env, workflow_data)
        self.logger.info(
            f"Reset workflow for user {ctx.user.user_id}"
        )

    async def delete_user_workflow_data(
        self,
        ctx: EvalContext,
        env: Environment
    ) -> None:
        key = self.get_redis_key(ctx)
        reward_id_str = str(self._reward.reward_id)
        try:
            if await env.cache.exists(key):
                rewards_data = await env.cache.hget(key, 'rewards')
                if rewards_data:
                    rewards = json_decoder(rewards_data)

                    # Remove this reward's data
                    rewards.pop(reward_id_str, None)

                    # Save back
                    await env.cache.hset(key, 'rewards', json_encoder(rewards))

        except Exception as err:
            self.logger.error(
                f"Error deleting workflow data: {err}"
            )

    async def _progress_workflow(
        self,
        machine: Machine,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ) -> bool:
        """
        Progress the workflow to the next step.

        Returns:
            True if workflow was completed
        """
        try:
            # Trigger the next step
            if hasattr(machine.model, 'next_step'):
                machine.model.next_step()
            else:
                # Alternative: use trigger method
                machine.trigger('next_step')

            # Update workflow data
            workflow_data['progress'] += 1
            workflow_data['state'] = machine.model.state
            workflow_data['last_updated'] = env.timestamp.isoformat()

            # Check if completed
            if self.is_complete(machine.model):
                workflow_data['completed_at'] = env.timestamp.isoformat()

            # Save to Redis
            await self._save_user_workflow_data(ctx, env, workflow_data)

            # Execute step callbacks
            await self._execute_step_callbacks(
                machine.model.state, ctx, env, workflow_data
            )

            # If completed, execute completion callbacks
            if self.is_complete(machine.model):
                await self._execute_completion_callbacks(
                    ctx,
                    env,
                    workflow_data
                )
                return True

            return False

        except Exception as err:
            self.logger.error(
                f"Error progressing workflow: {err}"
            )
            raise

    async def _execute_step_callbacks(
        self,
        step_name: str,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ):
        """Execute callbacks for a specific step."""
        if step_name in self.step_callbacks:
            callback_paths = self.step_callbacks[step_name]
            if not isinstance(callback_paths, list):
                callback_paths = [callback_paths]

            for callback_path in callback_paths:
                await self._execute_callback(
                    callback_path,
                    ctx,
                    env,
                    workflow_data
                )

    async def _execute_completion_callbacks(
        self,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ):
        """Execute callbacks when workflow is completed."""
        for callback_path in self.completion_callbacks:
            await self._execute_callback(
                callback_path,
                ctx,
                env,
                workflow_data
            )

    async def _execute_callback(
        self,
        callback_path: str,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ):
        """Execute a single callback function."""
        try:
            if callback := workflow_callback_registry.load_callback(callback_path):  # noqa: E501
                # Ensure callback is a valid function
                if inspect.iscoroutinefunction(callback):
                    await callback(ctx, env, workflow_data, self._reward)
                else:
                    callback(ctx, env, workflow_data, self._reward)

                self.logger.info(
                    f"Executed callback: {callback_path}"
                )
            else:
                self.logger.warning(
                    f"Callback not found: {callback_path}"
                )

        except Exception as err:
            self.logger.error(
                f"Error executing callback {callback_path}: {err}"
            )

    async def evaluate_event(
        self,
        data: Iterable,
        event: aiormq.abc.DeliveredMessage,
        env: Environment
    ) -> Iterable:
        """Evaluate event and return potential users."""
        try:
            users = filter_users(env.connection, **data)
            result = []
            for user in users:
                ctx, _ = self.get_user_context(user)
                ctx.event = event
                ctx.event_data = data
                result.append(ctx)

            return result

        except Exception as err:
            self.logger.error(f"Error evaluating event: {err}")
            return []

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """
        Evaluate the workflow reward against the user context.

        Returns:
            True if the reward should be awarded (workflow completed)
        """
        try:
            # Load user's workflow state
            workflow_data = await self.get_user_workflow_data(ctx, env)

            # Check if already completed and not multiple
            if (workflow_data['state'] == 'completed' and not self._reward.multiple):  # noqa: E501
                self.logger.debug(
                    f"User {ctx.user.user_id} already completed "
                    f"non-multiple workflow {self._reward.reward_id}"
                )
                return False

            # If completed and multiple allowed, reset workflow
            if (workflow_data['state'] == 'completed'):  # noqa: E501
                await self.reset_user_workflow(ctx, env)
                workflow_data = await self.get_user_workflow_data(ctx, env)

            # Create state machine and set current state
            machine = self._create_machine(ctx.user.user_id)
            machine.set_state(workflow_data['state'])

            # Check if user is eligible for reward (awardee check)
            if not await self.check_awardee(ctx):
                self.logger.debug(
                    f"User {ctx.user.user_id} not eligible for "
                    f"workflow reward {self._reward.reward_id}"
                )
                return False

            # Progress workflow if not completed
            completed = False
            if self.auto_evaluation:
                completed = await self._auto_progress_workflow(
                    machine, ctx, env, workflow_data
                )
            elif workflow_data['state'] != 'completed':
                completed = await self._progress_workflow(
                    machine, ctx, env, workflow_data
                )

            if completed:
                self.logger.info(
                    f"User {ctx.user.user_id} completed "
                    f"workflow {self._reward.reward_id}"
                )
                return True
            else:
                self.logger.debug(
                    f"User {ctx.user.user_id} progressed to step "
                    f"{workflow_data['progress']}/{workflow_data['steps']} "  # noqa: E501
                    f"in workflow {self._reward.reward_id}"
                )
                return False

        except Exception as err:
            self.logger.error(
                f"Error evaluating workflow: {err}"
            )
            return False

    def get_workflow_progress(self, workflow_data: dict) -> dict:
        """Get user's workflow progress summary."""
        return {
            'current_step': workflow_data.get('state'),
            'progress': workflow_data.get('progress', 0),
            'total_steps': workflow_data.get('steps', 0),
            'progress_percentage': round(
                (workflow_data.get('progress', 0) /
                 max(workflow_data.get('steps', 1), 1)) * 100, 2
            ),
            'is_completed': workflow_data.get('state') == 'completed',
            'started_at': workflow_data.get('started_at'),
            'completed_at': workflow_data.get('completed_at')
        }

    async def _auto_progress_workflow(
        self,
        machine: Machine,
        ctx: EvalContext,
        env: Environment,
        workflow_data: dict
    ) -> bool:
        """
        Automatically progress workflow through completed steps.

        Returns:
            True if workflow was completed
        """
        progressed = False
        max_iterations = len(self.states)  # Prevent infinite loops
        iterations = 0

        while iterations < max_iterations:
            current_state = machine.model.state

            # Check if we're already completed
            if current_state == 'completed':
                return True

            # Skip not_started state in auto-progression
            if current_state == 'not_started':
                if hasattr(machine.model, 'start_workflow'):
                    machine.model.start_workflow()
                    workflow_data['state'] = machine.model.state
                    workflow_data['enrolled_at'] = env.timestamp.isoformat()
                    workflow_data['started_at'] = env.timestamp.isoformat()
                    workflow_data['progress'] = 1
                    progressed = True
                    self.logger.info(
                        f"Auto-started workflow {self._reward.reward_id} for user {ctx.user.user_id}"  # noqa
                    )
                    iterations += 1
                    continue
                else:
                    break

            # Check if current step condition is met
            if not await self._evaluate_step_condition(
                current_state,
                ctx,
                env
            ):
                break

            # Check if current step condition is met
            if not (
                await self._evaluate_step_condition(
                    current_state, ctx, env
                )
            ):
                # Current step condition not met, stop progression
                break
            try:
                if hasattr(machine.model, 'next_step'):
                    machine.model.next_step()
                else:
                    machine.trigger('next_step')

                # Update workflow data
                workflow_data['progress'] += 1
                workflow_data['state'] = machine.model.state
                workflow_data['last_updated'] = env.timestamp.isoformat()

                # Mark step completion time
                step_completions = workflow_data.setdefault(
                    'step_completions', {}
                )
                step_completions[current_state] = env.timestamp.isoformat()

                progressed = True

                self.logger.info(
                    f"Auto-progressed workflow {self._reward.reward_id} "
                    f"from '{current_state}' to '{machine.model.state}' "
                    f"for user {ctx.user.user_id}"
                )

                # Execute step callbacks
                await self._execute_step_callbacks(
                    current_state, ctx, env, workflow_data
                )

                # Check if now completed
                if machine.model.state == 'completed':
                    workflow_data['completed_at'] = env.timestamp.isoformat()
                    await self._execute_completion_callbacks(
                        ctx, env, workflow_data
                    )
                    break

            except Exception as err:
                self.logger.error(f"Error progressing workflow: {err}")
                break
            iterations += 1

        if progressed:
            # Save updated workflow data
            await self._save_user_workflow_data(ctx, env, workflow_data)

        return machine.model.state == 'completed'
