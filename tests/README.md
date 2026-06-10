# Tests

Run the suite from the repo root with `python3 -m unittest` (or, equivalently,
`python3 -m unittest discover -s tests`) — stdlib `unittest` only, no pytest,
no pip installs. The empty `__init__.py` makes bare discovery find the suite;
`e2e/` has no `__init__.py`, so the Playwright suite is never descended into.
The tests boot the real `scripts/chat_server.py` on an OS-assigned port with
the deterministic mock backend and a throwaway lessons dir, so they never
touch your library in `~/.claude/daily-lessons`, never spawn the real `claude`
CLI, and burn no tokens. The claude-backend tests run against a fake `claude`
executable in a tempdir that records its argv and stdin.
`fixtures/stream_json_sample.jsonl` mirrors the real CLI's
`--output-format stream-json` line shapes and drives the parser tests.
