/// <reference types="node" />

import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = resolve(import.meta.dirname, '..', '..');

describe('Electron development shell setup', () => {
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
});
