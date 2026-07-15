import { existsSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { verifyAndRemoveE2EDatabase } from './playwright.global-teardown';


describe('verifyAndRemoveE2EDatabase', () => {
  it('verifies before removing the database and sidecars', () => {
    const databasePath = join(process.cwd(), `test-results/teardown-${process.pid}.db`);
    const calls: string[] = [];

    verifyAndRemoveE2EDatabase(databasePath, {
      runStage4CVerifier: () => { calls.push('verify-4c'); },
      runStage4DVerifier: () => { calls.push('verify-4d'); },
      runStage4EVerifier: () => { calls.push('verify-4e'); },
      removeFile: (path) => { calls.push(`remove:${path}`); },
      exists: () => true,
    });

    expect(calls).toEqual([
      'verify-4c',
      'verify-4d',
      'verify-4e',
      `remove:${databasePath}`,
      `remove:${databasePath}-wal`,
      `remove:${databasePath}-shm`,
    ]);
  });

  it('propagates verification failure after best-effort cleanup', () => {
    const databasePath = join(process.cwd(), `test-results/teardown-failure-${process.pid}.db`);
    const calls: string[] = [];

    expect(() => verifyAndRemoveE2EDatabase(databasePath, {
      runStage4CVerifier: () => { calls.push('verify-4c'); },
      runStage4DVerifier: () => {
        calls.push('verify-4d');
        throw new Error('privacy verification failed');
      },
      runStage4EVerifier: () => { calls.push('verify-4e'); },
      removeFile: (path) => { calls.push(`remove:${path}`); },
      exists: () => true,
    })).toThrow('privacy verification failed');

    expect(calls).toEqual([
      'verify-4c',
      'verify-4d',
      `remove:${databasePath}`,
      `remove:${databasePath}-wal`,
      `remove:${databasePath}-shm`,
    ]);
  });

  it('keeps the primary verifier failure while attempting every cleanup', () => {
    const databasePath = join(process.cwd(), `test-results/teardown-multiple-failure-${process.pid}.db`);
    const calls: string[] = [];

    expect(() => verifyAndRemoveE2EDatabase(databasePath, {
      runStage4CVerifier: () => { calls.push('verify-4c'); throw new Error('primary verifier failed'); },
      runStage4DVerifier: () => { calls.push('verify-4d'); },
      removeFile: (path) => {
        calls.push(`remove:${path}`);
        if (path === databasePath) throw new Error('database remove failed');
        if (path.endsWith('-wal')) throw new Error('wal remove failed');
      },
      exists: () => true,
    })).toThrow('primary verifier failed');

    expect(calls).toEqual([
      'verify-4c',
      `remove:${databasePath}`,
      `remove:${databasePath}-wal`,
      `remove:${databasePath}-shm`,
    ]);
  });

  it('propagates the first cleanup error after attempting all cleanup', () => {
    const databasePath = join(process.cwd(), `test-results/teardown-cleanup-failure-${process.pid}.db`);
    const calls: string[] = [];

    expect(() => verifyAndRemoveE2EDatabase(databasePath, {
      runStage4CVerifier: () => { calls.push('verify-4c'); },
      runStage4DVerifier: () => { calls.push('verify-4d'); },
      runStage4EVerifier: () => { calls.push('verify-4e'); },
      removeFile: (path) => {
        calls.push(`remove:${path}`);
        if (path === databasePath) throw new Error('first cleanup failed');
        if (path.endsWith('-wal')) throw new Error('second cleanup failed');
      },
      exists: () => true,
    })).toThrow('first cleanup failed');

    expect(calls).toEqual([
      'verify-4c',
      'verify-4d',
      'verify-4e',
      `remove:${databasePath}`,
      `remove:${databasePath}-wal`,
      `remove:${databasePath}-shm`,
    ]);
  });

  it('removes real files only under the explicit E2E database path', () => {
    const databasePath = join(process.cwd(), `test-results/teardown-real-${process.pid}.db`);
    const sidecars = [`${databasePath}-wal`, `${databasePath}-shm`];
    for (const path of [databasePath, ...sidecars]) writeFileSync(path, 'temporary');

    verifyAndRemoveE2EDatabase(databasePath, {
      runStage4CVerifier: () => undefined,
      runStage4DVerifier: () => undefined,
      runStage4EVerifier: () => undefined,
    });

    expect(existsSync(databasePath)).toBe(false);
    expect(sidecars.every((path) => !existsSync(path))).toBe(true);
  });

  it('does nothing without an explicit database path', () => {
    expect(() => verifyAndRemoveE2EDatabase(undefined)).not.toThrow();
  });
});
