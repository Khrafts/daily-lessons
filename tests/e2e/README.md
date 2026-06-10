Prerequisites: Node 20+, `python3` on PATH (runs `scripts/render_lesson.py` for fixtures and `scripts/chat_server.py` as the web server), and Chromium via `npx playwright install chromium`.
Install: `cd tests/e2e && npm install`.
Run: `npx playwright test` — global setup builds a fresh fixture library in `.tmp/lessons-home/` and Playwright boots the mock chat server on port 8799 automatically.
Screenshots land in `tests/e2e/test-results/shots/`; the HTML report is in `tests/e2e/playwright-report/`.
