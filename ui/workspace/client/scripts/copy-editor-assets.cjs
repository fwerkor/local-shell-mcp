/** Build-only assets for the retained Monaco editor; no runtime CDN. */
const fs = require('node:fs/promises');
const sync = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
// Monaco's exports map intentionally hides package.json. Locate its package
// from the public entry point, without executing the browser-only module.
let packageRoot = path.dirname(require.resolve('monaco-editor'));
while (!sync.existsSync(path.join(packageRoot, 'package.json')) ||
       JSON.parse(sync.readFileSync(path.join(packageRoot, 'package.json'), 'utf8')).name !== 'monaco-editor') {
  const parent = path.dirname(packageRoot);
  if (parent === packageRoot) throw new Error('Cannot locate installed Monaco assets');
  packageRoot = parent;
}
const source = path.join(packageRoot, 'min', 'vs');
const target = path.join(root, 'dist', 'monaco', 'vs');
(async () => {
  await fs.access(path.join(source, 'loader.js'));
  await fs.rm(target, { recursive: true, force: true });
  await fs.cp(source, target, { recursive: true });
  await fs.copyFile(path.join(packageRoot, 'LICENSE'), path.join(root, 'dist', 'monaco', 'LICENSE'));
  console.log('Bundled the retained Monaco editor assets and license');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
