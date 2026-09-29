from typing import Optional
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Integer,
    BigInteger,
    String,
    ForeignKey,
    DateTime,
    Date,
    Index,
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
from .enums import OperationCategory, OperationType

"""
Подсказка:

id, uuid, created_at, updated_at вшиты в Base.
"""


class UserModel(Base):
    __tablename__ = "users"
    
    email: Mapped[EmailStr] = mapped_column(String(100), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(24), nullable=False)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    password: Mapped[str] = mapped_column(String(512), nullable=False)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    targets: Mapped[list["TargetModel"]] = relationship(
        back_populates="user",
    )
    diary_entries: Mapped[list["DiaryModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

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


class TargetModel(Base):
    """Цели пользователя. Суммы учитываются в одной валюте приложения (RUB)."""

    __tablename__ = "targets"
    __table_args__ = (
        CheckConstraint("target_count > 0", name="ck_targets_target_count_positive"),
        CheckConstraint("current_count >= 0", name="ck_targets_current_count_nonnegative"),
        CheckConstraint("percentage >= 0 AND percentage <= 100", name="ck_targets_percentage"),
        Index("ix_targets_user_id", "user_id"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    current_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # прогресс выполнения цели в процентах
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))



    user: Mapped["UserModel"] = relationship(back_populates="targets")


class DiaryModel(Base):
    """Операция дневника. Суммы учитываются в одной валюте приложения (RUB)."""

    __tablename__ = "diary_entries"
    __table_args__ = (
        CheckConstraint("target_id IS NULL OR operation_type = 'investment'", name="ck_diary_entries_target_type"),
        CheckConstraint("amount > 0", name="ck_diary_entries_amount_positive"),
        Index("ix_diary_entries_user_id_operation_date", "user_id", "operation_date"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    target_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("targets.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    operation_date: Mapped[date] = mapped_column(Date, nullable=False)
    operation_type: Mapped[OperationType] = mapped_column(
        SAEnum(
            OperationType, name="operation_type", native_enum=False,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[Optional[OperationCategory]] = mapped_column(
        SAEnum(
            OperationCategory, name="operation_category", native_enum=False,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=True,
    )

    user: Mapped["UserModel"] = relationship(back_populates="diary_entries")
