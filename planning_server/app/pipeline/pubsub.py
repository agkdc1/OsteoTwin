"""Pub/Sub publisher for async simulation tasks.

Publishes SimActionRequest / CollisionCheckRequest to the Pub/Sub topic.
The worker (local or cloud Spot VM) picks up the message and processes it.
Falls back to direct HTTP call if Pub/Sub is not configured.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from .. import config

logger = logging.getLogger("osteotwin.pubsub")

_publisher = None
_topic_path = None


def _get_publisher():
    """Lazy-init Pub/Sub publisher."""
    global _publisher, _topic_path

    if _publisher is not None:
        return _publisher, _topic_path

    gcp_project = getattr(config, "GCP_PROJECT_ID", "") or ""
    if not gcp_project:
        logger.info("GCP_PROJECT_ID not set — Pub/Sub disabled, using direct HTTP")
        return None, None

    try:
        from google.cloud import pubsub_v1
        _publisher = pubsub_v1.PublisherClient()
        _topic_path = _publisher.topic_path(gcp_project, "simulation-tasks-topic")
        logger.info("Pub/Sub publisher initialized: %s", _topic_path)
        return _publisher, _topic_path
    except Exception as exc:
        logger.warning("Pub/Sub unavailable (%s) — falling back to direct HTTP", exc)
        return None, None


async def publish_simulation_task(task: dict) -> dict:
    """Publish a simulation task to Pub/Sub.

    Returns:
        Dict with task_id and status (either 'queued' or 'direct').
        If Pub/Sub is unavailable, falls back to direct HTTP call.
    """
    task_id = task.get("request_id", uuid.uuid4().hex)
    publisher, topic_path = _get_publisher()

    if publisher and topic_path:
        # Publish to Pub/Sub
        data = json.dumps(task, default=str).encode("utf-8")
        future = publisher.publish(
            topic_path,
            data,
            task_id=task_id,
            task_type=task.get("task_type", "action"),
        )
        message_id = future.result(timeout=10)
        logger.info("Published task %s (message_id=%s)", task_id, message_id)
        return {
            "task_id": task_id,
            "status": "queued",
            "message_id": message_id,
            "note": "Task queued for async processing. Poll /api/v1/tasks/{task_id} for result.",
        }
    else:
        # Fallback: direct HTTP to simulation server
        from ..simulation_client.client import sim_client
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))

        task_type = task.get("task_type", "action")

        if task_type == "collision":
            from shared.collision_protocol import CollisionCheckRequest
            import httpx
            req = CollisionCheckRequest.model_validate(task)
            async with httpx.AsyncClient() as http:
                r = await http.post(
                    f"{config.SIMULATION_SERVER_URL}/api/v1/simulate/collision",
                    json=req.model_dump(mode="json"),
                    headers={"X-API-Key": config.SIM_API_KEY},
                    timeout=30.0,
                )
                r.raise_for_status()
                return {"task_id": task_id, "status": "direct", "result": r.json()}
        else:
            from shared.simulation_protocol import SimActionRequest
            req = SimActionRequest.model_validate(task)
            result = await sim_client.simulate_action(req)
            return {"task_id": task_id, "status": "direct", "result": result.model_dump(mode="json")}
