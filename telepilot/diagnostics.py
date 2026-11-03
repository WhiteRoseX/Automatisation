"""Trace every exception frame without serializing request data or locals.

Exception messages, source lines and locals may contain API keys, phone numbers,
codes, passwords or session bytes. Deliberately omit them, including on chained
exceptions, while retaining the complete call stack and exception classes.
"""

import logging
import traceback
from pathlib import Path


def safe_traceback(error):
    lines = []
    seen = set()
    root = Path(__file__).resolve().parent.parent

    def visit(exc):
        if id(exc) in seen:
            return
        seen.add(id(exc))
        if exc.__cause__ is not None:
            visit(exc.__cause__)
            lines.append("Caused by:")
        elif exc.__context__ is not None and not exc.__suppress_context__:
            visit(exc.__context__)
            lines.append("During handling of the above exception:")
        lines.append("Traceback (most recent call last; values omitted):")
        for frame, lineno in traceback.walk_tb(exc.__traceback__):
            path = Path(frame.f_code.co_filename)
            try:
                filename = str(path.resolve().relative_to(root))
            except ValueError:
                # Do not disclose a private data path embedded in an exception.
                filename = (
                    "<external>/" + path.name if path.suffix == ".py" else "<external>"
                )
            lines.append(
                f'  File "{filename}", line {lineno}, in {frame.f_code.co_name}'
            )
        lines.append(f"{type(exc).__name__}: [exception message omitted for privacy]")
        if isinstance(exc, BaseExceptionGroup):
            for child in exc.exceptions:
                visit(child)

    visit(error)
    return "\n".join(lines)


def log_exception(error, operation="operation"):
    # Operations are code constants, never values supplied as command arguments.
    allowed = {
        "restore_session",
        "configure",
        "request_code",
        "sign_in",
        "logout",
        "reset_auth",
        "watch",
        "auto_import",
        "import",
        "snapshot",
        "worker",
        "shutdown",
        "keychain",
        "operation",
    }
    operation = operation if operation in allowed else "operation"
    logging.getLogger("telepilot").error(
        "Failure during %s\n%s", operation, safe_traceback(error)
    )
