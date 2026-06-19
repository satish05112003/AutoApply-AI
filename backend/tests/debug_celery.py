import sys
import time
from redis import Redis
from app.config import settings
from app.celery_app import celery_app
from app.tasks.discovery_tasks import run_job_discovery

def debug_celery():
    print("=" * 60)
    print("AutoApply AI: Celery & Redis Infrastructure Verification")
    print("=" * 60)

    # 1. Test Redis Connection
    print("1. Checking Redis Connection...")
    redis_url = settings.REDIS_URL
    print(f"  Target Redis URL: {redis_url}")
    
    try:
        # Parse connection options from redis url
        # redis://localhost:6379/0?protocol=2 -> host, port, db
        # We can just initialize using Redis.from_url
        r = Redis.from_url(redis_url)
        ping_res = r.ping()
        if ping_res:
            print("  [OK] Redis server is alive and responding to PING.")
        else:
            print("  [FAIL] Redis PING returned False.")
            sys.exit(1)
            
        # Get Redis database statistics
        info = r.info()
        print(f"  Redis Version: {info.get('redis_version')}")
        print(f"  Connected Clients: {info.get('connected_clients')}")
        print(f"  Memory Used: {info.get('used_memory_human')}")
    except Exception as e:
        print(f"  [CRITICAL] Redis Connection Failed: {e}")
        sys.exit(1)
        
    print("-" * 60)

    # 2. Check Celery configuration
    print("2. Checking Celery configuration...")
    print(f"  Broker URL: {celery_app.conf.broker_url}")
    print(f"  Result Backend: {celery_app.conf.result_backend}")
    print(f"  Timezone: {celery_app.conf.timezone}")
    
    # List expected tasks registered locally
    print("  Locally registered Celery tasks:")
    local_tasks = sorted(list(celery_app.tasks.keys()))
    for task in local_tasks:
        if task.startswith("app.tasks"):
            print(f"    - {task}")

    print("-" * 60)

    # 3. Check active workers
    print("3. Inspecting active background workers (requires running worker!)...")
    try:
        inspector = celery_app.control.inspect(timeout=3.0)
        pings = inspector.ping()
        
        if not pings:
            print("  [WARN] No active Celery workers found responding to ping!")
            print("         Please ensure a worker is running in another terminal via:")
            print("         venv\\Scripts\\celery -A app.celery_app.celery_app worker --loglevel=info -P solo")
            has_workers = False
        else:
            has_workers = True
            for worker_name, status in pings.items():
                print(f"  [OK] Active worker found: {worker_name} (Status: {status})")
                
            # List registered tasks on active workers
            registered = inspector.registered()
            if registered:
                for worker_name, tasks in registered.items():
                    print(f"  Registered tasks on worker '{worker_name}':")
                    for t in sorted(tasks):
                        if t.startswith("app.tasks"):
                            print(f"    - {t}")
    except Exception as e:
        print(f"  Failed inspecting workers: {e}")
        has_workers = False

    print("-" * 60)

    # 4. Check Celery Beat scheduled tasks configuration
    print("4. Celery Beat periodic schedule:")
    beat_schedule = celery_app.conf.beat_schedule
    if not beat_schedule:
        print("  No periodic tasks configured in beat_schedule.")
    else:
        for name, config in beat_schedule.items():
            print(f"  - {name:<30}: Task={config['task']:<50} Schedule={config['schedule']}")

    print("-" * 60)

    # 5. Trigger task trial if workers are running
    if has_workers:
        print("5. Enqueuing test job discovery task...")
        # linkedin, Software Engineer, Remote
        task_res = run_job_discovery.delay("linkedin", "Software Engineer", "Remote")
        print(f"  Task enqueued. Task ID: {task_res.id}")
        print("  Waiting for execution results (up to 10 seconds)...")
        
        start_time = time.time()
        completed = False
        while time.time() - start_time < 10.0:
            if task_res.ready():
                print(f"  [OK] Task finished successfully! Status: {task_res.status}")
                print(f"  Task Return Value: {task_res.result}")
                completed = True
                break
            time.sleep(0.5)
            
        if not completed:
            print("  [TIMEOUT] Task enqueued but did not complete within 10s.")
            print("            Is the worker busy, or did it crash?")
    else:
        print("5. Task execution skipped because no active workers are online.")
        print("   If you want to test task execution, start the worker first!")
    print("=" * 60)

if __name__ == "__main__":
    debug_celery()
