import os
import socket
import sys
import uvicorn
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] autoapply_ai.start - %(message)s",
)
logger = logging.getLogger("autoapply_ai.start")

def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Check if the socket port is free on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False

def find_free_port(start_port: int, host: str = "127.0.0.1") -> int:
    """Increment port number until a free one is found."""
    port = start_port
    while port <= 65535:
        if is_port_free(port, host):
            return port
        logger.warning(f"Port {port} is occupied. Scanning next port...")
        port += 1
    raise RuntimeError("No free socket ports found.")

def update_frontend_env(backend_port: int):
    """Automatically update the frontend .env.local file with the active port without duplicate keys and BOM-safe."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Check parent and sibling directories
    paths_to_try = [
        os.path.abspath(os.path.join(base_dir, "../frontend")),
        os.path.abspath(os.path.join(base_dir, "frontend")),
        os.path.abspath(os.path.join(base_dir, "../../frontend"))
    ]
    
    frontend_dir = None
    for p in paths_to_try:
        if os.path.exists(p) and os.path.isdir(p):
            frontend_dir = p
            break
            
    if frontend_dir:
        env_file = os.path.join(frontend_dir, ".env.local")
        logger.info(f"Dynamically writing port config to {env_file}")
        
        content = ""
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8-sig") as f:
                content = f.read()
                
        lines = content.splitlines()
        api_key = "NEXT_PUBLIC_API_URL"
        ws_key = "NEXT_PUBLIC_WS_URL"
        api_val = f"NEXT_PUBLIC_API_URL=http://localhost:{backend_port}/api/v1"
        ws_val = f"NEXT_PUBLIC_WS_URL=ws://localhost:{backend_port}"
        
        updated_keys = set()
        new_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
                
            if "=" in stripped:
                parts = stripped.split("=", 1)
                k = parts[0].strip()
                if k == api_key:
                    if api_key not in updated_keys:
                        new_lines.append(api_val)
                        updated_keys.add(api_key)
                elif k == ws_key:
                    if ws_key not in updated_keys:
                        new_lines.append(ws_val)
                        updated_keys.add(ws_key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        if api_key not in updated_keys:
            new_lines.append(api_val)
        if ws_key not in updated_keys:
            new_lines.append(ws_val)
            
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        logger.info(f"Frontend .env.local updated: NEXT_PUBLIC_API_URL=http://localhost:{backend_port}/api/v1")
    else:
        logger.warning("Could not automatically locate frontend directory to write .env.local")

def main():
    # Read host and port from env overrides (if provided by docker-compose)
    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    
    # Auto-adjust host binding inside Docker container context
    is_docker = os.path.exists("/.dockerenv")
    if is_docker:
        host = "0.0.0.0"
        
    port_env = os.environ.get("BACKEND_PORT", "8000")
    try:
        start_port = int(port_env)
    except ValueError:
        start_port = 8000
        
    logger.info(f"Checking socket availability on host={host}, starting from port={start_port}")
    
    # Inside docker containers, the bind checks should run against 0.0.0.0 if that's the exposing target
    bind_check_host = "0.0.0.0" if is_docker or host == "0.0.0.0" else host
    
    try:
        port = find_free_port(start_port, bind_check_host)
    except Exception as e:
        logger.error(f"Error finding free port: {e}")
        sys.exit(1)
        
    logger.info(f"Selected Port: {port} (Status: ACTIVE)")
    
    # Expose variables to sub-configurations
    os.environ["BACKEND_PORT"] = str(port)
    os.environ["FRONTEND_URL"] = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    
    # Update local NextJS env configurations
    try:
        update_frontend_env(port)
    except Exception as e:
        logger.warning(f"Frontend env sync skipped: {e}")
        
    # Start FastAPI / Uvicorn server programmatically
    # Disable reload in docker/production context
    reload_mode = not is_docker and os.environ.get("BACKEND_RELOAD", "true").lower() == "true"
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload_mode
    )

if __name__ == "__main__":
    main()
