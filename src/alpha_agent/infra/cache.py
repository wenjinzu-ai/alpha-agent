import json
import io
import threading
from typing import Optional, Any
from datetime import timedelta
import pandas as pd

from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


class DataCache:
    _instance: Optional["DataCache"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._client = None
        self._enabled = settings.redis_enabled
        if self._enabled:
            self._connect()

    @classmethod
    def get_instance(cls) -> "DataCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _connect(self):
        try:
            import redis
            self._client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password or None,
                decode_responses=True,
            )
            self._client.ping()
            logger.info("DataCache: Redis connected")
        except Exception as e:
            logger.warning(f"DataCache: Redis连接失败，缓存将不可用: {e}")
            self._client = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def get(self, key: str) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning(f"DataCache get error: {e}")
            return None

    def set(self, key: str, value: str, ex: Optional[timedelta] = None):
        if not self.enabled:
            return
        try:
            self._client.set(key, value, ex=ex)
        except Exception as e:
            logger.warning(f"DataCache set error: {e}")

    def get_json(self, key: str) -> Optional[Any]:
        data = self.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    def set_json(self, key: str, value: Any, ex: Optional[timedelta] = None):
        self.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ex)

    def get_df(self, key: str) -> Optional[pd.DataFrame]:
        data = self.get(key)
        if data:
            try:
                return pd.read_json(io.StringIO(data), orient="records")
            except Exception:
                return None
        return None

    def set_df(self, key: str, df: pd.DataFrame, ex: Optional[timedelta] = None):
        if df is None or df.empty:
            return
        try:
            self.set(key, df.to_json(orient="records", force_ascii=False), ex=ex)
        except Exception as e:
            logger.warning(f"DataCache set_df error: {e}")

    def delete(self, key: str):
        if not self.enabled:
            return
        try:
            self._client.delete(key)
        except Exception as e:
            logger.warning(f"DataCache delete error: {e}")

    def exists(self, key: str) -> bool:
        if not self.enabled:
            return False
        try:
            return self._client.exists(key) > 0
        except Exception:
            return False


def get_cache() -> DataCache:
    return DataCache.get_instance()
