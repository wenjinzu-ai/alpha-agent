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


def _build_sync_url() -> str:
    url = settings.postgres_url
    return url.replace("postgresql+asyncpg://", "postgresql://")


engine = create_engine(
    _build_sync_url(),
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表初始化完成")


def check_db_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(func.now().select())
        return True
    except Exception as e:
        logger.warning(f"数据库连接失败: {e}")
        return False
