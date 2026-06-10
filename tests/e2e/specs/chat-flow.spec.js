// Core send/stream/render flow against the deterministic mock backend.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const QUESTION = 'What is this lesson about?';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('chat flow', () => {
  test('Enter sends, mock reply streams in with rendered markdown, input gates correctly', async ({
    page,
    request,
  }) => {
    await resetChat(request, ALPHA);

    // Hold the POST /api/chat request on the wire briefly so the
    // "disabled while in flight" window is reliably observable.
    await page.route('**/api/chat', async (route) => {
      if (route.request().method() === 'POST') {
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      await route.continue();
    });

    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');

    const input = page.getByTestId('chat-input');
    const send = page.getByTestId('chat-send');

    await input.fill(QUESTION);
    await input.press('Enter');

    // In flight: input + send disabled.
    await expect(input).toBeDisabled();
    await expect(send).toBeDisabled();

    // The user turn appears with the typed text.
    const userBody = page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body');
    await expect(userBody).toHaveCount(1);
    await expect(userBody).toContainText(QUESTION);

    // The assistant turn streams in and eventually echoes the question.
    const assistantBody = page.locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body');
    await expect(assistantBody).toContainText(`You asked: "${QUESTION}"`, {
      timeout: 15000,
    });
    await expect(assistantBody).toContainText('Mock tutor for', { timeout: 15000 });
    await expect(assistantBody).toContainText('Fixture Lesson Alpha');

    // Markdown rendering: the mock's `code spans` becomes a real <code> element.
    await expect(assistantBody.locator('code')).toHaveText('code spans');

    // Stream done: input re-enabled.
    await expect(input).toBeEnabled({ timeout: 15000 });
    await expect(send).toBeEnabled();
  });
});
