"""Regression tests for intermediate FGLair retry warning suppression."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize

T0 = datetime(2026, 11, 14, 6, 29, 27, tzinfo=timezone.utc)
RETRY_FIRST = "API call failed (attempt 1/3): FGLairBaseException has been raised. Retrying in 1.0s..."
RETRY_SECOND = "API call failed (attempt 2/3): FGLairBaseException has been raised. Retrying in 2.0s..."


def retry_event(message=RETRY_FIRST, **changed):
    event = {
        "level": "WARNING",
        "name": "custom_components.fglair_heatpump_controller.climate",
        "source": "custom_components/fglair_heatpump_controller/climate.py:85",
        "message": [message],
        "exception": "",
    }
    event.update(changed)
    return event


class FujitsuFglairRetryTests(unittest.TestCase):
    def test_intermediate_retries_are_counted_without_alerting(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(retry_event(), T0))
        self.assertFalse(state.observe(retry_event(RETRY_SECOND), T0 + timedelta(seconds=1)))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_api_retry"]["total"], 2)
        self.assertEqual(state.ignored["fujitsu_api_retry"]["pending"], 2)
        self.assertFalse(state.pending_ignored(include_count_only=False))
        self.assertFalse(state.ignored_due(T0 + timedelta(days=10), timedelta(hours=1)))
        _, report = summarize([], state.pending_ignored())
        self.assertIn("Fujitsu FGLair automatic API retry warnings: 2 WARNING(s)", report)

    def test_source_from_digest_and_tuple_format_match(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(retry_event(
            source="custom_components/fglair_heatpump_controller/climate.py 85",
        ), T0))
        self.assertFalse(state.observe(retry_event(
            source=("custom_components/fglair_heatpump_controller/climate.py", 85),
        ), T0))
        self.assertEqual(state.ignored["fujitsu_api_retry"]["pending"], 2)

    def test_final_failures_and_different_exceptions_remain_actionable(self):
        cases = (
            retry_event("API call failed (attempt 3/3): FGLairBaseException has been raised. Retrying in 3.0s..."),
            retry_event("API call failed (attempt 1/4): FGLairBaseException has been raised. Retrying in 1.0s..."),
            retry_event("API call failed (attempt 1/3): AuthenticationException has been raised. Retrying in 1.0s..."),
            retry_event("API call failed (attempt 1/3): FGLairBaseException has been raised. Giving up."),
            retry_event("API call failed (attempt 1/3): FGLairBaseException has been raised. Retrying in never..."),
            retry_event(level="ERROR"),
            retry_event(name="unrelated.module"),
            retry_event(source="custom_components/fglair_heatpump_controller/__init__.py:85"),
            retry_event(source="custom_components/fglair_heatpump_controller/climate.py.bak:85"),
            retry_event(exception="Traceback (most recent call last):\nRuntimeError: something else"),
        )
        for case in cases:
            with self.subTest(case=case):
                state = ErrorDigestState()
                self.assertTrue(state.observe(case, T0))
                self.assertEqual(len(state.groups), 1)
                self.assertFalse(state.ignored)

    def test_pending_historical_warning_migrates_but_previously_reported_does_not(self):
        old = {"groups": {"old_retry": {
            "level": "WARNING",
            "logger": "custom_components.fglair_heatpump_controller.climate",
            "source": "custom_components/fglair_heatpump_controller/climate.py 85",
            "message": RETRY_FIRST, "exception": "",
            "first": (T0 - timedelta(days=3)).isoformat(),
            "last": T0.isoformat(),
            "total": 21, "unreported": 1,
            "pending_since": T0.isoformat(), "notified_at": T0.isoformat(),
        }}}
        state = ErrorDigestState(old)
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_api_retry"]["pending"], 1)
        self.assertEqual(state.ignored["fujitsu_api_retry"]["total"], 1)
        self.assertTrue(state.dirty)

    def test_after_restart_it_remains_count_only(self):
        state = ErrorDigestState()
        state.observe(retry_event(), T0)
        restored = ErrorDigestState(state.snapshot())
        self.assertFalse(restored.observe(retry_event(), T0 + timedelta(seconds=10)))
        self.assertEqual(restored.ignored["fujitsu_api_retry"]["pending"], 2)


if __name__ == "__main__":
    unittest.main()
