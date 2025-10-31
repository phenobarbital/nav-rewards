from abc import abstractmethod
from collections.abc import Iterable
from typing import Any, Optional
import pandas as pd
from resources.users import User
from .abstract import AbstractRule
from ..env import Environment
from ..context import EvalContext


# pylint: disable=too-many-instance-attributes


class ComputedRule(AbstractRule):
    """ComputedRule.

    Description: This Rule computes the best candidates for a given context.

    Attributes:
    ----------
    name: str: name of the rule
    description: str: description of the rule
    conditions: dict: dictionary of conditions affecting the Rule object
    context: optional dict: dictionary of context (user specific attributes)
        to be used for policy
    environment: The Environment is an object with a broader context of
        each access request.
        All environmental attributes speak to contextual factors like the time
        and location of an access attempt
    groups: list: a List of groups the user belongs to (e.g. administrators)
    programs: list: a list of programs to which this Rule applies.
    """
    def __init__(
            self,
            conditions: dict = None,
            **kwargs
    ):
        super().__init__(conditions, **kwargs)
        self.attributes = kwargs
        self.current_reward_id = kwargs.get('current_reward_id', None)

    def fits(self, ctx, env) -> bool:
        """
        Check if the current environment match the rule.

        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        return True

    async def evaluate(self, ctx, env) -> bool:
        """
        Evaluates the rule against the provided user context and environment.

        :param ctx: The evaluation context, containing user and session
           information.
        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        return True

    def fits_computed(self, env: Environment) -> bool:
        """
        Check if the current environment match the rule.

        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        return True

    def get_dataframe(self, data: Iterable) -> pd.DataFrame:
        """
        Get a DataFrame from data.

        :param data: The data to be converted to a DataFrame.
        :return: a Pandas DataFrame.
        """
        try:
            df = pd.DataFrame(
                [dict(r) for r in data],
                dtype=str
            )
            df.infer_objects()
            df = df.convert_dtypes(
                convert_string=True
            )
            return df
        except Exception:
            return None

    @abstractmethod
    async def _get_candidates(
        self,
        env: Environment,
        dataset: Optional[Iterable] = None
    ) -> list:
        """
        Generate (or evaluate) a List the potencial users to match the rule.

        :param ctx: The evaluation context, containing user and session
           information.
        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        pass

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
            session = {
                "username": user.email,
                "id": user.email,
                "user_id": user.user_id,
                "name": user.display_name,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": user.display_name,
                "email": user.email,
                "associate_id": user.associate_id,
                "birth_date": user.birth_date(),
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
        return EvalContext(
            request=None,
            user=user,
            session=session
        )

    async def evaluate_dataset(self, env, dataset: Any = None) -> Iterable:
        _candidates = await self._get_candidates(env, dataset)
        potential_users = []
        async with await env.connection.acquire() as conn:
            User.Meta.connection = conn
            for position, (idx, u) in enumerate(_candidates.iterrows()):
                try:
                    key = 'user_id'
                    if 'user_id' not in u:
                        key = 'associate_id'
                    candidate = u.to_dict()
                    if key not in candidate:
                        continue
                    args = {
                        key: candidate[key]
                    }
                    user = await User.get(**args)
                    self.logger.notice(
                        f'Fetching User: {user.email}'
                    )
                    ctx = self._get_context_user(user)
                    ctx.args = {
                        "position": position + 1,
                        "index": idx,
                        **candidate
                    }
                    potential_users.append(ctx)
                except Exception as err:
                    self.logger.warning(
                        f"Error Fetching User {args}: {err}"
                    )
                    continue
        # print('==== LIST OF POTENTIAL USERS === ')
        # print(potential_users)
        return potential_users
