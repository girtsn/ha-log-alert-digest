"""Regression tests for exact Fujitsu/Ayla device-list DNS resolver timeouts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize

T0 = datetime(2026, 11, 12, 11, 35, 34, tzinfo=timezone.utc)
DEVICES_URL = "https://ads-field-eu.aylanetworks.com/apiv1/devices.json"
DNS_FAILURE = (
    f"Error fetching information from {DEVICES_URL} - "
    "Cannot connect to host ads-field-eu.aylanetworks.com:443 "
    "ssl:default [Timeout while contacting DNS servers]"
)


def event(**changes):
    result = {
        "level": "ERROR", "name": "pyfujitsugeneral",
        "source": "custom_components/fglair_heatpump_controller/__init__.py:80",
        "message": [DNS_FAILURE], "exception": "",
    }
    result.update(changes)
    return result


class FujitsuDnsTimeoutTests(unittest.TestCase):
    def test_exact_dns_timeout_is_not_urgent_but_has_daily_summary(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(event(), T0))
        self.assertFalse(state.groups)
        self.assertFalse(state.pending_ignored(include_count_only=False) == {})
        self.assertEqual(state.ignored["fujitsu_ayla_dns_timeout"]["pending"], 1)
        self.assertNotIn("fujitsu_ayla_timeout", state.ignored)
        self.assertFalse(state.ignored_due(T0 + timedelta(hours=23), timedelta(hours=1)))
        self.assertTrue(state.ignored_due(T0 + timedelta(hours=24), timedelta(hours=1)))
        title, summary = summarize([], state.pending_ignored())
        self.assertIn("1 ignored ERROR", title)
        self.assertIn("Fujitsu/Ayla DNS resolution timeouts: 1 ERROR", summary)
        self.assertNotIn("devices.json", summary)

    def test_source_as_tuple(self):
        state = ErrorDigestState()
        changed = event(source=("custom_components/fglair_heatpump_controller/__init__.py", 80))
        self.assertFalse(state.observe(changed, T0))
        self.assertEqual(state.ignored["fujitsu_ayla_dns_timeout"]["pending"], 1)

    def test_unrelated_dns_and_other_errors_are_actionable(self):
        cases = [
            event(message=[DNS_FAILURE.replace("/devices.json", "/properties.json")]),
            event(message=[DNS_FAILURE.replace("ads-field-eu", "other-field-eu")]),
            event(message=[DNS_FAILURE.replace(":443", ":8443")]),
            event(message=[DNS_FAILURE.replace("ssl:default", "ssl:False")]),
            event(message=[DNS_FAILURE.replace(
                "Timeout while contacting DNS servers", "Name or service not known")]),
            event(message=[DNS_FAILURE.replace(
                "Timeout while contacting DNS servers", "Connection refused")]),
            event(message=[f"Error fetching information from {DEVICES_URL} - 500, message='Internal Server Error'"]),
            event(level="WARNING"),
            event(name="unrelated_logger"),
            event(source="custom_components/another_integration/__init__.py:80"),
            event(exception="OSError: another failure"),
        ]
        for case in cases:
            state = ErrorDigestState()
            with self.subTest(case=case):
                self.assertTrue(state.observe(case, T0))
                self.assertEqual(len(state.groups), 1)
                self.assertFalse(state.ignored)

    def test_migrate_three_pending_not_all_five_historical_occurrences(self):
        stored = {
            "groups": {
                "dns_pending": {
                    "level": "ERROR", "logger": "pyfujitsugeneral",
                    "source": "custom_components/fglair_heatpump_controller/__init__.py 80",
                    "message": DNS_FAILURE, "exception": "",
                    "first": (T0 - timedelta(days=4)).isoformat(),
                    "last": T0.isoformat(), "total": 5, "unreported": 3,
                    "pending_since": T0.isoformat(),
                    "notified_at": (T0 - timedelta(days=1)).isoformat(),
                }
            }
        }
        restored = ErrorDigestState(stored)
        self.assertFalse(restored.groups)
        self.assertEqual(restored.ignored["fujitsu_ayla_dns_timeout"]["pending"], 3)
        self.assertEqual(restored.ignored["fujitsu_ayla_dns_timeout"]["total"], 3)
        self.assertTrue(restored.dirty)

    def test_dns_failure_can_explain_nearby_fglair_climate_error(self):
        state = ErrorDigestState()
        state.observe(event(), T0)
        climate = {
            "level": "ERROR",
            "name": "homeassistant.helpers.entity",
            "source": "helpers/entity.py:1035",
            "message": ["Update for climate.fjac_2fl_bedroom fails"],
            "exception": (
                "pyfujitsugeneral.exceptions.FGLairGeneralException: "
                "FGLairBaseException has been raised"
            ),
        }
        self.assertFalse(state.observe(climate, T0 + timedelta(milliseconds=110)))
        self.assertEqual(state.ignored["fujitsu_ayla_climate_update"]["pending"], 1)
        self.assertTrue(state.observe(climate, T0 + timedelta(seconds=31)))

    def test_daily_dns_summary_does_not_delay_actionable_error(self):
        state = ErrorDigestState()
        state.observe(event(), T0)
        now = T0 + timedelta(hours=24)
        self.assertTrue(state.ignored_due(now, timedelta(hours=1)))
        state.acknowledge_ignored(state.pending_ignored(), now)
        state.observe({
            "level": "ERROR", "name": "unrelated_logger", "source": "other.py:1",
            "message": ["Something else broke"], "exception": "",
        }, now + timedelta(minutes=1))
        self.assertEqual(len(state.ready(
            now + timedelta(minutes=3), timedelta(minutes=2),
            timedelta(hours=1), timedelta(hours=24)
        )), 1)


if __name__ == "__main__":
    unittest.main()
