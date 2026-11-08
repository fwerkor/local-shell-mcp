#!/usr/bin/env node
/** Export source-only Agent authoring validation as a development oracle. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const [root, nodeModules = path.resolve(__dirname, '../ui/workspace/node_modules')] = process.argv.slice(2);
if (!root) throw new Error('Pinned LibreChat source root required');
const dependency = createRequire(path.resolve(nodeModules, '../package.json'));
const ts = dependency('typescript');
const out = path.resolve(__dirname, '../tests/fixtures/librechat');
const hashes = {};
for (const [sourcePath, destination] of [
  ['packages/api/src/agents/validation.ts', 'agent_validation_reference.cjs'],
  ['packages/api/src/agents/parameters.ts', 'agent_parameters_reference.cjs'],
]) {
  const source = fs.readFileSync(path.join(root, sourcePath), 'utf8');
  hashes[sourcePath] = crypto.createHash('sha256').update(source).digest('hex');
  const js = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  fs.writeFileSync(path.join(out, destination), '// Original LibreChat source; see LICENSE.LibreChat.\n' + js);
}
fs.writeFileSync(path.join(out, 'agent_config_source_hashes.json'), JSON.stringify(hashes, null, 2) + '\n');
