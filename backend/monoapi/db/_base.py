import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Self
from uuid import UUID, uuid4

from sqlalchemy import UUID as COLUMN_UUID
from sqlalchemy import Column, DateTime, Row, Select, select, text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.inspection import Inspectable
from sqlalchemy.orm import DeclarativeBaseNoMeta as _DeclarativeBaseNoMeta
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.decl_api import DeclarativeAttributeIntercept as _DeclarativeAttributeIntercept
from sqlalchemy.orm.strategy_options import Load
from sqlalchemy.sql import func
from sqlalchemy.sql._typing import _HasClauseElement
from sqlalchemy.sql.elements import BinaryExpression, ColumnElement, SQLCoreOperations, UnaryExpression
from sqlalchemy.sql.roles import ColumnsClauseRole, TypedColumnsClauseRole

if TYPE_CHECKING:
    from sqlalchemy.engine.result import Result

logger = logging.getLogger(__name__)


class ModelBaseError(Exception): ...


class ModelDoesNotExistError(ModelBaseError):
    """Исключение: запись не найдена в БД."""
    def __init__(self, model_name: str = None, field: str | None = None, value: Any = None):
        if model_name and field and value is not None:
            message = f"Запись {model_name} с {field}={value} не найдена"
        else:
            message = "Запись не найдена"
        super().__init__(message)
        self.model_name = model_name
        self.field = field
        self.value = value


class FilterStatementKwargs(NamedTuple):
    offset: int | None = None
    limit: int | None = None
    order_by: str | None = "id"
    order_by_direction: Literal["asc", "desc"] = "asc"
    extra: dict | None = None


class DeclarativeBaseNoMeta(_DeclarativeBaseNoMeta):
    """
    Тоже самое что и Declarative Base, 
    Но при создании Base можно добавить DeclarativeAttributeIntercept"""
    pass


class DeclarativeAttributeIntercept(_DeclarativeAttributeIntercept):
    """Тут можно задать методы для метакласса"""
    @property
    def select_(
        cls,  # noqa: N805
    ) -> Callable[
        [
            tuple[
                TypedColumnsClauseRole[Any]
                | ColumnsClauseRole
                | SQLCoreOperations[Any]
                | Inspectable[_HasClauseElement[Any]]
                | _HasClauseElement[Any]
                | Any,
                ...,
            ],
            dict[str, Any],
        ],
        Select[Any],
    ]:
        return select


class Base(
    DeclarativeBaseNoMeta,
    metaclass=DeclarativeAttributeIntercept
):
    """
    Кастомный Base:
        - По дефолту определеяет общие поля в таблицах
    """
    __abstract__ = True
    
    negattion: str = "!"

    id: Mapped[int] = mapped_column(primary_key=True)

    uuid: Mapped[UUID] = mapped_column(
        COLUMN_UUID(as_uuid=True),
        primary_key=False,
        unique=True,
        nullable=False,
        default=uuid4,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('utc', now())"),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("TIMEZONE('utc', now())"),
        onupdate=text("TIMEZONE('utc', now())"),
        nullable=False)
    


    order_by_direction: Literal["asc", "desc"] = "asc"

    @classmethod
    async def count(cls, session: AsyncSession, /) -> int:
        """
        Count total by id
        Use: total_users = await User.count(session)
        """
        cursor: Result = await session.execute(func.count(cls.id))
        return cursor.scalar()
    
    @staticmethod
    def get_select_in_load() -> list[Load]:
        return []

    @classmethod
    def get_options(cls) -> list[Load]:
        return cls.get_select_in_load()

    @classmethod
    def get_cond_list(cls, **kwargs) -> list[BinaryExpression]:
        return []

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        val: int | str | UUID,
        /,
        *,
        field: InstrumentedAttribute | None = None,
        extra_where: list[ColumnElement[bool]] | None = None,
    ) -> Self:
        options: list[Load] = cls.get_options()
        if field is None:
            field = cls.id

        where_cond: list = [field == val]
        if extra_where is not None:
            where_cond.extend(extra_where)

        # TODO: I mean fix ignoring
        statement: Select = cls.select_(cls).where(*where_cond)  # type: ignore[call-arg]
        if options:
            statement = statement.options(*options)

        cursor: Result = await session.execute(statement)
        try:
            return cursor.scalars().one()
        except NoResultFound as err:
            raise ModelDoesNotExistError() from err

    @classmethod
    def get_order_by(
        cls,
        *,
        field_name: str | None = None,
        direction: Literal["asc", "desc"] = "asc",
    ) -> UnaryExpression:
        field: InstrumentedAttribute
        if field_name is None:
            field = cls.id
        else:
            field = cls.__table__.c[field_name.lower()]

        if direction == "desc":
            return field.desc()
        return field.asc()

    @classmethod
    def get_filter_statement(
        cls,
        kwargs: FilterStatementKwargs,
        /,
    ) -> Select[tuple[Self]]:
        # TODO: I mean fix ignoring
        statement: Select[tuple[Base]] = cls.select_(cls)  # type: ignore[call-arg]
        statement = statement.order_by(
            cls.get_order_by(
                field_name=kwargs.order_by,
                direction=kwargs.order_by_direction,
            )
        )

        cond_list: list = []
        if kwargs.extra is not None:
            cond_list = cls.get_cond_list(**kwargs.extra)
        if cond_list:
            statement = statement.where(*cond_list)
        options: list[Load] = cls.get_options()
        if options:
            statement = statement.options(*options)
        if kwargs.offset is not None:
            statement = statement.offset(kwargs.offset)
        if kwargs.limit is not None:
            statement = statement.limit(kwargs.limit)
        return statement

    @classmethod
    def get_binary_cond(cls, field: Column[str | Enum], value: str, /) -> BinaryExpression:
        if value.startswith(cls.negation):
            return field != value[1:]

        return field == value

    @classmethod
    async def filter(
        cls,
        session: AsyncSession,
        kwargs: FilterStatementKwargs,
        /,
    ) -> Sequence[Row[tuple[Any, ...] | Any]]:
        statement = cls.get_filter_statement(kwargs)
        cursor: Result = await session.execute(statement)
        return cursor.scalars().all()