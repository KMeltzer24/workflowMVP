"""Flask application factory.

Gunicorn entry: ``gunicorn workflowmvp.app:app``
"""

from __future__ import annotations

import os
import warnings
from importlib.resources import files

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from workflowmvp.blueprints.codegen import bp as codegen_bp
from workflowmvp.blueprints.meta import bp as meta_bp
from workflowmvp.blueprints.pages import bp as pages_bp
from workflowmvp.blueprints.planning import bp as planning_bp
from workflowmvp.blueprints.run import bp as run_bp
from workflowmvp.http import enforce_same_origin_post, max_upload_mb

load_dotenv()

os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_TRACE", "")
os.environ.setdefault("GLOG_minloglevel", "2")

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*LibreSSL.*",
)


def create_app() -> Flask:
    web_dir = files("web")
    application = Flask(
        __name__,
        template_folder=str(web_dir / "templates"),
        static_folder=str(web_dir / "static"),
    )
    upload_mb = max_upload_mb()
    application.config["MAX_CONTENT_LENGTH"] = upload_mb * 1024 * 1024

    @application.errorhandler(413)
    def _too_large(_err):  # pragma: no cover - exercised manually
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        f"Upload exceeds the {upload_mb} MB limit. "
                        "Trim the recording or raise WORKFLOW_MAX_UPLOAD_MB."
                    ),
                }
            ),
            413,
        )

    @application.before_request
    def _enforce_same_origin_posts():
        return enforce_same_origin_post(request)

    application.register_blueprint(pages_bp)
    application.register_blueprint(meta_bp)
    application.register_blueprint(planning_bp)
    application.register_blueprint(codegen_bp)
    application.register_blueprint(run_bp)
    return application


app = create_app()
