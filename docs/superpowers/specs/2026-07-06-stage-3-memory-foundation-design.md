# Stage 3 Memory Foundation Design

Date: 2026-07-06
Status: APPROVED BY DEFAULT — user instructed recommended decisions should be executed.

## Goal

Build the first Stage 3 long-term memory vertical slice: user-visible, user-editable, auditable memories stored separately from chat messages and usable as optional context for future chat replies.

This design does not implement Stage 4 emotion state.

## Project Context

The project is now in Stage 3 after Stage 2 voice acceptance passed on 2026-07-06.

Current relevant architecture:

- Backend: FastAPI, Python, SQLite.
- Existing persistence: `sessions` and `messages` tables in `backend/app/repositories/sqlite.py`.
- Existing repository pattern: `SessionRepository` and `MessageRepository` wrap SQLite operations.
- Existing API pattern: route modules under `backend/app/api/routes/`, dependencies in `backend/app/api/dependencies.py`, schemas in `backend/app/domain/schemas.py`.
- Existing chat context: `ContextBuilder.build_recent_context(session_id)` reads recent chat messages only.
- Frontend: React + TypeScript + Vite. `App.tsx` owns top-level state and passes props into `ChatLayout`.

`CLAUDE.md` Stage 3 requires:

- Long-term memory independent from chat context.
- Coverage of user facts, preferences, long-term goals, important events, and relationship events.
- Every memory has source, time, type, importance, and confidence.
- Writes follow explicit rules or user confirmation.
- User can view, modify, and delete memories.
- Retrieved memories are context only, not absolute facts.
- Conflicts are not silently overwritten.
- Chat history, session summaries, and long-term memory stay separate.

## External Research Notes

Deep research completed on 2026-07-06. The strongest verified findings for this project:

- Long-term memory should be stored separately from thread-scoped chat context and persist across sessions/conversations, scoped by user or application namespace.
- A practical memory model should use first-class records with stable id/key, content/value, timestamps, type/category, source metadata, importance, confidence, and lifecycle status rather than embedding memories in chat messages.
- For this project's audit and conflict requirements, narrower memory records are better than one mutable user profile document.
- Memory retrieval should be explicit RAG-style context construction: retrieve a small subset and inject it into the prompt as contextual evidence, not hidden state or absolute truth.
- User-auditable CRUD should be normal application/database lifecycle behavior: list, retrieve, create, update, delete/archive, with status or supersession history where needed.
- Conflict handling should be additive and auditable by default: new memories must not silently overwrite existing memories.
- A database-backed local store is appropriate for production use; for this FastAPI + SQLite project, SQLite tables should be the initial source of truth, with FTS/vector indexing added only when retrieval quality needs it.

LangChain's public memory documentation distinguishes long-term memory from short-term conversation context and describes semantic, episodic, and procedural memory categories. It also presents long-term memories as structured documents stored outside a single conversation thread and retrieved later as context.

Mem0's public overview describes a memory lifecycle that includes adding, searching, and updating memories from application conversations. That automatic extraction model is useful later, but this project's first Stage 3 slice should be more conservative because `CLAUDE.md` requires explicit write rules, user visibility, and deletion.

Additional sources such as Letta, Microsoft Semantic Kernel, and the Generative Agents paper support separate memory records, retrieval-augmented context construction, lifecycle operations, and importance/retrieval signals, but they do not fully specify this project's user-auditable CRUD and conflict-resolution policy. Those policies are therefore defined explicitly in this design.

Sources:

- https://docs.langchain.com/oss/python/concepts/memory
- https://docs.langchain.com/oss/python/langgraph/memory
- https://docs.langchain.com/oss/python/langgraph/add-memory
- https://docs.mem0.ai/overview
- https://docs.mem0.ai/api-reference/memory
- https://docs.letta.com/guides/agents/memory-blocks
- https://learn.microsoft.com/en-us/semantic-kernel/concepts/vector-store-connectors/
- https://research.google/pubs/generative-agents-interactive-simulacra-of-human-behavior/
- https://arxiv.org/abs/2304.03442

## Chosen Approach

Use manual or explicit long-term memory CRUD first.

Users create, edit, and delete memories through a small UI. The backend stores them in a dedicated `memories` table. Chat may retrieve active memories and inject them into the LLM context with a clear caveat: they are user-editable memory records and should be treated as contextual hints, not absolute truth.

This is preferred over automatic extraction or vector search because it is smaller, auditable, safer for privacy, and directly satisfies Stage 3 acceptance rules.

## Non-Goals

- No automatic memory extraction from chat.
- No background LLM memory writer.
- No embedding provider or vector database.
- No session summary system.
- No emotion state, relationship score, mood, trust, concern, irritation, or formality field.
- No claim that the character has real memory or consciousness.
- No voice feature changes.

## Data Model

Add a `Memory` domain model with these fields:

```text
id: string
content: string
memory_type: user_fact | preference | long_term_goal | important_event | relationship_event | other
source: manual
source_session_id: string | null
importance: integer, 1 through 5
confidence: float, 0.0 through 1.0
status: active | archived
created_at: datetime
updated_at: datetime
metadata: object
```

### Field Meaning

- `content`: concise human-readable memory text, for example `用户偏好中文回复。`.
- `memory_type`: categorizes why the memory exists.
- `source`: first slice only supports `manual`.
- `source_session_id`: optional link to a chat session if the user creates a memory while viewing that session.
- `importance`: user/system ranking for retrieval order. Default `3`.
- `confidence`: confidence in correctness. Manual memories default to `1.0`.
- `status`: deletion is implemented as archive in the first slice, so audit data remains recoverable in SQLite while UI/API default list excludes archived records.
- `metadata`: reserved for non-sensitive implementation metadata. It must not store API keys, raw audio, private credentials, or hidden prompts.

## SQLite Schema

Add a `memories` table in `SCHEMA_SQL`:

```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
    source TEXT NOT NULL CHECK (source IN ('manual')),
    source_session_id TEXT,
    importance INTEGER NOT NULL CHECK (importance >= 1 AND importance <= 5),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_status_importance_updated
ON memories(status, importance DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_type_status
ON memories(memory_type, status);
```

This keeps long-term memory independent from chat messages while allowing optional source-session traceability.

## Backend Components

### `backend/app/domain/models.py`

Add:

- `MemoryType` enum.
- `MemorySource` enum.
- `MemoryStatus` enum.
- `Memory` dataclass.

### `backend/app/domain/schemas.py`

Add Pydantic schemas:

- `MemoryResponse`
- `CreateMemoryRequest`
- `UpdateMemoryRequest`
- `MemoryConflictResponse`
- `CreateMemoryResponse`
- `UpdateMemoryResponse`

Create/update responses include `memory` and `conflicts` so the API can warn without overwriting.

### `backend/app/repositories/memories.py`

Add `MemoryRepository` with:

- `create(...) -> tuple[Memory, list[Memory]]`
- `list(status: MemoryStatus = ACTIVE) -> list[Memory]`
- `get(memory_id: str) -> Memory | None`
- `require(memory_id: str) -> Memory`
- `update(memory_id: str, ...) -> tuple[Memory, list[Memory]]`
- `archive(memory_id: str) -> bool`
- `list_for_context(limit: int) -> list[Memory]`
- `find_conflicts(content: str, memory_type: MemoryType, exclude_id: str | None = None) -> list[Memory]`

Conflict rule for the first slice:

- Normalize content by trimming whitespace and lowercasing ASCII characters.
- A conflict exists when another active memory of the same `memory_type` has exactly the same normalized content.
- The repository returns conflicts but does not overwrite or archive them automatically.

This is intentionally conservative. Semantic contradiction detection can be added later as a separate Stage 3 task.

### `backend/app/api/routes/memories.py`

Add routes:

- `GET /api/memories?status=active`
- `POST /api/memories`
- `PATCH /api/memories/{memory_id}`
- `DELETE /api/memories/{memory_id}`

Delete archives the memory and returns `204 No Content`.

Validation:

- `content`: 1 to 1000 chars after trim.
- `importance`: 1 to 5.
- `confidence`: 0.0 to 1.0.
- `memory_type`: enum value.
- `source_session_id`: optional; if provided, it must point to an existing session.

### `backend/app/api/dependencies.py`

Add `get_memory_repository`.

### `backend/app/main.py`

Include the new memories router.

## Chat Context Integration

The first implementation should include a small, explicit integration so memories are not only stored but can affect chat behavior.

Update `ContextBuilder` to accept an optional `MemoryRepository` and a max memory count. It should build two separate context sections:

1. Long-term memory context.
2. Recent chat context.

The LLM message sequence should remain:

```text
system prompt
system memory context message, if any
recent user/assistant messages
```

The memory context message must say:

```text
以下是用户可查看、可修改、可删除的长期记忆记录，仅作为回复时的参考上下文；它们可能过时或不完整，不得描述为绝对事实，也不得声称你具有真实人类记忆。
- [preference | importance 3 | confidence 1.00] 用户偏好中文回复。
```

This wording preserves the Stage 1/3 safety boundary.

Add config:

- `MEMORY_CONTEXT_ENABLED`, default `true`.
- `MEMORY_CONTEXT_LIMIT`, default `8`.

Do not add auto-write config in this slice.

## Frontend Components

### API Types and Client

Add TypeScript types:

- `MemoryType`
- `MemoryStatus`
- `MemoryRecord`
- `CreateMemoryRequest`
- `UpdateMemoryRequest`
- `MemoryMutationResponse`

Add `apiClient` methods:

- `listMemories()`
- `createMemory(request)`
- `updateMemory(id, request)`
- `deleteMemory(id)`

### UI

Add a small `MemoryPanel` component rendered in `ChatLayout`.

Panel behavior:

- Shows a title: `长期记忆`.
- Shows helper text: `只保存你明确创建或确认的内容；聊天记录不会自动变成长期记忆。`
- Lists active memories with type, importance, confidence, and content.
- Provides a minimal create form:
  - content input/textarea
  - memory type select
  - importance select, default 3
  - confidence input/select, default 1.0
- Provides edit and delete actions for each memory.
- Shows conflict warnings returned by create/update responses.

Placement:

- First slice can render it below `SessionList` in the left column or below the chat messages in the main panel. The recommended placement is below `SessionList` because it is global, not per-message.

## Error Handling

- API validation errors use existing app error envelope where possible.
- Missing memory returns `404` with a user-readable message.
- Invalid source session returns `404` or validation error and does not create memory.
- Duplicate same-type content returns `201` or `200` with conflicts in response; it does not fail the operation because a user may intentionally store similar facts. The UI must display the conflict warning.
- Text chat must remain usable if memory loading fails. The UI shows memory panel error without blocking chat.
- Chat generation must continue if memory retrieval fails only when the failure is non-corrupt recoverable; for the first slice, repository errors should surface as normal server errors in tests rather than being swallowed silently.

## Testing Strategy

### Backend repository tests

Add tests for:

- Create/list/get memory.
- Memories persist after reconnect.
- Archive hides memory from default active list.
- Chat messages do not appear in memory list.
- Duplicate same-type active content is returned as a conflict and does not overwrite the existing row.
- Same content in different type is not a conflict.

### Backend API tests

Add tests for:

- `POST /api/memories` creates manual memory with required metadata.
- `GET /api/memories` lists active memories.
- `PATCH /api/memories/{id}` updates content, importance, confidence, and type.
- `DELETE /api/memories/{id}` archives memory.
- Invalid importance/confidence/type is rejected.
- Provided missing `source_session_id` is rejected.
- Duplicate create returns conflicts without deleting or changing the previous memory.

### Chat context tests

Add tests for:

- Memory context is inserted as a separate system message before recent chat messages.
- Memory context includes the caveat that memories are user-editable context and not absolute facts.
- Disabling `MEMORY_CONTEXT_ENABLED` removes memory context.
- Recent chat context still works without any memories.

### Frontend tests

Add tests for:

- `apiClient` memory methods call the expected endpoints.
- `MemoryPanel` renders empty state and helper boundary text.
- User can create a memory and see it in the list.
- Delete archives/removes memory from active UI list.
- Conflict warnings render without blocking chat UI.
- Chat UI remains usable if memory list load fails.

### End-to-end test

Add one fake-provider E2E test:

1. Load app.
2. Create a manual memory.
3. Verify it appears in the memory panel.
4. Send a text message.
5. Verify chat still completes.

This test proves memory UI does not break existing text chat. It does not need to verify real LLM semantic use of the memory.

## Documentation Updates

Update:

- `CLAUDE.md`: mark Stage 3 memory foundation slice completed only after tests pass.
- `README.md`: document memory CRUD, stage boundary, and the fact that chat history is not automatically saved as memory.
- New evidence doc: `docs/stage3-memory-foundation.md` with validation commands and results.

## Privacy and Safety Boundaries

- Do not store raw audio.
- Do not store API keys or hidden prompts in memory metadata.
- Do not automatically infer sensitive facts.
- Do not claim memory is always correct.
- Let the user edit and delete memory.
- Keep memory records separate from chat messages.
- Do not implement emotional relationship state in this slice.

## Implementation Order

1. Backend repository tests for memory persistence and conflicts.
2. Backend model/schema/repository implementation.
3. Backend API tests and routes.
4. ContextBuilder tests for optional memory context.
5. ContextBuilder/ChatService integration.
6. Frontend API client tests/types.
7. MemoryPanel tests and implementation.
8. App/ChatLayout integration.
9. E2E smoke.
10. Docs and final verification.

## Acceptance Criteria

- User can create, view, edit, and delete/archive long-term memories.
- Each memory has source, timestamps, type, importance, confidence, and status.
- Memory storage is independent from chat messages.
- Duplicate same-type memory content is surfaced as a conflict and does not silently overwrite.
- Chat can include active memories as caveated context.
- Memory retrieval is presented as context, not absolute truth.
- Text chat remains usable if memory UI has an error.
- No Stage 4 emotion system is implemented.
- Backend tests, frontend tests, typecheck, build, and E2E pass.

## Self-Review

- Placeholder scan: no TBD, TODO, or unspecified implementation placeholders remain.
- Internal consistency: the design uses manual memory writes throughout; it does not mix in automatic extraction.
- Scope check: the slice is focused on one subsystem, long-term memory foundation, with one small chat-context integration.
- Ambiguity check: delete behavior is explicitly archive; conflict detection is exact normalized duplicate within the same memory type; semantic contradiction detection is deferred.
