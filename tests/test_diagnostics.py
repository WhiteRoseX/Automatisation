import io
import logging
import unittest
from telepilot.diagnostics import log_exception


class PrivateTracebackTests(unittest.TestCase):
    def test_chained_trace_has_every_frame_but_no_secret_messages_locals_or_notes(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("telepilot")
        logger.addHandler(handler)
        try:
            def inner():
                api_id = "fake-api-id-secret"
                api_hash = "fake-api-hash-secret"
                password = "fake-password-secret"
                code = "fake-code-secret"
                session = b"fake-session-secret"
                raise TypeError(api_id, api_hash, password, code, session)

            def outer():
                try:
                    inner()
                except TypeError as cause:
                    error = RuntimeError("fake-phone-secret")
                    error.add_note("fake-note-secret")
                    raise error from cause

            try:
                outer()
            except Exception as exc:
                log_exception(exc, "configure")
            output = stream.getvalue()
            for name in ("inner", "outer", "test_chained_trace", "TypeError", "RuntimeError", "Caused by", "line"):
                self.assertIn(name, output)
            for secret in ("fake-api-id-secret", "fake-api-hash-secret", "fake-password-secret", "fake-code-secret", "fake-session-secret", "fake-phone-secret", "fake-note-secret"):
                self.assertNotIn(secret, output)
        finally:
            logger.removeHandler(handler)
            handler.close()

