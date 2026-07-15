interface ResolveE2EDatabaseOptions {
  databaseUrl?: string;
  databasePath?: string;
  defaultDatabasePath: string;
}

interface ResolvedE2EDatabase {
  databasePath: string;
  databaseUrl: string;
}

function sqliteUrlForPath(path: string): string {
  return `sqlite:///${path.replaceAll('\\', '/')}`;
}

function pathFromSqliteUrl(databaseUrl: string): string {
  const prefix = 'sqlite:///';
  if (!databaseUrl.startsWith(prefix)) {
    throw new Error('E2E_DATABASE_URL must be an absolute sqlite file URL');
  }
  const path = databaseUrl.slice(prefix.length);
  if (!path || path === ':memory:') {
    throw new Error('E2E_DATABASE_URL must be an absolute sqlite file URL');
  }
  return path;
}

export function resolveE2EDatabase({
  databaseUrl,
  databasePath,
  defaultDatabasePath,
}: ResolveE2EDatabaseOptions): ResolvedE2EDatabase {
  if (databaseUrl) {
    return {
      databasePath: pathFromSqliteUrl(databaseUrl),
      databaseUrl,
    };
  }
  const path = databasePath ?? defaultDatabasePath;
  return { databasePath: path, databaseUrl: sqliteUrlForPath(path) };
}
