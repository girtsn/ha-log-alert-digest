"""Regression checks for native System Log event activation.

These use lightweight stubs, so they can run in HACS CI without a live
Home Assistant installation.
"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "log_error_digest" / "event_source.py"
spec = importlib.util.spec_from_file_location("log_error_digest_event_source_test", MODULE)
event_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(event_source)


class EventActivationTests(unittest.TestCase):
    def test_enable_and_restore_disabled_system_log(self):
        handler = SimpleNamespace(fire_event=False)
        hass = SimpleNamespace(data={"system_log": handler})
        used, previous = event_source.enable_system_log_events(hass)
        self.assertIs(used, handler)
        self.assertFalse(previous)
        self.assertTrue(handler.fire_event)
        event_source.restore_system_log_events(hass, used, previous)
        self.assertFalse(handler.fire_event)

    def test_existing_enabled_system_log_remains_enabled(self):
        handler = SimpleNamespace(fire_event=True)
        hass = SimpleNamespace(data={"system_log": handler})
        used, previous = event_source.enable_system_log_events(hass)
        event_source.restore_system_log_events(hass, used, previous)
        self.assertTrue(handler.fire_event)

    def test_missing_or_changed_system_log_api_fails_explicitly(self):
        for data in ({}, {"system_log": object()}):
            with self.subTest(data=data), self.assertRaisesRegex(RuntimeError, "fire_event"):
                event_source.enable_system_log_events(SimpleNamespace(data=data))

    def test_replaced_core_handler_is_not_modified_on_unload(self):
        original = SimpleNamespace(fire_event=False)
        hass = SimpleNamespace(data={"system_log": original})
        old_handler, previous = event_source.enable_system_log_events(hass)
        new_handler = SimpleNamespace(fire_event=True)
        hass.data["system_log"] = new_handler
        event_source.restore_system_log_events(hass, old_handler, previous)
        self.assertTrue(new_handler.fire_event)

    def test_manifest_is_config_flow_enabled_and_versioned(self):
        manifest = json.loads(
            (ROOT / "custom_components" / "log_error_digest" / "manifest.json").read_text()
        )
        self.assertEqual(manifest["version"], "0.2.0")
        self.assertTrue(manifest["config_flow"])
        self.assertTrue(manifest["single_config_entry"])
        self.assertIn("system_log", manifest["dependencies"])


if __name__ == "__main__":
    unittest.main()
