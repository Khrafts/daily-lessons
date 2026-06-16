"""Tests for scripts/render_lesson.py — focused on the `mode` provenance field.

The renderer slots model-authored content into the frozen shells and appends a
ledger record. These tests run the real script as a subprocess against a
throwaway lessons dir and the repo's real assets, so they never touch the user's
library in ~/.claude/daily-lessons and never depend on a particular machine.

`mode` (the lecture mode the lesson was written in — tutorial/grounded/deep/
briefing) is an OPTIONAL meta field: when present it must flow into the ledger
record and the stdout summary; when absent the renderer must still succeed and
must not invent the key (backward compatibility with pre-mode lessons).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RENDER = REPO / "scripts" / "render_lesson.py"

BODY = (
    '<h2><span class="h2n">01</span> What it is</h2>\n'
    "<p>A minimal body fragment used only to exercise the renderer.</p>\n"
)

BASE_META = {
    "slug": "namespaced-storage",
    "concept_key": "evm-erc7201-namespaced-storage",
    "title": "Namespaced storage layout",
    "dek": "Why a struct gets its own <code>slot</code>.",
    "one_liner": "ERC-7201 gives a struct a collision-proof storage home.",
    "source_day": "2026-06-15",
    "taught_at": "2026-06-16T09:30:00+01:00",
    "tags": ["evm", "solidity"],
}


def _render(meta, lessons_dir):
    """Run the renderer as a subprocess; return (proc, stdout_json_or_None)."""
    md = dict(meta)
    meta_path = lessons_dir / "meta.json"
    body_path = lessons_dir / "body.html"
    meta_path.write_text(json.dumps(md), encoding="utf-8")
    body_path.write_text(BODY, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(RENDER),
         "--meta", str(meta_path), "--body", str(body_path),
         "--lessons-dir", str(lessons_dir)],
        capture_output=True, text=True,
    )
    out = None
    if proc.stdout.strip():
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            out = None
    return proc, out


@unittest.skipUnless(RENDER.is_file(), "render_lesson.py not present")
class ModeProvenanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger(self):
        return json.loads((self.dir / "index.json").read_text(encoding="utf-8"))

    def test_mode_flows_into_ledger_and_stdout(self):
        meta = dict(BASE_META, mode="grounded")
        proc, out = _render(meta, self.dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNotNone(out, proc.stdout)
        self.assertEqual(out.get("mode"), "grounded")
        ledger = self._ledger()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0].get("mode"), "grounded")

    def test_mode_absent_is_backward_compatible(self):
        # No `mode` key at all — must still render and must not invent the key.
        proc, out = _render(BASE_META, self.dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNotNone(out, proc.stdout)
        self.assertTrue(out.get("ok"))
        ledger = self._ledger()
        self.assertEqual(len(ledger), 1)
        self.assertNotIn("mode", ledger[0])
        # stdout summary carries the key but as a null when there's no mode.
        self.assertIsNone(out.get("mode"))

    def test_blank_mode_is_treated_as_absent(self):
        meta = dict(BASE_META, mode="")
        proc, out = _render(meta, self.dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("mode", self._ledger()[0])

    def test_missing_required_field_still_exits_2(self):
        meta = dict(BASE_META, mode="briefing")
        del meta["title"]
        proc, _ = _render(meta, self.dir)
        self.assertEqual(proc.returncode, 2, proc.stderr)


if __name__ == "__main__":
    unittest.main()
