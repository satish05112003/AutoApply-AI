import subprocess
import sys
import time
import os

dependencies = [
    "numpy",
    "pandas",
    "sklearn",
    "lightgbm",
    "xgboost",
    "sentence_transformers",
    "transformers",
    "torch"
]

def run_import_test(dep):
    # Construct a Python command to execute in a subprocess.
    code = f"""
import sys
import time
import os
import ctypes

class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]

def get_memory():
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        pass
    try:
        GetProcessMemoryCounters = ctypes.windll.psapi.GetProcessMemoryCounters
        GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if GetProcessMemoryCounters(GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return 0.0

start_mem = get_memory()
start_time = time.time()
try:
    import {dep}
    end_time = time.time()
    end_mem = get_memory()
    duration = end_time - start_time
    mem_used = end_mem - start_mem
    print(f"RESULT:SUCCESS:{{duration:.4f}}:{{mem_used:.2f}}:{{end_mem:.2f}}")
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=25
        )
        return result
    except subprocess.TimeoutExpired as te:
        return te

def main():
    print("=" * 60)
    print("AutoApply AI: OpenBLAS Diagnostic & Dependency Import Test")
    print(f"Running using Python interpreter: {sys.executable}")
    print("=" * 60)
    
    # Check if thread limiting is currently active in the environment
    env_vars = ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]
    print("Current Environment Thread Limits:")
    for var in env_vars:
        print(f"  {var}: {os.environ.get(var, 'NOT SET')}")
    print("-" * 60)

    for dep in dependencies:
        print(f"Testing import: {dep}...", end="", flush=True)
        res = run_import_test(dep)
        
        if isinstance(res, subprocess.TimeoutExpired):
            print("\n  [FAIL] Import timed out after 25 seconds.")
        else:
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()
            
            if res.returncode == 0 and "RESULT:SUCCESS" in stdout:
                parts = stdout.split(":")
                # SUCCESS:duration:mem_used:end_mem
                # Parts: ['RESULT', 'SUCCESS', duration, mem_used, end_mem]
                duration = float(parts[2])
                mem_used = float(parts[3])
                end_mem = float(parts[4])
                print(f" [OK] (Time: {duration:.3f}s | Delta Mem: {mem_used:+.1f} MB | Total Mem: {end_mem:.1f} MB)")
            else:
                print(" [FAIL]")
                print(f"  Exit code: {res.returncode}")
                if stdout:
                    print("  STDOUT:")
                    print("\n".join(f"    | {line}" for line in stdout.splitlines()))
                if stderr:
                    print("  STDERR:")
                    print("\n".join(f"    | {line}" for line in stderr.splitlines()))
        print("-" * 60)

if __name__ == "__main__":
    main()
