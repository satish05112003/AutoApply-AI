#!/bin/bash

# AutoApply AI - Local Development Startup Script (Linux)

get_free_port() {
    local start_port=$1
    python3 -c "
import socket
port = $start_port
while port <= 65535:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            print(port)
            break
        except OSError:
            port += 1
"
}

echo "=========================================="
echo "      AutoApply AI Startup System         "
echo "=========================================="

# 1. Detect ports
echo "[System] Scanning for available ports..."
BACKEND_PORT=$(get_free_port 8000)
FRONTEND_PORT=$(get_free_port 3000)

echo "[System] Backend selected port:  $BACKEND_PORT"
echo "[System] Frontend selected port: $FRONTEND_PORT"

# 2. Update frontend env configuration
FRONTEND_DIR="$(pwd)/frontend"
if [ -d "$FRONTEND_DIR" ]; then
    ENV_FILE="$FRONTEND_DIR/.env.local"
    echo "[System] Writing frontend environment config to $ENV_FILE"
    echo "NEXT_PUBLIC_API_URL=http://localhost:$BACKEND_PORT/api/v1" > "$ENV_FILE"
    echo "NEXT_PUBLIC_WS_URL=ws://localhost:$BACKEND_PORT" >> "$ENV_FILE"
fi

# 3. Start Backend in background
echo "[System] Launching FastAPI Backend Service..."
BACKEND_DIR="$(pwd)/backend"
if [ -d "$BACKEND_DIR" ]; then
    cd "$BACKEND_DIR"
    export BACKEND_PORT=$BACKEND_PORT
    export FRONTEND_URL="http://localhost:$FRONTEND_PORT"
    # Launch in background
    ./venv/bin/python start.py &
    BACKEND_PID=$!
    
    # Launch Celery background worker
    echo "[System] Launching Celery background worker..."
    ./venv/bin/celery -A app.celery_app.celery_app worker --loglevel=info &
    WORKER_PID=$!
    
    # Launch Celery background periodic scheduler
    echo "[System] Launching Celery periodic beat scheduler..."
    ./venv/bin/celery -A app.celery_app.celery_app beat --loglevel=info &
    BEAT_PID=$!
    
    cd ..
    
    # Configure exit trap to kill backend, worker, and beat background processes
    trap "echo '[System] Shutting down backend, worker, and beat...'; kill $BACKEND_PID $WORKER_PID $BEAT_PID 2>/dev/null" EXIT
else
    echo "Error: Backend directory not found!"
    exit 1
fi

# 4. Wait for backend to warm up
sleep 2

# 5. Open browser if possible
echo "[System] Launching dashboard browser..."
if command -v xdg-open > /dev/null; then
    xdg-open "http://localhost:$FRONTEND_PORT" &
elif command -v open > /dev/null; then
    open "http://localhost:$FRONTEND_PORT" &
fi

# 6. Start Frontend in foreground
echo "[System] Starting Next.js Dev Server..."
if [ -d "$FRONTEND_DIR" ]; then
    cd "$FRONTEND_DIR"
    export PORT=$FRONTEND_PORT
    npm run dev -- -p $FRONTEND_PORT
else
    echo "Error: Frontend directory not found!"
    exit 1
fi
