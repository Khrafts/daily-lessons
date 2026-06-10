// Expand toggle: the drawer can widen into a centered reading column, and the
// choice persists in localStorage across reloads.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';

async function resetChat(request, lessonParam) {
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('expand toggle', () => {
  test.beforeEach(async ({ request }) => {
    await resetChat(request, ALPHA);
  });

  test('toggles the panel width and persists the choice across reloads', async ({
    page,
  }) => {
    // Start from a known, collapsed localStorage state. Do this AFTER the first
    // navigation (so the origin exists) and only once — clearing it on every
    // navigation would wipe the very persistence this spec is verifying.
    await page.goto(`/${ALPHA}`);
    await page.evaluate(() => {
      try {
        window.localStorage.removeItem('dlc-expanded');
      } catch (e) {}
    });
    await page.reload();

    await page.getByTestId('chat-fab').click();
    const panel = page.getByTestId('chat-panel');
    await expect(panel).toHaveAttribute('data-open', 'true');

    // Default is collapsed.
    await expect(panel).toHaveAttribute('data-expanded', 'false');
    const expandBtn = page.getByTestId('chat-expand');
    await expect(expandBtn).toBeVisible();
    await expect(expandBtn).toHaveAttribute('aria-pressed', 'false');

    // Expand.
    await expandBtn.click();
    await expect(panel).toHaveAttribute('data-expanded', 'true');
    await expect(expandBtn).toHaveAttribute('aria-pressed', 'true');
    // Persisted to localStorage as "1".
    expect(await page.evaluate(() => window.localStorage.getItem('dlc-expanded'))).toBe(
      '1'
    );

    // Reload: still expanded, applied at init (open the drawer to observe).
    await page.reload();
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-expanded', 'true');
    await expect(page.getByTestId('chat-expand')).toHaveAttribute('aria-pressed', 'true');

    // Collapse again, and that too persists.
    await page.getByTestId('chat-expand').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-expanded', 'false');
    expect(await page.evaluate(() => window.localStorage.getItem('dlc-expanded'))).toBe(
      '0'
    );

    await page.reload();
    await page.getByTestId('chat-fab').click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-expanded', 'false');
  });
});
