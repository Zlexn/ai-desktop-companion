# Windows Electron Dual-Window Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows 11 development-only Electron shell that preserves the existing React chat renderer as the sole owner of chat, API, recording, TTS, playback, and Stage 4E presentation state while providing a transparent, tray-controlled, read-only pet window.

**Architecture:** Electron main owns only desktop capabilities: constrained window/tray lifecycle, narrow IPC validation, in-memory presentation relay, window preferences, and controlled local static-asset storage. The React chat renderer derives complete versioned presentation snapshots from the existing Stage 4E state and publishes them through a sandboxed preload; the pet renderer consumes only validated snapshots and renders a static authorized PNG/WebP or a neutral fallback. Main issues `projectionEpoch`, enforces epoch/sequence ordering, validates exact IPC objects, blocks non-whitelisted navigation/network egress, and never becomes a chat, audio, emotion, SQLite, or Provider state owner.

**Tech Stack:** Electron **43.1.1** as a pinned development dependency, native ESM `.mjs` Electron main/shared modules, sandbox-compatible CommonJS `.cjs` preloads, React + TypeScript + Vite renderers, Vitest/Testing Library/Playwright, Node filesystem APIs, Electron `nativeImage`, and existing fake FastAPI/TTS providers.

---

## Scope and non-goals

This plan implements only the approved Windows Electron dual-window development shell.

It must not:

- modify FastAPI application/domain code, SQLite schema, Stage 4 expression APIs, Provider interfaces, or backend startup behavior;
- launch, stop, restart, proxy around, or otherwise manage FastAPI or Vite from Electron;
- add Live2D, Cubism, model parsing, WebGL, lip-sync, animation packages, sidecars, installers, signing, auto-update, or packaging;
- store presentation snapshots, message identifiers, display labels, audio state, source asset paths, file names, prompts, credentials, or chat content in Electron settings, manifests, logs, or test evidence;
- introduce background recording, global shortcuts, automatic wake-word behavior, or remote control.

## File structure and responsibilities

### Create

- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\main.mjs`
  - Electron application entry point; registers the privileged `pet-asset:` scheme before readiness, creates the desktop controller, and handles true quit only.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\runtime-config.mjs`
  - Parses one exact development Vite origin and derives the allowed HTTP/WebSocket origins and chat/pet entry URLs.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\presentation-contract.mjs`
  - Single shared strict `PresentationSnapshotV1` parser and invariants used by both main and renderer bundles.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\presentation-contract.d.mts`
  - Type declarations for importing the native ESM shared contract from TypeScript renderers.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\settings.mjs`
  - Atomic, schema-validated settings persistence for window bounds, display identifier, always-on-top, and click-through only.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-store.mjs`
  - Validates authorized static PNG/WebP imports, atomically copies them to `userData/assets`, and maintains the manifest as the sole asset authority.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-scheme.mjs`
  - Implements fixed, read-only `pet-asset://active/current?revision=<n>` handling.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\projection-broker.mjs`
  - Issues epochs, validates chat publication order, stores only the latest valid snapshot in memory, relays snapshots/resets, and replays current state.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\security.mjs`
  - Creates hardened BrowserWindow preferences, CSP headers, explicit navigation/popup/download rules, permission policy, and outbound request allowlists.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\windows.mjs`
  - Creates singleton chat/pet windows, applies safe bounds restoration, controls hide-vs-quit semantics, draggable regions, always-on-top, and click-through.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\tray.mjs`
  - Creates the fixed tray menu and reflects actual window/native-API state.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\ipc.mjs`
  - Registers fixed IPC channels with sender, frame, origin, exact-object, and schema validation.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\preload-chat.cjs`
  - Exposes the restricted chat bridge; no generic IPC, Node, filesystem, paths, shell, environment, or Electron objects.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\preload-pet.cjs`
  - Exposes the restricted pet bridge for snapshot subscription/replay and limited pet-window interaction only.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\assets\neutral.png`
  - Repository-owned, neutral static PNG fallback fixture; no protected or user-provided material.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\presentation.ts`
  - Typed renderer-facing re-export of the shared parser and protocol types.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\bridge.ts`
  - Narrow TypeScript declarations for `window.desktopChat` and `window.desktopPet`.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\useDesktopProjection.ts`
  - Derives and publishes full snapshots from existing Stage 4E preview state; browser use remains a safe no-op.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\useDesktopControls.ts`
  - Owns chat-side desktop command status and sanitized asset/window feedback.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\components\DesktopControls.tsx`
  - Minimal chat UI for pet visibility, static asset import/clear, and safe state feedback.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\pet.html`
  - Independent pet Vite entry document.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\main.tsx`
  - React entry for the pet renderer.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\PetApp.tsx`
  - Read-only pet root; never imports API clients, audio hooks, recording code, or chat state.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\presentationReducer.ts`
  - Epoch/sequence/reset-aware pet state reducer with neutral/idle failure downgrade.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\StaticImageRenderer.tsx`
  - `contain`-based static asset renderer with limited delivery CSS and reduced-motion behavior.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\pet.css`
  - Transparent window styles, explicit pet hit target, finite delivery styles, phase animation, and reduced-motion override.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\vite.electron-tests.config.ts`
  - Node-environment Vitest configuration for Electron pure module/integration tests.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\scripts\smoke_windows_electron_shell.ps1`
  - Headed Windows-only fake-first smoke orchestration and cleanup verifier.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\scripts\smoke_windows_electron_shell.cmd`
  - Command Prompt wrapper for the PowerShell smoke.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\docs\windows-electron-shell-smoke-checklist.md`
  - Human-executed Windows tray/layering/click-through checklist, filled only with real observed results after validation.

### Modify

- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\package.json`
  - Pin Electron 43.1.1, add desktop/test/smoke scripts, and do not add a packager.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\package-lock.json`
  - Lock the exact Electron dependency graph generated by npm.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\vite.config.ts`
  - Support two renderer HTML entries and an explicitly configured loopback dev origin without changing the existing `/api` or `/health` proxy semantics.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\App.tsx`
  - Connect the existing Stage 4E preview state to desktop publication and desktop controls without moving business/audio ownership.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\components\ChatLayout.tsx`
  - Place `DesktopControls` in the chat UI and forward only desktop control state/callbacks.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\styles.css`
  - Add desktop-control styles only. The chat window keeps its native Windows frame; all pet transparent/drag rules remain in `src/pet/pet.css`.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\.gitignore`
  - Ignore only explicit Electron smoke output and local temporary `userData` directories.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\README.md`
  - Add run instructions and completed evidence only after all acceptance gates pass.
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\CLAUDE.md`
  - Update the current desktop-shell status only after real validation is complete.

### Test files to create

- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\presentation-contract.test.ts`
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\desktop-state.test.ts`
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-manifest.test.ts`
- `frontend/electron/asset-store.test.ts`
- `frontend/electron/asset-scheme.test.ts`
- `frontend/electron/projection-broker.test.ts`
- `frontend/electron/ipc.test.ts`
- `frontend/electron/security.test.ts`
- `frontend/electron/windows.test.ts`
- `frontend/electron/tray.test.ts`
- `frontend/electron/preload-contract.test.ts`
- `frontend/electron/desktop-application.integration.test.ts`
- `frontend/src/desktop/electronSetup.test.ts`
- `frontend/src/desktop/useDesktopProjection.test.tsx`
- `frontend/src/desktop/useDesktopControls.test.tsx`
- `frontend/src/pet/presentationReducer.test.ts`
- `frontend/src/pet/StaticImageRenderer.test.tsx`
- `frontend/src/pet/PetApp.test.tsx`
- `frontend/src/components/DesktopControls.test.tsx`
- `frontend/scripts/smoke-electron-shell.test.mjs`

---

## Task 1: Establish Electron development tooling and two renderer entries

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\dev-origin.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\electronSetup.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\pet.html`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\vite.electron-tests.config.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\package.json`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\package-lock.json`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\vite.config.ts`

- [ ] **Step 1: Add a failing configuration test that requires an exact Electron pin and pet HTML entry.**

```ts
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = resolve(import.meta.dirname, '..', '..');

it('pins Electron 43.1.1 and exposes development shell scripts', async () => {
  const pkg = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'));
  expect(pkg.devDependencies.electron).toBe('43.1.1');
  expect(pkg.scripts['desktop:renderer']).toBe('vite --host 127.0.0.1 --port 5173 --strictPort');
  expect(pkg.scripts['desktop:dev']).toBe('electron electron/main.mjs');
  expect(pkg.scripts['test:electron']).toContain('vite.electron-tests.config.ts');
});

it('has an independent pet renderer entry', async () => {
  const html = await readFile(resolve(root, 'pet.html'), 'utf8');
  expect(html).toContain('<script type="module" src="/src/pet/main.tsx"></script>');
});
```

- [ ] **Step 2: Run the focused test and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run src/desktop/electronSetup.test.ts
Pop-Location
```

Expected: FAIL because `electron` is not pinned and `pet.html` does not exist.

- [ ] **Step 3: Add the pinned dependency, scripts, entry page, and Vite multi-page configuration.**

Create `frontend/dev-origin.mjs` as the single configuration source:

```js
export const DESKTOP_DEV_HOST = '127.0.0.1';
export const DESKTOP_DEV_PORT = 5173;
export const DESKTOP_DEV_ORIGIN = `http://${DESKTOP_DEV_HOST}:${DESKTOP_DEV_PORT}`;
export const DESKTOP_DEV_WS_ORIGIN = `ws://${DESKTOP_DEV_HOST}:${DESKTOP_DEV_PORT}`;
export const DESKTOP_CSP_NONCE = 'ai-desktop-dev-shell';
```

Both `vite.config.ts` and `electron/runtime-config.mjs` import these constants. Set Vite `html.cspNonce: DESKTOP_CSP_NONCE` so `@vitejs/plugin-react` applies it to the injected Fast Refresh module preamble/scripts; Task 4 includes the matching nonce in CSP `script-src`. Task 4 may validate an optional `VITE_DEV_ORIGIN`, but it must equal `DESKTOP_DEV_ORIGIN` exactly. This prevents Vite, Electron, CSP, and smoke from selecting different aliases/ports.

Use the following exact `package.json` additions; retain all existing scripts and dependencies.

```json
{
  "scripts": {
    "desktop:renderer": "vite --host 127.0.0.1 --port 5173 --strictPort",
    "desktop:dev": "electron electron/main.mjs",
    "test:electron": "vitest run --config vite.electron-tests.config.ts",
    "smoke:electron:windows": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ..\\scripts\\smoke_windows_electron_shell.ps1"
  },
  "devDependencies": {
    "electron": "43.1.1"
  }
}
```

Use this Vite build entry configuration while preserving the existing proxy entries unchanged:

```ts
import { resolve } from 'node:path';
import { DESKTOP_CSP_NONCE } from './dev-origin.mjs';

html: { cspNonce: DESKTOP_CSP_NONCE },
build: {
  rollupOptions: {
    input: {
      chat: resolve(import.meta.dirname, 'index.html'),
      pet: resolve(import.meta.dirname, 'pet.html'),
    },
  },
},
server: {
  host: '127.0.0.1',
  port: 5173,
  strictPort: true,
  origin: 'http://127.0.0.1:5173',
  proxy: {
    '/api': {
      target: backendProxyTarget,
      changeOrigin: true,
      timeout: longProxyTimeoutMs,
      proxyTimeout: longProxyTimeoutMs,
    },
    '/health': {
      target: backendProxyTarget,
      changeOrigin: true,
      timeout: longProxyTimeoutMs,
      proxyTimeout: longProxyTimeoutMs,
    },
  },
},
```

Create `pet.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 桌宠悬浮窗</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/pet/main.tsx"></script>
  </body>
</html>
```

Create the Node test configuration:

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['electron/**/*.test.ts'],
    exclude: ['node_modules/**', 'dist/**'],
  },
});
```

Install only the locked development dependency:

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm install --save-dev --save-exact electron@43.1.1
Pop-Location
```

- [ ] **Step 4: Run setup, type, and production-build checks.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run src/desktop/electronSetup.test.ts
npm run typecheck
npm run build
Pop-Location
```

Expected: PASS; the build emits both chat and pet HTML entry bundles. No Electron application is started by these commands.

- [ ] **Step 5: Commit the tooling boundary.**

```powershell
git add "frontend/package.json" "frontend/package-lock.json" "frontend/dev-origin.mjs" "frontend/vite.config.ts" "frontend/pet.html" "frontend/vite.electron-tests.config.ts" "frontend/src/desktop/electronSetup.test.ts"
git commit -m "build: add pinned Electron development shell tooling"
```

---

## Task 2: Define the shared strict presentation contract

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\presentation-contract.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\presentation-contract.d.mts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\presentation-contract.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\bridge.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\presentation.ts`

- [ ] **Step 1: Write parser tests for exact objects, Stage 4E enums, finite values, and state invariants.**

```ts
import { describe, expect, it } from 'vitest';
import { parsePresentationSnapshot } from './presentation-contract.mjs';

const valid = {
  schemaVersion: 1,
  projectionEpoch: 4,
  sequence: 7,
  selectedAssistantMessageId: 'assistant-1',
  expression: {
    assistantMessageId: 'assistant-1',
    delivery: 'warm',
    intensity: 'medium',
    rate: 1,
    source: 'persisted_plan',
  },
  phase: 'speaking',
  activeRun: { assistantMessageId: 'assistant-1', playbackRunId: 9 },
  displayLabel: '已截断的助手消息',
  asset: { kind: 'static', assetRevision: 3 },
};

describe('parsePresentationSnapshot', () => {
  it('accepts the complete version-one snapshot', () => {
    expect(parsePresentationSnapshot(valid)).toEqual(valid);
  });

  it.each([
    [{ ...valid, unknown: true }],
    [{ ...valid, sequence: Number.NaN }],
    [{ ...valid, expression: { ...valid.expression, assistantMessageId: 'different' } }],
    [{ ...valid, expression: { ...valid.expression, intensity: 'high' } }],
    [{ ...valid, expression: { ...valid.expression, source: 'local_fallback' } }],
    [{ ...valid, phase: 'speaking', activeRun: null }],
    [{ ...valid, activeRun: { assistantMessageId: 'different', playbackRunId: 9 } }],
    [{ ...valid, displayLabel: 'x'.repeat(257) }],
  ])('rejects invalid exact snapshot %#', (value) => {
    expect(() => parsePresentationSnapshot(value)).toThrow('DESKTOP_INVALID_SNAPSHOT');
  });
});
```

- [ ] **Step 2: Run the parser test and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/shared/presentation-contract.test.ts
Pop-Location
```

Expected: FAIL because the shared module does not exist.

- [ ] **Step 3: Implement a strict, common native-ESM parser.**

Use a reusable exact-object helper; never cast an unvalidated input object into the protocol type.

```js
const DELIVERY = new Set(['neutral', 'warm', 'reassuring', 'reserved', 'firm']);
const INTENSITY = new Set(['low', 'medium']);
const SOURCE = new Set(['persisted_plan', 'default']);
const PHASE = new Set(['idle', 'ready', 'speaking', 'paused']);

function invalid() {
  throw new Error('DESKTOP_INVALID_SNAPSHOT');
}

function exactRecord(value, keys) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) invalid();
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) invalid();
  return value;
}

function safeInteger(value) {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

export function parsePresentationSnapshot(value) {
  const item = exactRecord(value, [
    'schemaVersion', 'projectionEpoch', 'sequence', 'selectedAssistantMessageId',
    'expression', 'phase', 'activeRun', 'displayLabel', 'asset',
  ]);
  if (item.schemaVersion !== 1 || !safeInteger(item.projectionEpoch) || !safeInteger(item.sequence)) invalid();
  if (item.selectedAssistantMessageId !== null && (typeof item.selectedAssistantMessageId !== 'string' || item.selectedAssistantMessageId.length < 1 || item.selectedAssistantMessageId.length > 128)) invalid();
  if (!PHASE.has(item.phase)) invalid();

  const expression = parseExpression(item.expression);
  const activeRun = parseActiveRun(item.activeRun);
  if (item.displayLabel !== null && (typeof item.displayLabel !== 'string' || Array.from(item.displayLabel).length > 256)) invalid();
  const asset = parseAsset(item.asset);

  if (item.phase === 'idle' && (expression !== null || activeRun !== null)) invalid();
  if (item.phase === 'ready' && (expression === null || activeRun !== null)) invalid();
  if ((item.phase === 'speaking' || item.phase === 'paused') && (expression === null || activeRun === null)) invalid();
  if (item.phase !== 'idle' && expression.assistantMessageId !== item.selectedAssistantMessageId) invalid();
  if (activeRun !== null && item.selectedAssistantMessageId !== activeRun.assistantMessageId) invalid();

  return {
    schemaVersion: 1,
    projectionEpoch: item.projectionEpoch,
    sequence: item.sequence,
    selectedAssistantMessageId: item.selectedAssistantMessageId,
    expression,
    phase: item.phase,
    activeRun,
    displayLabel: item.displayLabel,
    asset,
  };
}
```

Implement `parseExpression`, `parseActiveRun`, and `parseAsset` with the same `exactRecord` rule. `parseExpression` must require exactly `assistantMessageId`, `delivery`, `intensity`, `rate`, and `source`; the ID is 1–128 characters and must match `selectedAssistantMessageId` for every non-idle snapshot. It allows only the five existing deliveries, `low | medium`, `persisted_plan | default`, and a finite `rate` in the current Stage 4E `[0.9, 1.1]` range. `parseActiveRun` must require an `assistantMessageId` of 1–128 characters and positive safe `playbackRunId`. `parseAsset` must require exactly `kind` and `assetRevision`, accept only `neutral | static`, and require a non-negative safe revision.

Expose typed declarations using the same literal union types, then re-export these types and the parser in `src/desktop/presentation.ts`. In the same task create `src/desktop/bridge.ts` with the complete, fixed `DesktopChatBridge` and `DesktopPetBridge` method signatures listed in Task 9 and global `Window` declarations. Task 3 may depend on `window.desktopPet` immediately; Task 9 supplies the matching preload implementation without changing this public renderer contract.

- [ ] **Step 4: Run protocol tests and renderer typecheck.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/shared/presentation-contract.test.ts
npm run typecheck
Pop-Location
```

Expected: PASS. Invalid objects fail with the fixed `DESKTOP_INVALID_SNAPSHOT` code, with no payload data in errors.

- [ ] **Step 5: Commit the protocol contract.**

```powershell
git add "frontend/electron/shared/presentation-contract.mjs" "frontend/electron/shared/presentation-contract.d.mts" "frontend/electron/shared/presentation-contract.test.ts" "frontend/src/desktop/presentation.ts" "frontend/src/desktop/bridge.ts"
git commit -m "feat: define strict desktop presentation contract"
```

---

## Task 3: Implement the read-only pet renderer and epoch-aware reducer

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\presentationReducer.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\presentationReducer.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\StaticImageRenderer.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\StaticImageRenderer.test.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\PetApp.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\PetApp.test.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\main.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\pet\pet.css`

- [ ] **Step 1: Write reducer tests for reset, stale epoch, stale sequence, and neutral fallback.**

```ts
import { describe, expect, it } from 'vitest';
import { initialPetPresentation, petPresentationReducer } from './presentationReducer';

const snapshot = (projectionEpoch: number, sequence: number) => ({
  schemaVersion: 1 as const,
  projectionEpoch,
  sequence,
  selectedAssistantMessageId: 'assistant-1',
  expression: { assistantMessageId: 'assistant-1', delivery: 'warm' as const, intensity: 'low' as const, rate: 1, source: 'default' as const },
  phase: 'speaking' as const,
  activeRun: { assistantMessageId: 'assistant-1', playbackRunId: 1 },
  displayLabel: '助手消息',
  asset: { kind: 'static' as const, assetRevision: 2 },
});

it('accepts only a newer sequence in the current epoch', () => {
  const first = petPresentationReducer(initialPetPresentation, { type: 'snapshot', snapshot: snapshot(2, 1) });
  const stale = petPresentationReducer(first, { type: 'snapshot', snapshot: snapshot(2, 1) });
  const next = petPresentationReducer(first, { type: 'snapshot', snapshot: snapshot(2, 2) });
  expect(stale).toEqual(first);
  expect(next.sequence).toBe(2);
});

it('clears state on epoch reset and rejects old-epoch data', () => {
  const active = petPresentationReducer(initialPetPresentation, { type: 'snapshot', snapshot: snapshot(4, 5) });
  const reset = petPresentationReducer(active, { type: 'reset', projectionEpoch: 5 });
  const stale = petPresentationReducer(reset, { type: 'snapshot', snapshot: snapshot(4, 99) });
  expect(reset).toEqual({ ...initialPetPresentation, projectionEpoch: 5 });
  expect(stale).toEqual(reset);
});
```

- [ ] **Step 2: Run focused renderer tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run src/pet/presentationReducer.test.ts src/pet/StaticImageRenderer.test.tsx
Pop-Location
```

Expected: FAIL because no pet renderer modules exist.

- [ ] **Step 3: Implement renderer state and static rendering without business imports.**

The reducer must hold only the current validated snapshot and a `(projectionEpoch, sequence)` watermark. It must reset to this state:

```ts
export const initialPetPresentation = {
  projectionEpoch: -1,
  sequence: -1,
  snapshot: null,
};
```

On malformed bridge data, `PetApp` must dispatch reset/fallback rather than throw into chat or request any API. The fixed asset URL must be derived only from snapshot revision:

```ts
const assetUrl = `pet-asset://active/current?revision=${snapshot.asset.assetRevision}`;
```

`StaticImageRenderer` must receive a renderer-neutral view model only:

```ts
interface CharacterPresentation {
  delivery: 'neutral' | 'warm' | 'reassuring' | 'reserved' | 'firm';
  intensity: 'low' | 'medium';
  rate: number;
  phase: 'idle' | 'ready' | 'speaking' | 'paused';
  activeRun: { assistantMessageId: string; playbackRunId: number } | null;
  assetRevision: number;
}
```

It must render an image with `object-fit: contain`, use a fixed Chinese fallback label, provide a bounded `.pet-hit-target` drag region, and never display message text, file names, IDs, paths, or audio controls. Apply lightweight speaking animation only for `phase === 'speaking'`; disable it under:

```css
@media (prefers-reduced-motion: reduce) {
  .pet-character,
  .pet-character--speaking {
    animation: none;
    transition: none;
  }
}
```

- [ ] **Step 4: Run the pet tests and production build.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run src/pet/presentationReducer.test.ts src/pet/StaticImageRenderer.test.tsx src/pet/PetApp.test.tsx
npm run build
Pop-Location
```

Expected: PASS. Search confirms `src/pet/` does not import `../api/client`, audio controllers, recorder hooks, or browser storage.

- [ ] **Step 5: Commit the isolated pet renderer.**

```powershell
git add "frontend/src/pet" "frontend/pet.html"
git commit -m "feat: add read-only static pet renderer"
```

---

## Task 4: Add hardened runtime configuration and BrowserWindow security defaults

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\runtime-config.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\security.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\security.test.ts`

- [ ] **Step 1: Write security tests for exact origin parsing, CSP, and blocked outbound classes.**

```ts
it('accepts only the configured loopback Vite origin', () => {
  expect(() => parseRuntimeConfig({ VITE_DEV_ORIGIN: 'http://127.0.0.1:5173' })).not.toThrow();
  expect(() => parseRuntimeConfig({ VITE_DEV_ORIGIN: 'http://localhost:5173' })).toThrow('DESKTOP_INVALID_VITE_ORIGIN');
  expect(() => parseRuntimeConfig({ VITE_DEV_ORIGIN: 'http://127.0.0.1:5174' })).toThrow('DESKTOP_INVALID_VITE_ORIGIN');
});

it('blocks external fetches but retains Vite HMR, same-origin proxy, blob audio, and pet assets', () => {
  const policy = createRequestPolicy(parseRuntimeConfig({ VITE_DEV_ORIGIN: 'http://127.0.0.1:5173' }));
  expect(policy.allows('https://example.com/beacon.png', 'image')).toBe(false);
  expect(policy.allows('ws://127.0.0.1:5173/', 'webSocket')).toBe(true);
  expect(policy.allows('http://127.0.0.1:5173/api/sessions', 'xhr')).toBe(true);
  expect(policy.allows('blob:opaque-audio-id', 'media')).toBe(true);
  expect(policy.allows('pet-asset://active/current?revision=1', 'image')).toBe(true);
});
```

- [ ] **Step 2: Run focused security tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/security.test.ts
Pop-Location
```

Expected: FAIL because runtime configuration and security modules do not exist.

- [ ] **Step 3: Implement exact configuration and secure BrowserWindow defaults.**

Every window must set:

```js
webPreferences: {
  nodeIntegration: false,
  contextIsolation: true,
  sandbox: true,
  webSecurity: true,
  preload,
}
```

Import `DESKTOP_DEV_ORIGIN` / `DESKTOP_DEV_WS_ORIGIN` from `frontend/dev-origin.mjs`. `parseRuntimeConfig` accepts no different host or port: if `VITE_DEV_ORIGIN` is provided it must equal the shared `http://127.0.0.1:5173` value exactly; reject `localhost`, credentials, path, query, and fragment, and derive:

```js
{
  viteOrigin: 'http://127.0.0.1:5173',
  viteWebSocketOrigin: 'ws://127.0.0.1:5173',
  chatUrl: 'http://127.0.0.1:5173/',
  petUrl: 'http://127.0.0.1:5173/pet.html',
}
```

Install response-header CSP through Electron session hooks. Record the actual Vite-compatible development directives in code:

```text
Chat:
default-src 'none';
script-src 'self' 'nonce-ai-desktop-dev-shell';
style-src 'self' 'unsafe-inline';
connect-src 'self' ws://127.0.0.1:5173;
img-src 'self' pet-asset: data:;
media-src 'self' blob:;
frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'

Pet:
default-src 'none';
script-src 'self' 'nonce-ai-desktop-dev-shell';
style-src 'self' 'unsafe-inline';
img-src 'self' pet-asset: data:;
connect-src ws://127.0.0.1:5173;
media-src 'none';
frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'
```

Generate both CSP strings from `runtimeConfig.viteOrigin`, `runtimeConfig.viteWebSocketOrigin`, and the shared `DESKTOP_CSP_NONCE`; the shown `5173`/nonce values are the default concrete result, not independent constants. Assert the Vite-served chat and pet HTML preamble/script tags carry this nonce and that Fast Refresh connects without CSP violations. Use `webContents.setWindowOpenHandler(() => ({ action: 'deny' }))`, prevent non-Vite navigation, prevent downloads, reject all permission requests for pet, and allow only chat `media` requests originating from the exact Vite chat origin. Do not use wildcard domains, aliases, arbitrary loopback ports, `unsafe-inline` for scripts, or permissive `*` CSP directives.

- [ ] **Step 4: Run security tests and a manual DevTools CSP inspection.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/security.test.ts
npm run typecheck
Pop-Location
```

Expected: PASS. During later headed smoke, verify no CSP console violations for Vite HMR, `/api`, `/health`, `blob:` playback, or `pet-asset:` image loading.

- [ ] **Step 5: Commit the security baseline.**

```powershell
git add "frontend/electron/runtime-config.mjs" "frontend/electron/security.mjs" "frontend/electron/security.test.ts"
git commit -m "feat: harden Electron renderer security boundary"
```

---

## Task 5: Implement settings, safe bounds restoration, and window preferences only

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\settings.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\settings.test.ts`

- [ ] **Step 1: Write tests for exact settings schema, corruption fallback, clamping, and prohibited fields.**

```ts
it('uses safe defaults for damaged settings and quarantines the damaged file', async () => {
  await fs.writeFile(settingsPath, '{"assetRevision":99}', 'utf8');
  await expect(store.load()).resolves.toEqual(defaultDesktopSettings);
  expect(await fs.readdir(tempDirectory)).toContainEqual(expect.stringMatching(/^desktop-settings\.corrupt-/));
});

it('clamps offscreen pet bounds into the current display work area', () => {
  expect(clampBounds(
    { x: -9000, y: -9000, width: 480, height: 480 },
    { x: 0, y: 0, width: 1920, height: 1040 },
  )).toEqual({ x: 16, y: 16, width: 480, height: 480 });
});
```

- [ ] **Step 2: Run settings tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/settings.test.ts
Pop-Location
```

Expected: FAIL because no settings module exists.

- [ ] **Step 3: Implement atomic settings with a deliberately narrow schema.**

The only accepted persisted structure is:

```ts
{
  schemaVersion: 1,
  chatBounds: { x: number, y: number, width: number, height: number } | null,
  petBounds: { x: number, y: number, width: number, height: number, displayId: string | null } | null,
  petAlwaysOnTop: boolean,
  petClickThrough: boolean
}
```

Require exact object keys; reject `asset`, `assetRevision`, `activeAssetId`, `expression`, `phase`, `selectedAssistantMessageId`, `displayLabel`, or arbitrary nested fields. Persist only on `move`/`resize` completion events with debounced save, not continuously. Use temp-file write followed by rename for atomic replacement. On parse/schema failure, move the invalid settings file to a generated `desktop-settings.corrupt-<timestamp>.json` name and load defaults.

For first pet display, calculate a visible right-bottom location from the primary display `workArea`, with a fixed safe margin and dimensions that fit into the work area. On restore, clamp bounds into the target display work area and fall back to primary display when saved `displayId` is unavailable.

- [ ] **Step 4: Run settings tests.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/settings.test.ts
Pop-Location
```

Expected: PASS. The test suite proves settings cannot become a second asset or presentation state store.

- [ ] **Step 5: Commit settings isolation.**

```powershell
git add "frontend/electron/settings.mjs" "frontend/electron/settings.test.ts"
git commit -m "feat: persist only safe desktop window preferences"
```

---

## Task 6: Implement atomic authorized static-asset import and manifest recovery

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-manifest.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-store.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-manifest.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-store.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\test-fixtures\authorized-static.png`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\test-fixtures\authorized-static.webp`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\test-fixtures\animated.webp`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\test-fixtures\invalid-image.bin`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\assets\neutral.png`

- [ ] **Step 1: Write failing asset tests for valid import, rejection, rollback, clear, and restart restoration.**

```ts
it('copies a valid authorized PNG under an opaque ID and never persists source metadata', async () => {
  const result = await store.importFile(sourcePngPath);
  expect(result).toEqual({ kind: 'static', assetRevision: 1 });
  const manifest = await store.readManifestForTest();
  expect(manifest).toMatchObject({ schemaVersion: 1, kind: 'static', assetRevision: 1 });
  expect(JSON.stringify(manifest)).not.toContain(sourcePngPath);
  expect(JSON.stringify(manifest)).not.toContain('original-name');
});

it('removes the renamed destination when atomic manifest replacement fails', async () => {
  store.failNextManifestReplaceForTest();
  await expect(store.importFile(sourcePngPath)).rejects.toThrow('DESKTOP_ASSET_IMPORT_FAILED');
  expect(await store.listInternalAssetsForTest()).toEqual([]);
});

it('serializes concurrent import and clear mutations without colliding revisions', async () => {
  await Promise.allSettled([store.importFile(sourcePngPath), store.clear()]);
  const manifest = await store.readManifestForTest();
  expect(manifest.assetRevision).toBeGreaterThan(0);
  await expect(store.assertManifestTargetExists()).resolves.toBe(true);
});

it.each([
  ['malformed JSON', '{'],
  ['extra fields', JSON.stringify({ schemaVersion: 1, kind: 'neutral', activeAssetId: null, fileName: null, assetRevision: 0, path: 'secret' })],
  ['traversal filename', JSON.stringify({ schemaVersion: 1, kind: 'static', activeAssetId: 'a'.repeat(32), fileName: '../x.png', assetRevision: 1 })],
])('quarantines %s and recovers to a neutral exact manifest', async (_name, contents) => {
  await fs.writeFile(manifestPath, contents, 'utf8');
  await expect(store.load()).resolves.toEqual({ kind: 'neutral', assetRevision: expect.any(Number) });
});

it.each([
  ['wrong extension', fakeJpegPath],
  ['signature mismatch', pngNamedWebpPath],
  ['animated PNG', animatedPngPath],
  ['animated WebP', animatedWebpPath],
  ['oversized dimensions', giantHeaderPngPath],
])('rejects %s without changing the active asset', async (_name, path) => {
  const before = await store.readManifestForTest();
  await expect(store.importFile(path)).rejects.toThrow('DESKTOP_ASSET_INVALID');
  expect(await store.readManifestForTest()).toEqual(before);
});
```

- [ ] **Step 2: Run asset-store tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/asset-store.test.ts
Pop-Location
```

Expected: FAIL because asset storage does not exist.

- [ ] **Step 3: Implement the import transaction and manifest parser.**

Use this manifest, and no other persistent asset representation:

```ts
interface AssetManifestV1 {
  schemaVersion: 1;
  activeAssetId: string | null;
  kind: 'neutral' | 'static';
  fileName: string | null;
  assetRevision: number;
}
```

Implement `parseAssetManifestV1` in `asset-manifest.mjs` with exact keys and cross-field invariants: neutral requires null ID/fileName; static requires a 32-hex-character opaque ID and exactly `<id>.png|webp` with no separator. Missing manifest creates neutral; malformed JSON, extra/missing fields, incompatible version, traversal, inconsistent fields, or a missing active file quarantines the manifest under a fixed generated prefix and atomically restores neutral. On startup remove temporary files and internal opaque files not referenced by the one valid manifest.

Put every `importFile()` and `clear()` mutation through one promise queue/mutex. The queue covers manifest reload, revision allocation, validation, copy/rename, manifest replacement, and deletion scheduling. Concurrent import/import and import/clear therefore cannot reuse a revision or leave the manifest pointing at a missing target.

Enforce these import rules before copying:

- one selected file;
- extension exactly `.png` or `.webp`;
- maximum bytes: `20 * 1024 * 1024`;
- PNG signature or RIFF/WEBP signature matching the extension;
- reject PNG `acTL`, WebP `ANIM`, WebP `ANMF`, and animated `VP8X` flags;
- parse dimensions before decode and reject width/height above `8192` or pixels above `32_000_000`;
- verify decodability using `nativeImage.createFromBuffer`, rejecting empty images;
- create a random opaque ID using `randomBytes(16).toString('hex')`;
- use an internal `<opaque-id>.<png|webp>` filename only.

The transaction must:

1. copy to a uniquely named temporary file inside `app.getPath('userData')/assets`;
2. atomically rename it to the opaque internal file name;
3. atomically replace `asset-manifest.json`;
4. expose the new `{ kind, assetRevision }` only after both operations succeed;
5. if manifest replacement fails after destination rename, delete that new destination before rejecting; if this deletion fails, emit only `DESKTOP_ASSET_ORPHAN_CLEANUP_FAILED` and let startup orphan cleanup remove it;
6. preserve the previous manifest and active file if any validation/copy/manifest step fails.

`clear()` must atomically write the neutral manifest first, increment revision, then best-effort delete the formerly referenced copy. A deletion failure returns a fixed recoverable error code but never restores the old manifest reference.

- [ ] **Step 4: Run asset-store tests.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/asset-store.test.ts
Pop-Location
```

Expected: PASS. Tests confirm that moving or deleting the original selected file after import does not affect the copied active asset.

- [ ] **Step 5: Commit controlled asset storage.**

```powershell
git add "frontend/electron/asset-manifest.mjs" "frontend/electron/asset-store.mjs" "frontend/electron/asset-manifest.test.ts" "frontend/electron/asset-store.test.ts" "frontend/electron/assets/neutral.png" "frontend/electron/test-fixtures"
git commit -m "feat: add atomic authorized static asset storage"
```

---

## Task 7: Register the fixed `pet-asset:` scheme

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\bootstrap-config.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\bootstrap-config.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\desktop-application.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\main.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-scheme.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-scheme.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\main.mjs`

- [ ] **Step 1: Write scheme resolution tests.**

```ts
it('rejects unsafe smoke userData overrides before readiness', () => {
  const canonicalPath = canonicalSmokePaths('run-1').userData;
  expect(() => parseSmokeUserDataOverride({ ELECTRON_USER_DATA_DIR: '.\\relative' })).toThrow('DESKTOP_INVALID_USER_DATA_DIR');
  expect(() => parseSmokeUserDataOverride({ ELECTRON_USER_DATA_DIR: canonicalPath })).toThrow('DESKTOP_INVALID_USER_DATA_DIR');
  expect(() => parseSmokeUserDataOverride({ ELECTRON_SMOKE_RUN_ID: 'run-1', ELECTRON_USER_DATA_DIR: outsideRoot })).toThrow('DESKTOP_INVALID_USER_DATA_DIR');
  expect(parseSmokeUserDataOverride({ ELECTRON_SMOKE_RUN_ID: 'run-1', ELECTRON_USER_DATA_DIR: canonicalPath })).toBe(canonicalPath);
});

it('serves only the active current asset URL at the active revision', async () => {
  await expect(resolvePetAssetRequest('pet-asset://active/current?revision=3', manifest)).resolves.toEqual(activeFile);
});

it.each([
  'pet-asset://other/current?revision=3',
  'pet-asset://active/other?revision=3',
  'pet-asset://active/current?revision=2',
  'pet-asset://active/current?revision=3&x=1',
  'pet-asset://active/current?revision=not-a-number',
  'pet-asset://active/../secret?revision=3',
])('rejects unsafe or stale scheme request %s', async (url) => {
  await expect(resolvePetAssetRequest(url, manifest)).rejects.toThrow('DESKTOP_ASSET_URL_REJECTED');
});
```

- [ ] **Step 2: Run scheme tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/asset-scheme.test.ts
Pop-Location
```

Expected: FAIL because the scheme resolver does not exist.

- [ ] **Step 3: Register and implement the restricted scheme.**

Create pure `bootstrap-config.mjs` (no Electron import). It exports `canonicalSmokePaths(runId)` using exactly:

```js
const runRoot = join(tmpdir(), 'ai-desktop-pet-smoke', runId);
const userData = join(runRoot, 'userData');
```

and `parseSmokeUserDataOverride(env)`, which accepts the override only when `ELECTRON_SMOKE_RUN_ID` is a bounded safe slug and `ELECTRON_USER_DATA_DIR` equals that exact canonical path after normalization. Tests cover relative/non-normalized/missing-marker/outside/mismatched-run values.

Create `desktop-application.mjs` as the Node-importable composition root; it statically imports no `electron` module and accepts an injected Electron facade. Vitest imports only this file and pure modules.

Create `main.mjs` as an untested minimal Electron-runtime bootstrap: import Electron `app`/`protocol`, call the pure validator, apply `app.setPath` before readiness, register the privileged scheme, construct the facade, and call `createDesktopApplication(facade)`. Full composition behavior is completed in Task 12.

Call `protocol.registerSchemesAsPrivileged` before `app.whenReady()`:

```js
protocol.registerSchemesAsPrivileged([{
  scheme: 'pet-asset',
  privileges: {
    standard: true,
    secure: true,
    supportFetchAPI: false,
    corsEnabled: false,
    stream: true,
  },
}]);
```

After readiness, register `protocol.handle('pet-asset', handler)`. The handler must accept exactly:

```text
pet-asset://active/current?revision=<current non-negative safe integer>
```

It must reject all other host/path/query combinations. Resolve the file from the validated manifest only; normalize the candidate and ensure it remains under `<userData>/assets`. For neutral/missing/corrupt asset cases, use the repository-owned neutral fixture. Never accept an asset ID, filesystem path, directory traversal string, original file name, or query parameter beyond the sole current `revision`.

- [ ] **Step 4: Run scheme and asset regression tests.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/asset-scheme.test.ts electron/asset-store.test.ts
Pop-Location
```

Expected: PASS. Unknown URLs and stale revisions are rejected; missing manifest/assets resolve safely to the neutral fixture.

- [ ] **Step 5: Commit the scheme boundary.**

```powershell
git add "frontend/electron/bootstrap-config.mjs" "frontend/electron/bootstrap-config.test.ts" "frontend/electron/desktop-application.mjs" "frontend/electron/asset-scheme.mjs" "frontend/electron/asset-scheme.test.ts" "frontend/electron/main.mjs"
git commit -m "feat: serve active pet assets through fixed scheme"
```

---

## Task 8: Implement the main-owned projection epoch and sequence broker

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\projection-broker.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\projection-broker.test.ts`

- [ ] **Step 1: Write the epoch, reload, stale sequence, and replay tests.**

```ts
it('issues a new epoch, clears the latest snapshot, and atomically resets pet on chat replacement', () => {
  const broker = createProjectionBroker();
  const firstEpoch = broker.attachChat(chatA);
  broker.publish(chatA, validSnapshot({ projectionEpoch: firstEpoch, sequence: 1 }));
  const secondEpoch = broker.attachChat(chatB);

  expect(secondEpoch).toBe(firstEpoch + 1);
  expect(broker.getLatest()).toBeNull();
  expect(pet.send).toHaveBeenLastCalledWith('desktop:pet-reset', { projectionEpoch: secondEpoch });
});

it('invalidates one chat document exactly once across reload/crash lifecycle signals', () => {
  const epoch = broker.attachChat(chatA);
  broker.onDidStartLoading();
  broker.onRenderProcessGone();
  expect(broker.getEpoch()).toBe(epoch + 1);
  expect(pet.send).toHaveBeenCalledTimes(1);
});

it('advances exactly once for each of two sequential reload generations', () => {
  const start = broker.getEpoch();
  broker.onDidStartLoading();
  broker.onRenderProcessGone();
  broker.onDidFinishLoad();
  broker.onDidStartLoading();
  broker.onDidFinishLoad();
  expect(broker.getEpoch()).toBe(start + 2);
  expect(pet.send).toHaveBeenCalledTimes(2);
});

it('rejects stale sequences and replays only the latest current-epoch snapshot', () => {
  const epoch = broker.attachChat(chatA);
  broker.publish(chatA, validSnapshot({ projectionEpoch: epoch, sequence: 2 }));
  expect(() => broker.publish(chatA, validSnapshot({ projectionEpoch: epoch, sequence: 2 }))).toThrow('DESKTOP_STALE_SEQUENCE');
  expect(broker.replayToPet()).toEqual(validSnapshot({ projectionEpoch: epoch, sequence: 2 }));
});
```

- [ ] **Step 2: Run broker tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/projection-broker.test.ts
Pop-Location
```

Expected: FAIL because the broker module does not exist.

- [ ] **Step 3: Implement main-issued epoch and only in-memory latest snapshot storage.**

The broker must:

- allocate a new non-negative safe `projectionEpoch` per chat document lifecycle, not merely per `webContents` object;
- implement an explicit document-generation state machine: initial attach establishes the current generation; `did-start-loading` opens the next generation and performs its one reset; duplicate `render-process-gone`/`destroyed`/replacement signals for that transition do not increment again; `did-finish-load` marks the generation ready and re-arms the next transition; a crash/replacement without prior start performs the current generation’s one invalidation;
- begin at epoch `0` and never persist epochs;
- clear `latestSnapshot` and `lastSequence` whenever chat reloads/crashes/is replaced;
- send `desktop:pet-reset` before a new-epoch snapshot may be accepted;
- require `snapshot.projectionEpoch === assignedEpoch`;
- require each sequence to be strictly greater than the previous accepted sequence in the same epoch;
- parse every snapshot through `parsePresentationSnapshot`;
- relay only the full parsed snapshot;
- retain only the latest valid snapshot in memory;
- return exact cursor `{ projectionEpoch, lastAcceptedSequence }` for chat mount/HMR resynchronization and as every successful publish acknowledgement;
- return `null` to a pet replay request when no current valid snapshot exists;
- record only fixed error code, window type, and schema version—never snapshot content or identifiers.

- [ ] **Step 4: Run broker tests.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/projection-broker.test.ts
Pop-Location
```

Expected: PASS. The tests prove a chat reload cannot be permanently blocked by the old renderer’s sequence watermark.

- [ ] **Step 5: Commit projection authority.**

```powershell
git add "frontend/electron/projection-broker.mjs" "frontend/electron/projection-broker.test.ts"
git commit -m "feat: broker ordered read-only pet projections"
```

---

## Task 9: Add sandbox-compatible preloads and fixed IPC validation

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\desktop-state.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\desktop-state.d.mts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\shared\desktop-state.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\preload-chat.cjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\preload-pet.cjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\ipc.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\ipc.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\preload-contract.test.ts`

- [ ] **Step 1: Write failing tests for sender/frame/origin checks and bridge API whitelists.**

```ts
it('rejects a valid-looking chat snapshot from pet, child frame, or wrong origin', async () => {
  await expect(handlers.publishSnapshot(petEvent, validSnapshot())).rejects.toThrow('DESKTOP_IPC_SENDER_REJECTED');
  await expect(handlers.publishSnapshot(childFrameEvent, validSnapshot())).rejects.toThrow('DESKTOP_IPC_FRAME_REJECTED');
  await expect(handlers.publishSnapshot(wrongOriginEvent, validSnapshot())).rejects.toThrow('DESKTOP_IPC_ORIGIN_REJECTED');
});

it('exposes no generic Electron capability in either preload bridge', () => {
  expect(Object.keys(chatBridge).sort()).toEqual([
    'clearAsset', 'getDesktopState', 'getProjectionCursor', 'importAsset',
    'publishPresentation', 'setPetVisible', 'subscribeDesktopState',
  ]);
  expect(Object.keys(petBridge).sort()).toEqual([
    'requestLatestPresentation', 'subscribePresentation', 'subscribeReset',
  ]);
});
```

- [ ] **Step 2: Run IPC tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/ipc.test.ts electron/preload-contract.test.ts
Pop-Location
```

Expected: FAIL because the IPC and preload files do not exist.

- [ ] **Step 3: Implement fixed bridge APIs and main IPC handlers.**

Define and exact-parse `DesktopStateV1` in the shared module:

```ts
interface DesktopStateV1 {
  schemaVersion: 1;
  petVisible: boolean;
  petAlwaysOnTop: boolean;
  petClickThrough: boolean;
  asset: { kind: 'neutral' | 'static'; assetRevision: number };
  errorCode: 'DESKTOP_ASSET_INVALID' | 'DESKTOP_NATIVE_CALL_FAILED' | null;
}
```

It rejects extra keys and any asset ID/path/file name, snapshot, label, message/run ID, or free-form error text. Main parses before sending; `useDesktopControls` parses again before consuming.

Expose only these chat APIs:

```js
contextBridge.exposeInMainWorld('desktopChat', {
  getProjectionCursor: () => ipcRenderer.invoke('desktop:chat-get-cursor'),
  publishPresentation: (snapshot) => ipcRenderer.invoke('desktop:chat-publish', snapshot),
  setPetVisible: (visible) => ipcRenderer.invoke('desktop:pet-visible', Boolean(visible)),
  importAsset: () => ipcRenderer.invoke('desktop:asset-import'),
  clearAsset: () => ipcRenderer.invoke('desktop:asset-clear'),
  getDesktopState: () => ipcRenderer.invoke('desktop:state'),
  subscribeDesktopState: (listener) => subscribe('desktop:state-changed', listener),
});
```

Expose only these pet APIs:

```js
contextBridge.exposeInMainWorld('desktopPet', {
  requestLatestPresentation: () => ipcRenderer.invoke('desktop:pet-replay'),
  subscribePresentation: (listener) => subscribe('desktop:pet-snapshot', listener),
  subscribeReset: (listener) => subscribe('desktop:pet-reset', listener),
});
```

The chat cursor response and successful publish ack are exact `{ projectionEpoch: nonNegativeSafeInteger, lastAcceptedSequence: nonNegativeSafeInteger }` objects. `subscribe` must pass only serialized plain objects to callbacks and return an unsubscribe function. Neither bridge may expose `ipcRenderer`, `send`, `invoke`, `require`, `process`, `Buffer`, Electron modules, real paths, shell, or environment variables.

For each main handler, verify the exact `event.sender`, `event.senderFrame === event.sender.mainFrame`, and exact Vite URL for the expected entry page. Before invoking the broker, the chat preload must reject a mismatched renderer-provided epoch and pass a new plain snapshot object with the authoritative epoch injected. Main independently repeats all sender/origin/schema/parser checks.

- [ ] **Step 4: Run IPC/preload tests.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/ipc.test.ts electron/preload-contract.test.ts electron/projection-broker.test.ts
Pop-Location
```

Expected: PASS. Payload-containing errors are not emitted or logged.

- [ ] **Step 5: Commit IPC and preload boundaries.**

```powershell
git add "frontend/electron/shared/desktop-state.mjs" "frontend/electron/shared/desktop-state.d.mts" "frontend/electron/shared/desktop-state.test.ts" "frontend/electron/preload-chat.cjs" "frontend/electron/preload-pet.cjs" "frontend/electron/ipc.mjs" "frontend/electron/ipc.test.ts" "frontend/electron/preload-contract.test.ts"
git commit -m "feat: add validated desktop IPC bridges"
```

---

## Task 10: Implement singleton windows, tray lifecycle, topmost, click-through, and quit semantics

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\windows.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\tray.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\windows.test.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\tray.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\main.mjs`

- [ ] **Step 1: Write lifecycle and tray-state tests.**

```ts
it('hides either window on close until tray quit sets quitting', () => {
  const controller = createWindowController(fakeDependencies);
  controller.createChat();
  controller.createPet();

  controller.onClose(chatWindow, fakeCloseEvent);
  expect(fakeCloseEvent.preventDefault).toHaveBeenCalledOnce();
  expect(chatWindow.hide).toHaveBeenCalledOnce();

  controller.quitFromTray();
  controller.onClose(chatWindow, fakeCloseEvent);
  expect(chatWindow.hide).toHaveBeenCalledOnce();
});

it('falls back to interactive mode when click-through native call fails', async () => {
  petWindow.setIgnoreMouseEvents.mockImplementation(() => { throw new Error('native failure'); });
  await controller.setClickThrough(true);
  expect(controller.getState().petClickThrough).toBe(false);
  expect(tray.refresh).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run lifecycle tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/windows.test.ts electron/tray.test.ts
Pop-Location
```

Expected: FAIL because window and tray controllers do not exist.

- [ ] **Step 3: Implement window/tray controllers with injected Electron adapters.**

Create exactly one chat window and at most one pet window. Configure:

- chat: visible at startup, taskbar-visible, not always-on-top;
- pet: transparent, frameless, `skipTaskbar: true`, hidden initially, default always-on-top and interactive;
- close event: `preventDefault()` and hide unless `quitting === true`;
- tray quit: set `quitting`, destroy tray, close both windows, and call `app.quit()` only after local Electron cleanup;
- no automatic FastAPI/Vite termination.

Implement idempotent `showPet`, `hidePet`, and `togglePet` without focusing chat/other applications. In interactive mode, pet uses the `.pet-hit-target` draggable region. Click-through uses `setIgnoreMouseEvents(true, { forward: true })`; only persist and update the tray checked state after native success. If native calls fail, restore Interactive and refresh the tray.

Use exactly this fixed menu shape:

```text
显示聊天窗口
显示/隐藏桌宠
桌宠置顶
鼠标穿透
退出
```

The menu must rebuild/read current state before display. It must not claim checked success after a failed native call.

- [ ] **Step 4: Run controller tests and an Electron startup syntax check.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/windows.test.ts electron/tray.test.ts
node --check electron/main.mjs
Pop-Location
```

Expected: PASS. `node --check` validates syntax only; it does not start Electron.

- [ ] **Step 5: Commit desktop lifecycle behavior.**

```powershell
git add "frontend/electron/windows.mjs" "frontend/electron/tray.mjs" "frontend/electron/windows.test.ts" "frontend/electron/tray.test.ts" "frontend/electron/main.mjs"
git commit -m "feat: add Electron window and tray lifecycle"
```

---

## Task 11: Connect chat-owned Stage 4E state to desktop projection and controls

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\bridge.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\useDesktopProjection.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\useDesktopProjection.test.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\useDesktopControls.ts`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\desktop\useDesktopControls.test.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\components\DesktopControls.tsx`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\components\DesktopControls.test.tsx`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\App.tsx`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\components\ChatLayout.tsx`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\src\styles.css`

- [ ] **Step 1: Write projection hook tests that prove browser no-op and chat-owned ordering.**

```tsx
it('publishes complete snapshots using the main-issued epoch and increasing sequence', async () => {
  const getProjectionCursor = vi.fn().mockResolvedValue({ projectionEpoch: 8, lastAcceptedSequence: 0 });
  const publishPresentation = vi.fn().mockImplementation(async (snapshot) => ({ projectionEpoch: 8, lastAcceptedSequence: snapshot.sequence }));
  installDesktopChatBridge({ getProjectionCursor, publishPresentation });

  const { rerender } = renderHook(({ state }) => useDesktopProjection(state, '标签', { kind: 'neutral', assetRevision: 0 }), {
    initialProps: { state: readyPreviewState },
  });

  await waitFor(() => expect(publishPresentation).toHaveBeenCalledWith(expect.objectContaining({
    projectionEpoch: 8, sequence: 1, phase: 'ready',
  })));

  rerender({ state: speakingPreviewState });
  await waitFor(() => expect(publishPresentation).toHaveBeenLastCalledWith(expect.objectContaining({
    projectionEpoch: 8, sequence: 2, phase: 'speaking',
  })));
});

it('projects a real-shaped ExpressionEvent without leaking type or schemaVersion', () => {
  const snapshot = toSnapshot(8, 1, readyPreviewState, '标签', { kind: 'neutral', assetRevision: 0 });
  expect(snapshot.expression).toEqual({
    assistantMessageId: 'assistant-1', delivery: 'warm', intensity: 'low', rate: 1, source: 'default',
  });
  expect(() => parsePresentationSnapshot(snapshot)).not.toThrow();
});

it('resynchronizes from the main cursor after Fast Refresh remount', async () => {
  const getProjectionCursor = vi.fn().mockResolvedValue({ projectionEpoch: 8, lastAcceptedSequence: 2 });
  const publishPresentation = vi.fn().mockResolvedValue({ projectionEpoch: 8, lastAcceptedSequence: 3 });
  installDesktopChatBridge({ getProjectionCursor, publishPresentation });
  renderHook(() => useDesktopProjection(readyPreviewState, '标签', { kind: 'neutral', assetRevision: 0 }));
  await waitFor(() => expect(publishPresentation).toHaveBeenCalledWith(expect.objectContaining({ sequence: 3 })));
});

it('does nothing in existing browser tests when Electron bridge is absent', async () => {
  delete (window as { desktopChat?: unknown }).desktopChat;
  renderHook(() => useDesktopProjection(readyPreviewState, '标签', { kind: 'neutral', assetRevision: 0 }));
  await Promise.resolve();
  expect(fetch).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run focused hook/component tests and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run src/desktop/useDesktopProjection.test.tsx src/desktop/useDesktopControls.test.tsx src/components/DesktopControls.test.tsx
Pop-Location
```

Expected: FAIL because the bridge, hooks, and control component do not exist.

- [ ] **Step 3: Implement desktop bridge, projection derivation, and minimal controls.**

`useDesktopProjection` must take the existing `ExpressionPreviewState`, existing already-truncated `displayLabelForAssistantMessage(...)` output, and sanitized desktop asset state. It must publish no direct API calls and must not change `useExpressionPreviewController`, `useAudioPlaybackController`, recorder ownership, or the current message/session logic.

`DesktopAssetState` is the exact `DesktopStateV1['asset']` type defined in Task 9; `useDesktopControls` parses every initial/subscribed `DesktopStateV1` before exposing it to this hook. Derive only valid complete snapshots:

```ts
function toSnapshot(
  epoch: number,
  sequence: number,
  state: ExpressionPreviewState,
  displayLabel: string | null,
  asset: DesktopAssetState,
): PresentationSnapshotV1 {
  if (state.phase === 'idle' || state.expression === null) {
    return {
      schemaVersion: 1, projectionEpoch: epoch, sequence,
      selectedAssistantMessageId: state.selectedAssistantMessageId,
      expression: null, phase: 'idle', activeRun: null,
      displayLabel: null, asset,
    };
  }
  // ready copies expression including expression.assistantMessageId and requires it to equal selectedAssistantMessageId;
  // speaking/paused additionally requires a matching active run.
  return {
    schemaVersion: 1,
    projectionEpoch: epoch,
    sequence,
    selectedAssistantMessageId: state.selectedAssistantMessageId,
    expression: {
      assistantMessageId: state.expression.assistantMessageId,
      delivery: state.expression.delivery,
      intensity: state.expression.intensity,
      rate: state.expression.rate,
      source: state.expression.source,
    },
    phase: state.phase,
    activeRun: state.activeRun,
    displayLabel,
    asset,
  };
}
```

The hook must request the authoritative cursor `{ projectionEpoch, lastAcceptedSequence }` on every mount/remount, set its next sequence to `lastAcceptedSequence + 1`, and serialize publications so two React updates cannot publish the same cursor. A successful publication ack returns the new cursor. On `DESKTOP_STALE_SEQUENCE`, the hook re-reads cursor and retries only the newest pending complete snapshot once; other bridge errors are absorbed so chat remains usable. A new epoch resets the cursor from main; no sequence or snapshot is persisted in renderer storage.

`DesktopControls` must provide:

- a visibility toggle;
- “导入静态素材” with visible text stating the user may import only material they are authorized to use;
- clear asset action;
- sanitized status: pet shown/hidden, asset `neutral | static`, and revision only;
- fixed non-sensitive error text.

It must not show filesystem paths, original file names, opaque IDs, message IDs, display labels, expression details, raw Electron errors, or any chat/audio control.

- [ ] **Step 4: Run focused UI tests, Stage 4E regressions, and typecheck.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run src/desktop/useDesktopProjection.test.tsx src/desktop/useDesktopControls.test.tsx src/components/DesktopControls.test.tsx src/hooks/useExpressionPreviewController.test.tsx src/components/ExpressionPreview.test.tsx src/App.test.tsx
npm run typecheck
Pop-Location
```

Expected: PASS. Existing browser tests run without an Electron bridge and continue to own chat/audio state.

- [ ] **Step 5: Commit the chat-to-desktop integration.**

```powershell
git add "frontend/src/desktop" "frontend/src/components/DesktopControls.tsx" "frontend/src/components/DesktopControls.test.tsx" "frontend/src/App.tsx" "frontend/src/components/ChatLayout.tsx" "frontend/src/styles.css"
git commit -m "feat: publish chat-owned presentation to desktop shell"
```

---

## Task 12: Integrate all Electron modules in the main entry and test cross-boundary behavior

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\desktop-application.integration.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\desktop-application.mjs`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\main.mjs`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\ipc.mjs`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\projection-broker.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\settings.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-store.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\asset-scheme.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\security.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\windows.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\tray.test.ts`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\electron\ipc.test.ts`

- [ ] **Step 1: Add an integration-style fake-adapter test for chat reload, pet reload, asset change, and close-to-hide.**

```ts
it('derives every store from the already-configured facade userData path', async () => {
  const tempUserData = canonicalSmokePaths('integration-run').userData;
  fakeElectron.app.getPath.mockImplementation((name) => name === 'userData' ? tempUserData : tempRoot);
  const app = createDesktopApplication(fakeElectron, config);
  await app.start();
  expect(fakeElectron.app.setPath).not.toHaveBeenCalled();
  expect(app.testOnly.persistedPaths().every((path) => path.startsWith(tempUserData))).toBe(true);
});

it('does not let settings select or override an active asset', async () => {
  await assetStore.importFile(sourcePngPath);
  await settingsStore.save({ ...defaultDesktopSettings, petAlwaysOnTop: false });
  const manifestBefore = await assetStore.readManifestForTest();
  await createDesktopApplication(fakeElectron, config).start();
  expect(await assetStore.readManifestForTest()).toEqual(manifestBefore);
  expect(await scheme.resolveActiveForTest()).toBe(manifestBefore.fileName);
});

it('resets pet before accepting a snapshot after chat reload, while pet reload replays current state', async () => {
  const app = createDesktopApplication(fakeElectron, config);
  await app.start();

  const epoch = app.testOnly.currentEpoch();
  await app.testOnly.publishFromChat(validSnapshot({ projectionEpoch: epoch, sequence: 1 }));

  app.testOnly.simulatePetReload();
  expect(fakePet.webContents.send).toHaveBeenCalledWith('desktop:pet-snapshot', expect.objectContaining({ sequence: 1 }));

  app.testOnly.simulateChatReload();
  expect(fakePet.webContents.send).toHaveBeenCalledWith('desktop:pet-reset', expect.objectContaining({ projectionEpoch: epoch + 1 }));
  expect(app.testOnly.latestSnapshot()).toBeNull();
});
```

- [ ] **Step 2: Run the integration test and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron -- electron/desktop-application.integration.test.ts
Pop-Location
```

Expected: FAIL because the composed application factory and integration test do not yet exist.

- [ ] **Step 3: Compose the application only through injected, focused controllers.**

`desktop-application.mjs` (not `main.mjs`) must compose the injected facade:

1. receive an already-configured Electron facade after runtime bootstrap has applied any userData override and registered scheme privilege; it must never call `app.setPath` or parse process environment;
2. parse the exact `http://127.0.0.1:<port>` Vite origin;
3. initialize settings and manifest/asset store from the final `app.getPath('userData')` only;
4. create chat and tray first;
5. create pet lazily or hidden, but never create duplicates;
6. register IPC only after controllers/broker exist;
7. register security hooks for each renderer session;
8. wire chat `did-start-loading`, `render-process-gone`, `destroyed`, and replacement to the broker’s idempotent document invalidation before accepting publications;
9. attach pet `webContents` to reset/replay channels;
10. register the asset scheme handler against the same manifest store;
11. dispose tray/windows only on explicit quit.

The integration test must assert every settings/manifest/asset path begins with the facade’s final `app.getPath('userData')`, composition never calls `app.setPath`, duplicate lifecycle events increment the epoch once, and a poisoned settings file cannot alter the manifest-selected asset.

The composition root must not statically import the `electron` package, backend code, make fetch/Provider calls, open SQLite, write snapshot logs, or read source asset file paths from renderers. `main.mjs` remains a minimal runtime-only adapter and is checked with `node --check`, not imported by Vitest.

- [ ] **Step 4: Run all Electron unit/integration tests.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm run test:electron
Pop-Location
```

Expected: PASS for contract, security, settings, asset, scheme, projection, IPC/preload, windows, tray, and composed-controller tests.

- [ ] **Step 5: Commit composed desktop application behavior.**

```powershell
git add "frontend/electron"
git commit -m "feat: compose secure Electron dual-window shell"
```

---

## Task 13: Add fake-first Windows headed smoke orchestration and cleanup checks

**Files:**
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\scripts\smoke-electron-shell-plan.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend\scripts\smoke-electron-shell.test.mjs`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\scripts\smoke_windows_electron_shell.ps1`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\scripts\smoke_windows_electron_shell.cmd`
- Create: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\docs\windows-electron-shell-smoke-checklist.md`
- Modify: `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\.gitignore`

- [ ] **Step 1: Write a script-level test for isolated fake-first environment construction.**

```ts
it('passes unique fake-provider database, loopback ports, and Electron userData paths', () => {
  const plan = buildSmokePlan({
    root: 'C:\\repo',
    runId: 'test-run',
  });
  expect(plan.backend.env.LLM_PROVIDER).toBe('fake');
  expect(plan.backend.env.TTS_PROVIDER).toBe('fake');
  expect(plan.backend.env.DATABASE_URL).toContain('electron-shell-test-run.db');
  expect(plan.electron.env.ELECTRON_SMOKE_RUN_ID).toBe('test-run');
  expect(plan.electron.env.ELECTRON_USER_DATA_DIR).toBe(canonicalSmokePaths('test-run').userData);
  expect(plan.vite.origin).toBe('http://127.0.0.1:5173');
  expect(plan.preflight.requiredFreePorts).toContain(5173);
  expect(plan.electron.env.VITE_DEV_ORIGIN).toBe('http://127.0.0.1:5173');
});
```

- [ ] **Step 2: Run the smoke-plan test and verify RED.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run scripts/smoke-electron-shell.test.mjs
Pop-Location
```

Expected: FAIL because the smoke-plan helper does not exist.

- [ ] **Step 3: Implement a headed Windows smoke script with explicit cleanup.**

Implement `frontend/scripts/smoke-electron-shell-plan.mjs` by importing the same pure `canonicalSmokePaths(runId)` from `electron/bootstrap-config.mjs`; both plan and main therefore independently derive `path.join(os.tmpdir(), 'ai-desktop-pet-smoke', runId, 'userData')`, and no environment-provided root is trusted. It is the canonical plan builder and a `--json --root <absolute> --run-id <id>` CLI. The PowerShell script must invoke this CLI once and consume its JSON for every port, database, process environment, and cleanup path; it must not independently reconstruct those values. The script also supports `-PlanOnly`, which invokes the same CLI and exits before starting processes. The test imports `buildSmokePlan` and also executes `-PlanOnly`, proving the PowerShell path consumes the canonical plan.

The PowerShell script must:

- use generated run/filesystem identifiers and one unique backend port; keep the shared Vite port fixed at 5173 and set `BACKEND_PROXY_TARGET` for that run’s Vite process;
- preflight fixed Vite port 5173 before starting anything and abort if occupied; after spawn, verify readiness through both HTTP and the exact spawned Vite process remaining alive—never attach to a pre-existing server;
- set `LLM_PROVIDER=fake`, `TTS_PROVIDER=fake`, unique SQLite database URL, and a temporary Electron `userData` directory;
- start FastAPI, Vite, and Electron as three independent processes;
- wait for `/health` and the exact Vite URL;
- print the manual test checklist and process IDs;
- on explicit success/failure/interrupt, stop only processes created by the script;
- remove temporary database, WAL/SHM, temporary userData, profiles, and smoke logs;
- assert cleanup paths no longer contain user assets, manifest files, database data, or credentials.

The script must not claim that tray, true transparency, z-order, drag interaction, or click-through passed automatically. Those require the manual headed checklist.

- [ ] **Step 4: Run the script’s non-destructive help/preflight and inspect cleanup behavior.**

```powershell
Set-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\smoke_windows_electron_shell.ps1" -Help
```

Expected: PASS with usage, required manual scenarios, fake-provider statement, and cleanup guarantees. It must not start services in `-Help` mode.

- [ ] **Step 5: Commit smoke scaffolding and narrowly scoped ignores.**

```powershell
git add "scripts/smoke_windows_electron_shell.ps1" "scripts/smoke_windows_electron_shell.cmd" "docs/windows-electron-shell-smoke-checklist.md" ".gitignore" "frontend/scripts/smoke-electron-shell-plan.mjs" "frontend/scripts/smoke-electron-shell.test.mjs"
git commit -m "test: add headed Windows Electron shell smoke harness"
```

---

## Task 14: Run full regression, real Windows smoke, security review, and evidence-gated documentation

**Files (modify only after all checks pass):**
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\README.md`
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\CLAUDE.md`
- `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\docs\windows-electron-shell-smoke-checklist.md`

- [ ] **Step 1: Run the complete automated frontend and Electron test suite.**

```powershell
Push-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠\frontend"
npm test -- --run
npm run test:electron
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

Expected: PASS. Existing Playwright browser E2E remains browser-based and must not depend on Electron availability.

- [ ] **Step 2: Run the existing Python regression suite without changing backend code.**

```powershell
Set-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠"
.\.venv\Scripts\python.exe -m pytest backend\tests tests -q
```

Expected: PASS. If the repository uses a different approved virtual environment, use that interpreter explicitly and record the actual command/result in evidence.

- [ ] **Step 3: Execute the headed Windows 11 smoke in a real desktop session.**

```powershell
Set-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\smoke_windows_electron_shell.ps1"
```

Expected manual observations, all recorded individually in the checklist:

1. chat opens alone by default;
2. chat button and tray repeatedly show/hide the same pet window;
3. both window close actions hide; only tray Quit exits;
4. fake message plus play/pause/resume/stop/replay tracks Stage 4E expression/run state;
5. stale epoch/sequence/run cannot overwrite current pet state;
6. chat reload first resets pet to Neutral/Idle, then admits the new epoch;
7. pet reload replays only current valid snapshot and does not disrupt chat/TTS;
8. original neutral PNG/WebP fixture import copies into temporary userData and survives original-file movement;
9. invalid/missing/animated/oversized files reject or fall back safely;
10. drag, always-on-top, click-through, and tray click-through reversal work;
11. offscreen/restored bounds remain visible after display configuration change;
12. external fetch/image beacon/navigation/popup/download attempts are blocked while Vite HMR, same-origin proxy, `blob:` audio, and `pet-asset:` continue to work;
13. pet has no Node, filesystem, or media permissions;
14. script cleanup removes all temporary SQLite/userData/smoke artifacts.

- [ ] **Step 4: Perform final hygiene and review gates.**

```powershell
Set-Location "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠"
git diff --check
git status --short
```

Expected: no whitespace errors; no user assets, real database files, userData folders, credentials, generated packaging outputs, or smoke artifacts staged for commit. Run the required Critical/High code review before claiming completion.

- [ ] **Step 5: Update evidence/status documents only after every required check passes, then commit.**

Document actual commands and observed results—not anticipated results—in the smoke checklist. Update `README.md` and `CLAUDE.md` only if all automated and headed Windows gates passed. If any real Windows behavior was not performed, record it as **unverified** and do not mark the shell complete.

```powershell
git add "README.md" "CLAUDE.md" "docs/windows-electron-shell-smoke-checklist.md"
git commit -m "docs: record verified Electron shell acceptance evidence"
```

---

## Implementation consistency checks

- **Electron version:** `frontend/package.json` must contain `"electron": "43.1.1"` exactly, not a caret/range.
- **Ownership:** chat remains the only API, provider, recording, VAD, TTS, playback, session, message, expression-preview, and snapshot-derivation owner. Pet is read-only.
- **Epochs:** only main issues epochs; chat cannot retain a prior epoch after reload; main clears cached projection before reset/replacement.
- **Sequences:** chat begins at sequence `1` per assigned epoch; main/pet accept only strictly newer sequence values in the active epoch.
- **Expression contract:** preserves existing Stage 4E delivery enum, `low | medium` intensity enum, `persisted_plan | default` source enum, `rate` bounds, and exact `(assistantMessageId, playbackRunId)` identity.
- **Exact-object parsing:** every external/IPC/manifest/settings object rejects extra fields as well as missing/malformed values.
- **Persistence:** settings contain preferences only; manifest is the sole asset authority; neither contains snapshot or chat data.
- **Assets:** the pet receives no asset ID/path/file name; it uses only `pet-asset://active/current?revision=<n>`.
- **Security:** sandboxed CJS preloads expose explicit APIs only; both renderer origins are exact; CSP/network policy preserves only known Vite/HMR/proxy/blob/pet-asset functionality.
- **Validation:** unit and fake-adapter tests are not substitutes for the separate headed Windows 11 tray/window/click-through smoke.
- **Non-goals:** no backend, sidecar, packaging, installer, Live2D, model, WebGL, or Provider change is permitted.
