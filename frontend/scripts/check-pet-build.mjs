import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const petHtmlPath = resolve(import.meta.dirname, '..', 'dist', 'pet.html');
const html = await readFile(petHtmlPath, 'utf8');

if (!/<script type="module"[^>]+src="(?:\.\/|\/)assets\/pet-[^"]+\.js"/.test(html)) {
  throw new Error('PET_BUILD_MODULE_MISSING');
}
