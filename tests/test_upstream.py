"""Regression tests for stable release selection and monitor outcomes."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "check_upstream", Path(__file__).resolve().parents[1] / "scripts/check_upstream.py"
)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def release(tag, **flags):
    return {"tag_name": tag, "draft": False, "prerelease": False} | flags


class UpstreamReleaseTests(unittest.TestCase):
    def test_ignores_development_drafts_and_prereleases(self):
        releases = [
            release("v0.16.0"),
            release("v0.17.0", prerelease=True),
            release("v0.18.0", draft=True),
            release("nightly"),
            release("v0.19.0-rc1"),
        ]
        self.assertEqual(monitor.latest_stable(releases)["tag_name"], "v0.16.0")

    def test_orders_versions_numerically_and_ignores_backport_order(self):
        releases = [release("v0.10.0"), release("v0.9.2"), release("v0.9.11")]
        self.assertEqual(monitor.latest_stable(releases)["tag_name"], "v0.10.0")

    def test_missing_stable_release_is_an_error(self):
        with self.assertRaises(ValueError):
            monitor.latest_stable([release("nightly")])

    def test_current_pins_and_new_release_outcomes(self):
        for pocketbase_tag, expected in [("v0.40.5", 0), ("v0.40.6", 1)]:
            with self.subTest(tag=pocketbase_tag), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "opensoho").mkdir()
                (root / "opensoho/upstream.env").write_text(
                    "OPENSOHO_RELEASE=v0.16.0\nPOCKETBASE_RELEASE=v0.40.5\n"
                )
                summary = root / "summary.md"
                with patch.object(monitor, "ROOT", root), patch.object(
                    monitor, "fetch_releases",
                    side_effect=[[release("v0.16.0")], [release(pocketbase_tag)]],
                ), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                    self.assertEqual(monitor.main(), expected)
                self.assertIn(pocketbase_tag, summary.read_text())


if __name__ == "__main__":
    unittest.main()
