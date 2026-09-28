from typing import Optional
from datetime import datetime
from decimal import Decimal

from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    ForeignKey,
    DateTime,
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pydantic import EmailStr


from . import Base


class UserModel(Base):
    __tablename__ = "users"
    
    email: Mapped[EmailStr] = mapped_column(String(100), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(24), nullable=False)
    password: Mapped[str] = mapped_column(String(512), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, 
                                            nullable=False,
                                            default=True,
                                            server_default=text("true"))
    is_verified: Mapped[bool] = mapped_column(Boolean, 
                                              nullable=False, 
                                              default=False,
                                              server_default=text("false"))
    is_superuser: Mapped[bool] = mapped_column(Boolean, 
                                               nullable=False,
                                               default=False,
                                               server_default=text("false"))


    user_session: Mapped[Optional["UserSessionModel"]] = relationship(
        "UserSessionModel", 
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserSessionModel(Base):
    __tablename__ = "users_sessions"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["UserModel"] = relationship(
        "UserModel", 
        back_populates="user_session"
    )