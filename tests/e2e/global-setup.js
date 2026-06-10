// Global setup: build a fresh fixture library in .tmp/lessons-home by running
// the REAL renderer (scripts/render_lesson.py) twice, then derive a third,
// "legacy" lesson page that has the daily-lesson-chat:v1 marker block removed
// so the chat server's serve-time injection path gets exercised.
'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const RENDERER = path.resolve(__dirname, '..', '..', 'scripts', 'render_lesson.py');
const TMP_DIR = path.join(__dirname, '.tmp');
const LESSONS_HOME = path.join(TMP_DIR, 'lessons-home');
const FIXTURE_SRC = path.join(TMP_DIR, 'fixture-src');

// Minimal canonical body fragment; render_lesson.py does not validate body
// structure, this is just enough to look like a lesson.
const BODY_FRAGMENT =
  '<h2><span class="h2n">01</span> What it is</h2>\n' +
  '<p class="lead">A fixture lesson about widget testing.</p>';

const COMMON_META = {
  dek: 'A deterministic fixture lesson used by the e2e suite.',
  one_liner: 'Fixture lesson rendered by global-setup for chat-widget e2e tests.',
  source_day: '2026-06-09',
  taught_at: '2026-06-10T03:00:00+01:00',
  tags: ['test'],
};

const LEGACY_FILE_REL = 'lessons/2026-06-09-legacy-gamma.html';

// Matches the whole widget block, dotall, including both markers.
const WIDGET_BLOCK_RE =
  /<!--\s*daily-lesson-chat:v1\s*-->[\s\S]*?<!--\s*\/daily-lesson-chat:v1\s*-->\s*/g;

function renderLesson(meta) {
  const metaPath = path.join(FIXTURE_SRC, `${meta.slug}.meta.json`);
  const bodyPath = path.join(FIXTURE_SRC, `${meta.slug}.body.html`);
  fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2) + '\n');
  fs.writeFileSync(bodyPath, BODY_FRAGMENT + '\n');
  const stdout = execFileSync(
    'python3',
    [RENDERER, '--meta', metaPath, '--body', bodyPath, '--lessons-dir', LESSONS_HOME],
    { encoding: 'utf8' }
  );
  const summary = JSON.parse(stdout.trim().split('\n').pop());
  if (!summary.ok) {
    throw new Error(`render_lesson.py reported failure for ${meta.slug}: ${stdout}`);
  }
  return summary;
}

module.exports = async function globalSetup() {
  // Always start from a clean library so every run is deterministic.
  fs.rmSync(LESSONS_HOME, { recursive: true, force: true });
  fs.mkdirSync(FIXTURE_SRC, { recursive: true });

  const alpha = renderLesson({
    slug: 'fixture-alpha',
    concept_key: 'e2e-fixture-alpha',
    title: 'Fixture Lesson Alpha',
    ...COMMON_META,
  });
  renderLesson({
    slug: 'fixture-beta',
    concept_key: 'e2e-fixture-beta',
    title: 'Fixture Lesson Beta',
    ...COMMON_META,
  });

  // Legacy fixture: lesson A's page with the entire chat-widget marker block
  // removed. If the widget has not landed in assets/lesson-shell.html yet the
  // regex simply matches nothing and the copy is already legacy-shaped.
  const alphaHtml = fs.readFileSync(path.join(LESSONS_HOME, alpha.file), 'utf8');
  const legacyHtml = alphaHtml.replace(WIDGET_BLOCK_RE, '');
  if (legacyHtml.includes('daily-lesson-chat')) {
    throw new Error(
      'global-setup: stripped gamma copy still contains "daily-lesson-chat" — ' +
        'WIDGET_BLOCK_RE no longer matches the marker block in the rendered page'
    );
  }
  fs.writeFileSync(path.join(LESSONS_HOME, LEGACY_FILE_REL), legacyHtml);

  // Register the legacy page in the ledger so the library lists it.
  const ledgerPath = path.join(LESSONS_HOME, 'index.json');
  const ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
  const alphaRecord = ledger.find((r) => r.slug === 'fixture-alpha');
  if (!alphaRecord) {
    throw new Error('global-setup: fixture-alpha record missing from index.json');
  }
  ledger.push({
    ...alphaRecord,
    id: '2026-06-09-001',
    slug: 'legacy-gamma',
    concept_key: 'e2e-fixture-legacy-gamma',
    title: 'Fixture Lesson Gamma (legacy)',
    file: LEGACY_FILE_REL,
  });
  fs.writeFileSync(ledgerPath, JSON.stringify(ledger, null, 2) + '\n');

  // index.html is generated from the ledger, so regenerate it to make the
  // library actually list the legacy row.
  execFileSync('python3', [RENDERER, '--rebuild-library', '--lessons-dir', LESSONS_HOME], {
    encoding: 'utf8',
  });

  // Belt and braces: never inherit chat state from a previous run.
  fs.rmSync(path.join(LESSONS_HOME, 'chats.json'), { force: true });
};
