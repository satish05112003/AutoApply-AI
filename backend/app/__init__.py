import os

# 1. Limit OpenBLAS, MKL, OMP, and NUMEXPR thread usage to 1 to prevent memory allocation crashes
# under process loaders (e.g. uvicorn, celery) and parallel pools on Windows.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# 2. Limit Redis client connection to RESP2 (protocol 2) since local Redis server (3.0.504)
# does not support RESP3's HELLO handshake. We patch the default RESP version in redis-py
# and disable maintenance notifications config (which triggers exceptions if protocol is not 3).
try:
    import redis.connection
    redis.connection.DEFAULT_RESP_VERSION = 2
    
    import redis.maint_notifications
    original_maint_init = redis.maint_notifications.MaintNotificationsConfig.__init__
    def patched_maint_init(self, *args, **kwargs):
        kwargs['enabled'] = False
        original_maint_init(self, *args, **kwargs)
    redis.maint_notifications.MaintNotificationsConfig.__init__ = patched_maint_init
except ImportError:
    pass
