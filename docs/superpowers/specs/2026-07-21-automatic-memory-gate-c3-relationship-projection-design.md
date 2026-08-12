# Gate C3 Relationship Ledger and Deterministic Projection Design

**Date:** 2026-07-21  
**Status:** DESIGN APPROVED — implementation requires a separate file-level plan and review  
**Scope:** Gate C3 and final integrated Gate C evaluation  
**Prerequisites:** Gate C1 and C2 accepted and deployed  
**Parent design:** `docs/superpowers/specs/2026-07-16-automatic-memory-persona-consistency-enhancement-design.md`  
**C1 design:** `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c1-persona-context-design.md`  
**C2 design:** `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c2-controlled-summary-design.md`

## 1. Purpose

Gate C3 adds a local relationship-consistency layer built from already governed Gate B memory state:

1. an append-only relationship event ledger;
2. durable relationship-only user authority decisions;
3. idempotent reconciliation against exact current memory versions;
4. deterministic, bounded, recomputable projection snapshots;
5. safe C1 Context Composer injection;
6. a minimal RelationshipPanel;
7. final multi-session replay and role-consistency evaluation for Gate C.

C3 introduces no new LLM or extractor. It never infers relationship facts from summaries, raw messages, assistant output, Stage 4 emotion state/events, or free-text sentiment. It does not modify Persona, memory, summary, or emotion state.

## 2. Hard invariants

- Only an exact, current, active, non-conflicted, non-redacted Gate B MemoryVersion/record state may source an apply event.
- Pending, dismissed, archived, deleted, redacted, open-conflicted, or stale versions never source or validate an active relationship contribution.
- C2 summaries, raw messages, assistant output, Provider hidden reasoning, and Stage 4 emotion state/events are never relationship-fact sources.
- Relationship rules are deterministic, versioned, allowlisted, bounded, and local.
- Evidence counts and Evidence retractions never gate or compound relationship state.
- Repetition, support Evidence, retries, recovery, or rebuild cannot multiply a source version's effect.
- Ordinary history is append-only. A revoke points to one apply and carries no delta or readable relationship payload.
- A narrow privacy operation may irreversibly clear the bounded preferred-address text from an apply event; no projection snapshot duplicates that text.
- A relationship-only user suppression survives source-version changes, recovery, rebuild, and rule upgrades until a separate explicit re-enable decision.
- Event semantic ordering derives from immutable source time, never asynchronous reconciliation time.
- Projection recomputation independently rechecks source eligibility and user authority; stale events cannot remain effective merely because reconciliation failed.
- Familiarity has a fixed baseline, per-event cap, per-source lifetime cap, and total range.
- Projection and reconciliation failures never block text chat; invalid state yields a neutral relationship view.
- Relationship context is untrusted encoded data below Persona and structured-memory authority.
- True forget removes every readable relationship copy from raw SQLite and all public/derived surfaces while retaining only minimal no-revival metadata.
- No API key, HMAC, source message text, summary text, arbitrary memory prose, Prompt, raw Provider response, hidden reasoning, or private asset enters the ledger, projection, audit, or public API.

## 3. Scope and non-scope

### 3.1 In scope

- relationship rule schema and allowlist;
- append-only apply/revoke events;
- append-only suppress/reenable authority decisions;
- metadata-only reconciliation jobs/audits;
- Gate B mutation integration and recovery;
- immutable projection snapshots and active pointer;
- C1 Composer view/manifests;
- RelationshipPanel;
- final Gate C fixed replay and human evaluation.

### 3.2 Out of scope

- remote relationship extraction or any new consent;
- sentiment analysis, diagnostic inference, or implicit relationship scoring;
- relationship writes derived from C2 summaries or Stage 4 emotion;
- writing relationship values back to memory or emotion state;
- free-text model-generated relationship summaries;
- external commitments or real-world actions;
- Electron, Live2D, visual assets, voice cloning, packaging, or private media;
- official-character, real-person, or genuine-consciousness claims;
- commit, push, distribution, or publication.

## 4. Deterministic source eligibility

### 4.1 Exact source tuple

All reconcile, commit, projection-validation, and Composer-read paths operate on the same tuple:

```text
scope_id
source_memory_id
source_memory_version_id
record_head_version
record_generation/state
memory_type
canonical_subject_code
version_source_kind
version_confidence
version_importance
version_created_at
open_conflict_state
payload_redaction_state
effective_relationship_authority_decision_id
effective_relationship_authority_generation
relationship_rule_version
```

The exact version must still be the record's current head when an apply is committed or used.

### 4.2 Allowed source kinds

Eligible current versions may come from:

- manual/user-confirmed memory;
- user edit;
- user revert;
- consented Gate B automatic create/supersede paths.

The source-kind rules do not let Persona, summaries, or emotion create facts. Legacy active memories require an explicit compatibility mapping and are skipped when canonical subject cannot be established without guessing.

### 4.3 Allowlisted mappings

A versioned `RelationshipRuleSet` maps only:

- `relationship_event` memories with explicit canonical subjects such as:
  - `preferred_address`;
  - `shared_experience`;
  - `non_external_commitment`;
- `preference` or `user_fact` only when the canonical subject explicitly means user-preferred address.

General preferences/facts do not alter familiarity or relationship status. Unknown, ambiguous, inferred, or non-allowlisted subjects produce metadata-only skipped outcomes.

There is no free-text sentiment/keyword scoring. Mapping uses normalized memory type, explicit canonical subject, source kind, and bounded immutable version fields.

### 4.4 Evidence exclusion

C3 removes Evidence-dependent eligibility entirely:

- `source_evidence_id` is not part of relationship events;
- supports/corrects/contradicts Evidence counts do not add delta;
- an Evidence retraction alone does not revoke or recreate an event;
- automatic support without a new current memory version has zero C3 effect;
- confidence and importance are read from the exact immutable current MemoryVersion only.

Multiple supports and independent retractions therefore have no ambiguous C3 lifecycle. A relationship change occurs only when a Gate B operation changes the exact current version/state or eligibility tuple.

## 5. Append-only relationship event ledger

### 5.1 Event model

`relationship_events` stores:

```text
id                              TEXT PRIMARY KEY
event_kind                      apply | revoke
event_type                      preferred_address | shared_experience | non_external_commitment
subject_code                    TEXT NOT NULL
payload_state                   active | redacted
payload_json                    TEXT NULL
source_memory_id                TEXT NOT NULL
source_memory_version_id        TEXT NOT NULL
observed_at                     TEXT NOT NULL
observed_time_derivation_version TEXT NOT NULL
revokes_event_id                TEXT NULL
rule_version                    TEXT NOT NULL
persona_artifact_id             TEXT NOT NULL
created_at                      TEXT NOT NULL
```

The Persona ID is provenance only. Persona content does not alter event eligibility or delta.

### 5.2 Apply payload schemas

Apply payload is canonical and strict by event type:

- `preferred_address`:
  - validated short address text;
  - no numeric delta;
- `shared_experience`:
  - fixed category/reason code;
  - fixed signed familiarity delta bounded by the rule;
- `non_external_commitment`:
  - fixed category/reason code;
  - fixed signed familiarity delta bounded by the rule.

No event payload stores arbitrary memory prose, raw messages, summary text, Prompt, Provider response, credentials, HMAC, or private assets. A preferred address is the only bounded user-readable value copied from an eligible memory.

### 5.3 Apply idempotency

A partial unique identity permits at most one apply for:

```text
source_memory_version_id
rule_version
event_type
subject_code
```

Retries and recovery under the same rule cannot duplicate it. User authority decisions, described below, are independently checked and can suppress all rule versions and future source versions for the semantic source identity.

### 5.4 Revoke invariants

A revoke:

- points through `revokes_event_id` to an existing apply;
- stores no relationship delta or readable text;
- cannot revoke itself, another revoke, another scope, or a missing apply;
- is unique per target apply;
- cannot duplicate an already effective revoke.

Invalid attempts fail or produce a metadata-only rejected audit according to API/job context. Ordinary operations never update/delete historical rows.

### 5.5 Privacy-redaction exception

If preferred-address text is true-forgotten or explicitly redacted, the same managed transaction:

1. appends/ensures a revoke for the apply;
2. appends a relationship suppression authority decision where required;
3. sets that apply's `payload_json=NULL` and `payload_state=redacted` through a constrained monotonic database transition;
4. recomputes/activates a projection with no selected address;
5. appends metadata-only audit.

All identity, code, rule, source-version, and timestamp fields remain unchanged. The transition cannot restore or replace readable content.

No projection row stores preferred-address text, so the event is the only relationship-layer readable copy. If migration encounters an earlier experimental projection text column, C3 transactionally nulls it before enabling the feature.

## 6. Durable relationship-only user authority

### 6.1 Semantic key and decision model

`relationship_authority_decisions` is append-only and keyed semantically by:

```text
scope_id
source_memory_id
event_type
subject_code
```

Each row stores:

```text
id
predecessor_decision_id          nullable
generation                       monotonic per semantic key
action                           suppress | reenable
action_kind                      user_revoke | privacy_redact | user_reenable | inherited_conflict_suppression
reason_code
created_at
```

It stores no source text, address text, source hash, HMAC, or Prompt. A uniqueness constraint enforces one generation per semantic key and a linear predecessor chain.

The effective decision is the highest valid generation with stable ID validation. Ordinary rows are never updated or deleted.

### 6.2 Suppression authority

An explicit relationship-only revoke appends `suppress`. A preferred-address privacy redaction atomically appends `suppress` and clears payload. A suppression applies to all current and future memory versions and all relationship rule versions under the same semantic source key.

Reconciliation reservation, apply/revoke commit, projection validation, full rebuild, startup recovery, rule migration, and Composer view all capture and recheck the effective decision ID and generation. Stale in-flight work cannot apply after suppression.

Memory edits, Persona switches, recovery, and rule upgrades never re-enable a key.

### 6.3 Explicit re-enable

Only a separate explicit API action with expected decision ID/generation may append `reenable`. It does not mutate old events or recover redacted payload. If the current memory version is still independently eligible, reconciliation may append a new apply under current rules.

A re-enable is not implied by editing the source memory, switching Persona, rebuilding projection, or upgrading rules.

### 6.4 Conflict-resolution authority transfer

Gate B conflict resolution creates a new resolved memory identity for `choose_left`, `choose_right`, `replace_both`, and `both_contextual`. Relationship authority therefore cannot be looked up only on the new `source_memory_id`.

`relationship_memory_lineage` records metadata-only parentage for each resolved identity:

```text
resolved_memory_id
contributing_memory_id
conflict_id
resolution_kind
created_at
PRIMARY KEY(resolved_memory_id, contributing_memory_id)
```

It stores no memory text, address, Prompt, or HMAC. The resolution transaction inserts lineage for both conflict sides before the resolved identity can become relationship-eligible.

For each `(event_type, subject_code)` considered on the resolved identity, effective relationship authority is derived over the transitive contributing-identity closure plus the resolved identity's own latest decision:

- if any contributing lineage key has effective `suppress`, the resolved identity is conservatively suppressed;
- missing/no-decision lineage does not override a suppression;
- a contributing `reenable` affects only that contributing semantic key and does not cancel another side's suppression;
- disagreement therefore resolves to suppression;
- `dismiss_both` creates no resolved identity and all old effective applies remain revoked/ineligible;
- an explicit re-enable on the resolved identity, with expected inherited-authority fingerprint and generation, is the only action that can override inherited suppression for that resolved semantic key. It appends `reenable` on the resolved identity; it does not rewrite parent decisions.

The resolver records the contributing decision IDs/generations and a private non-reversible inherited-authority fingerprint. Reconciliation reservation, commit, projection validation, rebuild, recovery, and rule migration capture and recheck the complete lineage closure and inherited authority generation/fingerprint. A conflict resolution or parent suppression that lands while work is in flight makes that work stale. Lineage is never inferred from matching text or canonical subject alone.

### 6.5 True-forget retention

After source-memory true forget, payload is scrubbed but minimal metadata-only suppression and lineage may remain to prevent relationship-layer revival. Public APIs do not expose internal source hashes/HMACs, inherited-authority fingerprints, or deleted text.

## 7. Immutable semantic ordering

`observed_at` is the exact source MemoryVersion `created_at`, normalized to UTC under `relationship_observed_time_derivation_version`. It is never reconciliation processing time.

`created_at` on an event is processing/audit time only and never changes projection semantics.

The complete stable fold key is:

```text
observed_at ASC
source_memory_id ASC
source_memory_version_id ASC
event_type ASC
subject_code ASC
event_id ASC
```

The preferred-address winner is the newest valid event by the exact reverse of that full key. Random reconciliation order and delayed recovery cannot change precedence.

Tests run identical source snapshots through different reconcile order, delay, restart, and recovery schedules and require identical semantic ordering, selected address event ID, projection values, and fingerprint.

## 8. Reconciliation

### 8.1 Reconciler responsibilities

`RelationshipReconciler` converts eligible current memory versions into events and revokes stale contributions. It is deterministic, idempotent, local, and recoverable.

A reservation captures the exact source tuple from Section 4.1 plus current Persona ID for provenance. Commit opens a short transaction and rechecks every element before writing.

### 8.2 Mutation lifecycle

- Eligible new current version: append one apply if no effective suppression and no existing apply identity.
- Automatic support without a new current version: no event change.
- Supersede/user edit/user revert: revoke effective applies for the old version, then apply the new version if eligible and unsuppressed.
- Archive/true forget/open conflict/dismiss-both/no eligible head: append revokes for effective applies.
- Conflict resolution: the Gate B resolution transaction records both side identities as lineage contributors to any new resolved identity and transfers effective authority according to Section 6.4 before that identity may produce an apply. Only the resolved eligible current version may produce an apply; archived sides never do.
- `both_contextual`: maps only if its explicit canonical subject remains allowlisted and no contributor or resolved-key authority suppresses it.
- `choose_left/right`, `replace_both`, and `both_contextual` use the newly created/confirmed current version, never historical side activation, and conservatively inherit suppression from either side.
- Persona switch: no event is created or revoked; projection is recomputed with new Persona provenance.

### 8.3 Transaction boundaries and fail-closed validation

True forget and preferred-address privacy redaction add relationship revocation, authority suppression, event payload clearing, and projection replacement to the same write transaction as Gate B readable-payload removal where feasible and required for privacy.

Other Gate B mutations may schedule reconciliation after their own atomic commit. If post-commit reconciliation fails, projection validation independently verifies every source event against the current exact memory version/state and effective authority generation. Invalid/stale applies are ignored immediately, yielding a neutral or reduced view; recovery later appends missing revokes/events.

Chat never uses stale relationship facts merely because a background worker failed.

### 8.4 Session deletion

Events do not store raw message IDs or text. If a source memory remains eligible after source-session deletion, its memory/version IDs may continue to support the event. If the deletion/forget scope invalidates that memory, revocation/redaction occurs before message/session deletion commits.

Existing Gate B HMAC-only provenance remains internal and is never added to relationship API output.

## 9. Reconciliation jobs and audits

C3 uses metadata-only `relationship_reconcile_jobs` and audits with:

- source memory/current-version IDs;
- captured record head/state/generation;
- relationship authority decision ID/generation;
- rule and Persona artifact versions;
- status/outcome/reason category;
- attempt count and timestamps.

No job/audit copies source content, preferred address, message text, summary, Prompt, Provider response, credentials, or HMAC.

A uniqueness/attempt identity binds source current-version ID, rule version, and authority decision generation. Unchanged retries deduplicate; an explicit re-enable or genuinely new current version may produce a new attempt.

Incomplete compatible jobs recover. Stale/incompatible jobs become metadata-only terminal outcomes. Database failure rolls back event/projection/audit writes together.

## 10. Immutable projection snapshots

### 10.1 Model

`relationship_projections` stores:

```text
projection_id                   TEXT PRIMARY KEY
version                         INTEGER UNIQUE NOT NULL
scope_id                        TEXT NOT NULL
persona_artifact_id             TEXT NOT NULL
projection_rule_version         TEXT NOT NULL
familiarity                     REAL NOT NULL
preferred_address_event_id      TEXT NULL
relationship_summary_code       TEXT NOT NULL
source_relationship_event_ids_json TEXT NOT NULL
source_emotion_snapshot_id      TEXT NULL
computed_at                     TEXT NOT NULL
integrity_fingerprint           TEXT NOT NULL
```

`source_emotion_snapshot_id` is always `NULL` in C3. Projection rows contain no address text or free-text relationship summary.

A singleton/current-scope pointer uses compare-and-swap. Projection snapshots are inserted, never edited or deleted in ordinary operation.

### 10.2 Effective event set

The projector:

1. reads applies in the stable semantic order;
2. excludes targets of valid revokes;
3. excludes redacted payloads where payload is required;
4. excludes effective `suppress` authority keys;
5. independently rechecks every exact source version remains current and eligible;
6. verifies rule/schema versions and event integrity;
7. folds only the remaining set.

### 10.3 Bounded familiarity

The implementation plan freezes:

- baseline and legal range;
- per-event delta limits;
- per-source-memory lifetime contribution cap;
- total clamp;
- fixed mapping for each allowlisted event type.

Repeated support, duplicate jobs, retries, rebuilds, or rule recovery cannot add effect. A source's lifetime cap is applied across all its versions.

### 10.4 Preferred address

Projection stores only `preferred_address_event_id`. The selected ID is the newest valid preferred-address apply by the reverse full semantic key.

A `RelationshipProjectionView` resolves address text only at read/Composer time by joining that exact event and rechecking:

- payload active and not redacted;
- no effective revoke;
- no effective relationship suppression;
- exact source version still current/eligible;
- event and projection integrity.

Any failure yields no address. Historical projections therefore cannot retain or reveal forgotten address text.

### 10.5 Fixed summary code

`relationship_summary_code` is a bounded enum selected by deterministic thresholds. C1 maps it to a fixed Persona-aware phrase. It is not free text and cannot contain memory prose.

### 10.6 Failure behavior

Projection failure, unsupported version, integrity mismatch, invalid source, or authority mismatch yields a neutral view for that turn. A prior committed projection may be used only after all current source and fingerprint checks still pass. Otherwise it is not a fallback.

Projection cannot write EmotionRepository, trust/distance, Persona, memory, or summaries.

## 11. Persona and rule upgrades

A Persona switch creates no relationship event and changes no event-derived numeric state. C3 recomputes a new projection referencing the new Persona artifact; C1 may render the fixed code with Persona-specific phrasing.

Rule upgrades do not rewrite old events. There is no `rule_migration` relationship event type. Migration is represented by ordinary revokes with a fixed `rule_migration` reason code in metadata-only audit, followed where eligible by ordinary allowlisted applies under the new rule version. If a new rule version changes mapping semantics:

- effective user suppressions remain authoritative;
- appends ordinary revoke events for now-invalid applies, using the fixed `rule_migration` reason only in metadata-only audit;
- eligible unsuppressed current versions may receive new applies under the new rule;
- projection is recomputed under the new projection rule;
- history remains append-only except permitted privacy payload clearing.

Full reconcile/rebuild follows the same authority and eligibility checks. It cannot re-enable suppressed keys.

## 12. C1 Composer integration

C1 receives only a verified `RelationshipProjectionView`:

```text
projection_id
projection_version
familiarity_bucket
preferred_address             nullable, resolved at read time
relationship_summary_code
persona_artifact_id
projection_rule_version
```

C1 serializes it through the versioned canonical untrusted-data encoder. No event payload or arbitrary memory prose is copied except the validated bounded preferred address.

The relationship layer remains below Persona, current/recent conversation, and structured memory authority. It cannot modify ruleset. Under budget pressure it falls back to a neutral fixed data view and may be removed entirely by C1 residual-overflow behavior.

The assistant context manifest stores projection ID/version only. It never stores preferred-address text, event payload, source memory text, or event list.

C2 summary text never enters relationship reconciliation or projection.

## 13. API

Minimal APIs support:

- current verified projection view;
- paginated ledger metadata with bounded address value only when still readable/eligible;
- paginated metadata-only reconciliation jobs/audits;
- explicit reconcile/full rebuild;
- relationship-only revoke, which appends suppression and revoke without editing source memory;
- irreversible preferred-address payload redaction;
- explicit re-enable with expected authority decision ID/generation.

Mutation APIs use expected generation/state and fixed action/reason codes. Irreversible payload redaction requires explicit confirmation.

Responses never expose deleted memory text, redacted address text, HMAC/internal fingerprints, Prompt/raw output, summary text, credentials, or private assets. Source-memory links are returned only if that memory remains readable and eligible through the existing Memory API.

## 14. RelationshipPanel

A collapsible `RelationshipPanel`, independent from MemoryPanel, SummaryPanel, and EmotionPanel, shows:

- current familiarity bucket;
- currently readable preferred address, if any;
- fixed continuity label;
- Persona, projection, and rule versions;
- contributing event count;
- apply/revoke timeline with metadata-only reason/type labels;
- source-memory link only while readable;
- reconcile/rebuild state;
- relationship-only revoke/suppress;
- irreversible preferred-address redaction;
- explicit re-enable action with explanation that it may derive a new apply from current memory.

The UI explains that relationship-only revoke does not delete/edit the source memory; source-memory editing and true forget remain in MemoryPanel. It does not accept files, URLs, private assets, or arbitrary event payloads.

## 15. Privacy and true-forget

When an eligible preferred address is truly forgotten, one managed transaction must ensure:

- source memory/version readable payload is cleared according to Gate B;
- related relationship apply address payload is cleared;
- effective revoke exists;
- suppression authority prevents later reapply/rebuild/rule-upgrade revival;
- a current projection with no address is activated;
- no historical projection contains address text;
- context cannot resolve the old address;
- metadata-only audit remains without readable payload.

Privacy tests inspect all event and historical projection payload columns, API/UI, Composer output, assistant manifests, logs, jobs/audits, and selected raw SQLite surfaces. The forgotten sentinel must be absent everywhere readable.

If C3 migration sees a prior experimental projection schema that duplicated address text, it nulls that payload transactionally before feature enablement.

## 16. Failure and concurrency behavior

| Condition | Required behavior |
|---|---|
| source snapshot changes before commit | stale reconcile outcome; no apply/revoke from stale tuple |
| relationship suppression advances in flight | stale work fails; no reapply |
| support Evidence added/retracted | zero C3 change without new current version |
| open conflict | both sides immediately invalid for projection; recovery appends revokes |
| true forget/redaction | payload clearing + suppression + safe projection in privacy transaction |
| reconcile/recovery failure | projection independently ignores invalid source; chat continues |
| projection integrity/version failure | neutral relationship view |
| Persona switch | recompute projection provenance; no event/numeric invention |
| rule upgrade | append ordinary revokes with migration reason and allowlisted new applies; honor suppression; no history rewrite |
| database fault | event/projection/audit transaction rolls back |
| Relationship API/UI failure | chat uses neutral view; other panels continue |

Logs contain only IDs, versions, counts, reason/error categories, and timings.

## 17. Configuration

The C3 file-level plan freezes defaults and legal ranges for:

- relationship rule/projection schema versions;
- observed-time derivation version;
- preferred-address maximum characters and validation rules;
- familiarity baseline/range;
- per-event and per-source lifetime delta caps;
- summary-code thresholds;
- reconcile/recovery retry limits;
- Context Composer relationship-view hard cap.

Configuration cannot enable a non-allowlisted source type/subject without a reviewed rule-version change. Invalid configuration fails closed to neutral relationship view.

## 18. Test strategy

### 18.1 Schema and append-only invariants

Test:

- additive migration and old-data preservation;
- event/apply uniqueness;
- revoke target/type/scope uniqueness validation;
- ordinary update/delete rejection;
- constrained address-payload redaction only;
- linear authority-decision generations/predecessors;
- projection immutability and pointer CAS;
- transaction rollback fault injection.

### 18.2 Complete Gate B lifecycle matrix

Cover:

- create;
- support without a new version;
- multiple supports and independent Evidence retractions;
- supersede;
- user edit;
- user revert;
- archive;
- true forget;
- open conflict;
- choose left/right;
- replace both;
- both contextual;
- dismiss both;
- session deletion;
- stale/recovered reconcile.

Assert only the exact eligible current version contributes and no stale/invalid side remains effective.

### 18.3 Authority/no-reapply

Test user suppress across:

- source-memory edits and supersedes;
- full rebuild;
- startup recovery;
- Persona switch;
- rule upgrade and ordinary migration revokes/new applies;
- stale in-flight reconcile;
- conflict opening and stale work concurrent with resolution;
- `choose_left`, `choose_right`, `replace_both`, and `both_contextual` creating new resolved identities;
- inherited decision disagreement, which must conservatively suppress;
- `dismiss_both`, which creates no new eligible identity.

Only explicit generation-checked re-enable on the effective current/resolved identity, with the expected inherited-authority fingerprint, permits a later new apply. Privacy redaction never restores old payload. Tests prove that parent-side suppression transfers through complete conflict lineage and cannot be bypassed by new IDs, rebuild, recovery, or rule changes.

### 18.4 Determinism and bounds

Run identical source snapshots under different reconciliation order/delay/restart schedules. Require identical:

- semantic event order;
- effective event set;
- selected preferred-address event ID;
- familiarity value/bucket;
- summary code;
- projection fingerprint.

Prove per-event, per-source lifetime, and total caps. Duplicate/support/retry/rebuild paths must not compound values.

### 18.5 Independence tests

Prove:

- Stage 4 emotion changes do not change relationship events/projection;
- C2 summaries do not source relationship state;
- assistant text and raw messages do not source relationship state;
- Persona switches preserve event-derived numerical state;
- relationship operations do not mutate memory, summary, Persona, or emotion records.

### 18.6 Privacy and Composer

Prove forgotten/redacted preferred address is absent from:

- every event payload and historical projection payload column;
- public API and rendered UI;
- C1 encoded relationship context;
- assistant manifests;
- logs/jobs/audits;
- selected raw SQLite surfaces.

Injection fixtures verify relationship data stays escaped and low-authority across supported adapters; invalid projection yields neutral context and chat succeeds.

## 19. Fixed replay and final Gate C evaluation

C3 completes the integrated Gate C evaluation using versioned Chinese multi-session fixtures covering:

- cross-session user facts;
- preferences changing over time;
- long-term goals;
- shared experiences;
- non-external commitments;
- temporal context;
- explicit correction;
- unresolved and resolved conflicts;
- true forget and no revival;
- summary errors and low-trust conflicts;
- uncertainty when evidence is absent;
- Prompt-injection text in memory/summary/relationship values;
- Persona switches;
- relationship suppression and re-enable.

Fixtures declare schema/rule/Composer/encoder versions and a tested content hash.

At least 30 cross-session assistant replies are sampled and scored 0–2 on:

1. core Persona consistency;
2. factual caution;
3. relationship continuity;
4. natural language;
5. non-official/non-real-person/non-consciousness declaration behavior.

Each category average must be at least 1.6. Replies scoring below 1 must be less than 5% of the sample. Any prohibited behavior is an immediate failure.

Evaluation combines deterministic rule assertions, fixed questions, and user blind review. An LLM judge may assist but cannot be sole acceptance evidence. If two reviewers are unavailable, the same user may conduct two blind-order passes with times and raw scores recorded.

## 20. Acceptance criteria

C3 and integrated Gate C are complete only when:

- ledger history is append-only except irreversible readable-payload clearing;
- exact current Gate B memory state is the sole fact source;
- Evidence/support activity has zero independent relationship effect;
- relationship-only suppression survives every version/rule/recovery path until explicit re-enable;
- preferred-address payload has one readable relationship copy and true forget removes it from all surfaces;
- projection history stores event IDs/codes/numbers, not address text;
- observed-time ordering and projection recomputation are deterministic;
- familiarity changes remain within per-event/per-source/total bounds;
- Persona switches do not invent relationship changes;
- summaries and Stage 4 emotion never source relationship facts;
- projection/relationship failure does not block text chat;
- C1 encoding/manifests preserve the trust and privacy boundary;
- fixed replay and quantitative 30-reply evaluation pass;
- Stage 1–4, Gate A/B, C1/C2, backend, frontend, static, typecheck, and build regressions pass;
- independent final review returns `APPROVED` with no unresolved high/critical privacy, correctness, or acceptance-integrity finding;
- acceptance records distinguish fake/local evidence from any real Provider evidence;
- no Electron, Live2D, private asset, or voice-cloning work enters the Gate.

## 21. Completion boundary

Gate C completion does not itself authorize the deferred Windows Electron shell or Live2D work. Those remain separate design, plan, implementation, privacy, and acceptance cycles. No commit or push occurs without explicit user authorization.
