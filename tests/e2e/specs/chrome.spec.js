// Library chrome + drawer open/close mechanics.
'use strict';

const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';

async function resetChat(request, lessonParam) {
  // Lesson identity is passed both as query param and JSON body so the test
  // is agnostic to which one the server reads.
  const res = await request.post(
    `/api/chat/reset?lesson=${encodeURIComponent(lessonParam)}`,
    { data: { lesson: lessonParam } }
  );
  if (!res.ok()) {
    throw new Error(`chat reset failed for ${lessonParam}: HTTP ${res.status()}`);
  }
}

test.describe('library and drawer chrome', () => {
  test('library page lists the three fixture lessons', async ({ page }) => {
    await page.goto('/');
    const rows = page.locator('ul.list li.row');
    await expect(rows).toHaveCount(3);
    await expect(page.locator('ul.list')).toContainText('Fixture Lesson Alpha');
    await expect(page.locator('ul.list')).toContainText('Fixture Lesson Beta');
    await expect(page.locator('ul.list')).toContainText('Fixture Lesson Gamma (legacy)');
  });

  test('clicking a library row opens the lesson page', async ({ page }) => {
    await page.goto('/');
    await page
      .locator('li.row a.title')
      .filter({ hasText: 'Fixture Lesson Alpha' })
      .click();
    await expect(page).toHaveURL(/lessons\/2026-06-10-fixture-alpha\.html/);
    await expect(page.locator('h1')).toHaveText('Fixture Lesson Alpha');
  });

  test('FAB is visible with the empty-history label and the drawer opens/closes', async ({
    page,
    request,
  }) => {
    await resetChat(request, ALPHA);
    await page.goto(`/${ALPHA}`);

    const fab = page.getByTestId('chat-fab');
    const panel = page.getByTestId('chat-panel');

    await expect(fab).toBeVisible();
    await expect(fab).toContainText('Ask about this lesson');

    // Closed by default.
    await expect(panel).not.toHaveAttribute('data-open', 'true');

    // FAB opens.
    await fab.click();
    await expect(panel).toHaveAttribute('data-open', 'true');

    // Escape closes.
    await page.keyboard.press('Escape');
    await expect(panel).not.toHaveAttribute('data-open', 'true');

    // FAB re-opens, the close button closes.
    await fab.click();
    await expect(panel).toHaveAttribute('data-open', 'true');
    await page.getByTestId('chat-close').click();
    await expect(panel).not.toHaveAttribute('data-open', 'true');
  });

  test('?chat=1 auto-opens the drawer after init', async ({ page, request }) => {
    await resetChat(request, ALPHA);
    await page.goto(`/${ALPHA}?chat=1`);
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
  });
});
