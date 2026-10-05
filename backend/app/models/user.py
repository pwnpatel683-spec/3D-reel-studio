"""
3D Reel Studio — User Database Model
Phase 16: Multi-User Authentication & Account Management
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    String,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def generate_user_id() -> str:
    """Generates a unique user ID with prefix (e.g. USR-A1B2C3D4)."""
    return f"USR-{uuid.uuid4().hex[:12].upper()}"


def utc_now() -> datetime:
    """Returns current UTC timestamp timezone-aware."""
    return datetime.now(timezone.utc)


class User(Base):
    """
    User account model for multi-user studio isolation.
    """
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, default=generate_user_id, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # One-to-many relationship with owned projects
    projects = relationship(
        "Project",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(Project.created_at)",
    )

    def __repr__(self) -> str:
        return f"<User id='{self.id}' email='{self.email}' is_active={self.is_active}>"
