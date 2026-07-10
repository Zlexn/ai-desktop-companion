# DeepSeek full-stack validation evidence — 2026-06-23

Scope: user manually completed a real DeepSeek UI two-turn chat and refreshed the page. This document records evidence checked after the fact. No browser driving, message sending, or model API call was performed during this evidence check.

## API evidence

- `GET /health` on `http://127.0.0.1:18082/health` returned HTTP 200 with `{"status":"ok"}`.
- `GET /api/sessions` on `http://127.0.0.1:18082` returned 1 session.
- Latest session ID: `dc6385b2-667d-4b63-beb6-5cdaf12ce6c9`.
- `GET /api/sessions/{id}/messages` returned 4 messages.
- API message role order: `user / assistant / user / assistant`.
- API assistant metadata:
  - Assistant 1: provider `deepseek`, model `deepseek-v4-flash`, finish_reason `stop`, usage `prompt_tokens=324`, `completion_tokens=16`, `total_tokens=340`, `prompt_cache_hit_tokens=0`, `prompt_cache_miss_tokens=324`.
  - Assistant 2: provider `deepseek`, model `deepseek-v4-flash`, finish_reason `stop`, usage `prompt_tokens=354`, `completion_tokens=5`, `total_tokens=359`, `prompt_cache_hit_tokens=256`, `prompt_cache_miss_tokens=98`.

## SQLite evidence

Database checked: `data/deepseek-live-ui.db`.

- Database exists.
- Tables present: `sessions`, `messages`.
- Latest session ID matches API: `dc6385b2-667d-4b63-beb6-5cdaf12ce6c9`.
- SQLite message count: 4.
- SQLite role order: `user / assistant / user / assistant`.
- The second user message asks about the test code.
- The second assistant message contains `AURORA-731`.
- Assistant metadata matches API evidence:
  - Assistant 1: provider `deepseek`, model `deepseek-v4-flash`, finish_reason `stop`, usage `prompt_tokens=324`, `completion_tokens=16`, `total_tokens=340`, `prompt_cache_hit_tokens=0`, `prompt_cache_miss_tokens=324`.
  - Assistant 2: provider `deepseek`, model `deepseek-v4-flash`, finish_reason `stop`, usage `prompt_tokens=354`, `completion_tokens=5`, `total_tokens=359`, `prompt_cache_hit_tokens=256`, `prompt_cache_miss_tokens=98`.

## Retry / call-count evidence

- `backend/app/providers/deepseek_provider.py` uses `httpx.AsyncClient` directly; httpx has no hidden automatic retry layer in this implementation.
- DeepSeek retry behavior is explicit: `attempts = settings.deepseek_max_retries + 1`.
- DeepSeek config default is `deepseek_max_retries = 0`.
- The recorded conversation has exactly two user messages and two assistant messages.
- Each assistant message has DeepSeek provider/model metadata and usage/finish_reason from the upstream response.

Conclusion: based on two user messages, two DeepSeek assistant messages, explicit no-hidden-retry implementation, and stored upstream metadata on both assistant messages, the manual UI run is consistent with exactly two upstream `POST /chat/completions` generation calls.

## Deletion evidence

After the user manually deleted the validation session in the UI, the following read-only checks were performed. No browser driving, message sending, or model API call was performed.

- `GET /health` on `http://127.0.0.1:18082/health` returned HTTP 200.
- `GET /api/sessions` on `http://127.0.0.1:18082` returned HTTP 200 with 0 sessions.
- The validation session ID `dc6385b2-667d-4b63-beb6-5cdaf12ce6c9` was not present in the API session list.
- SQLite `data/deepseek-live-ui.db` still existed during the deletion check.
- SQLite `sessions` count: 0.
- SQLite `messages` count: 0.
- SQLite rows for validation session `dc6385b2-667d-4b63-beb6-5cdaf12ce6c9`: 0 sessions, 0 messages.

## Redaction and limits

This document intentionally does not include:

- API keys.
- Authorization headers.
- Full System Prompt.
- Full request bodies.
- Full model responses.
- Full message contents.

No model API call, browser action, or message-sending action was performed while creating this document.
