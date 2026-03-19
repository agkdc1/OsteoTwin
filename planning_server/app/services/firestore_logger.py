"""Firestore Clinical Case Logger.

Asynchronously pushes SurgicalCaseLog documents to the
`clinical_case_logs` Firestore collection.

Uses google-cloud-firestore async client so logging never blocks
the main API response thread.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import sys, pathlib

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
)
from shared.clinical_log_schemas import SurgicalCaseLog, compute_delta_metrics

logger = logging.getLogger("osteotwin.firestore_logger")

COLLECTION = "clinical_case_logs"


class FirestoreFeedbackLogger:
    """Async Firestore logger for clinical case data.

    Usage:
        logger = FirestoreFeedbackLogger(project_id="osteotwin-37f03c")
        await logger.connect()
        await logger.log_case(case_log)
        await logger.close()

    Designed to be injected as a FastAPI dependency via lifespan.
    """

    def __init__(self, project_id: Optional[str] = None):
        self._project_id = project_id
        self._db: Any = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def connect(self) -> None:
        """Initialize the Firestore async client.

        Silently degrades if google-cloud-firestore is not installed
        or credentials are unavailable — logging is non-critical.
        """
        if not self._project_id:
            logger.warning(
                "GCP_PROJECT_ID not set — clinical logging disabled. "
                "Set GCP_PROJECT_ID in .env to enable Firestore."
            )
            return
        try:
            from google.cloud.firestore_v1 import AsyncClient

            self._db = AsyncClient(project=self._project_id)
            self._available = True
            logger.info("Firestore logger connected (project=%s)", self._project_id)
        except ImportError:
            logger.warning(
                "google-cloud-firestore not installed — clinical logging disabled. "
                "Install with: pip install google-cloud-firestore"
            )
        except Exception as exc:
            logger.warning("Firestore connection failed (non-blocking): %s", exc)

    async def close(self) -> None:
        """Close the Firestore client."""
        if self._db:
            self._db.close()
            self._db = None
            self._available = False

    async def log_case(self, case_log: SurgicalCaseLog) -> Optional[str]:
        """Push a SurgicalCaseLog document to Firestore.

        Returns the Firestore document ID on success, None on failure.
        Non-blocking: failures are logged but never raise.
        """
        if not self._available or not self._db:
            logger.debug("Firestore not available, skipping log for case %s", case_log.case_id)
            return None

        try:
            # Auto-compute delta metrics if both plans present
            if (
                case_log.ai_proposed_plan
                and case_log.surgeon_final_plan
                and case_log.delta_metrics is None
            ):
                case_log.delta_metrics = compute_delta_metrics(
                    case_log.ai_proposed_plan, case_log.surgeon_final_plan
                )

            doc_data = case_log.model_dump(mode="json")
            # Firestore uses its own timestamp type
            doc_data["timestamp"] = case_log.timestamp

            doc_ref = self._db.collection(COLLECTION).document(case_log.log_id)
            await doc_ref.set(doc_data)

            logger.info(
                "Logged case %s (surgeon=%s, anatomy=%s) → Firestore doc %s",
                case_log.case_id,
                case_log.surgeon_id,
                case_log.target_anatomy,
                case_log.log_id,
            )
            return case_log.log_id

        except Exception as exc:
            logger.error("Failed to log case %s to Firestore: %s", case_log.case_id, exc)
            return None

    async def log_case_fire_and_forget(self, case_log: SurgicalCaseLog) -> None:
        """Fire-and-forget: schedule log_case as a background task.

        Use this from endpoint handlers to avoid blocking the response.
        """
        asyncio.create_task(self.log_case(case_log))

    async def get_case_logs(
        self,
        case_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve logs for a specific case, ordered by timestamp DESC."""
        if not self._available or not self._db:
            return []

        try:
            query = (
                self._db.collection(COLLECTION)
                .where("case_id", "==", case_id)
                .order_by("timestamp", direction="DESCENDING")
                .limit(limit)
            )
            docs = []
            async for doc in query.stream():
                docs.append(doc.to_dict())
            return docs
        except Exception as exc:
            logger.error("Failed to query logs for case %s: %s", case_id, exc)
            return []

    async def get_surgeon_logs(
        self,
        surgeon_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve all logs for a surgeon, ordered by timestamp DESC."""
        if not self._available or not self._db:
            return []

        try:
            query = (
                self._db.collection(COLLECTION)
                .where("surgeon_id", "==", surgeon_id)
                .order_by("timestamp", direction="DESCENDING")
                .limit(limit)
            )
            docs = []
            async for doc in query.stream():
                docs.append(doc.to_dict())
            return docs
        except Exception as exc:
            logger.error("Failed to query logs for surgeon %s: %s", surgeon_id, exc)
            return []

    async def update_post_op(
        self,
        log_id: str,
        deviation_log: str,
        satisfaction: Optional[int] = None,
        additional_notes: Optional[str] = None,
    ) -> bool:
        """Update a log with post-operative feedback.

        Called after the surgery to record real-world deviations.
        """
        if not self._available or not self._db:
            return False

        try:
            doc_ref = self._db.collection(COLLECTION).document(log_id)
            update: dict[str, Any] = {
                "post_op_deviation_log": deviation_log,
            }
            if satisfaction is not None:
                update["surgeon_satisfaction"] = satisfaction
            if additional_notes is not None:
                update["additional_notes"] = additional_notes

            await doc_ref.update(update)
            logger.info("Updated post-op feedback for log %s", log_id)
            return True
        except Exception as exc:
            logger.error("Failed to update post-op for log %s: %s", log_id, exc)
            return False


# ---------------------------------------------------------------------------
# Singleton instance (initialized in FastAPI lifespan)
# ---------------------------------------------------------------------------

def _get_project_id() -> str:
    """Read GCP_PROJECT_ID at import time (config already loaded)."""
    import os
    return os.getenv("GCP_PROJECT_ID", "osteotwin-37f03c")


clinical_logger = FirestoreFeedbackLogger(project_id=_get_project_id())
