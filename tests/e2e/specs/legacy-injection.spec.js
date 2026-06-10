// Serve-time widget injection: a lesson page WITHOUT the daily-lesson-chat:v1
// marker block on disk must still get the widget when served.
'use strict';

const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const GAMMA = 'lessons/2026-06-09-legacy-gamma.html';
const GAMMA_ON_DISK = path.resolve(__dirname, '..', '.tmp', 'lessons-home', GAMMA);
const MESSAGE = 'Hello from the legacy page';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('legacy page injection', () => {
  test('widget is injected at serve time and a message round-trips', async ({
    page,
    request,
  }) => {
    await resetChat(request, GAMMA);

    // Guard: the fixture on disk must actually be legacy-shaped — otherwise
    // this spec would silently exercise the prerendered widget instead of
    // serve-time injection.
    expect(fs.readFileSync(GAMMA_ON_DISK, 'utf8')).not.toContain('daily-lesson-chat:v1');

    await page.goto(`/${GAMMA}`);

    // The on-disk file has no widget block; if the FAB exists the server
    // injected it while serving.
    const fab = page.getByTestId('chat-fab');
    await expect(fab).toBeVisible();
    await expect(fab).toContainText('Ask about this lesson');

    await fab.click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');

    const input = page.getByTestId('chat-input');
    await input.fill(MESSAGE);
    await input.press('Enter');

    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: MESSAGE })
    ).toBeVisible();
    await expect(
      page
        .locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
        .filter({ hasText: `You asked: "${MESSAGE}"` })
    ).toBeVisible({ timeout: 15000 });
    await expect(input).toBeEnabled({ timeout: 15000 });
  });
});
