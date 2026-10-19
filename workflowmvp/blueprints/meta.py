from __future__ import annotations

from flask import Blueprint, jsonify

from workflowmvp.http import json_internal_error
from workflowmvp.services.examples import list_examples
from workflowmvp.tools import ToolRegistry

bp = Blueprint("meta", __name__)


@bp.route("/api/tools")
def get_tools():
    try:
        registry = ToolRegistry()
        return jsonify(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.param_descriptions(),
                    "required": tool.required_params(),
                    "category": tool.category,
                }
                for tool in registry.list_tools()
            ]
        )
    except Exception as exc:
        return json_internal_error(exc)


@bp.route("/api/examples")
def get_examples():
    try:
        return jsonify(list_examples())
    except Exception as exc:
        return json_internal_error(exc)
