"""No-Home-Assistant dependency tests for error grouping and rate limits."""
from datetime import datetime, timedelta, timezone
import sys
from copy import deepcopy
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize

T0 = datetime(2026, 11, 8, 9, 10, tzinfo=timezone.utc)
INITIAL = timedelta(minutes=2)
COOLDOWN = timedelta(minutes=60)
REPEAT = timedelta(hours=24)


def error(name="homeassistant", msg="Task exception was never retrieved", exception="AttributeError: missing method"):
    return {"level": "ERROR", "name": name,
            "source": "custom_components/device_availability_digest/__init__.py:297",
            "message": [msg], "exception": f"Traceback...\n{exception}"}


class DigestTests(unittest.TestCase):
    def test_9539_duplicates_generate_one_group_and_one_initial_email(self):
        state = ErrorDigestState()
        for _ in range(9539):
            state.observe(error(), T0)
        self.assertEqual(len(state.groups), 1)
        self.assertFalse(state.ready(T0+timedelta(minutes=1), INITIAL, COOLDOWN, REPEAT))
        batch = state.ready(T0+timedelta(minutes=2), INITIAL, COOLDOWN, REPEAT)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0][1]["unreported"], 9539)
        title, message = summarize(batch)
        self.assertIn("9539 ERROR", title)
        state.acknowledge(batch, T0+timedelta(minutes=2))
        self.assertFalse(state.ready(T0+timedelta(minutes=3), INITIAL, COOLDOWN, REPEAT))

    def test_repeat_is_suppressed_for_24_hours(self):
        state = ErrorDigestState()
        state.observe(error(), T0)
        batch = state.ready(T0+INITIAL, INITIAL, COOLDOWN, REPEAT)
        state.acknowledge(batch, T0+INITIAL)
        for i in range(1000):
            state.observe(error(), T0+timedelta(hours=1, seconds=i))
        self.assertEqual(len(state.groups), 1)
        self.assertFalse(state.ready(T0+timedelta(hours=23), INITIAL, COOLDOWN, REPEAT))
        self.assertEqual(state.ready(T0+timedelta(hours=24, minutes=2), INITIAL, COOLDOWN, REPEAT)[0][1]["unreported"],1000)

    def test_new_exception_waits_for_global_cooldown(self):
        state = ErrorDigestState()
        state.observe(error(), T0)
        state.acknowledge(state.ready(T0+INITIAL, INITIAL, COOLDOWN, REPEAT), T0+INITIAL)
        state.observe(error(exception="ValueError: new"), T0+timedelta(minutes=4))
        self.assertFalse(state.ready(T0+timedelta(minutes=8), INITIAL, COOLDOWN, REPEAT))
        self.assertEqual(len(state.ready(T0+timedelta(minutes=62), INITIAL, COOLDOWN, REPEAT)),1)

    def test_restart_retains_last_email_and_counts(self):
        state = ErrorDigestState()
        state.observe(error(), T0)
        state.acknowledge(state.ready(T0+INITIAL, INITIAL, COOLDOWN, REPEAT),T0+INITIAL)
        state.observe(error(), T0+timedelta(minutes=3))
        restored = ErrorDigestState(state.snapshot())
        self.assertEqual(next(iter(restored.groups.values()))["unreported"], 1)
        self.assertFalse(restored.ready(T0+timedelta(hours=2), INITIAL, COOLDOWN, REPEAT))

    def test_new_events_arriving_during_send_are_preserved(self):
        state = ErrorDigestState()
        state.observe(error(), T0)
        snapshot = deepcopy(state.ready(T0+INITIAL, INITIAL, COOLDOWN, REPEAT))
        state.observe(error(), T0+timedelta(minutes=3))
        state.acknowledge(snapshot, T0+timedelta(minutes=3))
        self.assertEqual(next(iter(state.groups.values()))["unreported"], 1)
        self.assertTrue(state.dirty)

    def test_many_distinct_errors_have_bounded_memory(self):
        state = ErrorDigestState()
        for index in range(300):
            state.observe(error(exception=f"ErrorCode: {index}"), T0)
        self.assertLessEqual(len(state.groups), 200)
        self.assertIn("other_ERROR", state.groups)

    def test_warnings_wait_for_daily_digest(self):
        state = ErrorDigestState()
        state.observe({**error(), "level": "WARNING"}, T0)
        self.assertFalse(state.ready(T0+timedelta(hours=23), INITIAL, COOLDOWN, REPEAT))
        batch = state.ready(T0+timedelta(hours=24), INITIAL, COOLDOWN, REPEAT)
        self.assertEqual(len(batch), 1)
        self.assertIn("1 WARNING", summarize(batch)[0])
        state.acknowledge(batch, T0+timedelta(hours=24))
        state.observe({**error(), "level": "WARNING"}, T0+timedelta(hours=25))
        self.assertFalse(state.ready(T0+timedelta(hours=47), INITIAL, COOLDOWN, REPEAT))
        self.assertEqual(len(state.ready(T0+timedelta(hours=49), INITIAL, COOLDOWN, REPEAT)), 1)

    def test_pending_warnings_join_an_error_digest(self):
        state = ErrorDigestState()
        state.observe({**error(), "level": "WARNING"}, T0)
        state.observe(error(exception="RuntimeError: urgent"), T0+timedelta(minutes=1))
        batch = state.ready(T0+timedelta(minutes=3), INITIAL, COOLDOWN, REPEAT)
        self.assertEqual({g["level"] for _, g in batch}, {"ERROR", "WARNING"})

    def test_monitor_error_does_not_recurse(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(error(name="custom_components.log_error_digest"), T0))
        self.assertFalse(state.groups)

    def test_failed_send_can_retry_without_clearing_events(self):
        state = ErrorDigestState()
        state.observe(error(), T0)
        state.mark_failed(T0+INITIAL)
        self.assertFalse(state.ready(T0+timedelta(minutes=4), INITIAL, COOLDOWN, REPEAT))
        self.assertEqual(len(state.ready(T0+timedelta(minutes=7), INITIAL, COOLDOWN, REPEAT)),1)

    def test_different_exception_lines_produce_different_groups(self):
        state = ErrorDigestState()
        state.observe(error(exception="AttributeError: area"), T0)
        state.observe(error(exception="TimeoutError: connection"), T0)
        self.assertEqual(len(state.groups),2)


if __name__ == "__main__":
    unittest.main()
