# Gate C2 Controlled Session Summary Design

**Date:** 2026-07-21  
**Status:** DESIGN APPROVED — implementation requires a separate file-level plan and review  
**Scope:** Gate C2 only  
**Prerequisite:** Gate C1 accepted and deployed  
**Parent design:** `docs/superpowers/specs/2026-07-16-automatic-memory-persona-consistency-enhancement-design.md`  
**C1 design:** `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c1-persona-context-design.md`

## 1. Purpose

Gate C2 adds a privacy-safe session-summary lifecycle:

1. durable summary jobs and metadata-only status;
2. an independent consent for remote summary processing;
3. a separate consent or local enablement decision for summary injection;
4. exact, turn-closed summary provenance;
5. transactional invalidation and payload redaction when memory is truly forgotten;
6. controlled, explicit rebuild with durable suppression authority;
7. deterministic, low-trust summary selection through the C1 Context Composer;
8. a minimal SummaryPanel.

C2 reuses the existing summary generator, Gate B deletion barrier/source exclusions, and C1 data encoder where safe. It does not create or update structured memories, Persona artifacts, relationship events/projections, or Stage 4 emotion state. C3 remains a separate, unauthorized implementation gate.

## 2. Hard invariants

- Environment configuration is not consent.
- Remote summary-processing consent, summary-injection consent, chat authorization, remote memory-extraction consent, automatic-memory write consent, and remote emotion-analysis consent are mutually non-substitutable authorities.
- Default, declined, revoked, stale, or fingerprint-mismatched remote-processing authority produces zero remote summary Provider construction and zero remote send.
- Default, declined, revoked, stale, or fingerprint-mismatched injection authority produces zero injected summary fragments.
- Generation and injection are independent: a summary may be generated but never injected; injection permission does not authorize new summary generation calls.
- Summary text is low-trust derived data. It cannot create or modify memory, Persona, relationship state, emotion state, or permissions.
- A summary cannot bypass a tombstone, deletion generation, summary barrier, source exclusion, source-set suppression, or session deletion.
- Summary lookup, ranking, generation, rebuild, status, or injection failure never blocks text chat.
- Provider I/O never occurs while holding a SQLite write transaction.
- Every summary source set is exact, ordered, and closed over complete chat turns.
- Excluding either member of a turn excludes the complete turn, including an assistant reply that repeats forgotten user content.
- Any persisted derived payload affected by true forget is removed from raw SQLite, not merely hidden by repository readers.
- An automatic scheduler cannot reverse a user summary redaction or consume an explicit rebuild permit.
- Summary fragments are serialized only through C1's versioned untrusted-data encoder.
- Logs, public audits, and public APIs do not store or expose source text, hidden Prompt, raw Provider response, credentials, HMAC material, deleted summary payload, or private internal hashes/fingerprints. Dedicated private SQLite authority, job, summary, and suppression columns may persist non-reversible source-set hashes, policy fingerprints, logical identities, and attempt epochs strictly where required for consent binding, idempotency, suppression, and commit revalidation. They are never copied into normal logs, public audit responses, frontend state, or acceptance artifacts. Raw HMAC keys, credentials, source text, Prompts, and deleted payloads remain forbidden outside their explicitly authorized payload stores.

## 3. Scope and exclusions

### 3.1 In scope

- additive and privacy-reconciling SQLite migration;
- durable chat-turn identity for summary provenance;
- exact summary-source maps;
- summary payload state and immutable replacement lineage;
- independent processing and injection authorities;
- summary dispatch fencing and in-flight result discard;
- durable job recovery and idempotency;
- suppression and one-time rebuild permits;
- deterministic current/cross-session retrieval and injection;
- SummaryPanel and metadata-only status APIs;
- Gate A/B/C1 privacy, deletion, conflict, and context regressions.

### 3.2 Out of scope

- relationship events/projection or relationship-derived emotion;
- feeding summaries to Memory Governor, any memory extractor, or future relationship derivation;
- arbitrary LLM-generated Persona changes;
- Electron, Live2D, visual assets, voice cloning, packaging, or private media ingestion;
- real remote-Provider claims when only fake/local test doubles were used;
- commit, push, distribution, or publication.

## 4. Independent authority model

### 4.1 Remote summary-processing consent

`summary_processing_consents` stores one authority for the configured remote summarizer:

```text
scope_id                    TEXT PRIMARY KEY
status                      unknown | granted | declined | revoked
disclosure_version          TEXT NULL
purpose                     TEXT NULL
provider                    TEXT NULL
disclosed_fields_json       TEXT NOT NULL
policy_fingerprint          TEXT NULL
generation                  INTEGER NOT NULL
updated_at                  TEXT NOT NULL
```

A grant is valid only when all of these match current configuration exactly:

- status is `granted`;
- disclosure version;
- purpose;
- exact disclosed-field set;
- Provider;
- Provider/model/configuration policy fingerprint;
- captured generation.

The disclosed fields are bounded ordered source-message role/content values and necessary non-sensitive structural labels. The consent never authorizes the whole database, unrelated sessions, memories, Persona payload history, relationship state, emotion records, or private assets.

Changing Provider, model, endpoint policy, summarizer schema, purpose, or field set invalidates the authority. An environment variable may select a route but cannot create a grant.

### 4.2 Summary-injection authority

`summary_injection_consents` independently governs use of historical summary text in chat context:

```text
scope_id                    TEXT PRIMARY KEY
status                      unknown | granted | declined | revoked
disclosure_version          TEXT NULL
chat_provider_fingerprint   TEXT NULL
disclosed_fields_json       TEXT NOT NULL
generation                  INTEGER NOT NULL
max_fragment_count          INTEGER NOT NULL
max_total_characters        INTEGER NOT NULL
updated_at                  TEXT NOT NULL
```

For a remote chat Provider, injection requires an exact, current `granted` record. Validity requires equality for every persisted disclosure component: status; consent generation; disclosure version; exact disclosed-field set; maximum fragment count; maximum total summary characters; and the current chat Provider/model/endpoint/configuration policy fingerprint. Changing any one component invalidates the grant and requires a new explicit grant before any summary can be selected or dispatched. Until re-granted, selection and send counts are both zero. It authorizes only:

- eligible bounded `summary_text`;
- low-trust type label;
- source session ID;
- summary ID/source kind/created time required for context provenance.

For a genuinely local chat Provider, the UI exposes an explicit local enable/disable decision under the same generation model, while making no remote-disclosure claim. In both cases, default is off.

Generation may continue under its own valid local/remote authority while injection is off. Injection authority cannot authorize a new summarizer call. Processing authority cannot inject anything into chat.

### 4.3 Mutation rules

Both authority records:

- are changed only through explicit API/UI actions;
- increment a monotonic generation;
- use expected generation/CAS;
- expose the applicable disclosure before grant;
- are independently revocable;
- record metadata-only audit;
- never accept a grant from environment configuration.

## 5. Turn-closed source provenance

### 5.1 Durable chat turns

`chat_turns` binds one user message to its derived assistant reply:

```text
id                          TEXT PRIMARY KEY
session_id                  TEXT NOT NULL
user_message_id             TEXT NOT NULL UNIQUE
assistant_message_id        TEXT NOT NULL UNIQUE
turn_order                  INTEGER NOT NULL
created_at                  TEXT NOT NULL
UNIQUE(session_id, turn_order)
```

New successful chats persist this relation atomically with the assistant reply or in the same managed transaction boundary that establishes reply success. A failed Provider call has no completed `chat_turn`.

C1 still sends the current user message exactly once. C2 uses `chat_turns` only for summary provenance and deletion closure; it does not change conversational authority.

### 5.2 Legacy turn reconstruction

Migration reconstructs existing turn pairs only when role order and session membership make the pairing deterministic and one-to-one. It never guesses across ambiguous sequences, missing messages, duplicate roles, or deleted coverage boundaries.

An ambiguous historical segment is `legacy_unverified`. A summary depending on such a segment is redacted during C2 migration and cannot be injected or rebuilt from that mapping.

### 5.3 Exact source map

`session_summary_sources` records exactly what was sent:

```text
summary_id                  TEXT NOT NULL
chat_turn_id                TEXT NOT NULL
message_id                  TEXT NOT NULL
turn_order                  INTEGER NOT NULL
message_order_in_turn       INTEGER NOT NULL
source_order                INTEGER NOT NULL
PRIMARY KEY(summary_id, message_id)
UNIQUE(summary_id, source_order)
```

Every new summary source set consists of complete turns: the user and derived assistant message are both present in canonical order. The ordered source-set hash is computed over internal IDs, turn/message ordering, and the hash schema version. It remains internal and never appears in public API or normal logs.

### 5.4 Turn-closure exclusion

A source exclusion applies to the complete containing turn. If either the user or assistant member is excluded, both members are ineligible for:

- generation snapshots;
- source-set hashing;
- Provider input;
- commit validation;
- summary eligibility;
- barrier revalidation;
- rebuild input;
- context injection.

Gate B true forget and C2 migration expand reconstructable existing exclusions to all members of their turn in the same write transaction. This closes the case where an assistant reply repeats a forgotten value.

## 6. Summary payload and provenance model

`session_summaries` gains compatible fields:

```text
payload_state               active | redacted | quarantined
source_set_hash             TEXT NULL
summarizer_schema_version   TEXT NULL
injection_schema_version    TEXT NULL
replaces_summary_id         TEXT NULL
provenance_state            exact | legacy_unverified
redacted_at                 TEXT NULL
redaction_reason_code       TEXT NULL
```

`summary_text` becomes nullable only for `redacted` or `quarantined` rows. Constraints require:

- active payload has non-empty bounded text;
- redacted/quarantined payload is `NULL`;
- a new generated row has exact source mapping and supported schema;
- a replacement points to an older summary from the same session;
- replacement lineage is acyclic.

Generated payload is credential-sanitized, bounded, non-empty, and schema-validated before insertion. Unsupported, corrupt, or oversized persisted rows are quarantined and their readable payload is cleared.

Manual legacy summaries may remain viewable only when their payload survives migration safety checks, but C2 never injects them. C2 injection is limited to generated, exact-provenance rows.

Public readers return a fixed payload-unavailable state for redacted/quarantined rows and never reveal old text.

## 7. Required migration privacy reconciliation

C2 migration is not merely additive. Before any C2 generation or injection capability is enabled, one migration transaction must:

1. create turn, exact-source, payload-state, job, consent, suppression, and audit structures;
2. deterministically reconstruct every pre-C2 covered summary's ordered turn/source map where possible;
3. read the current singleton summary barrier and all existing source exclusions;
4. expand every reconstructable exclusion to complete turn closure;
5. classify every existing summary;
6. clear unsafe payloads;
7. verify postconditions;
8. commit all schema/data changes together.

The migration sets `summary_text=NULL`, `payload_state=redacted`, and appends a metadata-only migration-invalidation audit for every row that is:

- unmappable or ambiguously mapped;
- `legacy_unverified`;
- behind the current memory summary barrier;
- mapped to any message whose complete turn intersects an existing exclusion;
- corrupt, unsupported, or inconsistent with declared coverage.

Only an exact, reconstructable row observed at the current barrier with no excluded turn member may retain payload. A retained pre-C2 manual row is still noninjectable.

Post-migration checks assert:

- no redacted/quarantined row retains `summary_text`;
- no retained row is behind the current barrier;
- no retained row intersects the turn-closed exclusion set;
- every new exact row's stored source-set hash matches its source map;
- foreign keys and uniqueness constraints hold.

Any failure rolls back all C2 migration changes. The application does not enable C2 on a partially reconciled database.

## 8. Durable summary jobs

### 8.1 Job model

`summary_jobs` stores metadata only:

```text
id
session_id
job_kind                    incremental | rebuild
status                      pending | running | succeeded | failed | cancelled | skipped
logical_source_identity
attempt_epoch
source_message_count
source_turn_count
captured_barrier_generation
captured_processing_consent_generation
captured_processing_policy_fingerprint
captured_session_deletion_generation
captured_suppression_generation
rebuild_permit_id           nullable
route
provider                    nullable
model                       nullable
summarizer_schema_version
attempt_count
reason_code                 nullable
error_category              nullable
created_at
started_at                  nullable
finished_at                 nullable
```

`summary_job_audits` records status/outcome transitions, counts, generations, route/provider/model labels, elapsed time, reason/error category, and timestamps. It never stores source text, summary text, Prompt, raw response, hidden reasoning, credentials, or internal source hashes in public output.

### 8.2 Two-level idempotency

`logical_source_identity` binds:

- session ID;
- job kind;
- ordered turn-closed source-set hash;
- current summary barrier generation;
- summarizer schema version;
- route.

`attempt_epoch` additionally binds:

- remote-processing consent generation and fingerprint, or explicit local route epoch;
- Provider/model/configuration fingerprint;
- session deletion generation;
- suppression generation;
- rebuild-authorization generation and one-time permit ID when applicable.

A uniqueness constraint on `(logical_source_identity, attempt_epoch)` deduplicates retries while all authority/configuration epochs are unchanged. A consent grant, valid config transition, new suppression decision, or explicit rebuild authorization can create a legitimately new attempt without mutating or being blocked by an older skipped/cancelled attempt.

Reservation, pre-send dispatch, and commit recheck every captured epoch. Prior terminal attempts remain immutable.

### 8.3 Scheduling and recovery

Chat schedules summary work only after a persisted assistant reply and completed `chat_turn`. Reservation or scheduling failure does not change the successful text reply.

Compatible pending/running jobs recover on restart. Incompatible jobs become structured terminal outcomes. Duplicate scheduler calls create one effective attempt under the same epoch.

Memory and summary jobs remain independent. A summary failure cannot mark a memory job failed or roll back committed memory changes.

## 9. Remote dispatch and revocation races

A summary-specific asynchronous dispatch fence gives queued consent mutations priority.

A remote job snapshots before dispatch:

- exact processing-consent generation and fingerprint;
- Provider/model/config fingerprint;
- current barrier generation;
- session deletion generation;
- exact ordered complete-turn source IDs and source-set hash;
- suppression generation;
- rebuild permit/authorization epoch where relevant.

Immediately before sending, under the fence, the worker reopens a short read boundary and verifies exact authority and source eligibility. It then releases all SQLite transactions before Provider I/O.

Revocation or capability change terminalizes jobs that have not sent. If a request was already sent, its result is untrusted until commit. Commit performs one transaction that rechecks all captured consent/config/barrier/session/source/suppression/permit epochs and exact source mapping. Any change discards the returned payload and stores only a metadata outcome.

If route is remote without exact authority, no remote Provider is instantiated or called. The attempt ends as `skipped_no_consent`; it does not silently masquerade as fake/local semantic output. An explicitly configured fake or genuinely local route follows its separate explicit route epoch.

### 9.1 Chat-summary disclosure linearization

Summary generation and chat injection use separate fences. A chat-summary disclosure fence gives queued injection-consent mutation, summary redaction/suppression, Gate B source exclusion/barrier mutation, and session deletion priority over a chat send that selected summaries.

The composition result captures the exact injection authority generation and complete policy binding plus, for every selected summary, its ID, payload-state/schema identity, observed barrier, turn-closed source-map identity, suppression generation, and source-session generation/existence proof.

Immediately before the chat Provider call, under the disclosure fence and with no SQLite write transaction held, `ChatService` rechecks:

- injection status/generation, disclosure version, exact field set and limits, and current chat Provider/model/configuration fingerprint;
- every selected summary's active payload state and supported schemas;
- current barrier and complete turn-closed exclusion state;
- source-set suppression generation/state;
- source session, turn, and mapped-message existence.

A consent revocation or any queued deletion/redaction/suppression/barrier mutation wins before send. The result then depends on which session changed:

- If an injection-consent change, summary mutation, barrier/exclusion change, or deletion of a **different selected summary source session** invalidates only optional summary context, the service discards the summary-bearing composition and deterministically recomposes with zero summaries while preserving the same frozen Persona artifact, still-existing active chat session/current user message/current turn, eligible higher-authority context snapshot, and C1 budget contract. The IDs-only context manifest records the summary IDs actually sent and is therefore empty on this fallback. Chat continues without summary disclosure.
- If the **active chat session** was deleted or its current message/turn no longer exists, recomposition is forbidden. The service makes no chat Provider call, persists no assistant reply or context manifest, and returns the existing structured session-deleted/not-found outcome. It never recreates the deleted session or treats the current turn as still valid.

No SQLite transaction remains open during Provider I/O.

The fence is not a claim that the system can recall bytes after Provider dispatch. A mutation that starts after the send linearization point invalidates later use/persistence according to its own transaction, while the already-authorized disclosure is represented by the captured consent generation.

## 10. Transactional forget and invalidation

A `SummaryInvalidationPrimitive` becomes part of the same managed write transaction that:

- adds Gate B source exclusions;
- expands them to complete turn closure;
- advances the summary barrier;
- redacts the forgotten memory/Evidence payload.

For every summary whose exact mapped turn set intersects the expanded exclusions, the primitive:

1. sets `summary_text=NULL`;
2. sets `payload_state=redacted` and fixed reason/time;
3. appends metadata-only invalidation audit;
4. advances the matching source-set suppression generation to `suppressed`.

No affected derived payload remains readable in raw SQLite after the transaction commits.

For exact-provenance summaries that do not intersect an exclusion, the same transaction may revalidate them to the new barrier only after confirming all mapped messages and complete turns still exist and remain eligible. This changes barrier metadata and appends an audit; it does not call a Provider.

Legacy or unmappable provenance is conservatively redacted whenever barrier safety cannot be proven.

## 11. Durable source-set suppression and explicit rebuild

### 11.1 Suppression state

`summary_source_suppressions` is owned by a session and keyed by `(session_id, ordered_turn_source_set_hash)`:

```text
generation                  INTEGER NOT NULL
state                       suppressed | rebuild_authorized | rebuild_in_progress | rebuild_completed
rebuild_permit_id           TEXT NULL
bound_job_id                TEXT NULL
reason_code                 TEXT NOT NULL
created_at
updated_at
```

A metadata-only audit records every generation/state transition. Source-set hashes remain internal.

Redacting a summary atomically inserts or increments `suppressed`. Ordinary automatic scheduling rejects a source set with an active suppression and cannot consume a rebuild permit.

### 11.2 Explicit rebuild state machine

A rebuild requires an explicit user action with expected suppression generation. One CAS transaction:

1. verifies current `suppressed` state/generation;
2. advances generation;
3. enters `rebuild_authorized`;
4. issues a one-time random permit ID;
5. records metadata-only authorization audit.

Reservation with that permit atomically binds it to exactly one rebuild job and enters `rebuild_in_progress`. Retries reuse the bound job; another job cannot consume the permit.

Commit requires the same session, suppression generation, permit ID, bound job ID, session generation, barrier, consent/config epoch, and safe source set. It inserts a new immutable replacement summary and advances the suppression row to `rebuild_completed` in one transaction.

Failure leaves an explicitly retryable or cancellable bound state; it never opens ordinary scheduling. A later redaction or cancellation advances suppression generation and invalidates in-flight work.

Suppressions and their audits are session-owned and cascade on session deletion. In-flight results also fail the captured session-generation check.

### 11.3 Safe replacement source set

Rebuild uses complete safe turns from the original coverage after removing every excluded turn. It never retains only the assistant half of a forgotten user/assistant pair. If safe complete turns fall below the configured minimum, no replacement is created or injected.

The replacement is a new summary linked by `replaces_summary_id`; old payload remains redacted.

## 12. Eligibility and selection

Injection requires all of:

- exact current injection grant or explicit local enable decision;
- payload state `active`;
- source `generated`;
- supported summarizer and injection schema versions;
- exact ordered complete-turn source map;
- observed barrier equals current barrier;
- no mapped turn member is excluded;
- all mapped messages, turns, and session still exist;
- source-set hash is not actively suppressed;
- bounded, validated, non-empty text;
- no corruption/integrity flag.

### 12.1 Candidate retrieval

C2 selects at most one latest eligible summary per source session.

Candidates are:

- current-session older coverage that does not overlap any selected recent-message turn;
- other-session summaries with positive deterministic lexical relevance to the current user text.

Cross-session summaries with zero relevance are excluded.

### 12.2 Stable ranking

Stable order is:

1. current-session continuity before cross-session context;
2. lexical score descending;
3. updated time descending;
4. summary ID ascending.

C1 Composer applies the frozen maximum fragment count, per-fragment hard cap, and total summary-character budget. A fragment is never truncated mid-text; the lowest-ranked whole fragment is dropped. Under global pressure, summaries are removed before structured memories or necessary recent messages, as defined by C1.

## 13. C1 encoding and manifest

Each selected fragment is serialized through C1's canonical untrusted-data encoder with fixed fields:

```json
{
  "authority": "low_trust_session_summary",
  "summary_id": "...",
  "source_session_id": "...",
  "source_kind": "generated",
  "created_at": "...",
  "summary_text": "..."
}
```

All text is JSON escaped inside the versioned data envelope. Summary content cannot close the envelope, alter Persona/ruleset, or become an instruction-bearing prefix. Anthropic/DeepSeek adapter contract fixtures include fake rules, system roles, JSON, and delimiter injection.

The assistant context manifest stores selected summary IDs only. It does not copy summary text, source text, source-set hash, or internal consent fingerprint.

Summary text never enters Memory Governor/extractor or C3 relationship derivation. A conflict with structured memory does not upgrade summary authority; structured active non-conflicted memory remains the deterministic fact layer.

## 14. API

Minimal endpoint groups provide:

- read/update remote-processing consent;
- read/update injection consent or local enable decision;
- session/global summary status;
- safe summary list/detail states;
- paginated metadata-only jobs/audits;
- irreversible summary payload redaction;
- explicit CAS-authorized rebuild/retry/cancel.

Mutation endpoints require expected generation/state where applicable. Irreversible redaction requires an explicit confirmation field.

Responses omit:

- source message text;
- redacted/quarantined summary text;
- Prompt/raw Provider output/hidden reasoning;
- source-set and policy hashes;
- HMAC references;
- credentials and private assets.

A status endpoint failure is non-blocking to chat and results in zero injected summaries for that turn.

## 15. SummaryPanel

A collapsible `SummaryPanel`, independent of MemoryPanel and EmotionPanel, shows:

- configured generation route and capability state;
- exact remote-processing disclosure and grant/decline/revoke controls;
- separate injection disclosure and grant/decline/revoke or local enable control;
- latest summary job states and retryable reason labels;
- active, stale, redacted, quarantined, legacy-unverified, and replacement states;
- prominent `低可信会话概述` label;
- bounded source count and time range, not source text;
- irreversible payload-redaction action;
- explicit suppression-generation-aware rebuild/retry/cancel actions.

Memory synchronization and summary state are displayed separately. The panel does not use frequent modal interruptions and accepts no file, URL, image, audio, video, archive, or private asset.

## 16. Failure behavior

| Condition | Required behavior |
|---|---|
| no exact remote-processing consent | zero remote Provider construction/send; metadata-only skipped status |
| no exact injection authority | Composer receives zero summaries |
| Provider timeout/invalid response | metadata-only failure; no summary payload committed |
| consent revoked before send | job terminalized; zero send |
| consent/barrier/source/session/suppression changes in flight | returned payload discarded |
| lookup/ranking failure | inject zero summaries; chat continues |
| rebuild failure | old payload remains redacted; bound permit state remains explicit |
| database commit failure | summary/job/suppression transition rolls back atomically |
| different selected summary source session deleted before chat send | recompose with zero summaries; active-session chat may continue |
| active chat session deleted before chat send | zero chat Provider call; no assistant reply/manifest; structured not-found outcome |
| source session deleted during summary generation | owned summaries/maps/jobs/suppressions cascade; in-flight summary commit fails |
| corrupt/unsupported payload | clear/quarantine payload; never inject |
| assistant echoes forgotten source | complete turn excluded; echo never reaches rebuild input |

Errors and audits contain only IDs, counts, schema/route/provider/model labels, generations, reason categories, timings, and correlation IDs.

## 17. Configuration

The C2 file-level plan must freeze defaults and legal ranges for:

- generation route;
- trigger complete-turn count;
- maximum input turns/messages/characters;
- Provider timeout/retry/token output cap;
- generated-summary payload hard cap;
- injection fragment count;
- per-fragment and total injection character caps;
- lexical relevance minimum;
- rebuild minimum safe-turn count;
- job retry/recovery policy;
- consent disclosure and summarizer/injection schema versions.

All values are represented in settings, `.env.example`, and configuration tests. No route or setting can grant consent. Invalid configuration fails closed without widening disclosure.

## 18. Test strategy

### 18.1 Migration and raw-payload privacy

Test fresh and legacy databases containing:

- current exact summaries;
- stale summaries behind the barrier;
- existing exclusions;
- assistant replies repeating forgotten user values;
- ambiguous legacy role sequences;
- manual and generated summaries;
- corrupt/oversized rows.

Assert transaction rollback on fault injection and verify no redacted/quarantined/stale/unmappable/excluded row retains readable payload in selected raw SQLite columns.

### 18.2 Consent matrix and remote races

Cover every pair of processing and injection authority states. Prove:

- neither substitutes for the other;
- default/declined/revoked/stale processing authority means zero remote construction/send;
- missing injection authority means zero selected and zero dispatched fragments even when summaries exist;
- independently changing disclosure version, exact field set, fragment limit, total-character limit, or chat Provider/model/endpoint/configuration fingerprint invalidates injection authority until a new explicit grant;
- pending processing-consent revoke wins before summary-generation send;
- in-flight summary-generation return after processing-consent revoke cannot commit;
- generation barrier/exclusion/session/suppression change during summarizer I/O discards output;
- after summary-bearing composition but before chat dispatch, queued injection revoke, payload redaction, suppression, and barrier/source exclusion each win the chat-summary disclosure fence;
- deleting a different selected summary source session causes deterministic recomposition with zero summaries, an empty sent-summary manifest, no summary bytes sent, and successful text chat;
- deleting the active chat session causes zero chat Provider calls, no assistant reply/manifest persistence, and the existing structured session-deleted/not-found outcome;
- no SQLite transaction remains open during either summarizer or chat Provider I/O.

### 18.3 Job identity, recovery, and suppression

Test:

- retry deduplication under unchanged logical identity/attempt epoch;
- a post-grant attempt is allowed after `skipped_no_consent`;
- config and session epochs distinguish legitimate attempts;
- one rebuild permit binds one job;
- ordinary scheduler cannot consume permit or bypass suppression;
- retries reuse the bound rebuild job;
- cancellation/redaction advances generation and invalidates stale workers;
- recovery and rollback preserve state-machine invariants;
- session deletion cascades owned suppression state.

### 18.4 Turn closure and true forget

An end-to-end fixture has an assistant repeat a user value that later becomes true-forgotten. Assert that both turn members are excluded and the sentinel is absent from:

- rebuild Provider input;
- generated replacement output;
- summary API/UI;
- chat context and manifests;
- logs/audits;
- selected raw SQLite summary/source payload surfaces.

The same suppressed source set cannot regenerate automatically. Explicit rebuild includes only safe remaining complete turns.

### 18.5 Deterministic injection

Test:

- only generated exact-provenance active rows enter selection;
- current/recent turn overlap is absent;
- cross-session zero relevance is absent;
- ranking and whole-fragment trimming are deterministic;
- global C1 budget removes summaries before higher-authority layers;
- manifests contain IDs only;
- Summary fake rules/delimiters remain escaped across Anthropic/DeepSeek adapters;
- structured memory remains authoritative and summary is always labeled low trust.

### 18.6 Regression and privacy contract

Run affected and full backend/frontend suites, typecheck/build/static checks, Gate A/B privacy/deletion/conflict/concurrency tests, and C1 Persona/Composer tests. No real keys, private assets, or actual remote Provider call is needed for automated acceptance. Any real-Provider limitation is recorded honestly.

## 19. Acceptance criteria

C2 is complete only when:

- migration scrubs every preexisting unsafe summary payload before enablement;
- complete-turn closure prevents assistant echoes from restoring forgotten content;
- remote processing and injection authorities are independent, persisted, explicit, versioned, and revocable;
- unauthorized/stale remote processing constructs no remote Provider and sends zero bytes;
- unauthorized/stale or pre-dispatch-revoked injection selects and dispatches zero fragments;
- every injection disclosure field, limit, disclosure version, and chat Provider/model/configuration fingerprint is grant-bound;
- queued summary invalidation/deletion beats chat disclosure, recomposes without summaries, and records only IDs actually sent;
- durable job identity permits newly authorized work without weakening retry idempotency;
- redaction suppression cannot be bypassed by ordinary scheduling;
- an explicit one-time rebuild permit has precise CAS/binding/commit behavior;
- true forget removes affected summary payload from raw SQLite and all public/derived surfaces;
- only eligible exact generated summaries are injected as escaped low-trust data;
- summary failure never blocks text chat or changes memory/Persona/emotion/relationship state;
- all affected and full regressions pass;
- independent review returns `APPROVED` without unresolved high/critical privacy, correctness, or acceptance-integrity findings;
- acceptance evidence distinguishes fake/local behavior from real remote Provider evidence.

## 20. Next gate boundary

C2 completion does not authorize C3. C3 must retain the rule that summaries are never relationship-fact sources. It requires its own approved written specification, file-level TDD plan, implementation, acceptance evidence, and independent review under the delegated reviewer-approval policy.
