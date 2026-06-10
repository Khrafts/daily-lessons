// Visual artifacts for review: full-page screenshots into test-results/shots/.
'use strict';

const path = require('path');
const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const BETA = 'lessons/2026-06-10-fixture-beta.html';
const SHOTS_DIR = path.resolve(__dirname, '..', 'test-results', 'shots');

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('desktop screenshots', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('lesson closed, drawer open empty, drawer after reply', async ({
    page,
    request,
  }) => {
    await resetChat(request, BETA);
    await page.goto(`/${BETA}`);

    const fab = page.getByTestId('chat-fab');
    const panel = page.getByTestId('chat-panel');
    await expect(fab).toBeVisible();
    await expect(fab).toContainText('Ask about this lesson');
    await page.screenshot({
      path: path.join(SHOTS_DIR, 'lesson-closed.png'),
      fullPage: true,
    });

    await fab.click();
    await expect(panel).toHaveAttribute('data-open', 'true');
    await page.screenshot({
      path: path.join(SHOTS_DIR, 'drawer-open-empty.png'),
      fullPage: true,
    });

    const input = page.getByTestId('chat-input');
    await input.fill('Show me a rendered reply');
    await input.press('Enter');
    await expect(
      page
        .locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
        .filter({ hasText: 'You asked: "Show me a rendered reply"' })
    ).toBeVisible({ timeout: 15000 });
    await expect(input).toBeEnabled({ timeout: 15000 });
    await page.screenshot({
      path: path.join(SHOTS_DIR, 'drawer-after-reply.png'),
      fullPage: true,
    });
  });
});

test.describe('mobile screenshots', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('drawer open on mobile', async ({ page, request }) => {
    await resetChat(request, ALPHA);
    await page.goto(`/${ALPHA}?chat=1`);
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    await page.screenshot({
      path: path.join(SHOTS_DIR, 'drawer-open.png'),
      fullPage: true,
    });
  });
});
