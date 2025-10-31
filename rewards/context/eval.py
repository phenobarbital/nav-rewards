from typing import Any
from collections.abc import MutableMapping, Iterator
from aiohttp import web
from navconfig.logging import logging
from navigator_auth.conf import AUTH_SESSION_OBJECT
from datamodel import BaseModel
from ..env import Environment
from ..registry import AchievementRegistry


# Global registry instance
achievement_registry = AchievementRegistry()


class EvalContext(dict, MutableMapping):
    """EvalContext.

    Build The Evaluation Context from Request and User Data.
    Includes a dynamic achievement function support to evaluate
    the context against a set of rules.
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
        ## initialize the mutable mapping:
        self.store = {
            'userinfo': {},
            'request': request,
            'connection': connection,
            'user': user if user is not None else {},
            'session': session if session is not None else {},
        }
        if session:
            self.store['programs'] = session.get('programs', [])
        self.update(*args, **kwargs)
        self._columns = list(self.store.keys())
        if user:
            if isinstance(user, BaseModel):
                self.store['user_keys'] = user.get_fields()
            else:
                self.store['user_keys'] = user.keys()
        # Session Context:
        if AUTH_SESSION_OBJECT in self.store['session']:
            self.store['userinfo'] = self.store['session'][AUTH_SESSION_OBJECT]
        # Calculate the Start Date, employment duration and birthday
        # Achievement functions cache:
        self._achievement_cache = {}
        self.logger = logging.getLogger('rewards.EvalContext')

    def __missing__(self, key):
        return False

    # def items(self) -> zip:  # type: ignore
    #     return zip(self._columns, self.store)

    def items(self):
        return self.store.items()

    def keys(self) -> list:
        return self._columns

    def set(self, key, value) -> None:
        self.store[key] = value
        if key not in self._columns:
            self._columns.append(key)

    ### Section: Simple magic methods
    def __len__(self) -> int:
        return len(self.store)

    def __str__(self) -> str:
        return f"<{type(self).__name__}({self.store})>"

    def __repr__(self) -> str:
        return f"<{type(self).__name__}({self.store})>"

    def __contains__(self, key: str) -> bool:
        return key in self._columns

    def __iter__(self) -> Iterator:
        yield from self.store

    def __delitem__(self, key):
        del self.store[key]
        if key in self._columns:
            self._columns.remove(key)

    def __setitem__(self, key, value):
        self.store[key] = value
        if key not in self._columns:
            self._columns.append(key)

    def __getitem__(self, key):
        return self.store[key]

    def __getattr__(self, key):
        try:
            return super().__getattribute__('store')[key]
        except KeyError as ex:
            raise AttributeError(key) from ex

    def __setattr__(self, key, value):
        if key == 'store':
            super().__setattr__(key, value)
        else:
            self.store[key] = value

    def __delattr__(self, key):
        try:
            del self.store[key]
        except KeyError as ex:
            raise AttributeError(key) from ex

    async def get_achievement(
        self,
        function_path: str,
        env: Environment,
        **kwargs
    ) -> Any:
        """
        Calculate and cache an achievement value using function loading.

        Args:
            function_path: Function String path
                like "rewards.functions.calls.get_call_count"
            env: Environment context
            **kwargs: Additional parameters for the achievement function

        Returns:
            The calculated achievement value
        """
        # Check cache first
        cache_key = f"{function_path}_{hash(str(sorted(kwargs.items())))}"
        if cache_key in self._achievement_cache:
            return self._achievement_cache[cache_key]

        # Load the achievement function
        func = achievement_registry.get_function(function_path)
        if not func:
            self.logger.warning(
                f"Achievement function '{function_path}' not found"
            )
            return None

        try:
            # Calculate the achievement value
            if env.connection:
                async with await env.connection.acquire() as conn:
                    value = await func(self.user, env, conn, **kwargs)
            else:
                value = await func(self.user, env, None, **kwargs)

            # Cache the result
            self._achievement_cache[cache_key] = value
            return value

        except Exception as err:
            self.logger.error(
                f"Error calculating achievement '{function_path}': {err}"
            )
            return None

    def clear_achievement_cache(self):
        """Clear the achievement cache."""
        self._achievement_cache.clear()
