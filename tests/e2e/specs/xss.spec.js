// Hostile message content must render inert — on the live stream AND on the
// restored transcript. The mock echoes the message inside 'You asked: "..."',
// so one send exercises both the user path (escHtml) and the assistant
// markdown path (mdToHtml).
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const PAYLOAD =
  '<img src=x onerror="window.__dlc_pwned=1"> **bold** ' +
  '<script>window.__dlc_pwned=2</script>';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

async function assertInert(page) {
  const messages = page.locator('#dlc-messages');

  // No active elements made it into the DOM, on either path.
  await expect(messages.locator('img')).toHaveCount(0);
  await expect(messages.locator('script')).toHaveCount(0);

  // The user turn shows the payload as literal text.
  await expect(
    page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body')
  ).toContainText('<img');

  // Neither the onerror nor the script body ever executed.
  expect(await page.evaluate(() => window.__dlc_pwned)).toBeUndefined();

  // Escaping did not kill markdown: **bold** still becomes a real <strong>.
  await expect(
    page.locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body strong')
  ).toHaveText('bold');
}

test.describe('xss hardening', () => {
  test('hostile markup is inert when streamed and when restored', async ({
    page,
    request,
  }) => {
    await resetChat(request, ALPHA);
    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');

    const input = page.getByTestId('chat-input');
    await input.fill(PAYLOAD);
    await input.press('Enter');

    // Wait for the full mock reply, then for the turn to finish.
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
    ).toContainText('Mock tutor for', { timeout: 15000 });
    await expect(input).toBeEnabled({ timeout: 15000 });

    await assertInert(page);

    // Reload: the transcript is re-rendered from chats.json — the restore
    // path must be exactly as inert as the streaming path.
    await page.reload();
    await expect(page.getByTestId('chat-fab')).toContainText('Continue the chat');
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(2);

    await assertInert(page);
  });
});
