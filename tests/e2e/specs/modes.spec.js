// Lesson tone bar: switch between renditions + generate a new tone (mock backend).
'use strict';

const { test, expect } = require('@playwright/test');

// The fixture lessons are rendered with no mode, so each shows as "Original"
// with all four modes available to generate.
const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';

test.describe('lesson tone bar', () => {
  test('shows tones, generates a new tone, navigates, and switches back', async ({
    page,
  }) => {
    await page.goto('/' + ALPHA);

    const bar = page.getByTestId('modes-bar');
    await expect(bar).toBeVisible();

    // The primary is "Original"; the four modes are offered as generate buttons.
    await expect(
      page.locator('[data-testid="modes-tone"].is-current')
    ).toHaveText(/Original/);
    await expect(page.getByTestId('modes-generate')).toHaveCount(4);

    // Generate the Tutorial rendition (mock backend → instant) and follow it.
    await page
      .getByTestId('modes-generate')
      .filter({ hasText: 'Tutorial' })
      .first()
      .click();
    await page.waitForURL(/fixture-alpha-tutorial\.html/, { timeout: 20000 });

    // On the new rendition, Tutorial is the current tone…
    await expect(
      page.locator('[data-testid="modes-tone"].is-current')
    ).toHaveText(/Tutorial/);
    // …and all the other features (chat) are present on this page too.
    await expect(page.getByTestId('chat-fab')).toBeVisible();

    // Switching is navigation: jump back to the Original rendition.
    await page
      .getByTestId('modes-tone')
      .filter({ hasText: 'Original' })
      .first()
      .click();
    await page.waitForURL(/fixture-alpha\.html(\?|$)/, { timeout: 10000 });
    await expect(
      page.locator('[data-testid="modes-tone"].is-current')
    ).toHaveText(/Original/);
    // Tutorial is now an existing tone (a switch chip), no longer offered to generate.
    await expect(
      page.getByTestId('modes-tone').filter({ hasText: 'Tutorial' })
    ).toHaveCount(1);
  });
});
