// "New chat" (v2): NON-destructive — creates a fresh conversation, empties the
// transcript view, but the prior conversation survives and is reachable from the
// history list. No confirm() any more.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const FIRST = 'First chat message that must survive new-chat';

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

test.describe('new chat (non-destructive)', () => {
  test('creates a fresh conversation, empties the view, keeps the old one', async ({
    page,
    request,
  }) => {
    // Start from a clean lesson so the row counts below are unambiguous.
    await resetChat(request, ALPHA);
    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    await sendAndAwaitReply(page, FIRST);
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(2);

    // New chat is no longer a destructive reset: no confirm() should fire. If a
    // dialog appears the test fails (a confirm would block forever otherwise).
    let dialogSeen = false;
    page.on('dialog', (dialog) => {
      dialogSeen = true;
      dialog.dismiss().catch(() => {});
    });
    await page.getByTestId('chat-new').click();

    // The transcript view empties (the new, empty conversation is now active).
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(0);
    // FAB label resets to the empty-conversation label.
    await expect(page.getByTestId('chat-fab')).toContainText('Ask about this lesson');
    expect(dialogSeen).toBe(false);

    // The prior conversation was NOT wiped: open history and see both rows.
    await page.getByTestId('chat-history').click();
    const convs = page.getByTestId('chat-conversations');
    await expect(convs).toBeVisible();
    const rows = convs.getByTestId('chat-conv-item');
    await expect(rows).toHaveCount(2);
    // One of the rows carries the title derived from the first message.
    await expect(rows.filter({ hasText: FIRST })).toHaveCount(1);

    // Switch back to the first conversation — its messages come back.
    await rows.filter({ hasText: FIRST }).click();
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: FIRST })
    ).toBeVisible();
    await expect(
      page
        .locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
        .filter({ hasText: `You asked: "${FIRST}"` })
    ).toBeVisible();

    // The server still holds the first conversation's two messages (by id).
    const view = await (
      await page.request.get(`/api/chat?lesson=${encodeURIComponent(ALPHA)}`)
    ).json();
    expect(view.ok).toBe(true);
    expect(Array.isArray(view.conversations)).toBe(true);
    expect(view.conversations.length).toBe(2);
    const withFirst = view.conversations.find((c) => c.title === FIRST);
    expect(withFirst).toBeTruthy();
    expect(withFirst.message_count).toBe(2);
  });
});
