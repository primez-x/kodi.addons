"""Exercise Pages verification against a local HTTP endpoint."""

import copy
import importlib
import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


class VerifyPagesTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("verify_pages"), "Pages verifier is missing")
        self.verifier = importlib.import_module("verify_pages")
        self.expected = {"addons": [
            {"id": "a", "repository": "o/a", "sha": "a" * 40, "version": "1.0.1"},
            {"id": "b", "repository": "o/b", "sha": "b" * 40, "version": "2.0.0"},
        ]}
        self.responses = []
        self.paths = []
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.paths.append(self.path)
                status, body = case.responses.pop(0)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/repo/"

    def verify(self, attempts):
        with mock.patch.object(self.verifier.time, "sleep") as sleep, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.verifier.verify_pages(self.expected, self.url, attempts=attempts)
        return sleep

    def response(self, manifest):
        return 200, json.dumps(manifest).encode()

    def test_retries_old_manifest_then_accepts_matching_sha_and_version(self):
        old = copy.deepcopy(self.expected)
        old["addons"][0]["sha"] = "c" * 40
        self.responses = [self.response(old), self.response(self.expected)]
        sleep = self.verify(2)
        self.assertEqual(sleep.call_count, 1)
        self.assertNotEqual(self.paths[0], self.paths[1])
        self.assertTrue(all(path.startswith("/repo/source-manifest.json?") for path in self.paths))

    def test_retries_http_errors_and_malformed_json(self):
        self.responses = [(503, b"unavailable"), (200, b"not-json"), self.response(self.expected)]
        sleep = self.verify(3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len(self.paths), 3)

    def test_rejects_changed_version_missing_extra_and_duplicate_addons(self):
        changed_version = copy.deepcopy(self.expected)
        changed_version["addons"][0]["version"] = "1.0.0"
        for candidate in [changed_version, {"addons": self.expected["addons"][:1]},
                          {"addons": self.expected["addons"] + [dict(self.expected["addons"][0], id="c")]},
                          {"addons": self.expected["addons"] + [self.expected["addons"][0]]},
                          {"addons": [{}]}, {"addons": []}]:
            with self.subTest(candidate=candidate):
                self.responses = [self.response(candidate)]
                with self.assertRaisesRegex(RuntimeError, "Pages verification failed"):
                    self.verify(1)

    def test_accepts_reordered_entries_and_unrelated_manifest_fields(self):
        live = {"addons": list(reversed(self.expected["addons"])), "generated": "later"}
        self.responses = [self.response(live)]
        self.verify(1)

    def test_retry_window_expires_and_preserves_mismatch_details(self):
        old = copy.deepcopy(self.expected)
        old["addons"][0]["sha"] = "c" * 40
        self.responses = [self.response(old)] * 3
        with self.assertRaisesRegex(RuntimeError, "Pages verification failed.*a"):
            self.verify(3)
        self.assertEqual(len(self.paths), 3)

    def test_invalid_expected_manifest_fails_before_any_http_request(self):
        self.expected = {"addons": [{"id": "a"}]}
        with self.assertRaises(ValueError):
            self.verify(1)
        self.assertEqual(self.paths, [])
