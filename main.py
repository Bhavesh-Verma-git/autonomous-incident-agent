"""
main.py — Entry point for the AIRP FastAPI service.

Usage:
    # Development (auto-reload on file changes):
    python main.py

    # Production (via uvicorn directly):
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2

The `app` object is exported at module level so uvicorn can find it
when you run `uvicorn main:app`.
"""

import uvicorn
import config
from api.app import create_app

# Export `app` at module level for `uvicorn main:app`
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host    = config.API_HOST,
        port    = config.API_PORT,
        reload  = config.API_DEBUG,   # True in dev: restarts on code changes
        log_level = "info",
    )
