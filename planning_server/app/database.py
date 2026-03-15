"""SQLAlchemy async database setup and ORM models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from . import config

engine = create_async_engine(config.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    role = Column(String(20), default="user")  # admin | user
    status = Column(String(20), default="pending")  # pending | approved | rejected
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    cases = relationship("FractureCaseRecord", back_populates="owner")


class FractureCaseRecord(Base):
    __tablename__ = "fracture_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    ao_code = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(30), default="created")  # created | meshed | simulating | planned
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="cases")
    debates = relationship("DebateRecord", back_populates="case")


class DebateRecord(Base):
    __tablename__ = "debates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    debate_id = Column(String(64), unique=True, index=True, nullable=False)
    case_id = Column(String(64), ForeignKey("fracture_cases.case_id"), nullable=False)
    status = Column(String(30), default="pending")
    rounds_completed = Column(Integer, default=0)
    selected_plan_label = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    case = relationship("FractureCaseRecord", back_populates="debates")


async def init_db() -> None:
    """Create all tables and ensure admin user exists."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure admin user exists
    from .auth.dependencies import hash_password

    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.username == config.ADMIN_USERNAME)
        )
        admin = result.scalar_one_or_none()
        if not admin:
            admin = User(
                username=config.ADMIN_USERNAME,
                hashed_password=hash_password(config.ADMIN_PASSWORD),
                role="admin",
                status="approved",
            )
            session.add(admin)
            await session.commit()
