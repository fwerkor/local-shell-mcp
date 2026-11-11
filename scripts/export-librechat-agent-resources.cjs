#!/usr/bin/env node
/** Extract pinned resource operators, unchanged, for a storage-boundary oracle. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const [root, modules = path.resolve(__dirname, '../ui/workspace/node_modules')] = process.argv.slice(2);
if (!root) throw new Error('Pinned LibreChat root required');
const ts = createRequire(path.resolve(modules, '../package.json'))('typescript');
const relative = 'packages/data-schemas/src/methods/agent.ts';
const source = fs.readFileSync(path.join(root, relative), 'utf8');
const tree = ts.createSourceFile(relative, source, ts.ScriptTarget.Latest, true);
const names = new Set(['resolveDocumentPath','deleteDocumentPath','addToSetCandidates',
 'operatorsMutateDocument','isDuplicateVersion','updateAgent','addAgentResourceFile','removeAgentResourceFiles']);
const found = new Map();
function visit(node) {
 if (ts.isFunctionDeclaration(node) && node.name && names.has(node.name.text))
   found.set(node.name.text, node.getText(tree));
 if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'hasOperatorKeys')
   found.set('hasOperatorKeys', 'const ' + node.getText(tree) + ';');
 ts.forEachChild(node, visit);
}
visit(tree);
for (const name of [...names, 'hasOperatorKeys']) if (!found.has(name)) throw new Error('Missing source function: ' + name);
const output = path.resolve(__dirname, '../tests/fixtures/librechat');
const declarations = ts.transpileModule([...found.values()].join('\n'), {compilerOptions:{
 target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS}}).outputText;
fs.writeFileSync(path.join(output,'agent_resource_operators.cjs'),
 '// Original LibreChat source; see LICENSE.LibreChat.\nmodule.exports = function resourceOperators(mongoose, getAgent, withCodeEnvironmentReference) {\n' +
 declarations + '\nreturn {addAgentResourceFile,removeAgentResourceFiles};\n};\n');
fs.writeFileSync(path.join(output,'agent_resource_sources.json'), JSON.stringify({
 commit:'e8f3be08623663d4ad7f7241e693c94469b63bb0',
 files:{[relative]:crypto.createHash('sha256').update(source).digest('hex')},
 functions:[...found.keys()],
 boundary:'Original resource/update functions; Mongo storage and no-code-environment dependency are supplied by a strict test adapter. No OCR/RAG/runtime parity claim.'
},null,2)+'\n');
