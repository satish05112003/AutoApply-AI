import os
import socket
import pytest
from fastapi.testclient import TestClient

from start import is_port_free, find_free_port
from app.main import app

client = TestClient(app)

def test_is_port_free_functional():
    """Verify that is_port_free correctly identifies open vs bound ports."""
    # Find an open port
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_socket.bind(("127.0.0.1", 0))  # OS binds to random free port
    bound_port = test_socket.getsockname()[1]
    
    # Check that this bound port is NOT free
    assert is_port_free(bound_port, "127.0.0.1") is False
    
    # Close it
    test_socket.close()
    
    # Now it should be free
    assert is_port_free(bound_port, "127.0.0.1") is True

def test_find_free_port_functional():
    """Verify that find_free_port skips occupied ports."""
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_socket.bind(("127.0.0.1", 0))
    bound_port = test_socket.getsockname()[1]
    
    # If we check starting from bound_port, it should return bound_port + 1 (or next free)
    free_port = find_free_port(bound_port, "127.0.0.1")
    assert free_port > bound_port
    assert is_port_free(free_port, "127.0.0.1") is True
    
    test_socket.close()

def test_cors_middleware_regex():
    """Verify that CORSMiddleware allows dynamic ports on localhost for development."""
    test_origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3005",
        "http://localhost:9999",
        "http://127.0.0.1:4000",
        "https://localhost:443",
    ]
    
    for origin in test_origins:
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            }
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin

def test_cors_middleware_invalid_origins():
    """Verify that non-localhost invalid origins are rejected."""
    invalid_origins = [
        "http://malicious-site.com",
        "http://local-fakehost.com:3000",
    ]
    
    for origin in invalid_origins:
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            }
        )
        assert response.headers.get("access-control-allow-origin") is None

def test_health_endpoint():
    """Verify that backend Health status endpoint is responsive."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
