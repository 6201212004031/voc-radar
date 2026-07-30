"""SQLAlchemy 引擎、Session、Base 与数据库初始化.

使用方式:
    # 1. 在应用启动时调用 init_db() 建表
    from app.models.database import init_db
    init_db()

    # 2. 通过 get_session 上下文管理器获取会话
    from app.models.database import get_session
    with get_session() as session:
        ...  # 操作 ORM

    # 3. 直接运行此模块可初始化数据库
    python -m app.models.database
"""
from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


logger = logging.getLogger(__name__)


# ---------- 全局 Base（所有 ORM 模型继承） ----------
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式 Base."""


# ---------- 引擎与会话工厂 ----------
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _make_engine() -> Engine:
    """创建 SQLAlchemy 引擎.

    SQLite 启用 WAL 与外键约束。
    """
    db_path = settings.db_path
    # 确保目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # SQLite URL 使用绝对路径 4 斜杠
    url = f"sqlite:///{db_path.as_posix()}"

    engine = create_engine(
        url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    # SQLite 启用外键约束（默认关闭）
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def get_engine() -> Engine:
    """获取全局引擎单例."""
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_sessionmaker() -> sessionmaker:
    """获取全局 sessionmaker 单例."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionLocal


@contextlib.contextmanager
def get_session() -> Iterator[Session]:
    """获取 Session 上下文管理器.

    用法:
        with get_session() as session:
            ...  # 操作
            session.commit()  # 显式提交

    异常时自动回滚并关闭。

    Yields:
        Session 实例
    """
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------- 初始化 ----------
def init_db(drop_all: bool = False) -> None:
    """初始化数据库：创建所有表.

    Args:
        drop_all: 是否先 drop 再 create（原型调试用，慎用）
    """
    # 确保所有模型被导入，Base.metadata 才能收集到表定义
    from app.models import schemas  # noqa: F401

    engine = get_engine()
    if drop_all:
        logger.warning("DROP ALL TABLES")
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    logger.info("数据库初始化完成: %s", settings.db_path)


def reset_db() -> None:
    """重置数据库（drop + create）。仅用于开发期调试."""
    init_db(drop_all=True)


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    from app.core.logging import setup_logging

    setup_logging()
    print(f"初始化数据库: {settings.db_path}")
    init_db()
    # 输出已创建的表
    from sqlalchemy import inspect

    inspector = inspect(get_engine())
    tables = inspector.get_table_names()
    print(f"已创建 {len(tables)} 张表: {', '.join(tables)}")
