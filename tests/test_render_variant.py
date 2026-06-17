"""Tests for render_lesson.py --variant — alternate-tone renditions of a lesson.

A "variant" is the SAME concept re-rendered in a different lecture mode, persisted
as its own retrievable lesson alongside the original. Uniqueness becomes
(concept_key, mode): the same concept in a *different* tone is allowed; the same
concept in the *same* tone is still a duplicate (exit 3). Variants get a
mode-suffixed filename, a `variant_of` link to the primary, and share the
primary's lesson number. The library groups renditions: one row per concept_key,
with the extra tones reachable from that row.

Run as a subprocess against a throwaway lessons dir and the repo's real assets.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RENDER = REPO / "scripts" / "render_lesson.py"

BODY = '<h2><span class="h2n">01</span> What it is</h2><p>x</p>'

BASE = {
    "slug": "erc7201",
    "concept_key": "evm-erc7201",
    "title": "Namespaced storage",
    "dek": "d",
    "one_liner": "o",
    "source_day": "2026-06-15",
    "taught_at": "2026-06-16T09:00:00+01:00",
    "tags": ["evm"],
}


@unittest.skipUnless(RENDER.is_file(), "render_lesson.py not present")
class VariantTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, meta, *extra):
        mp = self.dir / "m.json"
        bp = self.dir / "b.html"
        mp.write_text(json.dumps(meta), encoding="utf-8")
        bp.write_text(BODY, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(RENDER), "--meta", str(mp), "--body", str(bp),
             "--lessons-dir", str(self.dir), *extra],
            capture_output=True, text=True,
        )
        out = None
        if proc.stdout.strip():
            try:
                out = json.loads(proc.stdout)
            except json.JSONDecodeError:
                out = None
        return proc, out

    def _ledger(self):
        return json.loads((self.dir / "index.json").read_text(encoding="utf-8"))

    def test_variant_persists_as_sibling(self):
        # Primary in grounded, then a tutorial variant of the same concept.
        p_proc, p_out = self._run(dict(BASE, mode="grounded"))
        self.assertEqual(p_proc.returncode, 0, p_proc.stderr)
        primary_n = p_out["lesson_number"]
        primary_id = self._ledger()[0]["id"]

        v_proc, v_out = self._run(dict(BASE, mode="tutorial"), "--variant")
        self.assertEqual(v_proc.returncode, 0, v_proc.stderr)
        # Mode-suffixed filename so it never overwrites the primary.
        self.assertTrue(v_out["file"].endswith("-tutorial.html"), v_out["file"])
        self.assertNotEqual(v_out["file"], p_out["file"])
        # Both renditions are on disk and in the ledger.
        self.assertTrue((self.dir / v_out["file"]).is_file())
        ledger = self._ledger()
        self.assertEqual(len(ledger), 2)
        variant = ledger[1]
        self.assertEqual(variant["mode"], "tutorial")
        self.assertEqual(variant["concept_key"], BASE["concept_key"])
        self.assertEqual(variant["variant_of"], primary_id)
        # A variant shares the primary's lesson number (same concept).
        self.assertEqual(v_out["lesson_number"], primary_n)

    def test_same_mode_variant_is_duplicate(self):
        self._run(dict(BASE, mode="grounded"))
        proc, _ = self._run(dict(BASE, mode="grounded"), "--variant")
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_variant_requires_mode(self):
        self._run(dict(BASE, mode="grounded"))
        meta = dict(BASE)  # no mode
        proc, _ = self._run(meta, "--variant")
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_variant_of_unknown_concept_is_rejected(self):
        proc, _ = self._run(dict(BASE, mode="tutorial"), "--variant")
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_library_groups_renditions_into_one_row(self):
        # Two distinct concepts, plus one variant of the first.
        self._run(dict(BASE, mode="grounded"))
        self._run(dict(BASE, slug="other", concept_key="evm-other",
                       title="Other concept", mode="grounded"))
        v_proc, v_out = self._run(dict(BASE, mode="briefing"), "--variant")
        self.assertEqual(v_proc.returncode, 0, v_proc.stderr)

        index = (self.dir / "index.html").read_text(encoding="utf-8")
        # One row per concept (2), not one per rendition (3).
        self.assertEqual(index.count('<li class="row">'), 2, index)
        # The variant is reachable from the library (its file is linked).
        self.assertIn(v_out["file"], index)


if __name__ == "__main__":
    unittest.main()
