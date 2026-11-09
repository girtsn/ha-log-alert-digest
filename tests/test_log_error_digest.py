"""No-Home-Assistant dependency tests for error grouping and rate limits."""
from datetime import datetime, timedelta, timezone
import sys
from copy import deepcopy
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize

T0 = datetime(2026, 11, 8, 9, 10, tzinfo=timezone.utc)
CUSTOM_INTEGRATION_NOTICE = (
    "We found a custom integration {} which has not been tested by Home Assistant. "
    "This component might cause stability problems, be sure to disable it "
    "if you experience issues with Home Assistant"
)
FUJITSU_TIMEOUT = (
    "Timeout error fetching information from "
    "https://ads-field-eu.aylanetworks.com/apiv1/dsns/AC000W002919187/properties.json -"
)
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

    def test_standard_custom_integration_notices_are_ignored(self):
        state = ErrorDigestState()
        for domain in ("resmed_myair", "ps3", "other_custom_integration"):
            accepted = state.observe({
                "level": "WARNING",
                "name": "homeassistant.loader",
                "source": "loader.py:833",
                "message": [CUSTOM_INTEGRATION_NOTICE.format(domain)],
                "exception": "",
            }, T0)
            self.assertFalse(accepted)
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["untested_custom_integration"]["pending"], 3)
        self.assertTrue(state.dirty)

    def test_other_loader_warnings_and_real_errors_are_retained(self):
        state = ErrorDigestState()
        notice = CUSTOM_INTEGRATION_NOTICE.format("ps3")
        for level, logger, message in (
            ("WARNING", "homeassistant.loader", "Could not load custom integration ps3"),
            ("ERROR", "homeassistant.loader", notice),
            ("WARNING", "custom_components.ps3", notice),
            ("WARNING", "homeassistant.loader", notice + " Unexpected extra details"),
        ):
            self.assertTrue(state.observe({
                "level": level, "name": logger,
                "source": "loader.py:833", "message": [message],
            }, T0))
        self.assertEqual(len(state.groups), 4)

    def test_upgrade_drops_previous_notice_groups_but_keeps_other_warnings(self):
        state = ErrorDigestState()
        state.observe({
            "level": "WARNING", "name": "homeassistant.loader",
            "source": "loader.py:833", "message": ["Other relevant loader warning"],
        }, T0)
        saved = state.snapshot()
        # Simulate a pending group persisted by the previous release.
        saved["groups"]["legacy_notice"] = {
            "level": "WARNING", "logger": "homeassistant.loader",
            "source": "loader.py:833",
            "message": CUSTOM_INTEGRATION_NOTICE.format("resmed_myair"),
            "exception": "", "last": T0.isoformat(), "unreported": 3,
        }
        restored = ErrorDigestState(saved)
        self.assertEqual(len(restored.groups), 1)
        self.assertTrue(restored.dirty)
        self.assertEqual(restored.ignored["untested_custom_integration"]["pending"], 3)
        self.assertEqual(next(iter(restored.groups.values()))["message"], "Other relevant loader warning")
        self.assertEqual(len(saved["groups"]), 2)

    def test_fujitsu_cloud_timeout_is_counted_not_reported_individually(self):
        state = ErrorDigestState()
        for i in range(7):
            self.assertFalse(state.observe({
                "level": "ERROR", "name": "pyfujitsugeneral",
                "source": "custom_components/fglair_heatpump_controller/climate.py:80",
                "message": [FUJITSU_TIMEOUT], "exception": "",
            }, T0 + timedelta(minutes=i)))
        self.assertFalse(state.groups)
        self.assertFalse(state.ready(T0 + INITIAL, INITIAL, COOLDOWN, REPEAT))
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 7)
        self.assertFalse(state.ignored_due(T0 + timedelta(hours=23), COOLDOWN))
        self.assertTrue(state.ignored_due(T0 + timedelta(hours=24), COOLDOWN))
        title, message = summarize([], state.pending_ignored())
        self.assertIn("7 ignored ERROR", title)
        self.assertIn("Fujitsu/Ayla cloud properties fetch timeouts: 7 ERROR", message)
        self.assertNotIn("AC000W002919187", message)

    def test_other_fujitsu_errors_and_unexpected_timeouts_remain_actionable(self):
        state = ErrorDigestState()
        for name, source, message, exception in (
            ("pyfujitsugeneral", "custom_components/fglair_heatpump_controller/climate.py:80",
             "Authentication failed fetching FGLair", ""),
            ("pyfujitsugeneral", "custom_components/fglair_heatpump_controller/climate.py:80",
             FUJITSU_TIMEOUT.replace("properties.json", "status.json"), ""),
            ("pyfujitsugeneral", "custom_components/another/climate.py:80", FUJITSU_TIMEOUT, ""),
            ("some_other_library", "custom_components/fglair_heatpump_controller/climate.py:80",
             FUJITSU_TIMEOUT, ""),
            ("pyfujitsugeneral", "custom_components/fglair_heatpump_controller/climate.py:80",
             FUJITSU_TIMEOUT, "TimeoutError: persistent failure"),
        ):
            self.assertTrue(state.observe({
                "level": "ERROR", "name": name, "source": source,
                "message": [message], "exception": exception,
            }, T0))
        self.assertEqual(len(state.groups), 5)

    def test_known_noise_summary_is_restart_safe_and_keeps_new_events(self):
        state = ErrorDigestState()
        event = {
            "level": "ERROR", "name": "pyfujitsugeneral",
            "source": "custom_components/fglair_heatpump_controller/climate.py:80",
            "message": [FUJITSU_TIMEOUT], "exception": "",
        }
        state.observe(event, T0)
        snapshot = deepcopy(state.pending_ignored())
        state.observe(event, T0 + timedelta(minutes=1))
        state.acknowledge_ignored(snapshot, T0 + timedelta(hours=24))
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        restored = ErrorDigestState(state.snapshot())
        self.assertEqual(restored.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        self.assertFalse(restored.ignored_due(T0 + timedelta(hours=25), COOLDOWN))
        self.assertTrue(restored.ignored_due(T0 + timedelta(hours=49), COOLDOWN))

    def test_daily_known_noise_summary_does_not_delay_real_errors(self):
        state = ErrorDigestState()
        state.observe({
            "level": "WARNING", "name": "homeassistant.loader",
            "source": "loader.py:833",
            "message": [CUSTOM_INTEGRATION_NOTICE.format("ps3")],
        }, T0)
        self.assertTrue(state.ignored_due(T0 + timedelta(hours=24), COOLDOWN))
        state.acknowledge_ignored(deepcopy(state.pending_ignored()), T0 + timedelta(hours=24))
        state.observe(error(), T0 + timedelta(hours=24, minutes=1))
        self.assertTrue(state.ready(T0 + timedelta(hours=24, minutes=3),
                                    INITIAL, COOLDOWN, REPEAT))
        self.assertFalse(state.ignored_due(T0 + timedelta(hours=25), COOLDOWN))

    def test_actionable_digest_contains_compact_ignored_summary(self):
        state = ErrorDigestState()
        state.observe(error(), T0)
        state.observe({
            "level": "WARNING", "name": "homeassistant.loader",
            "source": "loader.py:833",
            "message": [CUSTOM_INTEGRATION_NOTICE.format("ps3")],
        }, T0)
        batch = state.ready(T0 + INITIAL, INITIAL, COOLDOWN, REPEAT)
        title, message = summarize(batch, state.pending_ignored())
        self.assertIn("1 ERROR", title)
        self.assertIn("Known messages filtered from actionable alerts:", message)
        self.assertIn("Routine untested custom integration notices: 1 WARNING", message)
        state.acknowledge(batch, T0 + INITIAL)
        state.acknowledge_ignored(deepcopy(state.pending_ignored()), T0 + INITIAL)
        self.assertFalse(state.pending_ignored())

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
