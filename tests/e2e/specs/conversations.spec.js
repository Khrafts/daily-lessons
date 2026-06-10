// Multiple conversations per lesson: create two via "New chat", browse them in
// history, switch between them, confirm they are independent (distinct
// session_ids), and delete one without touching the other. Plus: conversation
// titles come from user text and must be rendered escaped, never as live markup.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const CHAT_ONE = 'Tell me about the first thing';
const CHAT_TWO = 'And now a completely different question';

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

test.describe('multiple conversations', () => {
  test.beforeEach(async ({ request }) => {
    await resetChat(request, ALPHA);
  });

  test('two chats: history, switch, independent sessions, delete', async ({
    page,
    request,
  }) => {
    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');

    // Chat 1.
    await sendAndAwaitReply(page, CHAT_ONE);

    // New chat -> chat 2 (no confirm in v2).
    await page.getByTestId('chat-new').click();
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(0);
    await sendAndAwaitReply(page, CHAT_TWO);

    // Open history: two rows, titled from each opening message.
    await page.getByTestId('chat-history').click();
    const convs = page.getByTestId('chat-conversations');
    await expect(convs).toBeVisible();
    const rows = convs.getByTestId('chat-conv-item');
    await expect(rows).toHaveCount(2);
    await expect(rows.filter({ hasText: CHAT_ONE })).toHaveCount(1);
    await expect(rows.filter({ hasText: CHAT_TWO })).toHaveCount(1);

    // The active conversation (chat 2) is marked.
    await expect(
      rows.filter({ hasText: CHAT_TWO })
    ).toHaveAttribute('aria-current', 'true');

    // Switch to chat 1 -> its messages load.
    await rows.filter({ hasText: CHAT_ONE }).click();
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: CHAT_ONE })
    ).toBeVisible();
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: CHAT_TWO })
    ).toHaveCount(0);

    // A typed follow-up must RESUME the switched-to conversation (chat 1) — not
    // mint a new session, not land in chat 2. This exercises the routing-after-
    // switch seam, not just the UI repaint.
    const preSwitch = await (
      await request.get(`/api/chat?lesson=${encodeURIComponent(ALPHA)}`)
    ).json();
    const c1pre = preSwitch.conversations.find((c) => c.title === CHAT_ONE);
    const c2pre = preSwitch.conversations.find((c) => c.title === CHAT_TWO);
    expect(preSwitch.active_id).toBe(c1pre.id); // switch moved active to chat 1
    await sendAndAwaitReply(page, 'A follow-up that belongs to chat one.');
    const c1after = await (
      await request.get(
        `/api/chat?lesson=${encodeURIComponent(ALPHA)}&conversation=${encodeURIComponent(c1pre.id)}`
      )
    ).json();
    expect(c1after.messages.length).toBe(4); // original exchange + this one
    expect(c1after.session_id).toBe(c1pre.session_id); // resumed, not re-minted
    const c2after = await (
      await request.get(
        `/api/chat?lesson=${encodeURIComponent(ALPHA)}&conversation=${encodeURIComponent(c2pre.id)}`
      )
    ).json();
    expect(c2after.messages.length).toBe(2); // chat 2 untouched

    // The two conversations have DIFFERENT session_ids — confirm by id via the API.
    const view = await (
      await request.get(`/api/chat?lesson=${encodeURIComponent(ALPHA)}`)
    ).json();
    expect(view.conversations.length).toBe(2);
    const c1 = view.conversations.find((c) => c.title === CHAT_ONE);
    const c2 = view.conversations.find((c) => c.title === CHAT_TWO);
    expect(c1).toBeTruthy();
    expect(c2).toBeTruthy();

    const v1 = await (
      await request.get(
        `/api/chat?lesson=${encodeURIComponent(ALPHA)}&conversation=${encodeURIComponent(c1.id)}`
      )
    ).json();
    const v2 = await (
      await request.get(
        `/api/chat?lesson=${encodeURIComponent(ALPHA)}&conversation=${encodeURIComponent(c2.id)}`
      )
    ).json();
    expect(v1.session_id).toBeTruthy();
    expect(v2.session_id).toBeTruthy();
    expect(v1.session_id).not.toBe(v2.session_id);

    // Delete chat 1 — now the ACTIVE conversation — via its per-row delete
    // affordance (accept the confirm).
    await page.getByTestId('chat-history').click();
    await expect(convs).toBeVisible();
    page.once('dialog', (dialog) => dialog.accept());
    await convs
      .getByTestId('chat-conv-item')
      .filter({ hasText: CHAT_ONE })
      .getByTestId('chat-conv-del')
      .click();

    // It disappears from the list; the other remains.
    await expect(
      convs.getByTestId('chat-conv-item').filter({ hasText: CHAT_ONE })
    ).toHaveCount(0);
    await expect(
      convs.getByTestId('chat-conv-item').filter({ hasText: CHAT_TWO })
    ).toHaveCount(1);

    // Deleting the active conversation repaints the transcript to the new active.
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: CHAT_TWO })
    ).toBeVisible();

    // Server agrees: one conversation left.
    const after = await (
      await request.get(`/api/chat?lesson=${encodeURIComponent(ALPHA)}`)
    ).json();
    expect(after.conversations.length).toBe(1);
    expect(after.conversations[0].title).toBe(CHAT_TWO);
  });

  test('conversation titles are escaped, never rendered as live markup', async ({
    page,
  }) => {
    const PAYLOAD = '<img src=x onerror="window.__dlc_pwned=1">';

    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');

    // First message of a fresh chat sets the title — make it hostile.
    await sendAndAwaitReply(page, PAYLOAD);

    // Open history and inspect the conversation list.
    await page.getByTestId('chat-history').click();
    const convs = page.getByTestId('chat-conversations');
    await expect(convs).toBeVisible();

    // The row shows the literal text...
    await expect(
      convs.getByTestId('chat-conv-item').filter({ hasText: '<img' })
    ).toHaveCount(1);
    // ...and no live <img> made it into the list.
    await expect(convs.locator('img')).toHaveCount(0);
    // The onerror never fired.
    expect(await page.evaluate(() => window.__dlc_pwned)).toBeUndefined();
  });
});
