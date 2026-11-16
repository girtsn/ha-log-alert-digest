"""Regression tests for FGLair coordinator duplicate errors and cloud correlation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize

T0 = datetime(2026, 11, 16, 12, 0, 12, tzinfo=timezone.utc)
WARNING_MESSAGE = "Failed to update coordinator data: FGLairBaseException has been raised"
ERROR_MESSAGE = "Error fetching fglair_heatpump_controller data:"
CLOUD_MESSAGE = (
    "Timeout error fetching information from "
    "https://ads-field-eu.aylanetworks.com/apiv1/devices.json -"
)


def warning(**changes):
    event = {
        "level": "WARNING",
        "name": "custom_components.fglair_heatpump_controller",
        "source": "custom_components/fglair_heatpump_controller/__init__.py:82",
        "message": [WARNING_MESSAGE],
        "exception": "",
    }
    event.update(changes)
    return event


def error(**changes):
    event = {
        "level": "ERROR",
        "name": "custom_components.fglair_heatpump_controller",
        "source": "helpers/update_coordinator.py:527",
        "message": [ERROR_MESSAGE],
        "exception": "",
    }
    event.update(changes)
    return event


def cloud_error():
    return {
        "level": "ERROR",
        "name": "pyfujitsugeneral",
        "source": "custom_components/fglair_heatpump_controller/__init__.py:80",
        "message": [CLOUD_MESSAGE],
        "exception": "",
    }


class FujitsuCoordinatorTests(unittest.TestCase):
    def test_observed_pair_without_root_cause_keeps_only_actionable_error(self):
        state = ErrorDigestState()
        self.assertTrue(state.observe(warning(), T0))
        self.assertTrue(state.observe(error(), T0 + timedelta(microseconds=66)))
        self.assertEqual(len(state.groups), 1)
        only = next(iter(state.groups.values()))
        self.assertEqual(only["level"], "ERROR")
        self.assertEqual(only["message"], ERROR_MESSAGE)
        self.assertEqual(state.ignored["fujitsu_coordinator_duplicate_warning"]["pending"], 1)
        self.assertFalse(state.pending_ignored(include_count_only=False))
        title, message = summarize(list(state.groups.items()), state.pending_ignored())
        self.assertIn("1 ERROR(s), 0 WARNING(s)", title)
        self.assertIn("Duplicate Fujitsu coordinator warnings alongside errors: 1 WARNING", message)

    def test_reverse_order_and_standard_source_encodings(self):
        state = ErrorDigestState()
        self.assertTrue(state.observe(error(source=("helpers/update_coordinator.py", 527)), T0))
        self.assertFalse(state.observe(warning(
            source="custom_components/fglair_heatpump_controller/__init__.py 82"
        ), T0 + timedelta(milliseconds=3)))
        self.assertEqual(len(state.groups), 1)
        self.assertEqual(state.ignored["fujitsu_coordinator_duplicate_warning"]["pending"], 1)

    def test_known_ayla_failure_explains_both_coordinator_messages(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(cloud_error(), T0))
        self.assertFalse(state.observe(warning(), T0 + timedelta(seconds=1)))
        self.assertFalse(state.observe(error(), T0 + timedelta(seconds=1, microseconds=66)))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        self.assertEqual(state.ignored["fujitsu_ayla_coordinator_warning"]["pending"], 1)
        self.assertEqual(state.ignored["fujitsu_ayla_coordinator_error"]["pending"], 1)
        self.assertFalse(state.pending_ignored(include_count_only=False))
        self.assertFalse(state.ignored_due(T0 + timedelta(days=3), timedelta(hours=1)))

    def test_cause_between_warning_and_error_migrates_warning_to_noise(self):
        state = ErrorDigestState()
        self.assertTrue(state.observe(warning(), T0))
        self.assertFalse(state.observe(cloud_error(), T0 + timedelta(milliseconds=20)))
        self.assertFalse(state.observe(error(), T0 + timedelta(milliseconds=50)))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_coordinator_warning"]["pending"], 1)
        self.assertEqual(state.ignored["fujitsu_ayla_coordinator_error"]["pending"], 1)
        self.assertNotIn("fujitsu_coordinator_duplicate_warning", state.ignored)

    def test_unexplained_or_lonely_coordinator_failure_is_actionable(self):
        state = ErrorDigestState()
        self.assertTrue(state.observe(warning(), T0))
        self.assertEqual(len(state.groups), 1)
        self.assertFalse(state.ignored)
        self.assertTrue(state.observe(error(), T0 + timedelta(seconds=31)))
        self.assertEqual(len(state.groups), 2)
        self.assertFalse(state.ignored)

    def test_cloud_correlation_expires_in_thirty_seconds(self):
        state = ErrorDigestState()
        state.observe(cloud_error(), T0)
        self.assertTrue(state.observe(error(), T0 + timedelta(seconds=31)))
        self.assertNotIn("fujitsu_ayla_coordinator_error", state.ignored)

    def test_wrong_sources_levels_exceptions_or_messages_are_never_hidden(self):
        cases = [
            warning(level="ERROR"),
            warning(name="unrelated.module"),
            warning(source="custom_components/other/__init__.py:82"),
            warning(source="custom_components/fglair_heatpump_controller/__init__.py.bak:82"),
            warning(message=["Failed to update coordinator data: AuthenticationException"]),
            warning(exception="RuntimeError: unrelated"),
            error(level="WARNING"),
            error(name="homeassistant.helpers.update_coordinator"),
            error(source="custom_components/fglair_heatpump_controller/__init__.py:82"),
            error(message=["Error fetching other_integration data:"]),
            error(exception="KeyError: unexpected"),
        ]
        for case in cases:
            with self.subTest(case=case):
                state = ErrorDigestState()
                state.observe(cloud_error(), T0)
                self.assertTrue(state.observe(case, T0 + timedelta(seconds=1)))
                self.assertEqual(len(state.groups), 1)

    def test_saved_pair_migrates_only_unreported_warning_not_historical_total(self):
        ts = T0.isoformat()
        stored = {"groups": {
            "old_warning": {
                "level": "WARNING", "logger": warning()["name"],
                "source": "custom_components/fglair_heatpump_controller/__init__.py 82",
                "message": WARNING_MESSAGE, "exception": "",
                "first": (T0 - timedelta(days=5)).isoformat(), "last": ts,
                "total": 6, "unreported": 1, "pending_since": ts,
                "notified_at": (T0 - timedelta(days=1)).isoformat(),
            },
            "old_error": {
                "level": "ERROR", "logger": error()["name"],
                "source": "helpers/update_coordinator.py 527",
                "message": ERROR_MESSAGE, "exception": "",
                "first": (T0 - timedelta(days=5)).isoformat(), "last": ts,
                "total": 3, "unreported": 1, "pending_since": ts,
                "notified_at": (T0 - timedelta(days=1)).isoformat(),
            },
        }}
        state = ErrorDigestState(stored)
        self.assertIn("old_error", state.groups)
        self.assertEqual(state.groups["old_error"]["unreported"], 1)
        self.assertEqual(state.groups["old_warning"]["unreported"], 0)
        self.assertEqual(state.ignored["fujitsu_coordinator_duplicate_warning"]["total"], 1)
        self.assertTrue(state.dirty)
        restarted = ErrorDigestState(state.snapshot())
        self.assertEqual(restarted.ignored["fujitsu_coordinator_duplicate_warning"]["pending"], 1)
        self.assertFalse(restarted.dirty)

    def test_saved_pair_with_known_cloud_cause_migrates_both_pending_only(self):
        ts = T0.isoformat()
        state = ErrorDigestState({"groups": {
            "warn": {
                "level": "WARNING", "logger": warning()["name"],
                "source": warning()["source"], "message": WARNING_MESSAGE, "exception": "",
                "first": ts, "last": ts, "total": 6, "unreported": 1,
                "pending_since": ts, "notified_at": ts,
            },
            "err": {
                "level": "ERROR", "logger": error()["name"],
                "source": error()["source"], "message": ERROR_MESSAGE, "exception": "",
                "first": ts, "last": ts, "total": 3, "unreported": 1,
                "pending_since": ts, "notified_at": ts,
            },
        }, "ignored": {
            "fujitsu_ayla_timeout": {
                "level": "ERROR", "total": 2, "pending": 1,
                "pending_since": ts, "last": ts,
            },
        }})
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_coordinator_warning"]["pending"], 1)
        self.assertEqual(state.ignored["fujitsu_ayla_coordinator_error"]["pending"], 1)
        self.assertTrue(state.dirty)

    def test_multiple_older_warnings_are_not_all_assumed_duplicates(self):
        state = ErrorDigestState()
        self.assertTrue(state.observe(warning(), T0 - timedelta(minutes=6)))
        self.assertTrue(state.observe(warning(), T0))
        self.assertTrue(state.observe(error(), T0 + timedelta(milliseconds=1)))
        pending_warnings = [g for g in state.groups.values() if g["level"] == "WARNING"]
        self.assertEqual(len(pending_warnings), 1)
        self.assertEqual(pending_warnings[0]["unreported"], 1)
        self.assertEqual(state.ignored["fujitsu_coordinator_duplicate_warning"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
