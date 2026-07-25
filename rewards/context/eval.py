from typing import Any
from aiohttp import web
from navconfig.logging import logging
from navigator_auth.conf import AUTH_SESSION_OBJECT
from datamodel import BaseModel
from navrules import EvalContext as BaseEvalContext
from ..env import Environment
from ..registry import AchievementRegistry


# Global registry instance
achievement_registry = AchievementRegistry()


class EvalContext(BaseEvalContext):
    """EvalContext.

    Build The Evaluation Context from Request and User Data.
    Includes a dynamic achievement function support to evaluate
    the context against a set of rules.

    Backed by navrules.EvalContext (mapping with missing-key -> False,
    flatten() for the native matcher, computed-value cache); this subclass
    adds the aiohttp/navigator_auth specifics.
    """
    def __init__(
        self,
        request: web.Request,
        user: Any = None,
        session: Any = None,
        connection: Any = None,
        *args,
        **kwargs
    ):
        super().__init__(
            request=request,
            user=user,
            session=session,
            connection=connection,
            *args,
            session_object_key=AUTH_SESSION_OBJECT,
            **kwargs
        )
        # Preserve datamodel-specific field introspection for user_keys.
        if user is not None and isinstance(user, BaseModel):
            self.store['user_keys'] = list(user.get_fields())
        self.logger = logging.getLogger('rewards.EvalContext')

    async def get_achievement(
        self,
        function_path: str,
        env: Environment,
        **kwargs
    ) -> Any:
        """Calculate and cache an achievement value (legacy name)."""
        return await self.get_computed(
            function_path,
            env,
            registry=achievement_registry,
            **kwargs
        )

    def clear_achievement_cache(self):
        """Clear the achievement cache."""
        self.clear_computed_cache()
