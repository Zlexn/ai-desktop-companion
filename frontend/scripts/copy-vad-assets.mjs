import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const vadSource = path.join(root, 'node_modules', '@ricky0123', 'vad-web', 'dist');
const ortSource = path.join(root, 'node_modules', 'onnxruntime-web', 'dist');
const vadTarget = path.join(root, 'public', 'vendor', 'vad');
const ortTarget = path.join(root, 'public', 'vendor', 'onnxruntime');

const assetExtensions = new Set(['.onnx', '.wasm', '.mjs', '.js', '.data']);

async function assertDirectory(dir, label) {
  const stat = await fs.stat(dir).catch(() => null);
  if (!stat?.isDirectory()) {
    throw new Error(`${label} directory not found: ${dir}. Run npm install first.`);
  }
}

async function copyMatchingFiles(sourceDir, targetDir) {
  await fs.mkdir(targetDir, { recursive: true });
  const entries = await fs.readdir(sourceDir, { withFileTypes: true });
  const copied = [];

  for (const entry of entries) {
    const sourcePath = path.join(sourceDir, entry.name);
    const targetPath = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      const nested = await copyMatchingFiles(sourcePath, targetPath);
      copied.push(...nested);
      continue;
    }
    if (!entry.isFile()) continue;
    if (!assetExtensions.has(path.extname(entry.name))) continue;
    await fs.copyFile(sourcePath, targetPath);
    copied.push(path.relative(root, targetPath));
  }

  return copied;
}

await assertDirectory(vadSource, '@ricky0123/vad-web dist');
await assertDirectory(ortSource, 'onnxruntime-web dist');

const copied = [
  ...(await copyMatchingFiles(vadSource, vadTarget)),
  ...(await copyMatchingFiles(ortSource, ortTarget)),
];

if (copied.length === 0) {
  throw new Error('No VAD/ONNX assets were copied. Check installed package layout.');
}

console.log(`Copied ${copied.length} VAD/ONNX asset files:`);
for (const file of copied.sort()) {
  console.log(`- ${file}`);
}
