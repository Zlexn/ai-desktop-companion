interface ResolvePythonCommandOptions {
  explicitPython?: string;
  localVenvPython: string;
  localVenvExists: boolean;
}

function quoteExecutable(path: string): string {
  return `"${path.replaceAll('"', '\\"')}"`;
}

export function resolvePythonCommand({
  explicitPython,
  localVenvPython,
  localVenvExists,
}: ResolvePythonCommandOptions): string {
  const explicit = explicitPython?.trim();
  if (explicit) {
    const isBareExecutablePath = /\.exe$/i.test(explicit) && !explicit.startsWith('"');
    return isBareExecutablePath ? quoteExecutable(explicit) : explicit;
  }
  if (localVenvExists) return quoteExecutable(localVenvPython);
  return 'python';
}
