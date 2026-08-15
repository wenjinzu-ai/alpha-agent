from datetime import datetime

from sqlalchemy import DateTime, create_engine, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, comment="最后更新时间"
    )


_db_available: bool = False


def is_db_available() -> bool:
    return _db_available


def _build_sync_url() -> str:
    url = settings.postgres_url
    return url.replace("postgresql+asyncpg://", "postgresql://")


try:
    engine = create_engine(
        _build_sync_url(),
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    with engine.connect() as _conn:
        _conn.execute(func.now().select())
    _db_available = True
except Exception as _e:
    logger.warning(f"[db] 数据库不可用，将以无DB模式运行: {_e}")
    _db_available = False
    engine = None


def _null_session_factory(**_kwargs):  # pragma: no cover - stub
    raise RuntimeError("数据库不可用，无法创建 Session")


if _db_available and engine is not None:
    SessionLocal = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
else:
    SessionLocal = _null_session_factory  # type: ignore[assignment]


def get_db() -> Session:
    if not _db_available:
        raise RuntimeError("数据库不可用")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    global _db_available
    if not _db_available or engine is None:
        raise RuntimeError("数据库连接不可用，跳过表初始化")
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表初始化完成")


def check_db_connection() -> bool:
    global _db_available
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(func.now().select())
        _db_available = True
        return True
    except Exception as e:
        logger.warning(f"数据库连接失败: {e}")
        _db_available = False
        return False