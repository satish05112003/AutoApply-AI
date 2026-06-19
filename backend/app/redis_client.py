import json
import logging
from typing import Optional, Any
import redis
from app.config import settings

logger = logging.getLogger("autoapply_ai.redis")

class RedisClient:
    def __init__(self):
        self._client = None

    @property
    def client(self) -> redis.Redis:
        """Lazily initialize Redis connection pool."""
        if self._client is None:
            logger.info(f"Connecting to Redis at: {settings.REDIS_URL}...")
            self._client = redis.Redis.from_url(
                settings.REDIS_URL, 
                decode_responses=True # Returns string instead of bytes
            )
        return self._client

    def set_value(self, key: str, value: Any, expire_seconds: Optional[int] = None) -> bool:
        """Set a value in Redis cache (will serialize Dicts/Lists automatically)."""
        try:
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value)
            else:
                serialized = str(value)
                
            self.client.set(key, serialized, ex=expire_seconds)
            return True
        except Exception as e:
            logger.error(f"Failed setting key '{key}' in Redis: {e}")
            return False

    def get_value(self, key: str, is_json: bool = False) -> Optional[Any]:
        """Get a value from Redis cache."""
        try:
            val = self.client.get(key)
            if val is None:
                return None
                
            if is_json:
                return json.loads(val)
            return val
        except Exception as e:
            logger.error(f"Failed getting key '{key}' from Redis: {e}")
            return None

    def delete_key(self, key: str) -> bool:
        """Delete a key from Redis."""
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed deleting key '{key}' from Redis: {e}")
            return False

# Global Redis Client Instance
redis_client = RedisClient()
