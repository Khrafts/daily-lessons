// file:// with a chat server running on 127.0.0.1:8787: the FAB becomes a
// bridge that hands the reader off to the same lesson on the server origin
// with the drawer auto-opening.
'use strict';

const net = require('net');
const path = require('path');
const { spawn } = require('child_process');
const { pathToFileURL } = require('url');
const { test, expect } = require('@playwright/test');

const ALPHA = 'lessons/2026-06-10-fixture-alpha.html';
const LESSONS_HOME = path.resolve(__dirname, '..', '.tmp', 'lessons-home');
const ALPHA_ON_DISK = path.join(LESSONS_HOME, ALPHA);
const SERVER = path.resolve(__dirname, '..', '..', '..', 'scripts', 'chat_server.py');
const BRIDGE_PORT = 8787;
const BRIDGE_HEALTH = `http://127.0.0.1:${BRIDGE_PORT}/api/health`;

function portOccupied(port) {
  return new Promise((resolve) => {
    const sock = net.connect({ port, host: '127.0.0.1' });
    sock.setTimeout(1000);
    sock.once('connect', () => {
      sock.destroy();
      resolve(true);
    });
    sock.once('error', () => resolve(false));
    sock.once('timeout', () => {
      sock.destroy();
      resolve(false);
    });
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise((resolve) => child.once('exit', resolve));
  child.kill('SIGTERM');
  const terminated = await Promise.race([
    exited.then(() => true),
    delay(2000).then(() => false),
  ]);
  if (!terminated) {
    child.kill('SIGKILL');
    await Promise.race([exited, delay(2000)]);
  }
}

test.describe('bridge mode over file://', () => {
  test('FAB hands off to the same lesson on the server origin with ?chat=1', async ({
    page,
    request,
  }) => {
    // Precondition: something already listening on 8787 (a real user server,
    // a stale child) makes ownership of the port ambiguous — skip.
    test.skip(
      await portOccupied(BRIDGE_PORT),
      `port ${BRIDGE_PORT} is already occupied`
    );

    // Second mock server on the bridge port, same fixture library.
    const child = spawn(
      'python3',
      [
        SERVER,
        '--lessons-dir',
        LESSONS_HOME,
        '--backend',
        'mock',
        '--port',
        String(BRIDGE_PORT),
      ],
      { stdio: 'ignore' }
    );
    try {
      await expect
        .poll(
          async () => {
            try {
              const res = await request.get(BRIDGE_HEALTH, { timeout: 1000 });
              if (!res.ok()) return 'unhealthy';
              return (await res.json()).app;
            } catch {
              return 'down';
            }
          },
          {
            timeout: 10000,
            message: `second chat_server did not become healthy on :${BRIDGE_PORT}`,
          }
        )
        .toBe('daily-lesson-chat');

      await page.goto(pathToFileURL(ALPHA_ON_DISK).href);

      const fab = page.getByTestId('chat-fab');
      await expect(fab).toBeVisible();
      await expect(fab).toContainText('Open lesson chat');

      // One click: same lesson, server origin, drawer auto-opens via ?chat=1.
      await fab.click();
      await expect(page).toHaveURL(`http://127.0.0.1:${BRIDGE_PORT}/${ALPHA}?chat=1`);
      await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-open', 'true');
    } finally {
      await stopChild(child);
    }
  });
});
