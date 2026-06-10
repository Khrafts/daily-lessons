// Per-lesson chat isolation: messages sent on lesson A must not appear on lesson B.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const BETA = 'lessons/2026-06-10-fixture-beta.html';
const PROBE = 'alpha-only-isolation-probe-7f3a';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('per-lesson isolation', () => {
  test("lesson B's transcript does not contain lesson A's messages", async ({
    page,
    request,
  }) => {
    await resetChat(request, ALPHA);
    await resetChat(request, BETA);

    // Chat on lesson A.
    await page.goto(`/${ALPHA}`);
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    const input = page.getByTestId('chat-input');
    await input.fill(PROBE);
    await input.press('Enter');
    await expect(
      page
        .locator('#dlc-messages .dlc-msg.dlc-assistant .dlc-body')
        .filter({ hasText: `You asked: "${PROBE}"` })
    ).toBeVisible({ timeout: 15000 });
    await expect(input).toBeEnabled({ timeout: 15000 });

    // Open lesson B: init must restore an EMPTY transcript. The widget's
    // history GET during init is the real "init ran" signal — wait for it so
    // the empty-transcript assertions below cannot pass before init finished.
    const betaHistory = page.waitForResponse(
      (res) =>
        res.request().method() === 'GET' &&
        res.url().includes(`/api/chat?lesson=${encodeURIComponent(BETA)}`)
    );
    await page.goto(`/${BETA}`);
    const history = await (await betaHistory).json();
    expect(history.messages).toEqual([]);
    await expect(page.locator('#dlc-messages .dlc-msg')).toHaveCount(0);
    await expect(page.locator('#dlc-messages')).not.toContainText(PROBE);

    // Cross-check via the API: A holds the exchange, B holds nothing.
    const alphaState = await (
      await request.get(`/api/chat?lesson=${encodeURIComponent(ALPHA)}`)
    ).json();
    expect(alphaState.messages.length).toBeGreaterThanOrEqual(2);
    expect(alphaState.messages.some((m) => String(m.text).includes(PROBE))).toBe(true);

    const betaState = await (
      await request.get(`/api/chat?lesson=${encodeURIComponent(BETA)}`)
    ).json();
    expect(betaState.messages).toEqual([]);
  });
});
