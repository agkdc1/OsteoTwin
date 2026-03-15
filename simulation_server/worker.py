"""OsteoTwin Simulation Worker — Pub/Sub consumer with checkpoint/failover.

Designed to run on volatile Spot/Preemptible VMs. Saves intermediate state
to GCS so work can resume after preemption.

Local mode: Pulls from Pub/Sub but runs physics on the local machine.
Cloud mode: Same code, deployed to Spot VMs via the MIG.

Usage:
    python -m simulation_server.worker \
        --project osteotwin-37f03c \
        --subscription simulation-worker-sub \
        --checkpoint-bucket osteotwin-37f03c-checkpoints

    # Local mode (no Pub/Sub, process a single task):
    python -m simulation_server.worker --local --task-file task.json
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("osteotwin.worker")

# Graceful shutdown on SIGTERM (Spot preemption signal)
_shutdown_requested = False


def _handle_sigterm(signum, frame):
    global _shutdown_requested
    logger.warning("SIGTERM received — saving checkpoint and shutting down gracefully")
    _shutdown_requested = True


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Checkpoint manager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """Save/restore simulation state to GCS or local disk."""

    def __init__(self, bucket_name: Optional[str] = None, local_dir: str = "./checkpoints"):
        self._bucket_name = bucket_name
        self._local_dir = Path(local_dir)
        self._local_dir.mkdir(parents=True, exist_ok=True)
        self._gcs_client = None

        if bucket_name:
            try:
                from google.cloud import storage
                self._gcs_client = storage.Client()
                self._bucket = self._gcs_client.bucket(bucket_name)
                logger.info("Checkpoint storage: GCS gs://%s", bucket_name)
            except Exception as exc:
                logger.warning("GCS unavailable (%s) — using local checkpoints", exc)
                self._gcs_client = None

    def save(self, task_id: str, state: dict) -> str:
        """Save checkpoint state for a task."""
        checkpoint_data = json.dumps(state, default=str).encode("utf-8")
        blob_name = f"tasks/{task_id}/checkpoint.json"

        if self._gcs_client:
            blob = self._bucket.blob(blob_name)
            blob.upload_from_string(checkpoint_data, content_type="application/json")
            logger.info("Checkpoint saved to gs://%s/%s", self._bucket_name, blob_name)
        else:
            local_path = self._local_dir / task_id / "checkpoint.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(checkpoint_data)
            logger.info("Checkpoint saved to %s", local_path)

        return blob_name

    def load(self, task_id: str) -> Optional[dict]:
        """Load checkpoint for a task. Returns None if no checkpoint exists."""
        blob_name = f"tasks/{task_id}/checkpoint.json"

        if self._gcs_client:
            blob = self._bucket.blob(blob_name)
            if blob.exists():
                data = json.loads(blob.download_as_bytes())
                logger.info("Resumed from GCS checkpoint: %s", blob_name)
                return data
        else:
            local_path = self._local_dir / task_id / "checkpoint.json"
            if local_path.exists():
                data = json.loads(local_path.read_bytes())
                logger.info("Resumed from local checkpoint: %s", local_path)
                return data

        return None

    def save_result(self, task_id: str, result: dict) -> str:
        """Save final result and clean up checkpoint."""
        result_data = json.dumps(result, default=str).encode("utf-8")
        blob_name = f"tasks/{task_id}/result.json"

        if self._gcs_client:
            blob = self._bucket.blob(blob_name)
            blob.upload_from_string(result_data, content_type="application/json")
            # Clean up checkpoint
            cp_blob = self._bucket.blob(f"tasks/{task_id}/checkpoint.json")
            if cp_blob.exists():
                cp_blob.delete()
            logger.info("Result saved to gs://%s/%s", self._bucket_name, blob_name)
        else:
            local_path = self._local_dir / task_id / "result.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(result_data)
            # Clean up checkpoint
            cp_path = self._local_dir / task_id / "checkpoint.json"
            if cp_path.exists():
                cp_path.unlink()
            logger.info("Result saved to %s", local_path)

        return blob_name

    def clear(self, task_id: str) -> None:
        """Remove all data for a task."""
        if self._gcs_client:
            prefix = f"tasks/{task_id}/"
            blobs = self._bucket.list_blobs(prefix=prefix)
            for blob in blobs:
                blob.delete()
        else:
            task_dir = self._local_dir / task_id
            if task_dir.exists():
                import shutil
                shutil.rmtree(task_dir)


# ---------------------------------------------------------------------------
# Simulation executor
# ---------------------------------------------------------------------------


def execute_simulation(task: dict, checkpoint_mgr: CheckpointManager) -> dict:
    """Execute a simulation task with periodic checkpointing.

    Args:
        task: Parsed SimActionRequest or CollisionCheckRequest dict.
        checkpoint_mgr: CheckpointManager for save/restore.

    Returns:
        Simulation result dict.
    """
    task_id = task.get("request_id", uuid.uuid4().hex)
    task_type = task.get("task_type", "action")

    # Check for existing checkpoint
    checkpoint = checkpoint_mgr.load(task_id)
    start_step = 0
    accumulated_state = {}

    if checkpoint:
        start_step = checkpoint.get("completed_steps", 0)
        accumulated_state = checkpoint.get("state", {})
        logger.info("Resuming task %s from step %d", task_id, start_step)

    # Import simulation engine
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from simulation_server.app.collision.engine import CollisionEngine

    engine = CollisionEngine()

    # Load meshes if specified
    meshes_to_load = task.get("meshes", [])
    for mesh_info in meshes_to_load:
        engine.load_mesh(
            mesh_id=mesh_info["mesh_id"],
            file_path=mesh_info["file_path"],
            label=mesh_info.get("label", ""),
            mesh_type=mesh_info.get("mesh_type", "bone"),
        )

    # Execute simulation steps (for multi-step simulations)
    total_steps = task.get("total_steps", 1)

    for step in range(start_step, total_steps):
        if _shutdown_requested:
            # SIGTERM — save checkpoint immediately
            checkpoint_mgr.save(task_id, {
                "completed_steps": step,
                "state": accumulated_state,
                "task": task,
            })
            logger.warning("Preempted at step %d/%d — checkpoint saved", step, total_steps)
            sys.exit(0)

        # Execute the step
        if task_type == "collision":
            result = engine.ray_cast(
                origin=(
                    task["ray_origin"]["x"],
                    task["ray_origin"]["y"],
                    task["ray_origin"]["z"],
                ),
                direction=(
                    task["ray_direction"]["x"],
                    task["ray_direction"]["y"],
                    task["ray_direction"]["z"],
                ),
                max_length=task.get("max_length_mm"),
            )
            accumulated_state["hits"] = result
        elif task_type == "action":
            accumulated_state["fragment_id"] = task.get("fragment_id")
            accumulated_state["position"] = {
                "x": task.get("translation", {}).get("x", 0),
                "y": task.get("translation", {}).get("y", 0),
                "z": task.get("translation", {}).get("z", 0),
            }

        # Periodic checkpoint (every 10 steps for multi-step sims)
        if total_steps > 1 and step % 10 == 0 and step > start_step:
            checkpoint_mgr.save(task_id, {
                "completed_steps": step + 1,
                "state": accumulated_state,
                "task": task,
            })

    # Save final result
    final_result = {
        "request_id": task_id,
        "success": True,
        "completed_steps": total_steps,
        **accumulated_state,
    }
    checkpoint_mgr.save_result(task_id, final_result)

    return final_result


# ---------------------------------------------------------------------------
# Pub/Sub consumer
# ---------------------------------------------------------------------------


def run_pubsub_worker(
    project_id: str,
    subscription: str,
    checkpoint_bucket: Optional[str],
    idle_timeout: int = 300,
):
    """Pull simulation tasks from Pub/Sub and execute them.

    Args:
        idle_timeout: Seconds to wait with no messages before exiting (default 300s = 5min).
            Set to 0 for infinite wait.
    """
    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription)
    checkpoint_mgr = CheckpointManager(bucket_name=checkpoint_bucket)

    logger.info("Worker listening on %s (idle_timeout=%ds)", subscription_path, idle_timeout)

    _last_message_time = [time.time()]
    _tasks_completed = [0]

    def callback(message):
        task_id = message.attributes.get("task_id", "unknown")
        logger.info("Received task: %s", task_id)
        _last_message_time[0] = time.time()

        try:
            task = json.loads(message.data.decode("utf-8"))
            result = execute_simulation(task, checkpoint_mgr)
            logger.info("Task %s completed: %s", task_id, result.get("success"))
            _tasks_completed[0] += 1
            # ACK only after 100% completion
            message.ack()
        except Exception as exc:
            logger.error("Task %s failed: %s", task_id, exc)
            # NACK — message will be redelivered for retry
            message.nack()

        _last_message_time[0] = time.time()

    streaming_pull = subscriber.subscribe(subscription_path, callback=callback)
    logger.info("Worker started. Waiting for messages...")

    try:
        if idle_timeout > 0:
            # Poll for idle timeout
            while not _shutdown_requested:
                try:
                    streaming_pull.result(timeout=30)
                except Exception:
                    pass
                idle_secs = time.time() - _last_message_time[0]
                if idle_secs > idle_timeout:
                    logger.info(
                        "Idle for %ds (threshold %ds). Completed %d tasks. Shutting down.",
                        int(idle_secs), idle_timeout, _tasks_completed[0],
                    )
                    streaming_pull.cancel()
                    break
        else:
            streaming_pull.result()
    except KeyboardInterrupt:
        streaming_pull.cancel()
        logger.info("Worker stopped. Completed %d tasks.", _tasks_completed[0])


def run_local_worker(task_file: str, checkpoint_bucket: Optional[str]):
    """Process a single task from a JSON file (local mode)."""
    task = json.loads(Path(task_file).read_text())
    checkpoint_mgr = CheckpointManager(bucket_name=checkpoint_bucket)
    result = execute_simulation(task, checkpoint_mgr)
    print(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="OsteoTwin Simulation Worker")
    parser.add_argument("--project", default="osteotwin-37f03c", help="GCP project ID")
    parser.add_argument("--subscription", default="simulation-worker-sub")
    parser.add_argument("--checkpoint-bucket", default=None, help="GCS bucket for checkpoints")
    parser.add_argument("--local", action="store_true", help="Local mode (no Pub/Sub)")
    parser.add_argument("--task-file", help="JSON task file (local mode only)")
    parser.add_argument("--idle-timeout", type=int, default=300, help="Seconds idle before shutdown (0=infinite)")
    args = parser.parse_args()

    if args.local:
        if not args.task_file:
            parser.error("--task-file required in local mode")
        run_local_worker(args.task_file, args.checkpoint_bucket)
    else:
        run_pubsub_worker(args.project, args.subscription, args.checkpoint_bucket, args.idle_timeout)


if __name__ == "__main__":
    main()
