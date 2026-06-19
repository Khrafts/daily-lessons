// Serve-time modes injection: a lesson page WITHOUT the daily-lesson-modes:v1
// marker block on disk must still get the tone bar + confirm modal when served,
// and the bar must actually RENDER (it is hidden until /api/renditions resolves
// the lesson's concept group) — not merely be present in the bytes.
'use strict';

const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const GAMMA = 'lessons/2026-06-09-legacy-gamma.html';
const GAMMA_ON_DISK = path.resolve(__dirname, '..', '.tmp', 'lessons-home', GAMMA);

test.describe('legacy page modes injection', () => {
  test('tone bar + confirm modal are injected at serve time and the bar renders', async ({
    page,
  }) => {
    // Guard: the fixture on disk must actually lack the modes block — otherwise
    // this spec would exercise a prerendered bar instead of serve-time injection.
    expect(fs.readFileSync(GAMMA_ON_DISK, 'utf8')).not.toContain('daily-lesson-modes:v1');

    await page.goto(`/${GAMMA}`);

    // The bar is hidden by default and only un-hides after a successful
    // /api/renditions fetch — so visibility proves both injection AND that the
    // legacy (concept_key'd, no-mode) lesson resolves to Original + 4 modes.
    await expect(page.getByTestId('modes-bar')).toBeVisible();
    await expect(
      page.locator('[data-testid="modes-tone"].is-current')
    ).toHaveText(/Original/);
    await expect(page.getByTestId('modes-generate')).toHaveCount(4);

    // The injected confirm modal is wired: clicking generate opens it (with the
    // real explanatory copy), and Cancel dismisses it without recasting.
    await page.getByTestId('modes-generate').filter({ hasText: 'Grounded' }).first().click();
    const dlg = page.getByTestId('modes-confirm');
    await expect(dlg).toBeVisible();
    await expect(page.getByTestId('modes-confirm-body')).toContainText('claude');
    await page.getByTestId('modes-confirm-cancel').click();
    await expect(dlg).toBeHidden();
  });
});
