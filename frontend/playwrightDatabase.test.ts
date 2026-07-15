import { describe, expect, it } from 'vitest';
import { resolveE2EDatabase } from './playwrightDatabase';


describe('resolveE2EDatabase', () => {
  it('uses an explicit database path when no URL override exists', () => {
    expect(resolveE2EDatabase({
      databasePath: 'C:/tmp/e2e.db',
      defaultDatabasePath: 'C:/tmp/default.db',
    })).toEqual({
      databasePath: 'C:/tmp/e2e.db',
      databaseUrl: 'sqlite:///C:/tmp/e2e.db',
    });
  });

  it('derives a verifier path from an absolute sqlite URL', () => {
    expect(resolveE2EDatabase({
      databaseUrl: 'sqlite:///C:/tmp/custom.db',
      defaultDatabasePath: 'C:/tmp/default.db',
    })).toEqual({
      databasePath: 'C:/tmp/custom.db',
      databaseUrl: 'sqlite:///C:/tmp/custom.db',
    });
  });

  it('rejects URL overrides that cannot be verified as local SQLite files', () => {
    expect(() => resolveE2EDatabase({
      databaseUrl: 'postgresql://localhost/test',
      defaultDatabasePath: 'C:/tmp/default.db',
    })).toThrow('E2E_DATABASE_URL must be an absolute sqlite file URL');
  });
});
