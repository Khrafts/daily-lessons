// Transcript persistence across reloads + chats.json session continuity.
'use strict';

const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const BETA = 'lessons/2026-06-10-fixture-beta.html';
const CHATS_JSON = path.resolve(__dirname, '..', '.tmp', 'lessons-home', 'chats.json');
const FIRST = 'First message for beta';
const SECOND = 'Second message for beta';

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

async function fetchChatState(request, lessonParam) {
  const res = await request.get(`/api/chat?lesson=${encodeURIComponent(lessonParam)}`);
  if (!res.ok()) {
    throw new Error(`GET /api/chat failed for ${lessonParam}: HTTP ${res.status()}`);
  }
  return res.json();
}

test.describe('continuity across reloads', () => {
  test('transcript is restored, session_id is stable, chats.json grows to 4 messages', async ({
    page,
    request,
  }) => {
    await resetChat(request, BETA);

    // First exchange.
    await page.goto(`/${BETA}`);
    const fab = page.getByTestId('chat-fab');
    await fab.click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    await sendAndAwaitReply(page, FIRST);

    let sessionAfterFirst;
    await expect
      .poll(
        async () => {
          const state = await fetchChatState(request, BETA);
          sessionAfterFirst = state.session_id;
          return state.messages.length;
        },
        { timeout: 7000 }
      )
      .toBe(2);
    expect(sessionAfterFirst).toBeTruthy();

    // Reload: transcript restored, FAB label flips to "Continue the chat".
    await page.reload();
    await expect(fab).toContainText('Continue the chat');
    await fab.click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(2);
    await expect(
      page.locator('#dlc-messages .dlc-msg.dlc-user .dlc-body').filter({ hasText: FIRST })
    ).toBeVisible();
    await expect(
      page
        .locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
        .filter({ hasText: `You asked: "${FIRST}"` })
    ).toBeVisible();

    // Second exchange after the reload.
    await sendAndAwaitReply(page, SECOND);

    // Same session across both turns, now 4 messages.
    let sessionAfterSecond;
    await expect
      .poll(
        async () => {
          const state = await fetchChatState(request, BETA);
          sessionAfterSecond = state.session_id;
          return state.messages.length;
        },
        { timeout: 7000 }
      )
      .toBe(4);
    expect(sessionAfterSecond).toBe(sessionAfterFirst);

    // chats.json on disk follows the v2 schema:
    //   {"lessons/<f>.html": {"active_id": <id|null>,
    //      "conversations": [{id, session_id, title, messages:[{role,text,ts}], ...}]}}.
    // The ACTIVE conversation holds all 4 messages and the API-reported session id.
    function activeConv() {
      try {
        const entry = JSON.parse(fs.readFileSync(CHATS_JSON, 'utf8'))[BETA];
        if (!entry || !Array.isArray(entry.conversations)) return null;
        // Strictly require active_id to resolve — no positional fallback, so the
        // test fails (rather than silently passing) if active_id ever stops
        // pointing at the live conversation.
        return entry.conversations.find((c) => c.id === entry.active_id) || null;
      } catch {
        return null;
      }
    }

    await expect
      .poll(
        () => {
          const conv = activeConv();
          return conv && Array.isArray(conv.messages) ? conv.messages.length : -1;
        },
        { timeout: 7000 }
      )
      .toBe(4);

    const conv = activeConv();
    expect(conv).toBeTruthy();
    expect(conv.session_id).toBe(sessionAfterFirst);
    expect(conv.messages.map((m) => m.role)).toEqual([
      'user',
      'assistant',
      'user',
      'assistant',
    ]);
    expect(conv.messages[0].text).toBe(FIRST);
    expect(conv.messages[1].text).toContain(`You asked: "${FIRST}"`);
    expect(conv.messages[2].text).toBe(SECOND);
    expect(conv.messages[3].text).toContain(`You asked: "${SECOND}"`);
  });
});
