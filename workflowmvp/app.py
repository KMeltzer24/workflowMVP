"""WSGI import path for Flask app.

Provides a stable app module path for production servers:
`gunicorn workflowmvp.app:app`
"""

from main import app

__all__ = ["app"]
