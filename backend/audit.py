"""
Audit module for MSRIT AI.
Provides compliance logging to the audit_log table and an @audited decorator for tool calls.
"""
from typing import Optional, Dict, Any, Callable
import sys
import functools
import inspect
import psycopg2.extras
from db.connection import get_connection


def log_action(
    tool_name: str,
    student_id: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    result_summary: str = "",
    success: bool = True
) -> None:
    """
    Log an action or tool invocation into the audit_log table.
    Failures are caught and logged to stderr without crashing the caller.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        param_json = psycopg2.extras.Json(parameters if parameters is not None else {})
        cur.execute(
            """
            INSERT INTO audit_log (tool_name, student_id, parameters, result_summary, success)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (tool_name, student_id, param_json, str(result_summary)[:500], success)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Warning: Audit logging failed for {tool_name}: {e}", file=sys.stderr)


def _summarize_result(result: Any) -> str:
    """Helper to generate a concise summary of a function's return value."""
    if result is None:
        return "None"
    if isinstance(result, list):
        return f"List with {len(result)} items"
    if isinstance(result, dict):
        keys = list(result.keys())
        return f"Dict with keys: {keys}"
    return str(result)[:200]


def audited(tool_name: str):
    """
    Decorator to audit tool invocations.
    Records parameters and execution outcome into audit_log.
    Supports both synchronous and asynchronous functions.
    """
    def decorator(func: Callable):
        sig = inspect.signature(func)

        def _extract_args(args, kwargs):
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)
            # Find student_id if present
            student_id = params.get("student_id")
            # Don't serialize non-serializable objects in params
            cleaned_params = {}
            for k, v in params.items():
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    cleaned_params[k] = v
                else:
                    cleaned_params[k] = str(v)
            return student_id, cleaned_params

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                student_id, params = _extract_args(args, kwargs)
                try:
                    res = await func(*args, **kwargs)
                    log_action(
                        tool_name=tool_name,
                        student_id=student_id,
                        parameters=params,
                        result_summary=_summarize_result(res),
                        success=True
                    )
                    return res
                except Exception as exc:
                    log_action(
                        tool_name=tool_name,
                        student_id=student_id,
                        parameters=params,
                        result_summary=f"Exception: {str(exc)}",
                        success=False
                    )
                    raise
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                student_id, params = _extract_args(args, kwargs)
                try:
                    res = func(*args, **kwargs)
                    log_action(
                        tool_name=tool_name,
                        student_id=student_id,
                        parameters=params,
                        result_summary=_summarize_result(res),
                        success=True
                    )
                    return res
                except Exception as exc:
                    log_action(
                        tool_name=tool_name,
                        student_id=student_id,
                        parameters=params,
                        result_summary=f"Exception: {str(exc)}",
                        success=False
                    )
                    raise
            return sync_wrapper

    return decorator
