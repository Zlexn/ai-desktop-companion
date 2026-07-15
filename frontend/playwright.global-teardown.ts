import { execFileSync } from 'node:child_process';
import { existsSync, unlinkSync } from 'node:fs';
import { resolve } from 'node:path';
import { resolvePythonCommand } from './playwrightPython';

interface TeardownDependencies {
  runStage4CVerifier?: (databasePath: string) => void;
  runStage4DVerifier?: (databasePath: string) => void;
  runStage4EVerifier?: (databasePath: string) => void;
  removeFile?: (path: string) => void;
  exists?: (path: string) => boolean;
}

const frontendDir = process.cwd();

function runDatabaseVerifier(
  scriptName: string,
  databasePath: string,
  extraArgs: string[] = [],
): void {
  const localVenvPython = resolve(frontendDir, '..', '.venv', 'Scripts', 'python.exe');
  const pythonCommand = resolvePythonCommand({
    explicitPython: process.env.E2E_PYTHON,
    localVenvPython,
    localVenvExists: existsSync(localVenvPython),
  });
  const executable = pythonCommand.startsWith('"') && pythonCommand.endsWith('"')
    ? pythonCommand.slice(1, -1)
    : pythonCommand;
  execFileSync(executable, [
    resolve(frontendDir, '..', 'scripts', scriptName),
    '--database', databasePath,
    ...extraArgs,
  ], { stdio: 'inherit' });
}

function runStage4CVerifier(databasePath: string): void {
  runDatabaseVerifier('verify_stage4c_e2e_database.py', databasePath, [
    '--expected-jobs', '1',
    '--expected-audits', '1',
    '--expected-outcome', 'applied',
    '--forbid', 'e2e-analysis-secret',
    '--forbid', 'e2e-post-revoke-secret',
    '--forbid', 'stage4c-e2e-token',
    '--forbid', '我今天很难受',
    '--forbid', '我需要帮助',
  ]);
}

function runStage4DVerifier(databasePath: string): void {
  runDatabaseVerifier('verify_stage4d_e2e_database.py', databasePath);
}

function runStage4EVerifier(databasePath: string): void {
  runDatabaseVerifier('verify_stage4e_e2e_database.py', databasePath);
}


export function verifyAndRemoveE2EDatabase(
  databasePath: string | undefined,
  dependencies: TeardownDependencies = {},
): void {
  if (!databasePath) return;
  const exists = dependencies.exists ?? existsSync;
  if (!exists(databasePath)) return;
  const runStage4C = dependencies.runStage4CVerifier ?? runStage4CVerifier;
  const runStage4D = dependencies.runStage4DVerifier ?? runStage4DVerifier;
  const runStage4E = dependencies.runStage4EVerifier ?? runStage4EVerifier;
  const removeFile = dependencies.removeFile ?? unlinkSync;
  const databaseFiles = [databasePath, `${databasePath}-wal`, `${databasePath}-shm`];

  let primaryError: unknown;
  try {
    runStage4C(databasePath);
    runStage4D(databasePath);
    runStage4E(databasePath);
  } catch (error) {
    primaryError = error;
  }

  let cleanupError: unknown;
  for (const path of databaseFiles) {
    if (!exists(path)) continue;
    try {
      removeFile(path);
    } catch (error) {
      cleanupError ??= error;
    }
  }

  if (primaryError !== undefined) throw primaryError;
  if (cleanupError !== undefined) throw cleanupError;
}

export default function globalTeardown(): void {
  verifyAndRemoveE2EDatabase(process.env.E2E_DATABASE_PATH);
}
