// Playwright config for the daily-lesson chat e2e suite.
//
// The webServer block boots scripts/chat_server.py with the deterministic
// --backend mock against the fixture library that global-setup.js builds in
// .tmp/lessons-home. Specs are written to be order-independent (each resets
// the chat state it relies on), but we still run a single worker so the
// shared chats.json on disk is never written by two specs at once.
'use strict';

const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: path.join(__dirname, 'specs'),
  globalSetup: require.resolve('./global-setup'),
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }]],
  expect: {
    timeout: 7000,
  },
  use: {
    baseURL: 'http://127.0.0.1:8799',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command:
      'python3 ../../scripts/chat_server.py --lessons-dir .tmp/lessons-home --backend mock --port 8799',
    cwd: __dirname,
    url: 'http://127.0.0.1:8799/api/health',
    reuseExistingServer: false,
    timeout: 15000,
  },
});
