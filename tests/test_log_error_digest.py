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
FUJITSU_DATAPOINT_TIMEOUT = (
    "Timeout error fetching information from "
    "https://ads-field-eu.aylanetworks.com/apiv1/properties/125151666/datapoints.json -"
)
FUJITSU_TEMPERATURE_DEPRECATION = (
    "custom_components.fglair_heatpump_controller.climate::FujitsuClimate "
    "provides the deprecated current_temperature, this will stop working in "
    "Home Assistant 2027.11, use native_current_temperature instead, "
    "please report it to the custom integration author"
)
WITHINGS_WARNING = {
    "level": "WARNING", "name": "homeassistant.components.withings",
    "source": "components/withings/__init__.py:312",
    "message": ["Webhook not registered - port 443 is required. See "
                "https://www.home-assistant.io/integrations/withings/#webhook-requirements"],
    "exception": "",
}
ZEROCONF_PERMISSION_ERROR = "PermissionError: [Errno 1] Operation not permitted"
ZEROCONF_WARNING = {
    "level": "WARNING", "name": "zeroconf",
    "source": "/usr/local/lib/python3.14/site-packages/zeroconf/_logger.py:84",
    "message": ["Error with socket 15 (('::', 5353, 0, 0))): [Errno 1] Operation not permitted"],
    "exception": f"Traceback (most recent call last):\n{ZEROCONF_PERMISSION_ERROR}",
}
INITIAL = timedelta(minutes=2)
COOLDOWN = timedelta(minutes=60)
REPEAT = timedelta(hours=24)


def error(name="homeassistant", msg="Task exception was never retrieved", exception="AttributeError: missing method"):
    return {"level": "ERROR", "name": name,
            "source": "custom_components/device_availability_digest/__init__.py:297",
            "message": [msg], "exception": f"Traceback...\n{exception}"}


def sma_warning(key, name, unit="kWh", factor=1000):
    sensor = (
        f"Sensor(key='{key}', name='{name}', unit={unit!r}, factor={factor}, path=None, "
        "enabled=True, l10n_translate=False, value=None, mapped_value=None, "
        "range=None, webconnect_deviceId=None)"
    )
    return {
        "level": "WARNING", "name": "pysmaplus.sensor",
        "source": "custom_components/pysmaplus/__init__.py:113",
        "message": [f"Replacing sensor {sensor} with {sensor}"], "exception": "",
    }


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
        later = T0 + timedelta(hours=48)
        self.assertFalse(state.ignored_due(later, COOLDOWN))
        state.observe(error(), later)
        batch = state.ready(later + INITIAL, INITIAL, COOLDOWN, REPEAT)
        title, message = summarize(batch, state.pending_ignored())
        self.assertIn("1 ERROR", title)
        self.assertIn("Fujitsu/Ayla cloud properties fetch timeouts: 7 ERROR", message)
        self.assertNotIn("AC000W002919187", message)

    def test_fujitsu_datapoints_timeout_from_logs_is_ignored(self):
        state = ErrorDigestState()
        event = {
            "level": "ERROR", "name": "pyfujitsugeneral",
            "source": "custom_components/fglair_heatpump_controller/climate.py:617",
            "message": [FUJITSU_DATAPOINT_TIMEOUT], "exception": "",
        }
        self.assertFalse(state.observe(event, T0))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_ayla_timeout"]["pending"], 1)

        # Similar URL failures must not be silently hidden.
        for change in (
            {"message": [FUJITSU_DATAPOINT_TIMEOUT.replace("datapoints.json", "data.json")]},
            {"name": "unrelated_library"},
            {"source": "custom_components/other/climate.py:617"},
            {"exception": "TimeoutError: disconnected device"},
        ):
            self.assertTrue(state.observe({**event, **change}, T0))
        self.assertEqual(len(state.groups), 4)

    def test_fujitsu_temperature_deprecations_are_aggregated(self):
        state = ErrorDigestState()
        event = {
            "level": "WARNING",
            "name": "custom_components.fglair_heatpump_controller.climate",
            "source": "helpers/deprecation.py:706",
            "message": [FUJITSU_TEMPERATURE_DEPRECATION],
            "exception": "",
        }
        for attribute in ("current_temperature", "target_temperature", "temperature_unit"):
            with self.subTest(attribute=attribute):
                message = FUJITSU_TEMPERATURE_DEPRECATION.replace("current_temperature", attribute)
                self.assertFalse(state.observe({**event, "message": [message]}, T0))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_temperature_deprecation"]["pending"], 3)
        self.assertFalse(state.ignored_due(T0 + timedelta(hours=48), COOLDOWN))
        state.observe(error(), T0)
        batch = state.ready(T0 + INITIAL, INITIAL, COOLDOWN, REPEAT)
        _, summary = summarize(batch, state.pending_ignored())
        self.assertIn("Fujitsu climate temperature deprecation notices: 3 WARNING", summary)
        self.assertNotIn("FujitsuClimate", summary)

        for change in (
            {"message": [FUJITSU_TEMPERATURE_DEPRECATION.replace(
                "current_temperature", "temperature_offset")]},
            {"message": [FUJITSU_TEMPERATURE_DEPRECATION.replace(
                "native_current_temperature", "native_target_temperature")]},
            {"name": "custom_components.unrelated.climate"},
            {"source": "helpers/entity.py:706"},
            {"level": "ERROR"},
            {"exception": "RuntimeError: another issue"},
        ):
            self.assertTrue(state.observe({**event, **change}, T0))
        self.assertEqual(len(state.groups), 7)

    def test_upgrade_reclassifies_pending_count_only_examples(self):
        state = ErrorDigestState()
        sma = sma_warning("DcMs.TotDcEnCntWh.2", "pv_total_power_b")
        sample_events = (
            ("fujitsu_ayla_timeout", "ERROR", "pyfujitsugeneral",
             "custom_components/fglair_heatpump_controller/climate.py:617",
             FUJITSU_DATAPOINT_TIMEOUT, ""),
            ("fujitsu_temperature_deprecation", "WARNING",
             "custom_components.fglair_heatpump_controller.climate", "helpers/deprecation.py:706",
             FUJITSU_TEMPERATURE_DEPRECATION.replace("current_temperature", "target_temperature"), ""),
            ("withings_webhook_port", "WARNING", WITHINGS_WARNING["name"],
             WITHINGS_WARNING["source"], WITHINGS_WARNING["message"][0], ""),
            ("sma_sensor_replacement", "WARNING", sma["name"], sma["source"], sma["message"][0][:320], ""),
            ("zeroconf_mdns_permission", "WARNING", ZEROCONF_WARNING["name"],
             ZEROCONF_WARNING["source"].replace(":84", " 84"),
             ZEROCONF_WARNING["message"][0], ZEROCONF_PERMISSION_ERROR),
        )
        for category, level, name, source, message, exception in sample_events:
            # Mimic stored groups saved by the prior unfiltered version.
            state.groups[category] = {
                "level": level, "logger": name, "source": source,
                "message": message, "exception": exception, "last": T0.isoformat(),
                "unreported": 2, "total": 3,
            }
        restored = ErrorDigestState(state.snapshot())
        self.assertFalse(restored.groups)
        self.assertEqual({key: item["pending"] for key, item in restored.ignored.items()},
                         {sample[0]: 2 for sample in sample_events})
        self.assertFalse(restored.ignored_due(T0 + timedelta(hours=48), COOLDOWN))
        self.assertTrue(restored.dirty)

    def test_withings_and_sma_warnings_are_counted_without_standalone_alerts(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(WITHINGS_WARNING, T0))
        for key, name, unit, factor in (
            ("Metering.GridMs.TotWhIn.Bat", "battery_charge_total", "kWh", 1000),
            ("Metering.GridMs.TotWhOut.Bat", "battery_discharge_total", "kWh", 1000),
            ("DcMs.TotDcEnCntWh.1", "pv_total_power_a", "kWh", 1000),
            ("DcMs.TotDcEnCntWh.2", "pv_total_power_b", "kWh", 1000),
            ("DcMs.TotDcEnCntWh.3", "pv_total_power_c", "kWh", 1000),
            ("Operation.BckStt", "backup_mode_status", None, 1),
            ("GridMs.A.phsA", "current_l1", "A", 1),
        ):
            with self.subTest(sensor=name):
                self.assertFalse(state.observe(sma_warning(key, name, unit, factor), T0))
        self.assertFalse(state.groups)
        self.assertFalse(state.ignored_due(T0 + timedelta(hours=48), COOLDOWN))
        self.assertEqual(state.ignored["withings_webhook_port"]["pending"], 1)
        self.assertEqual(state.ignored["sma_sensor_replacement"]["pending"], 7)

        # Older noise cannot advance the clock for a separate legacy summary.
        later = T0 + timedelta(hours=48)
        state.observe({
            "level": "WARNING", "name": "homeassistant.loader",
            "source": "loader.py:833",
            "message": [CUSTOM_INTEGRATION_NOTICE.format("ps3")],
        }, later)
        self.assertFalse(state.ignored_due(later, COOLDOWN))
        self.assertTrue(state.ignored_due(later + REPEAT, COOLDOWN))
        self.assertEqual(set(state.pending_ignored(include_count_only=False)),
                         {"untested_custom_integration"})
        state.observe(error(), later)
        batch = state.ready(later + INITIAL, INITIAL, COOLDOWN, REPEAT)
        _, summary = summarize(batch, state.pending_ignored())
        self.assertIn("Withings webhook port 443 warnings: 1 WARNING", summary)
        self.assertIn("SMA known sensor replacement warnings: 7 WARNING", summary)
        self.assertNotIn("Replacing sensor Sensor(", summary)
        self.assertNotIn("#webhook-requirements", summary)

    def test_other_withings_and_sma_problems_remain_actionable(self):
        state = ErrorDigestState()
        sma = sma_warning("DcMs.TotDcEnCntWh.1", "pv_total_power_a")
        old, replacement = sma["message"][0].split(" with ")
        for event in (
            {**WITHINGS_WARNING, "message": ["Webhook not registered - callback rejected"]},
            {**WITHINGS_WARNING, "level": "ERROR"},
            {**WITHINGS_WARNING, "exception": "RuntimeError: setup failed"},
            {**sma, "message": [f"{old} with {replacement.replace('pv_total_power_a', 'pv_total_power_b')}"]},
            {**sma, "source": "custom_components/other/__init__.py:113"},
            {**sma, "exception": "ValueError: bad sensor mapping"},
            sma_warning("DcMs.TotDcEnCntWh.4", "pv_total_power_d"),
        ):
            with self.subTest(event=event):
                self.assertTrue(state.observe(event, T0))
        self.assertFalse(state.ignored)

    def test_zeroconf_ipv6_socket_permission_warning_is_counted(self):
        state = ErrorDigestState()
        self.assertFalse(state.observe(ZEROCONF_WARNING, T0))
        self.assertFalse(state.observe({
            **ZEROCONF_WARNING,
            "source": ("/usr/lib/python3.15/site-packages/zeroconf/_logger.py", 91),
            "message": [ZEROCONF_WARNING["message"][0].replace("socket 15", "socket 26")],
        }, T0))
        self.assertFalse(state.groups)
        self.assertFalse(state.pending_ignored(include_count_only=False))
        self.assertFalse(state.ignored_due(T0 + timedelta(hours=48), COOLDOWN))
        self.assertEqual(state.ignored["zeroconf_mdns_permission"]["pending"], 2)

        state.observe(error(), T0)
        batch = state.ready(T0 + INITIAL, INITIAL, COOLDOWN, REPEAT)
        _, summary = summarize(batch, state.pending_ignored())
        self.assertIn("Zeroconf IPv6 mDNS socket permission warnings: 2 WARNING", summary)
        self.assertNotIn("Error with socket", summary)

    def test_other_zeroconf_socket_failures_are_actionable(self):
        state = ErrorDigestState()
        message = ZEROCONF_WARNING["message"][0]
        for changes in (
            {"level": "ERROR"},
            {"name": "another_logger"},
            {"source": "another_package/_logger.py:84"},
            {"message": [message.replace("'::', 5353, 0, 0", "'0.0.0.0', 5353")]},
            {"message": [message.replace("5353", "5354")]},
            {"exception": "OSError: [Errno 101] Network is unreachable"},
        ):
            with self.subTest(changes=changes):
                self.assertTrue(state.observe({**ZEROCONF_WARNING, **changes}, T0))
        self.assertFalse(state.ignored)

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
            "level": "WARNING", "name": "homeassistant.loader",
            "source": "loader.py:833",
            "message": [CUSTOM_INTEGRATION_NOTICE.format("ps3")],
        }
        state.observe(event, T0)
        snapshot = deepcopy(state.pending_ignored())
        state.observe(event, T0 + timedelta(minutes=1))
        state.acknowledge_ignored(snapshot, T0 + timedelta(hours=24))
        self.assertEqual(state.ignored["untested_custom_integration"]["pending"], 1)
        restored = ErrorDigestState(state.snapshot())
        self.assertEqual(restored.ignored["untested_custom_integration"]["pending"], 1)
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

    def test_known_fujitsu_slow_entity_updates_are_aggregated(self):
        state = ErrorDigestState()
        for entity in ("climate.fjac_1fl_yard_bedr", "climate.fjac_0fl_living_room"):
            for _ in range(3):
                self.assertFalse(state.observe({
                    "level": "WARNING",
                    "name": "homeassistant.helpers.entity",
                    "source": "helpers/entity.py:1390",
                    "message": [f"Update of {entity} is taking over 10 seconds"],
                    "exception": "",
                }, T0))
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_slow_climate_update"]["pending"], 6)
        title, message = summarize([], state.pending_ignored())
        self.assertIn("6 ignored WARNING", title)
        self.assertIn("Fujitsu climate updates taking over 10 seconds: 6 WARNING", message)
        self.assertNotIn("fjac_1fl_yard_bedr", message)
        restored = ErrorDigestState(state.snapshot())
        self.assertEqual(restored.ignored["fujitsu_slow_climate_update"]["pending"], 6)

    def test_unrelated_slow_updates_and_other_entity_warnings_are_not_filtered(self):
        state = ErrorDigestState()
        for level, logger, source, message in (
            ("WARNING", "homeassistant.helpers.entity", "helpers/entity.py:1390",
             "Update of climate.other_room is taking over 10 seconds"),
            ("WARNING", "homeassistant.helpers.entity", "helpers/entity.py:1390",
             "Update of climate.fjac_1fl_yard_bedr is taking over 30 seconds"),
            ("WARNING", "homeassistant.helpers.entity", "helpers/entity.py:1390",
             "Update of climate.fjac_1fl_yard_bedr failed"),
            ("ERROR", "homeassistant.helpers.entity", "helpers/entity.py:1390",
             "Update of climate.fjac_1fl_yard_bedr is taking over 10 seconds"),
            ("WARNING", "custom_components.other", "helpers/entity.py:1390",
             "Update of climate.fjac_1fl_yard_bedr is taking over 10 seconds"),
        ):
            self.assertTrue(state.observe({
                "level": level, "name": logger, "source": source,
                "message": [message], "exception": "",
            }, T0))
        self.assertEqual(len(state.groups), 5)
        self.assertFalse(state.ignored)

    def test_upgrade_reclassifies_pending_fujitsu_slow_updates(self):
        state = ErrorDigestState()
        old = {
            "groups": {
                "legacy_fjac_slow_update": {
                    "level": "WARNING",
                    "logger": "homeassistant.helpers.entity",
                    "source": "helpers/entity.py:1390",
                    "message": "Update of climate.fjac_0fl_living_room is taking over 10 seconds",
                    "exception": "",
                    "last": T0.isoformat(),
                    "unreported": 4,
                }
            }
        }
        state = ErrorDigestState(old)
        self.assertFalse(state.groups)
        self.assertEqual(state.ignored["fujitsu_slow_climate_update"]["pending"], 4)

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
