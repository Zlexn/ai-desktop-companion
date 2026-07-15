import { describe, expect, it } from 'vitest';
import { resolvePythonCommand } from './playwrightPython';

describe('resolvePythonCommand', () => {
  it('prefers an explicit E2E_PYTHON command', () => {
    expect(resolvePythonCommand({
      explicitPython: 'py -3.12',
      localVenvPython: 'C:\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: true,
    })).toBe('py -3.12');
  });

  it('quotes an explicit executable path containing spaces', () => {
    expect(resolvePythonCommand({
      explicitPython: 'C:\\Program Files\\Python312\\python.exe',
      localVenvPython: 'C:\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: false,
    })).toBe('"C:\\Program Files\\Python312\\python.exe"');
  });

  it('quotes an existing local venv executable', () => {
    expect(resolvePythonCommand({
      explicitPython: '',
      localVenvPython: 'C:\\Users\\Example User\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: true,
    })).toBe('"C:\\Users\\Example User\\repo\\.venv\\Scripts\\python.exe"');
  });

  it('falls back to PATH python when the local venv is absent', () => {
    expect(resolvePythonCommand({
      explicitPython: undefined,
      localVenvPython: 'C:\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: false,
    })).toBe('python');
  });
});
