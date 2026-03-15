"""Neo4j Graph Database connection for the Anatomical Rule Engine.

Stores surgeon corrections, anatomical relationships, and past case
knowledge so the LLM can pre-fetch relevant context before answering.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("osteotwin.graph_db")


class GraphDBConnection:
    """Async wrapper around the Neo4j driver.

    Usage:
        graph_db = GraphDBConnection()
        await graph_db.connect()
        rules = await graph_db.get_anatomical_rules("distal_radius")
        await graph_db.store_surgeon_correction(...)
        await graph_db.close()
    """

    def __init__(self) -> None:
        self._driver = None

    async def connect(self) -> None:
        """Initialize the Neo4j async driver."""
        from .. import config

        if not config.NEO4J_PASSWORD:
            logger.warning(
                "NEO4J_PASSWORD not set — Graph DB disabled. "
                "Anatomical Rule Engine will not be available."
            )
            return

        try:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
            )
            # Verify connectivity
            async with self._driver.session() as session:
                await session.run("RETURN 1")
            logger.info("Connected to Neo4j at %s", config.NEO4J_URI)
        except Exception as exc:
            logger.warning("Neo4j connection failed (%s) — Graph DB disabled.", exc)
            self._driver = None

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed.")

    @property
    def available(self) -> bool:
        return self._driver is not None

    # ------------------------------------------------------------------
    # Anatomical Rule Engine queries
    # ------------------------------------------------------------------

    async def get_anatomical_rules(
        self, region: str, *, limit: int = 20
    ) -> list[dict]:
        """Fetch anatomical rules relevant to a body region.

        Returns rules/corrections previously stored by surgeons
        so the LLM can include them as pre-fetched context.
        """
        if not self._driver:
            return []

        query = """
        MATCH (r:AnatomicalRule)-[:APPLIES_TO]->(region:BodyRegion {name: $region})
        RETURN r.rule_id AS rule_id,
               r.description AS description,
               r.source AS source,
               r.created_at AS created_at
        ORDER BY r.created_at DESC
        LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, region=region, limit=limit)
            return [dict(record) async for record in result]

    async def store_surgeon_correction(
        self,
        region: str,
        correction: str,
        surgeon_id: Optional[str] = None,
    ) -> str:
        """Store a surgeon's correction as a permanent anatomical rule.

        Example: "The supraspinatus does not attach there" →
        creates an AnatomicalRule node linked to the relevant BodyRegion.
        """
        if not self._driver:
            raise RuntimeError("Graph DB is not connected")

        import uuid
        from datetime import datetime

        rule_id = uuid.uuid4().hex[:12]

        query = """
        MERGE (region:BodyRegion {name: $region})
        CREATE (r:AnatomicalRule {
            rule_id: $rule_id,
            description: $correction,
            source: $surgeon_id,
            created_at: datetime($now)
        })
        CREATE (r)-[:APPLIES_TO]->(region)
        RETURN r.rule_id AS rule_id
        """
        async with self._driver.session() as session:
            result = await session.run(
                query,
                region=region,
                rule_id=rule_id,
                correction=correction,
                surgeon_id=surgeon_id or "anonymous",
                now=datetime.utcnow().isoformat(),
            )
            record = await result.single()
            logger.info(
                "Stored surgeon correction '%s' for region '%s' (rule_id=%s)",
                correction[:60],
                region,
                rule_id,
            )
            return record["rule_id"]

    async def get_past_case_context(
        self, ao_code: str, *, limit: int = 5
    ) -> list[dict]:
        """Retrieve past case outcomes for similar AO classifications."""
        if not self._driver:
            return []

        query = """
        MATCH (c:PastCase {ao_code: $ao_code})-[:HAD_OUTCOME]->(o:Outcome)
        RETURN c.case_id AS case_id,
               c.ao_code AS ao_code,
               o.description AS outcome,
               o.success AS success
        ORDER BY c.created_at DESC
        LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, ao_code=ao_code, limit=limit)
            return [dict(record) async for record in result]


# Module-level singleton
graph_db = GraphDBConnection()
