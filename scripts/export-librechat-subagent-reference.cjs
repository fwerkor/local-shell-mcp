#!/usr/bin/env node
/** Development-only differential oracle from pinned SDK 4.0.1 sources. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ts = require('typescript');
const [agents, librechat] = process.argv.slice(2);
if (!agents || !librechat) throw new Error('Pinned SDK and LibreChat roots required');
const hashes = {};
function read(root, file) {
 const source = fs.readFileSync(path.join(root, file), 'utf8');
 hashes[file] = crypto.createHash('sha256').update(source).digest('hex');
 return ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
}
function pick(root, file, names) {
 const tree = read(root, file);
 return tree.statements.filter(node =>
  ts.isFunctionDeclaration(node) ? names.includes(node.name?.text) :
  ts.isVariableStatement(node) && node.declarationList.declarations.some(d => names.includes(d.name.text))
 ).map(node => node.getText(tree)).join('\n');
}
const intent = pick(agents, 'src/tools/intentArg.ts',
 ['INTENT_LABEL_MARKER', 'INTENT_DESCRIPTION', 'INTENT_PROPERTY']);
const tree = read(agents, 'src/tools/SubagentTool.ts');
const tool = tree.statements.filter(node => !ts.isImportDeclaration(node))
 .map(node => node.getText(tree)).join('\n');
const result = pick(agents, 'src/tools/subagent/SubagentExecutor.ts', ['filterSubagentResult']);
const limits = pick(librechat, 'packages/api/src/agents/config.ts',
 ['DEFAULT_RECURSION_LIMIT', 'SUBAGENT_RECURSION_MULTIPLIER', 'resolveRecursionLimit', 'resolveSubagentMaxTurns']);
const code = `const Constants = { SUBAGENT: 'subagent' }; const ContentTypes = { TEXT: 'text' }; const TEXT_DELTA_CONTENT_TYPE = 'text_delta';\n` + intent + '\n' + tool + '\n' + result + '\n' + limits;
const output = path.join(__dirname, '../tests/fixtures/librechat');
fs.writeFileSync(path.join(output, 'subagent_reference.cjs'),
 '// Original MIT-licensed LibreChat/agents functions; see LICENSE files and subagent_source_hashes.json.\n' +
 ts.transpile(code, {module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022}));
fs.writeFileSync(path.join(output, 'subagent_source_hashes.json'), JSON.stringify(hashes,null,2)+'\n');
