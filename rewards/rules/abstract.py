from typing import Optional
from abc import ABC, abstractmethod
import uuid
from navconfig.logging import logging
from ..env import Environment
from ..context import EvalContext


class AbstractRule(ABC):
    """AbstractRule Rule class.

    Base class for all Rules that are defined on Reward System.

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
            conditions: Optional[dict] = None,
            **kwargs
    ):
        self.name = self.__class__.__name__
        self.id = uuid.uuid1().hex
        self.conditions: dict = {}
        self.logger = logging.getLogger(__name__)
        if isinstance(conditions, dict):
            self.conditions = conditions
        ### any other attributes so far
        for name, arg in kwargs.items():
            setattr(self, name, arg)
        self.attributes = kwargs

    def __str__(self):
        return f"<{self.name}:>"

    @abstractmethod
    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """
        Check if the current context and environment match the rule.

        :param ctx: The evaluation context, containing user and session
           information.
        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        pass

    @abstractmethod
    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """
        Evaluates the rule against the provided user context and environment.

        :param ctx: The evaluation context, containing user and session
           information.
        :param environ: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        pass
