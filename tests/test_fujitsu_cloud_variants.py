"""Regression tests for exact Fujitsu/Ayla transient cloud failure variants."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "log_error_digest"))
from model import ErrorDigestState, summarize


T0 = datetime(2026, 11, 11, 22, 40, 13, tzinfo=timezone.utc)
PROPERTY_URL = "https://ads-field-eu.aylanetworks.com/apiv1/properties/737526639/datapoints.json"
LOGIN_URL = "https://user-field-eu.aylanetworks.com/users/sign_in.json"
ENTITY_EXCEPTION = (
    "pyfujitsugeneral.exceptions.FGLairGeneralException: "
    "FGLairBaseException has been raised"
)


def fujitsu_error(message):
    return {
        "level": "ERROR", "name": "pyfujitsugeneral",
        "source": "custom_components/fglair_heatpump_controller/climate.py:617",
        "message": [message], "exception": "",
    }


def entity_failure(entity="climate.fjac_2fl_bedroom", exception=ENTITY_EXCEPTION):
    return {
        "level": "ERROR", "name": "homeassistant.helpers.entity",
        "source": "helpers/entity.py:1035",
        "message": [f"Update for {entity} fails"],
        "exception": "Traceback (most recent call last):\n" + exception,
    }


def property_500(url=PROPERTY_URL):
    return f"Error fetching information from {url} - 500, message='Internal Server Error', url='{url}'"


class FujitsuCloudVariantsTests(unittest.TestCase):
    def test_signin_timeout_is_count_only(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(
            fujitsu_error(f"Timeout error fetching information from {LOGIN_URL} -"), T0))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        self.assertFalse(state.pending_ignored(include_count_only=False))

    def test_property_http_500_is_count_only(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(fujitsu_error(property_500()), T0))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        self.assertFalse(state.pending_ignored(include_count_only=False))

    def test_entity_update_is_counted_only_after_cloud_failure(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(fujitsu_error(property_500()), T0))
        # The real log emitted this update failure milliseconds after the HTTP 500.
        self.assertFalse(state.observe(entity_failure(), T0 + timedelta(milliseconds=2)))
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)
        self.assertEqual(state.ignored["fujitsu_ayla_climate_update"]["pending"], 1)
        self.assertFalse(state.groups)
        _, message = summarize([], state.pending_ignored())
        self.assertIn("Fujitsu climate update failures following Ayla errors: 1 ERROR", message)
        self.assertNotIn("fjac_2fl_bedroom", message)

    def test_entity_failure_without_recent_cloud_cause_is_actionable(self):
        state = ErrorDigestState()
        self.assertTrue(state.observe(entity_failure(), T0))
        self.assertEqual(len(state.groups), 1)
        state.observe(fujitsu_error(property_500()), T0 + timedelta(minutes=1))
        self.assertTrue(state.observe(entity_failure(), T0 + timedelta(minutes=1, seconds=31)))
        self.assertEqual(len(state.groups), 1)
        self.assertNotIn("fujitsu_ayla_climate_update", state.ignored)

    def test_nearby_unrelated_entity_failures_are_actionable(self):
        state = ErrorDigestState()
        state.observe(fujitsu_error(property_500()), T0)
        for changed in (
            {"message": ["Update for climate.other_room fails"]},
            {"exception": "Traceback\nKeyError: invalid data"},
            {"name": "custom_components.some_other_integration"},
            {"level": "WARNING"},
            {"source": "components/another/entity.py:1035"},
            {"message": ["Update for climate.fjac_2fl_bedroom fails unexpectedly"]},
        ):
            event = {**entity_failure(), **changed}
            with self.subTest(changed=changed):
                self.assertTrue(state.observe(event, T0 + timedelta(seconds=1)))
        self.assertEqual(len(state.groups), 6)

    def test_other_http_failures_are_actionable(self):
        state = ErrorDigestState()
        cases = (
            property_500().replace("500, message='Internal Server Error'", "401, message='Unauthorized'"),
            property_500().replace("500, message='Internal Server Error'", "503, message='Service Unavailable'"),
            property_500().replace("datapoints.json", "devices.json"),
            property_500().replace("url='" + PROPERTY_URL, "url='https://different.example"),
            f"Error fetching information from {LOGIN_URL} - 500, message='Internal Server Error', url='{LOGIN_URL}'",
            f"Timeout error fetching information from https://user-field-eu.aylanetworks.com/users/reset_password.json -",
        )
        for case in cases:
            with self.subTest(case=case):
                self.assertTrue(state.observe(fujitsu_error(case), T0))
        self.assertEqual(len(state.groups), len(cases))

    def test_pending_cloud_errors_migrate_with_correlated_entity(self):
        state = ErrorDigestState()
        cloud = fujitsu_error(property_500())
        entity = entity_failure()
        stored = state.snapshot()
        # Emulate v0.2.4 groups, with the entity group appearing first.
        for key, event, when in (
            ("entity", entity, T0 + timedelta(seconds=1)),
            ("cloud", cloud, T0),
        ):
            stored["groups"][key] = {
                "level": event["level"], "logger": event["name"],
                "source": event["source"], "message": event["message"][0],
                "exception": event["exception"].splitlines()[-1] if event["exception"] else "",
                "last": when.isoformat(), "unreported": 2, "total": 3,
            }
        restored = ErrorDigestState(stored)
        self.assertFalse(restored.groups)
        self.assertEqual(restored.ignored["fujitsu_ayla_timeout"]["pending"], 2)
        self.assertEqual(restored.ignored["fujitsu_ayla_climate_update"]["pending"], 2)
        self.assertTrue(restored.dirty)

    def test_recent_failure_correlation_survives_restart(self):
        state = ErrorDigestState()
        state.observe(fujitsu_error(property_500()), T0)
        restored = ErrorDigestState(state.snapshot())
        self.assertFalse(restored.observe(entity_failure(), T0 + timedelta(seconds=3)))
        self.assertEqual(restored.ignored["fujitsu_ayla_climate_update"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
