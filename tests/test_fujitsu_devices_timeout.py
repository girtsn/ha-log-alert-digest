"""Regression tests for the Fujitsu/Ayla device-list timeout signature."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize

T0 = datetime(2026, 11, 12, 12, 12, 46, tzinfo=timezone.utc)
DEVICES_URL = "https://ads-field-eu.aylanetworks.com/apiv1/devices.json"
DEVICES_TIMEOUT = f"Timeout error fetching information from {DEVICES_URL} -"


def event(**changes):
    base = {
        "level": "ERROR",
        "name": "pyfujitsugeneral",
        "source": "custom_components/fglair_heatpump_controller/__init__.py:80",
        "message": [DEVICES_TIMEOUT],
        "exception": "",
    }
    base.update(changes)
    return base


class FujitsuDevicesTimeoutTests(unittest.TestCase):
    def test_reported_device_list_timeout_is_counted_only(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(event(), T0))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        self.assertFalse(state.pending_ignored(include_count_only=False))
        _, msg = summarize([], state.pending_ignored())
        self.assertIn("Fujitsu/Ayla known cloud request failures: 1 ERROR", msg)
        self.assertNotIn("devices.json", msg)

    def test_real_event_tuple_source_is_matched(self):
        state = ErrorDigestState()
        real = event(source=("custom_components/fglair_heatpump_controller/__init__.py", 80))
        self.assertFalse(state.observe(real, T0))
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)

    def test_only_exact_known_timeout_is_suppressed(self):
        state = ErrorDigestState()
        variants = (
            event(message=["Timeout error fetching information from https://ads-field-eu.aylanetworks.com/apiv1/device.json -"]),
            event(message=["Timeout error fetching information from https://ads-field-eu.aylanetworks.com/apiv1/devices/123.json -"]),
            event(message=["Timeout error fetching information from https://other-field-eu.aylanetworks.com/apiv1/devices.json -"]),
            event(message=[f"Error fetching information from {DEVICES_URL} - 500, message='Internal Server Error', url='{DEVICES_URL}'"]),
            event(message=["Authentication failed fetching FGLair"]),
            event(level="WARNING"),
            event(name="unrelated_logger"),
            event(source="custom_components/another_integration/__init__.py:80"),
            event(exception="TimeoutError: unexpected connection failure"),
        )
        for item in variants:
            with self.subTest(item=item):
                self.assertTrue(state.observe(item, T0))
        self.assertEqual(len(state.groups), len(variants))
        self.assertNotIn("fujitsu_ayla_timeout", state.ignored)

    def test_previous_seven_pending_occurrences_migrate_without_resending(self):
        old = {
            "groups": {"previous_device_timeout": {
                "level": "ERROR", "logger": "pyfujitsugeneral",
                "source": "custom_components/fglair_heatpump_controller/__init__.py 80",
                "message": DEVICES_TIMEOUT, "exception": "",
                "first": (T0 - timedelta(days=4)).isoformat(),
                "last": T0.isoformat(), "total": 22,
                "unreported": 7, "pending_since": T0.isoformat(),
                "notified_at": T0.isoformat(),
            }}
        }
        restored = ErrorDigestState(old)
        self.assertFalse(restored.groups)
        self.assertEqual(restored.ignored["fujitsu_ayla_timeout"]["pending"], 7)
        self.assertEqual(restored.ignored["fujitsu_ayla_timeout"]["total"], 7)
        self.assertTrue(restored.dirty)

    def test_devices_timeout_can_correlate_climate_update(self):
        state = ErrorDigestState()
        state.observe(event(), T0)
        entity = {
            "level": "ERROR",
            "name": "homeassistant.helpers.entity",
            "source": "helpers/entity.py:1035",
            "message": ["Update for climate.fjac_2fl_bedroom fails"],
            "exception": "pyfujitsugeneral.exceptions.FGLairGeneralException: FGLairBaseException has been raised",
        }
        self.assertFalse(state.observe(entity, T0 + timedelta(milliseconds=120)))
        self.assertEqual(state.ignored["fujitsu_ayla_climate_update"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
