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

    // chats.json on disk follows the documented schema:
    // {"lessons/<f>.html": {"session_id": str|null, "messages": [{role, text, ts}]}}.
    // Beta's entry holds all 4 messages and the API-reported session id.
    await expect
      .poll(
        () => {
          try {
            const entry = JSON.parse(fs.readFileSync(CHATS_JSON, 'utf8'))[BETA];
            return entry && Array.isArray(entry.messages) ? entry.messages.length : -1;
          } catch {
            return -1;
          }
        },
        { timeout: 7000 }
      )
      .toBe(4);

    const entry = JSON.parse(fs.readFileSync(CHATS_JSON, 'utf8'))[BETA];
    expect(entry.session_id).toBe(sessionAfterFirst);
    expect(entry.messages.map((m) => m.role)).toEqual([
      'user',
      'assistant',
      'user',
      'assistant',
    ]);
    expect(entry.messages[0].text).toBe(FIRST);
    expect(entry.messages[1].text).toContain(`You asked: "${FIRST}"`);
    expect(entry.messages[2].text).toBe(SECOND);
    expect(entry.messages[3].text).toContain(`You asked: "${SECOND}"`);
  });
});
