"""Firestore-backed user and case storage.

Replaces the previous SQLAlchemy/SQLite setup with Firestore,
which has a generous free tier (50K reads, 20K writes/day) and
works natively on Cloud Run without persistent disk.

Collections:
  - users: {doc_id: auto} username, hashed_password, role, status, created_at
  - fracture_cases: {doc_id: case_id} owner_id, title, ao_code, description, status
  - debates: {doc_id: debate_id} case_id, status, rounds_completed, selected_plan_label
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("osteotwin.database")

try:
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    FieldFilter = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# User data model (replaces SQLAlchemy ORM User)
# ---------------------------------------------------------------------------


@dataclass
class User:
    """User model — serialized to/from Firestore documents."""

    id: str  # Firestore document ID
    username: str
    hashed_password: str
    role: str = "user"  # admin | user
    status: str = "pending"  # pending | approved | rejected
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "hashed_password": self.hashed_password,
            "role": self.role,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_doc(cls, doc_id: str, data: dict[str, Any]) -> User:
        created = data.get("created_at")
        if hasattr(created, "timestamp"):
            # Firestore Timestamp → datetime
            created = datetime.fromtimestamp(created.timestamp(), tz=timezone.utc)
        elif not isinstance(created, datetime):
            created = datetime.now(timezone.utc)
        return cls(
            id=doc_id,
            username=data["username"],
            hashed_password=data["hashed_password"],
            role=data.get("role", "user"),
            status=data.get("status", "pending"),
            created_at=created,
        )


# ---------------------------------------------------------------------------
# Firestore user store (singleton)
# ---------------------------------------------------------------------------


class UserStore:
    """Async Firestore-backed user CRUD.

    Gracefully degrades to in-memory dict when Firestore is unavailable
    (local development without GCP credentials).
    """

    COLLECTION = "users"

    def __init__(self) -> None:
        self._db: Any = None
        self._available = False
        # Fallback in-memory store for local dev
        self._mem: dict[str, dict[str, Any]] = {}
        self._mem_counter = 0

    @property
    def available(self) -> bool:
        return self._available

    async def connect(self, project_id: str = "") -> None:
        if not project_id:
            logger.warning(
                "GCP_PROJECT_ID not set — using in-memory user store. "
                "Set GCP_PROJECT_ID in .env or environment to enable Firestore."
            )
            return
        try:
            from google.cloud.firestore_v1 import AsyncClient

            client = AsyncClient(project=project_id)
            # Probe: verify Firestore is reachable (catches wrong project / disabled API)
            _ = await client.collection(self.COLLECTION).limit(1).get()
            self._db = client
            self._available = True
            logger.info("UserStore connected to Firestore (project=%s)", project_id or "default")
        except ImportError:
            logger.warning(
                "google-cloud-firestore not installed — using in-memory user store. "
                "Install with: pip install google-cloud-firestore"
            )
        except Exception as exc:
            logger.warning("Firestore unavailable, falling back to in-memory: %s", exc)

    async def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None
            self._available = False

    # --- CRUD ---

    async def create_user(self, user: User) -> str:
        """Create a user, returns the document ID."""
        if self._available and self._db:
            doc_ref = self._db.collection(self.COLLECTION).document()
            await doc_ref.set(user.to_dict())
            user.id = doc_ref.id
            return doc_ref.id
        else:
            self._mem_counter += 1
            doc_id = str(self._mem_counter)
            user.id = doc_id
            self._mem[doc_id] = user.to_dict()
            return doc_id

    async def get_by_id(self, user_id: str) -> Optional[User]:
        if self._available and self._db:
            doc = await self._db.collection(self.COLLECTION).document(user_id).get()
            if doc.exists:
                return User.from_doc(doc.id, doc.to_dict())
            return None
        else:
            data = self._mem.get(user_id)
            if data:
                return User.from_doc(user_id, data)
            return None

    async def get_by_username(self, username: str) -> Optional[User]:
        if self._available and self._db:
            query = (
                self._db.collection(self.COLLECTION)
                .where(filter=FieldFilter("username", "==", username))
                .limit(1)
            )
            async for doc in query.stream():
                return User.from_doc(doc.id, doc.to_dict())
            return None
        else:
            for doc_id, data in self._mem.items():
                if data["username"] == username:
                    return User.from_doc(doc_id, data)
            return None

    async def get_by_status(self, status: str) -> list[User]:
        if self._available and self._db:
            query = self._db.collection(self.COLLECTION).where(filter=FieldFilter("status", "==", status))
            users = []
            async for doc in query.stream():
                users.append(User.from_doc(doc.id, doc.to_dict()))
            return users
        else:
            return [
                User.from_doc(doc_id, data)
                for doc_id, data in self._mem.items()
                if data.get("status") == status
            ]

    async def update_status(self, user_id: str, new_status: str) -> bool:
        if self._available and self._db:
            doc_ref = self._db.collection(self.COLLECTION).document(user_id)
            await doc_ref.update({"status": new_status})
            return True
        else:
            if user_id in self._mem:
                self._mem[user_id]["status"] = new_status
                return True
            return False


# ---------------------------------------------------------------------------
# Singleton (initialized in FastAPI lifespan)
# ---------------------------------------------------------------------------

user_store = UserStore()


async def init_db() -> None:
    """Initialize Firestore user store and ensure admin user exists."""
    from . import config

    await user_store.connect(project_id=config.GCP_PROJECT_ID)

    # Ensure admin user exists
    from .auth.dependencies import hash_password

    admin = await user_store.get_by_username(config.ADMIN_USERNAME)
    if not admin:
        admin = User(
            id="",
            username=config.ADMIN_USERNAME,
            hashed_password=hash_password(config.ADMIN_PASSWORD),
            role="admin",
            status="approved",
        )
        await user_store.create_user(admin)
        logger.info("Created admin user: %s", config.ADMIN_USERNAME)
