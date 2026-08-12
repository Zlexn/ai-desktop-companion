---
name: verify
summary: Verify backend API changes through an isolated local server and SQLite database.
---

# Backend API runtime verification

1. Review `git diff HEAD --stat` and identify the changed API flow.
2. Start uvicorn with a new, uniquely named SQLite file and fake providers:

```powershell
$env:DATABASE_URL = "sqlite:///./verify-<unique>.db"
$env:LLM_PROVIDER = "fake"
$env:SESSION_SUMMARY_PROVIDER = "fake"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port <unused-port> --no-access-log
```

3. Use an HTTP client with environment proxies disabled (`httpx.Client(..., trust_env=False)` or `curl --noproxy '*'`) to drive `/health`, `/api/sessions`, and the affected message route.
4. Inspect the same isolated SQLite file to verify persisted effects; never use the normal configured database.
5. Probe one adjacent malformed/error request.
6. Stop the server. Keep evidence inline. Do not delete unknown or pre-existing database files.

Windows gotchas:

- This checkout may not have `.venv`; detect the available Python executable instead of assuming one.
- Local proxy environment variables can turn localhost HTTP requests into blank 502 responses unless bypassed.
- Use `--no-access-log` if the installed uvicorn access formatter is incompatible with the runtime logging configuration.
