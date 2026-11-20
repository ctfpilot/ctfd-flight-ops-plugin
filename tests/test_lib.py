import unittest
import importlib.util
import os
import sys
import types


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIB_PATH = os.path.join(ROOT_DIR, "src", "lib.py")


def _load_lib_module():
    src_pkg = types.ModuleType("src")
    src_pkg.__path__ = [os.path.join(ROOT_DIR, "src")]
    sys.modules["src"] = src_pkg

    config_mod = types.ModuleType("src.config")
    setattr(config_mod, "API_KIND", "flight-ops-status")
    setattr(config_mod, "API_VERSION", "v1")
    sys.modules["src.config"] = config_mod

    errors_mod = types.ModuleType("src.errors")

    class PluginError(object):
        def __init__(self, err_type, message, code):
            self.type = err_type
            self.message = message
            self.code = code

    setattr(errors_mod, "PluginError", PluginError)
    sys.modules["src.errors"] = errors_mod

    spec = importlib.util.spec_from_file_location("src.lib", LIB_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load module spec for src.lib")
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.lib"] = module
    spec.loader.exec_module(module)
    return module


lib = _load_lib_module()
build_status_response = lib.build_status_response
phase_to_state = lib.phase_to_state
select_relevant_flight = lib.select_relevant_flight


class LibTests(unittest.TestCase):
    def test_phase_to_state_mapping(self):
        self.assertEqual(phase_to_state("Pending"), "pending")
        self.assertEqual(phase_to_state("InFlight"), "ready")
        self.assertEqual(phase_to_state("Landed"), "landed")
        self.assertEqual(phase_to_state("Failed"), "failed")
        self.assertEqual(phase_to_state("Other"), "unknown")
        self.assertEqual(phase_to_state(None), "unknown")

    def test_build_status_response_missing(self):
        payload = build_status_response(None)
        self.assertEqual(payload["status"], "missing")
        self.assertIsNone(payload["flight_name"])
        self.assertEqual(payload["connection_strings"], [])
        self.assertIsNone(payload["expires_at"])
        self.assertIsNone(payload["started_at"])

    def test_build_status_response_ready(self):
        payload = build_status_response(
            {
                "name": "flight-a",
                "status": {
                    "phase": "InFlight",
                    "connectionStrings": ["https://example.com"],
                    "launchedAt": "2026-01-01T00:00:00Z",
                    "expiresAt": "2026-01-01T01:00:00Z",
                },
            }
        )
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["flight_name"], "flight-a")
        self.assertEqual(payload["connection_strings"], ["https://example.com"])
        self.assertEqual(payload["started_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(payload["expires_at"], "2026-01-01T01:00:00Z")

    def test_select_relevant_flight_prefers_phase(self):
        items = [
            {
                "name": "old-ready",
                "status": {
                    "phase": "InFlight",
                    "launchedAt": "2026-01-01T00:00:00Z",
                },
            },
            {
                "name": "new-pending",
                "status": {
                    "phase": "Pending",
                    "launchedAt": "2026-01-02T00:00:00Z",
                },
            },
        ]
        selected = select_relevant_flight(items)
        self.assertEqual(selected["name"], "old-ready")

    def test_select_relevant_flight_uses_recent_timestamp_tiebreaker(self):
        items = [
            {
                "name": "older",
                "status": {
                    "phase": "Pending",
                    "launchedAt": "2026-01-01T00:00:00Z",
                },
            },
            {
                "name": "newer",
                "status": {
                    "phase": "Pending",
                    "launchedAt": "2026-01-03T00:00:00Z",
                },
            },
        ]
        selected = select_relevant_flight(items)
        self.assertEqual(selected["name"], "newer")


if __name__ == "__main__":
    unittest.main()
