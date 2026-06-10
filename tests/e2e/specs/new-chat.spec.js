// "New chat" reset flow: confirm dialog, cleared transcript, cleared server state.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const MESSAGE = 'Message that should disappear after new chat';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

async function sendAndAwaitReply(page, text) {
  const input = page.getByTestId('chat-input');
  await input.fill(text);
  await input.press('Enter');
  await expect(
    page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: text })
  ).toBeVisible();
  await expect(
    page
      .locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
      .filter({ hasText: `You asked: "${text}"` })
  ).toBeVisible({ timeout: 15000 });
  await expect(input).toBeEnabled({ timeout: 15000 });
}

test.describe('new chat', () => {
  test('clears the transcript and resets server-side state', async ({ page }) => {
    // This spec creates its own history first; it does not depend on other specs.
    await resetChat(page.request, ALPHA);
    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    await sendAndAwaitReply(page, MESSAGE);
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(2);

    // With history present, #dlc-new asks for confirmation first — accept it.
    page.on('dialog', (dialog) => dialog.accept());
    await page.getByTestId('chat-new').click();

    // Transcript empties.
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(0);

    // FAB label resets to the empty-history label.
    await expect(page.getByTestId('chat-fab')).toContainText('Ask about this lesson');

    // Server state cleared: messages [] and session_id null.
    await expect
      .poll(
        async () => {
          const res = await page.request.get(
            `/api/chat?lesson=${encodeURIComponent(ALPHA)}`
          );
          if (!res.ok()) return { error: res.status() };
          const state = await res.json();
          return { messages: state.messages, session_id: state.session_id };
        },
        { timeout: 7000 }
      )
      .toEqual({ messages: [], session_id: null });
  });
});
