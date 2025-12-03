"""Utilities for managing the employee hierarchy stored in ArangoDB."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from asyncdb import AsyncDB
from ..conf import EMPLOYEES_TABLE, default_dsn

try:  # pragma: no cover - optional dependency at runtime
    from arangoasync import ArangoClient
    from arangoasync.auth import Auth
except ImportError as exc:  # pragma: no cover - handled gracefully at runtime
    ArangoClient = None  # type: ignore[assignment]
    Auth = None  # type: ignore[assignment]
    ARANGO_IMPORT_ERROR = exc
else:  # pragma: no cover - executed when dependency is installed
    ARANGO_IMPORT_ERROR = None


logging.getLogger("arangoasync").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class CacheMixin:
    """Very small asynchronous cache helper."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._cache_store: Dict[Tuple[Any, ...], Tuple[Optional[float], Any]] = {}
        self._cache_lock = asyncio.Lock()
        super().__init__()  # type: ignore[misc]

    async def _get_cached_value(self, key: Tuple[Any, ...]) -> Any:
        async with self._cache_lock:
            if key not in self._cache_store:
                return None
            expires_at, value = self._cache_store[key]
            if expires_at is None or expires_at > time.monotonic():
                return value
            # TTL expired
            self._cache_store.pop(key, None)
            return None

    async def _set_cached_value(
        self,
        key: Tuple[Any, ...],
        value: Any,
        ttl: Optional[int],
    ) -> None:
        expires_at: Optional[float] = None
        if ttl is not None:
            expires_at = time.monotonic() + ttl
        async with self._cache_lock:
            self._cache_store[key] = (expires_at, value)

    async def invalidate_cache(self, prefix: Optional[Iterable[Any]] = None) -> None:
        """Invalidate cached entries, optionally matching a prefix."""
        async with self._cache_lock:
            if not prefix:
                self._cache_store.clear()
                return
            prefix_tuple = tuple(prefix)
            to_remove = [
                key for key in self._cache_store if key[: len(prefix_tuple)] == prefix_tuple
            ]
            for key in to_remove:
                self._cache_store.pop(key, None)


def cached_query(cache_key: Optional[str] = None, ttl: Optional[int] = None):
    """Decorator that caches asynchronous query results on the instance."""

    def decorator(func):
        async def wrapper(self: CacheMixin, *args: Any, **kwargs: Any) -> Any:
            if not isinstance(self, CacheMixin):
                return await func(self, *args, **kwargs)

            key = (cache_key or func.__name__, args, tuple(sorted(kwargs.items())))
            cached = await self._get_cached_value(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            await self._set_cached_value(key, result, ttl)
            return result

        return wrapper

    return decorator


@dataclass
class Employee:
    """Basic employee information container."""

    employee_id: str
    associate_oid: str
    first_name: str
    last_name: str
    display_name: str
    email: str
    job_code: str
    position_id: str
    department: str
    program: str
    reports_to: Optional[str]


class EmployeeHierarchyManager(CacheMixin):
    """Manager that wraps the ArangoDB hierarchy graph for convenience."""

    def __init__(
        self,
        *,
        arango_host: str = "localhost",
        arango_port: int = 8529,
        db_name: str = "company_db",
        username: str = "root",
        password: str = "",
        employees_collection: str = "employees",
        reports_to_collection: str = "reports_to",
        graph_name: str = "org_hierarchy",
        primary_key: str = "employee_id",
        pg_employees_table: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if ARANGO_IMPORT_ERROR is not None:
            raise RuntimeError(
                "arangoasync is required to use EmployeeHierarchyManager"
            ) from ARANGO_IMPORT_ERROR

        super().__init__()
        self.client = ArangoClient(hosts=f"http://{arango_host}:{arango_port}")
        self.auth = Auth(username=username, password=password)
        self._username = username
        self._password = password
        self._database = db_name
        self.sys_db = None
        self.db = None
        self.employees_collection = employees_collection
        self.reports_to_collection = reports_to_collection
        self.graph_name = graph_name
        self._primary_key = primary_key
        self.pg_client = AsyncDB("pg", dsn=default_dsn)
        self.employees_table = pg_employees_table or EMPLOYEES_TABLE

    async def __aenter__(self) -> "EmployeeHierarchyManager":
        await self.connection()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        if self.client:
            with contextlib.suppress(Exception):
                await self.client.close()  # type: ignore[func-returns-value]

    async def connection(self):
        """Connect to ArangoDB, creating the database if needed."""
        self.sys_db = await self.client.db("_system", auth=self.auth)
        if not await self.sys_db.has_database(self._database):
            await self.sys_db.create_database(self._database)
        self.db = await self.client.db(self._database, auth=self.auth)
        return self.db

    async def _setup_collections(self) -> None:
        """Ensure collections, graphs and indexes exist."""
        if not await self.db.has_collection(self.employees_collection):
            await self.db.create_collection(self.employees_collection)
        if not await self.db.has_collection(self.reports_to_collection):
            await self.db.create_collection(self.reports_to_collection, edge=True)
        if not await self.db.has_graph(self.graph_name):
            graph = await self.db.create_graph(self.graph_name)
            await graph.create_edge_definition(
                edge_collection=self.reports_to_collection,
                from_vertex_collections=[self.employees_collection],
                to_vertex_collections=[self.employees_collection],
            )
        employees = self.db.collection(self.employees_collection)
        await self._ensure_index(employees, [self._primary_key], unique=True)
        await self._ensure_index(employees, ["department", "program"], unique=False)
        await self._ensure_index(employees, ["position_id"], unique=False)
        await self._ensure_index(employees, ["associate_oid"], unique=False)

    async def _ensure_index(self, collection, fields: List[str], unique: bool = False):
        """Ensure an index exists on the collection."""
        existing_indexes = await collection.indexes()
        for idx in existing_indexes:
            if idx["type"] == "primary":
                continue
            if idx["fields"] == fields:
                if idx.get("unique", False) == unique:
                    return
                with contextlib.suppress(Exception):
                    await collection.delete_index(idx["id"])
                break
        with contextlib.suppress(Exception):
            await collection.add_index(
                type="persistent",
                fields=fields,
                options={"unique": unique},
            )
        with contextlib.suppress(Exception):
            await collection.add_hash_index(fields=fields, unique=unique)

    async def drop_all_indexes(self) -> int:
        """Drop all non-primary indexes from the employees collection."""
        employees = self.db.collection(self.employees_collection)
        existing_indexes = await employees.indexes()
        dropped_count = 0
        for idx in existing_indexes:
            if idx["type"] == "primary":
                continue
            try:
                await employees.delete_index(idx["id"])
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Could not drop index %s: %s", idx["id"], exc)
            else:
                dropped_count += 1
        return dropped_count

    async def import_from_postgres(self) -> None:
        """Import the employee hierarchy from PostgreSQL."""
        query = f"""
SELECT
    associate_id as employee_id,
    associate_oid,
    first_name,
    last_name,
    display_name,
    job_code,
    position_id,
    corporate_email as email,
    department,
    reports_to_associate_id as reports_to,
    region as program
FROM {self.employees_table}
WHERE status = 'Active'
ORDER BY reports_to_associate_id NULLS FIRST
        """
        async with await self.pg_client.connection() as conn:  # pylint: disable=E1101
            employees_data = await conn.fetchall(query)
        await self.truncate_hierarchy()
        employees_collection = self.db.collection(self.employees_collection)
        reports_to_collection = self.db.collection(self.reports_to_collection)
        oid_to_id: Dict[str, str] = {}
        for row in employees_data:
            employee_identifier = (row.get(self._primary_key) or "").strip()
            reports_to = row.get("reports_to")
            reports_to = reports_to.strip() if isinstance(reports_to, str) else None
            employee_doc = {
                "_key": employee_identifier,
                self._primary_key: employee_identifier,
                "associate_oid": row.get("associate_oid"),
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "display_name": row.get("display_name"),
                "email": row.get("email"),
                "job_code": row.get("job_code"),
                "position_id": row.get("position_id"),
                "department": row.get("department"),
                "program": row.get("program"),
                "reports_to": reports_to,
            }
            result = await employees_collection.insert(employee_doc, overwrite=True)
            oid_to_id[employee_identifier] = result["_id"]
        for row in employees_data:
            employee_identifier = (row.get(self._primary_key) or "").strip()
            reports_to = row.get("reports_to")
            reports_to = reports_to.strip() if isinstance(reports_to, str) else None
            if not reports_to or reports_to not in oid_to_id:
                continue
            edge_doc = {
                "_from": oid_to_id[employee_identifier],
                "_to": oid_to_id[reports_to],
            }
            await reports_to_collection.insert(edge_doc)
        await self._setup_collections()

    async def truncate_hierarchy(self) -> None:
        """Remove all employees and relationships from the hierarchy."""
        if await self.db.has_collection(self.reports_to_collection):
            await self.db.collection(self.reports_to_collection).truncate()
        if await self.db.has_collection(self.employees_collection):
            await self.db.collection(self.employees_collection).truncate()

    async def insert_employee(self, employee: Employee) -> str:
        """Insert or update an employee in the hierarchy."""
        employees_collection = self.db.collection(self.employees_collection)
        reports_to_collection = self.db.collection(self.reports_to_collection)
        employee_doc = {
            "_key": employee.employee_id,
            self._primary_key: employee.employee_id,
            "associate_oid": employee.associate_oid,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "display_name": employee.display_name,
            "email": employee.email,
            "job_code": employee.job_code,
            "position_id": employee.position_id,
            "department": employee.department,
            "program": employee.program,
            "reports_to": employee.reports_to,
        }
        result = await employees_collection.insert(employee_doc, overwrite=True)
        employee_id = result["_id"]
        if employee.reports_to:
            boss_id = f"{self.employees_collection}/{employee.reports_to}"
            edge_doc = {"_from": employee_id, "_to": boss_id}
            await reports_to_collection.insert(edge_doc)
        await self.invalidate_cache(("get_employee_info",))
        return employee_id

    @cached_query("does_report_to", ttl=3600)
    async def does_report_to(self, employee_oid: str, boss_oid: str, limit: int = 1) -> bool:
        """Check if an employee reports to a specific boss within a certain depth."""
        query = """
        FOR v, e, p IN 1..10 OUTBOUND
            CONCAT(@collection, '/', @employee_oid)
            GRAPH @graph_name
            FILTER v.employee_id == @boss_oid
            LIMIT @limit
            RETURN true
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee_oid": employee_oid,
                "boss_oid": boss_oid,
                "graph_name": self.graph_name,
                "limit": limit,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return bool(results)

    @cached_query("get_all_superiors", ttl=3600)
    async def get_all_superiors(self, employee_oid: str) -> List[Dict[str, Any]]:
        """Get all superiors of an employee within a certain depth."""
        query = """
FOR v, e, p IN 1..10 OUTBOUND
    CONCAT(@collection, '/', @employee_oid)
    GRAPH @graph_name
    RETURN {
        employee_id: v.employee_id,
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program,
        level: LENGTH(p.edges)
    }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee_oid": employee_oid,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    @cached_query("get_direct_reports", ttl=3600)
    async def get_direct_reports(self, boss_oid: str) -> List[Dict[str, Any]]:
        """Get direct reports of a specific boss."""
        query = """
FOR v, e, p IN 1..1 INBOUND
    CONCAT(@collection, '/', @boss_oid)
    GRAPH @graph_name
    RETURN {
        employee_id: v.employee_id,
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program
    }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "boss_oid": boss_oid,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    @cached_query("get_all_subordinates", ttl=3600)
    async def get_all_subordinates(
        self,
        boss_oid: str,
        max_depth: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get all subordinates of a specific boss within a certain depth."""
        query = """
FOR v, e, p IN 1..@max_depth INBOUND
    CONCAT(@collection, '/', @boss_oid)
    GRAPH @graph_name
    RETURN {
        employee_id: v.employee_id,
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program,
        level: LENGTH(p.edges)
    }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "boss_oid": boss_oid,
                "max_depth": max_depth,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    @cached_query("get_org_chart", ttl=3600)
    async def get_org_chart(self, root_oid: Optional[str] = None) -> Dict[str, Any]:
        """Get the organizational chart starting from a root employee."""
        if root_oid is None:
            query_ceo = """
            FOR emp IN @@collection
                FILTER LENGTH(FOR v IN 1..1 OUTBOUND emp._id GRAPH @graph_name RETURN 1) == 0
                LIMIT 1
                RETURN emp.employee_id
            """
            cursor = await self.db.aql.execute(
                query_ceo,
                bind_vars={
                    "@collection": self.employees_collection,
                    "graph_name": self.graph_name,
                },
            )
            async with cursor:
                results = [doc async for doc in cursor]
            if results:
                root_oid = results[0]
            else:
                return {}
        query = """
        FOR v, e, p IN 0..10 INBOUND
            CONCAT(@collection, '/', @root_oid)
            GRAPH @graph_name
            RETURN {
                employee_id: v.employee_id,
                associate_oid: v.associate_oid,
                display_name: v.display_name,
                department: v.department,
                program: v.program,
                level: LENGTH(p.edges),
                path: p.vertices[*].employee_id
            }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "root_oid": root_oid,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    @cached_query("get_colleagues", ttl=3600)
    async def get_colleagues(self, employee_oid: str) -> List[Dict[str, Any]]:
        """Get colleagues of a specific employee (those who share the same boss)."""
        query = """
        FOR boss IN 1..1 OUTBOUND
            CONCAT(@collection, '/', @employee_oid)
            GRAPH @graph_name

            FOR colleague IN 1..1 INBOUND
                boss._id
                GRAPH @graph_name
                FILTER colleague.employee_id != @employee_oid
                RETURN {
                    employee_id: colleague.employee_id,
                    associate_oid: colleague.associate_oid,
                    display_name: colleague.display_name,
                    department: colleague.department,
                    program: colleague.program
                }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee_oid": employee_oid,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    @cached_query("get_employee_info", ttl=7200)
    async def get_employee_info(self, employee_oid: str) -> Optional[Dict[str, Any]]:
        """Get basic information about an employee."""
        query = """
        FOR emp IN @@collection
            FILTER emp.employee_id == @employee_oid
            LIMIT 1
            RETURN {
                employee_id: emp.employee_id,
                associate_oid: emp.associate_oid,
                display_name: emp.display_name,
                first_name: emp.first_name,
                last_name: emp.last_name,
                email: emp.email,
                department: emp.department,
                program: emp.program,
                position_id: emp.position_id,
                job_code: emp.job_code
            }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "@collection": self.employees_collection,
                "employee_oid": employee_oid,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results[0] if results else None

    async def are_in_same_department(self, employee1: str, employee2: str) -> bool:
        """Check if two employees are in the same department."""
        query = """
        LET emp1 = DOCUMENT(CONCAT(@collection, '/', @emp1))
        LET emp2 = DOCUMENT(CONCAT(@collection, '/', @emp2))

        RETURN {
            same_department: emp1.department == emp2.department,
            same_program: emp1.program == emp2.program,
            employee1: {
                name: emp1.display_name,
                department: emp1.department,
                program: emp1.program
            },
            employee2: {
                name: emp2.display_name,
                department: emp2.department,
                program: emp2.program
            }
        }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "emp1": employee1,
                "emp2": employee2,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        result = results[0] if results else {}
        return bool(result.get("same_department", False))

    async def are_in_same_program(self, employee1: str, employee2: str) -> bool:
        """Check if two employees are in the same program."""
        query = """
        LET emp1 = DOCUMENT(CONCAT(@collection, '/', @emp1))
        LET emp2 = DOCUMENT(CONCAT(@collection, '/', @emp2))

        RETURN {
            same_program: emp1.program == emp2.program
        }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "emp1": employee1,
                "emp2": employee2,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        result = results[0] if results else {}
        return bool(result.get("same_program", False))

    async def get_team_members(
        self,
        manager_id: str,
        include_all_levels: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get team members under a specific manager."""
        depth = "1..99" if include_all_levels else "1..1"
        query = f"""
        FOR member, e, p IN {depth} INBOUND CONCAT(@collection, '/emp_', @manager_id)
            GRAPH @graph_name
            RETURN {{
                employee_id: member.employee_id,
                display_name: member.display_name,
                department: member.department,
                program: member.program,
                associate_oid: member.associate_oid,
                level: LENGTH(p.edges),
                reports_directly: LENGTH(p.edges) == 1
            }}
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "manager_id": manager_id,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    async def are_colleagues(self, employee1: str, employee2: str) -> bool:
        """Check if two employees share the same direct boss."""
        if employee1 == employee2:
            return False
        query = """
    LET boss1 = (
        FOR v IN 1..1 OUTBOUND CONCAT(@collection, '/', @emp1)
            GRAPH @graph_name
            RETURN v._key
    )

    LET boss2 = (
        FOR v IN 1..1 OUTBOUND CONCAT(@collection, '/', @emp2)
            GRAPH @graph_name
            RETURN v._key
    )

    RETURN {
        same_boss: boss1[0] == boss2[0] AND boss1[0] != null
    }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "emp1": employee1,
                "emp2": employee2,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        result = results[0] if results else {}
        return bool(result.get("same_boss", False))

    async def is_manager(self, employee_oid: str) -> bool:
        """Check if an employee is a manager (has direct reports)."""
        query = """
        FOR v IN 1..1 INBOUND
            CONCAT(@collection, '/', @employee_oid)
            GRAPH @graph_name
            LIMIT 1
            RETURN true
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee_oid": employee_oid,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return bool(results)

    async def get_closest_common_boss(
        self,
        employee1: str,
        employee2: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the closest common boss between two employees."""
        query = """
        LET paths1 = (
            FOR v, e, p IN 1..10 OUTBOUND
                CONCAT(@collection, '/', @employee1)
                GRAPH @graph_name
                RETURN {boss: v, path: p}
        )

        LET paths2 = (
            FOR v, e, p IN 1..10 OUTBOUND
                CONCAT(@collection, '/', @employee2)
                GRAPH @graph_name
                RETURN {boss: v, path: p}
        )

        FOR p1 IN paths1
            FOR p2 IN paths2
                FILTER p1.boss._key == p2.boss._key
                SORT LENGTH(p1.path.edges) + LENGTH(p2.path.edges) ASC
                LIMIT 1
                RETURN {
                    employee_id: p1.boss.employee_id,
                    associate_oid: p1.boss.associate_oid,
                    display_name: p1.boss.display_name,
                    department: p1.boss.department,
                    program: p1.boss.program
                }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee1": employee1,
                "employee2": employee2,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results[0] if results else None

    async def is_boss_of(
        self,
        employee_oid: str,
        boss_oid: str,
        direct_only: bool = False,
    ) -> Dict[str, Any]:
        """Check if one employee is a boss of another."""
        if employee_oid == boss_oid:
            return {
                "is_manager": False,
                "is_direct_manager": False,
                "level": 0,
                "path": [],
                "relationship": "same_person",
            }
        depth = "1..1" if direct_only else "1..99"
        query = f"""
FOR v, e, p IN {depth} OUTBOUND CONCAT(@collection, '/', @employee_oid)
    GRAPH @graph_name
    FILTER v._key == @boss_oid OR v.employee_id == @boss_oid
    LIMIT 1
    RETURN {{
        found: true,
        level: LENGTH(p.edges),
        path: p.vertices[*].employee_id,
        manager_name: v.display_name,
        employee_name: DOCUMENT(CONCAT(@collection, '/', @employee_oid)).display_name
    }}
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee_oid": employee_oid,
                "boss_oid": boss_oid,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        if not results:
            return {
                "is_manager": False,
                "is_direct_manager": False,
                "level": 0,
                "path": [],
                "relationship": "not_manager",
            }
        result = results[0]
        level = result["level"]
        return {
            "is_manager": True,
            "is_direct_manager": level == 1,
            "level": level,
            "path": result["path"],
            "relationship": "direct_manager" if level == 1 else f"manager_level_{level}",
            "manager_name": result["manager_name"],
            "employee_name": result["employee_name"],
        }

    async def is_subordinate(
        self,
        employee_oid: str,
        manager_oid: str,
        direct_only: bool = False,
    ) -> Dict[str, Any]:
        """Check if one employee is a subordinate of another."""
        return await self.is_boss_of(employee_oid, manager_oid, direct_only)

    async def get_relationship(
        self,
        employee1: str,
        employee2: str,
    ) -> Dict[str, Any]:
        """Determine the relationship between two employees."""
        if employee1 == employee2:
            return {
                "relationship": "same_person",
                "employee1_id": employee1,
                "employee2_id": employee2,
            }
        results = await asyncio.gather(
            self.is_boss_of(employee1, employee2),
            self.is_boss_of(employee2, employee1),
            self.are_colleagues(employee1, employee2),
            self.are_in_same_department(employee1, employee2),
            return_exceptions=True,
        )
        emp1_manages_emp2 = (
            {"is_manager": False} if isinstance(results[0], Exception) else results[0]
        )
        emp2_manages_emp1 = (
            {"is_manager": False} if isinstance(results[1], Exception) else results[1]
        )
        are_colleagues = False if isinstance(results[2], Exception) else results[2]
        same_department = False if isinstance(results[3], Exception) else results[3]
        if emp1_manages_emp2.get("is_manager"):
            primary = "manager_subordinate"
            details = {
                "manager": employee1,
                "subordinate": employee2,
                "level": emp1_manages_emp2["level"],
                "is_direct": emp1_manages_emp2["is_direct_manager"],
            }
        elif emp2_manages_emp1.get("is_manager"):
            primary = "subordinate_manager"
            details = {
                "manager": employee2,
                "subordinate": employee1,
                "level": emp2_manages_emp1["level"],
                "is_direct": emp2_manages_emp1["is_direct_manager"],
            }
        elif are_colleagues:
            primary = "colleagues"
            details = {"same_boss": True}
        elif same_department:
            primary = "same_department"
            details = {"department_colleagues": True}
        else:
            primary = "no_direct_relationship"
            details = {}
        return {
            "relationship": primary,
            "employee1_id": employee1,
            "employee2_id": employee2,
            "details": details,
            "are_colleagues": are_colleagues,
            "same_department": same_department,
            "emp1_manages_emp2": emp1_manages_emp2.get("is_manager", False),
            "emp2_manages_emp1": emp2_manages_emp1.get("is_manager", False),
        }

    async def check_management_chain(
        self,
        employee_id: str,
        target_manager_id: str,
    ) -> Dict[str, Any]:
        """Check if an employee is in the management chain of a target manager."""
        query = """
        FOR v, e, p IN 1..99 OUTBOUND CONCAT(@collection, '/', @employee_id)
            GRAPH @graph_name
            OPTIONS {bfs: false}
            FILTER v._key == @target_manager OR v.employee_id == @target_manager
            LIMIT 1
            RETURN {
                found: true,
                level: LENGTH(p.edges),
                chain: (
                    FOR vertex IN p.vertices
                        RETURN {
                            id: vertex.employee_id,
                            name: vertex.display_name,
                            department: vertex.department
                        }
                )
            }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                "collection": self.employees_collection,
                "employee_id": employee_id,
                "target_manager": target_manager_id,
                "graph_name": self.graph_name,
            },
        )
        async with cursor:
            results = [doc async for doc in cursor]
        if results:
            return {"in_chain": True, **results[0]}
        return {
            "in_chain": False,
            "found": False,
            "level": 0,
            "chain": [],
        }


__all__ = ("EmployeeHierarchyManager", "Employee")
