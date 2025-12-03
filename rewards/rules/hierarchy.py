"""Hierarchy-related reward rules."""
from __future__ import annotations
from typing import Iterable, Optional, Sequence, Tuple
import asyncio
from contextlib import suppress
from navconfig.logging import logging
from ..env import Environment
from ..context import EvalContext
from ..models import ADPeople
from ..hierarchy import EmployeeHierarchyManager
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
            normalized_assigner is not None and normalized_assigner == normalized_manager
        )

    def _get_assigner_id(self, ctx: EvalContext) -> Optional[int]:
        """Extract the assigner's user identifier from the session context."""
        session_info = ctx.store.get("userinfo") if hasattr(ctx, "store") else None
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

class HierarchyRelationshipRule(AbstractRule):
    """General rule that validates relationships using ArangoDB hierarchy data."""

    SUPPORTED_RELATIONSHIPS = {
        "colleagues",
        "manager_to_subordinate",
        "direct_manager",
        "subordinate_to_manager",
        "direct_subordinate",
        "same_department",
        "same_program",
        "any",
    }

    def __init__(
        self,
        conditions: Optional[dict] = None,
        relationships: Optional[Sequence[str]] = None,
        hierarchy_manager: Optional[EmployeeHierarchyManager] = None,
        manager_config: Optional[dict] = None,
        assigner_id_fields: Optional[Iterable[str]] = None,
        receiver_id_fields: Optional[Iterable[str]] = None,
        allow_indirect_manager: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(conditions, **kwargs)
        if relationships is None:
            relationships = ("manager_to_subordinate",)
        if isinstance(relationships, str):
            relationships = (relationships,)
        normalized = tuple(rel.lower().strip() for rel in relationships)
        if invalid := [rel for rel in normalized if rel not in self.SUPPORTED_RELATIONSHIPS]:
            raise ValueError(
                "Unsupported hierarchy relationships: " + ", ".join(sorted(set(invalid)))
            )
        self.relationships: Tuple[str, ...] = normalized
        self.name = "Hierarchy Relationship"
        self.description = (
            "Restricts badge assignment based on configured employee hierarchy relationships."
        )
        self.logger = logging.getLogger(__name__)
        default_fields = ("associate_id", "associate_oid", "employee_id", "user_id")
        self.assigner_id_fields = tuple(assigner_id_fields or default_fields)
        self.receiver_id_fields = tuple(receiver_id_fields or default_fields)
        self.allow_indirect_manager = allow_indirect_manager
        self._manager = hierarchy_manager
        self._manager_config = manager_config or {}

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Check that both giver and receiver identifiers are available."""
        return (
            self._get_assigner_identifier(ctx) is not None and self._get_receiver_identifier(ctx) is not None
        )

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """Evaluate if the assigner and receiver satisfy the relationship conditions."""
        assigner_id = self._get_assigner_identifier(ctx)
        receiver_id = self._get_receiver_identifier(ctx)
        if not assigner_id or not receiver_id:
            self.logger.warning(
                "HierarchyRelationshipRule: missing hierarchy identifiers (assigner=%s, receiver=%s)",
                assigner_id,
                receiver_id,
            )
            return False

        try:
            manager, owned = await self._acquire_manager()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error("HierarchyRelationshipRule: cannot acquire manager: %s", exc)
            return False

        try:
            for relation in self.relationships:
                if await self._check_relation(manager, relation, assigner_id, receiver_id):
                    return True
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error(
                "HierarchyRelationshipRule: evaluation error: %s", exc
            )
            return False
        finally:
            await self._release_manager(manager, owned)

        return False

    async def _acquire_manager(self) -> Tuple[EmployeeHierarchyManager, bool]:
        """Acquire an EmployeeHierarchyManager instance, either existing or new."""
        if self._manager is not None:
            if getattr(self._manager, "db", None) is None:
                await self._manager.connection()
            return self._manager, False

        manager = EmployeeHierarchyManager(**self._manager_config)
        await manager.connection()
        return manager, True

    async def _release_manager(
        self, manager: EmployeeHierarchyManager, owned: bool
    ) -> None:
        """Release the EmployeeHierarchyManager if it was created internally."""
        if not owned:
            return
        if getattr(manager, "client", None) is None:
            return
        with suppress(Exception):
            await manager.client.close()  # type: ignore[func-returns-value]

    async def _check_relation(
        self,
        manager: EmployeeHierarchyManager,
        relation: str,
        assigner_id: str,
        receiver_id: str,
    ) -> bool:
        """Check if the assigner and receiver satisfy a specific relationship."""
        if relation == "colleagues":
            return await manager.are_colleagues(assigner_id, receiver_id)
        if relation == "manager_to_subordinate":
            result = await manager.is_boss_of(
                receiver_id,
                assigner_id,
                direct_only=not self.allow_indirect_manager,
            )
            return result.get("is_manager", False)
        if relation == "direct_manager":
            result = await manager.is_boss_of(receiver_id, assigner_id, direct_only=True)
            return result.get("is_manager", False)
        if relation == "subordinate_to_manager":
            result = await manager.is_boss_of(
                assigner_id,
                receiver_id,
                direct_only=not self.allow_indirect_manager,
            )
            return result.get("is_manager", False)
        if relation == "direct_subordinate":
            result = await manager.is_boss_of(assigner_id, receiver_id, direct_only=True)
            return result.get("is_manager", False)
        if relation == "same_department":
            return await manager.are_in_same_department(assigner_id, receiver_id)
        if relation == "same_program":
            return await manager.are_in_same_program(assigner_id, receiver_id)
        if relation == "any":
            assigner_info, receiver_info = await asyncio.gather(
                manager.get_employee_info(assigner_id),
                manager.get_employee_info(receiver_id),
            )
            return bool(assigner_info and receiver_info)
        return False

    def _get_assigner_identifier(self, ctx: EvalContext) -> Optional[str]:
        """Extract the assigner's user identifier from the session context."""
        session_info = None
        if hasattr(ctx, "store"):
            session_info = ctx.store.get("userinfo") or ctx.store.get("session")
        raw_session = getattr(ctx, "session", None)
        if not session_info and raw_session is not None:
            session_info = raw_session
        identifier = self._extract_identifier(session_info, self.assigner_id_fields)
        if identifier is None:
            nested = None
            if isinstance(session_info, dict):
                nested = session_info.get("session")
            elif session_info is not None:
                nested = getattr(session_info, "session", None)
            if nested is not None:
                identifier = self._extract_identifier(nested, self.assigner_id_fields)
        return identifier

    def _get_receiver_identifier(self, ctx: EvalContext) -> Optional[str]:
        """Extract the receiver's user identifier from the context user."""
        user = getattr(ctx, "user", None)
        if identifier := self._extract_identifier(user, self.receiver_id_fields):
            return identifier
        attributes = getattr(user, "attributes", None)
        return self._extract_identifier(attributes, self.receiver_id_fields)

    def _extract_identifier(
        self,
        source: Optional[object],
        fields: Sequence[str],
    ) -> Optional[str]:
        """Extract and normalize an identifier from the given source object."""
        if source is None:
            return None
        if isinstance(source, dict):
            for field in fields:
                if value := source.get(field):
                    if normalized := self._normalize_identifier(value):
                        return normalized
        else:
            for field in fields:
                if value := getattr(source, field, None):
                    if normalized := self._normalize_identifier(value):
                        return normalized
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
