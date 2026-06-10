// Backend error path: an SSE `error` frame must surface in the status line,
// keep the user's turn (retry is one click), drop the empty assistant turn,
// and re-enable the input.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const MESSAGE = 'This turn is doomed';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('backend error path', () => {
  test('SSE error frame shows in status, keeps the user turn, re-enables input', async ({
    page,
    request,
  }) => {
    await resetChat(request, ALPHA);

    // Replace the chat POST with a stream that fails before any delta.
    await page.route('**/api/chat', async (route) => {
      if (route.request().method() !== 'POST') {
        return route.continue();
      }
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: error\ndata: {"message":"kaboom"}\n\n',
      });
    });

    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');

    const input = page.getByTestId('chat-input');
    await input.fill(MESSAGE);
    await input.press('Enter');

    // The error lands in the status line with its error styling.
    const status = page.getByTestId('chat-status');
    await expect(status).toContainText('kaboom');
    await expect(status).toHaveClass(/(^|\s)dlc-err(\s|$)/);

    // The user turn survives; the empty assistant turn was removed.
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: MESSAGE })
    ).toBeVisible();
    await expect(page.locator('#dlc-messages .dlc-msg.dlc-user')).toHaveCount(1);
    await expect(page.locator('#dlc-messages .dlc-msg.dlc-assistant')).toHaveCount(0);

    // Ready for a retry.
    await expect(input).toBeEnabled();
    await expect(page.getByTestId('chat-send')).toBeEnabled();
  });
});
