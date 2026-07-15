# MemoryPanel Inline Memory Editing Design

> Date: 2026-07-12  
> Status: Implemented and verified

## Goal

Complete Stage 3 GUI CRUD by wiring the existing `onUpdate` callback into a minimal inline editor for active long-term memories. Pending candidates remain confirmation-only and are never directly edited.

## Alternatives

1. **Inline editor per active memory — chosen.** Keeps context, reuses existing fields/options, and needs no navigation or modal infrastructure.
2. Separate edit form — rejected because it duplicates the create form and makes the selected record less obvious.
3. Browser prompt — rejected because it cannot safely edit structured type/importance/confidence fields and has poor accessibility/error behavior.

## Interaction

Each active memory item adds an `编辑记忆` button beside `删除记忆`.

Clicking edit replaces that item's read-only content/metadata with fields initialized from the record:

- content textarea, max length 1000;
- memory type select using existing options;
- importance number, integer 1–5;
- confidence number, step 0.05, range 0–1.

Only one item may be edited at a time. The row shows `保存修改` and `取消编辑`.

Save trims content and calls the existing callback:

```ts
onUpdate(memory.id, {
  content,
  memory_type: memoryType,
  importance,
  confidence,
})
```

After a successful Promise resolution, editing closes. If it rejects, editing remains open; the parent already owns and displays the shared error state. Cancel closes without calling `onUpdate` and discards local changes.

Save is disabled while content is blank or while the row is submitting. Edit/delete controls for that row are replaced while editing. The panel-level `loading` state disables edit actions, but does not silently discard an open edit.

## Boundaries

- Only records in `memories` are editable; `candidates` remain confirm/dismiss only.
- No conflict-resolution UI is added. If update returns conflicts, the parent refreshes the existing conflict panel through current behavior.
- No optimistic mutation: the parent remains the source of truth and refreshes records after a successful update.
- No summary, emotion, avatar, or visual redesign work.
- Existing create/delete/candidate behavior remains unchanged.

## State

`MemoryPanel` owns minimal ephemeral state:

- `editingMemoryId: string | null`;
- edit content/type/importance/confidence values;
- `updatingMemoryId: string | null`.

Starting another edit replaces the previous draft explicitly. Prop updates do not overwrite a draft while the same item remains in edit mode.

## Accessibility and errors

- Labels include the memory context, e.g. `编辑记忆内容`.
- Buttons have distinct names: `编辑记忆`, `保存修改`, `取消编辑`, `删除记忆`.
- Number inputs use native min/max/step constraints.
- Promise rejection is caught locally only to keep the editor open; the parent-provided `error` remains rendered with `role="alert"`.
- No message content is logged.

## Tests

Component tests must prove:

- active memory exposes edit; pending candidate does not;
- fields initialize from the selected record;
- save calls `onUpdate` with trimmed, typed values;
- successful save exits editing;
- cancel does not call update and restores read-only view;
- blank content disables save;
- rejected update keeps editor open and shared error remains visible;
- create/delete/confirm/dismiss tests remain green.

Verification:

- focused `MemoryPanel.test.tsx` passes;
- full frontend Vitest, typecheck, and build pass;
- browser/E2E or component-driven interaction observes edit → save → refreshed memory;
- backend 410-test baseline remains unaffected because no backend file changes.
