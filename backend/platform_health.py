import sys
import json
import asyncio
import warnings
import urllib.request
import os
import time

# Suppress all warnings
warnings.filterwarnings("ignore")

import logging
# Suppress all verbose logging during startup diagnostic queries
logging.basicConfig(level=logging.ERROR)
logging.getLogger("autoapply_ai").setLevel(logging.ERROR)
logging.getLogger("qdrant_client").setLevel(logging.ERROR)

from sqlalchemy import text

sys.path.append(".")

# Import database, redis, celery clients
try:
    from app.database import SessionLocal
    from app.redis_client import redis_client
    from app.celery_app import celery_app
except Exception as e:
    print(json.dumps({"error": f"Failed importing core modules: {e}"}))
    sys.exit(1)

async def check_postgres():
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return "ONLINE"
    except Exception as e:
        return f"OFFLINE ({e})"

def check_redis():
    try:
        redis_client.client.ping()
        return "ONLINE"
    except Exception as e:
        return f"OFFLINE ({e})"

def check_backend():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2.0) as response:
            if response.getcode() == 200:
                return "ONLINE"
    except Exception as e:
        return f"OFFLINE ({e})"
    return "OFFLINE"

async def check_websocket():
    import websockets
    import asyncio
    try:
        async def _connect():
            async with websockets.connect("ws://127.0.0.1:8000/ws/health_check_dummy"):
                return "ONLINE"
        return await asyncio.wait_for(_connect(), timeout=2.0)
    except asyncio.TimeoutError:
        return "OFFLINE (timeout)"
    except Exception as e:
        return f"OFFLINE ({e})"

def check_celery_beat():
    try:
        # PIDs folder is in root, we are running in backend/
        pid_file = "../pids/beat.pid"
        if os.path.exists(pid_file):
            with open(pid_file, "r", encoding="utf-8-sig") as f:
                pid_str = f.read().strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if sys.platform == "win32":
                        try:
                            import ctypes
                            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                            if handle:
                                ctypes.windll.kernel32.CloseHandle(handle)
                                return "ONLINE"
                            return "OFFLINE"
                        except Exception:
                            import subprocess
                            try:
                                out = subprocess.check_output(f'tasklist /FI "PID eq {pid}"', shell=True, text=True)
                                if str(pid) in out:
                                    return "ONLINE"
                            except Exception:
                                pass
                            return "OFFLINE"
                    else:
                        try:
                            os.kill(pid, 0)
                            return "ONLINE"
                        except OSError:
                            return "OFFLINE"
    except Exception as e:
        return f"OFFLINE ({e})"
    return "OFFLINE"

def is_pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except Exception:
            pass
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            pass
    return False

def get_celery_workers():
    queues = ["discovery", "orchestrate", "applications", "sheets", "email"]
    workers_status = {q: "OFFLINE" for q in queues}
    
    # 1. Try Celery Inspect
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active = inspect.active_queues()
        if active:
            for w_name, q_list in active.items():
                for q_info in q_list:
                    q_name = q_info.get("name")
                    if q_name in workers_status:
                        workers_status[q_name] = "ONLINE"
    except Exception:
        pass
        
    # 2. Check if offline workers are actually busy processing a task
    # If a worker is busy under -P solo, Celery inspect fails to respond, but it is not frozen
    # We check if the process is alive and if the logs were recently modified (within 10 minutes)
    for q in queues:
        if workers_status[q] == "OFFLINE":
            try:
                pid_file = f"../pids/worker_{q}_child.pid"
                if os.path.exists(pid_file):
                    with open(pid_file, "r", encoding="utf-8-sig") as f:
                        pid_str = f.read().strip()
                        if pid_str.isdigit():
                            pid = int(pid_str)
                            if is_pid_alive(pid):
                                # Check log modification time
                                stdout_log = f"../logs/worker_{q}.stdout.log"
                                stderr_log = f"../logs/worker_{q}.stderr.log"
                                max_mtime = 0
                                for log_path in [stdout_log, stderr_log]:
                                    if os.path.exists(log_path):
                                        mtime = os.path.getmtime(log_path)
                                        if mtime > max_mtime:
                                            max_mtime = mtime
                                
                                # If the log has been modified in the last 10 minutes (600 seconds), mark as ONLINE/BUSY
                                if time.time() - max_mtime < 600:
                                    workers_status[q] = "ONLINE"
            except Exception:
                pass
                
    return workers_status

def check_frontend():
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000", timeout=2.0) as response:
            if response.getcode() == 200:
                return "ONLINE"
    except Exception as e:
        return f"OFFLINE ({e})"
    return "OFFLINE"

async def main():
    pg_status = await check_postgres()
    redis_status = check_redis()
    backend_status = check_backend()
    ws_status = await check_websocket()
    beat_status = check_celery_beat()
    workers_status = get_celery_workers()
    frontend_status = check_frontend()
    
    # Evaluate Pass/Fail
    all_ok = True
    if pg_status != "ONLINE": all_ok = False
    if redis_status != "ONLINE": all_ok = False
    if backend_status != "ONLINE": all_ok = False
    if ws_status != "ONLINE": all_ok = False
    if beat_status != "ONLINE": all_ok = False
    if frontend_status != "ONLINE": all_ok = False
    for w_name, w_status in workers_status.items():
        if w_status != "ONLINE":
            all_ok = False
            
    summary_status = "PASS" if all_ok else "FAIL"
    
    # Fetch DB & Queue Metrics for compatibility and detailed logging
    db_metrics = {"total_jobs": 0, "total_applications": 0, "submitted_count": 0, "pending_count": 0, "error": None}
    try:
        async with SessionLocal() as db:
            res = await db.execute(text("SELECT count(*) FROM jobs.job_postings"))
            db_metrics["total_jobs"] = res.scalar() or 0
            res = await db.execute(text("SELECT count(*) FROM applications.applications"))
            db_metrics["total_applications"] = res.scalar() or 0
            res = await db.execute(text("SELECT count(*) FROM applications.applications WHERE status = 'SUBMITTED'"))
            db_metrics["submitted_count"] = res.scalar() or 0
            res = await db.execute(text("SELECT count(*) FROM applications.applications WHERE status = 'PENDING_APPROVAL'"))
            db_metrics["pending_count"] = res.scalar() or 0
    except Exception as e:
        db_metrics["error"] = str(e)
        
    result = {
        "status": summary_status,
        "db": db_metrics,
        "postgres": pg_status,
        "redis": {
            "redis_online": redis_status,
            "queue_sizes": {q: 0 for q in ["discovery", "orchestrate", "applications", "sheets", "email"]}
        },
        "backend": backend_status,
        "websocket": ws_status,
        "celery_beat": beat_status,
        "workers": workers_status,
        "frontend": frontend_status
    }
    
    # Try to fetch Redis queue sizes if Redis is online
    if redis_status == "ONLINE":
        for q in result["redis"]["queue_sizes"].keys():
            try:
                result["redis"]["queue_sizes"][q] = redis_client.client.llen(q) or 0
            except Exception:
                pass
                
    # Output to stdout
    print(json.dumps(result, indent=2))
    
    # Exit with code 0 if pass, 1 if fail
    if summary_status == "PASS":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
