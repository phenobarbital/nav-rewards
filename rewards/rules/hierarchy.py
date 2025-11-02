"""Hierarchy-related reward rules."""
from __future__ import annotations

from contextlib import suppress
from typing import Optional
from navconfig.logging import logging
from ..env import Environment
from ..context import EvalContext
from ..models import ADPeople
from .abstract import AbstractRule


class DirectManagerRule(AbstractRule):
    """Restrict badge assignment to a user's direct manager."""

    def __init__(
        self,
        conditions: Optional[dict] = None,
        manager_field: str = "reports_to",
        allow_without_manager: bool = False,
        **kwargs,
    ) -> None:
        """Initialize the rule with optional configuration."""
        super().__init__(conditions, **kwargs)
        self.name = "Direct Manager Only"
        self.description = (
            "Ensures the badge can only be assigned by the receiver's direct manager"
        )
        self.manager_field = manager_field
        self.allow_without_manager = allow_without_manager
        self.logger = logging.getLogger(__name__)

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Check that both giver and receiver information are available."""
        return self._get_assigner_id(ctx) is not None and getattr(
            ctx.user, "user_id", None
        ) is not None

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """Validate that the giver matches the receiver's direct manager."""
        assigner_id = self._get_assigner_id(ctx)
        if assigner_id is None:
            self.logger.warning("DirectManagerRule: missing assigner information")
            return False

        manager_id = await self._get_manager_id(ctx, env)
        if manager_id is None:
            if self.allow_without_manager:
                self.logger.info(
                    "DirectManagerRule: manager data missing, allowing assignment"
                )
                return True
            self.logger.warning(
                "DirectManagerRule: manager data missing, rejecting assignment"
            )
            return False

        normalized_assigner = self._normalize_identifier(assigner_id)
        normalized_manager = self._normalize_identifier(manager_id)
        return (
            normalized_assigner is not None
            and normalized_assigner == normalized_manager
        )

    def _get_assigner_id(self, ctx: EvalContext) -> Optional[int]:
        """Extract the assigner's user identifier from the session context."""
        session_info: Optional[dict] = None
        # Prefer the normalized session context stored in EvalContext
        if hasattr(ctx, "store"):
            session_info = ctx.store.get("userinfo")

        raw_session = getattr(ctx, "session", None)
        if not session_info and raw_session is not None:
            if isinstance(raw_session, dict):
                session_info = raw_session.get("session") or raw_session
            else:
                with suppress(Exception):
                    session_info = raw_session["session"]  # type: ignore[index]

        if isinstance(session_info, dict):
            return session_info.get("user_id") or session_info.get("id")

        if session_info is not None:
            return getattr(session_info, "user_id", None)

        return None

    async def _get_manager_id(
        self, ctx: EvalContext, env: Environment
    ) -> Optional[object]:
        """Resolve the receiver's direct manager identifier."""
        user = getattr(ctx, "user", None)
        if user is None:
            return None

        # First try to read the manager information directly from the user model
        manager_id = getattr(user, self.manager_field, None)
        if manager_id is not None:
            return manager_id

        # Some user models expose additional attributes via a dictionary
        extra = getattr(user, "attributes", None)
        if isinstance(extra, dict) and extra.get(self.manager_field) is not None:
            return extra[self.manager_field]

        if not getattr(env, "connection", None):
            return None

        # As a final fallback, consult the ADPeople directory
        async with await env.connection.acquire() as conn:
            ADPeople.Meta.connection = conn
            with suppress(Exception):
                ad_person = await ADPeople.get(user_id=user.user_id)
                return getattr(ad_person, self.manager_field, None)

        return None

    def _normalize_identifier(self, identifier: Optional[object]) -> Optional[str]:
        """Normalize identifiers for comparison across different types."""
        if identifier is None:
            return None
        if isinstance(identifier, str):
            identifier = identifier.strip()
            return identifier or None
        with suppress(Exception):
            return str(int(identifier))
        return str(identifier)
