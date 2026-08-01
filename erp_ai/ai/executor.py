"""
Single tool-execution entry point, used by both providers (claude.py and
gemini.py). Previously there were two near-identical copies of this dispatch
logic (erp_ai/ai/executor.py and erp_ai/ai/tool_executor.py) plus a third
inline copy inside providers/claude.py - this is now the only one.

Permission enforcement happens *inside* each tool function (via
tools/_security.py's check_permission), not here - this layer's job is just
safe dispatch and turning exceptions into a clean {"error": ...} payload the
model can read and explain to the user, instead of a raw traceback.
"""

import json
import frappe
from erp_ai.ai.registry import get_tool


def execute_tool(name: str, args: dict = None):
    args = args or {}

    tool = get_tool(name)
    if not tool or not tool.get("function"):
        return {"error": f"Tool '{name}' is not registered."}

    # Normalize args to plain JSON-safe Python values, in case the SDK
    # handed us SDK-specific wrapper types instead of plain dict/list/str.
    try:
        clean_args = json.loads(json.dumps(args, default=str))
    except Exception:
        clean_args = args

    try:
        return tool["function"](**clean_args)
    except TypeError as e:
        # Almost always means the model passed an argument the tool doesn't
        # accept, or omitted a required one.
        frappe.log_error(
            title=f"ERP AI Executor Argument Error ({name})",
            message=f"{frappe.get_traceback()}\n\nArgs received: {clean_args}",
        )
        return {"error": f"Invalid arguments for tool '{name}': {e}"}
    except frappe.PermissionError as e:
        return {"error": str(e) or f"Permission denied for tool '{name}'."}
    except Exception as e:
        frappe.log_error(title=f"ERP AI Executor Error ({name})", message=frappe.get_traceback())
        return {"error": str(e)}
