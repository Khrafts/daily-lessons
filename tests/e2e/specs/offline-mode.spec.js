// file:// with no chat server on 127.0.0.1:8787: the widget must fall back to
// the offline panel — instructions instead of a dead input.
'use strict';

const path = require('path');
const { pathToFileURL } = require('url');
const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const ALPHA_ON_DISK = path.resolve(__dirname, '..', '.tmp', 'lessons-home', ALPHA);
const BRIDGE_HEALTH = 'http://127.0.0.1:8787/api/health';

test.describe('offline mode over file://', () => {
  test('FAB appears, drawer shows the offline panel, input is hidden', async ({
    page,
    request,
  }) => {
    // Precondition: a real user server answering on 8787 would flip the
    // widget into bridge mode and make this spec non-deterministic.
    let serverUp = false;
    try {
      serverUp = (await request.get(BRIDGE_HEALTH, { timeout: 1000 })).ok();
    } catch {
      // connection refused / timeout — exactly what this spec needs
    }
    test.skip(serverUp, 'a chat server is already answering on 127.0.0.1:8787');

    await page.goto(pathToFileURL(ALPHA_ON_DISK).href);

    // The probe fails, the widget settles into offline mode, the FAB appears.
    const fab = page.getByTestId('chat-fab');
    await expect(fab).toBeVisible();

    await fab.click();
    await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    await expect(page.getByTestId('chat-offline')).toBeVisible();

    // Offline presentation: no usable composer.
    await expect(page.getByTestId('chat-input')).toBeHidden();
    await expect(page.getByTestId('chat-send')).toBeHidden();
  });
});
