#!/usr/bin/env node
/** Development-only source oracle for approval policy and result semantics.
 * Usage: NODE_PATH=ui/workspace/node_modules node scripts/export-approval-runtime-reference.cjs LC_ROOT SDK_ROOT
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ts = require('typescript');
const [lc, sdk] = process.argv.slice(2);
if (!lc || !sdk) throw new Error('Pinned LibreChat and SDK roots required');
const hashes = {};
function pick(root, file, names) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  hashes[file] = crypto.createHash('sha256').update(source).digest('hex');
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  return tree.statements.filter(node => {
    if (ts.isFunctionDeclaration(node)) return names.includes(node.name?.text);
    return ts.isVariableStatement(node) && node.declarationList.declarations.some(d => names.includes(d.name.text));
  }).map(node => node.getText(tree)).join('\n');
}
const source = [
 pick(lc, 'packages/api/src/agents/hitl/policy.ts', ['DEFAULT_REVIEW_DECISIONS', 'buildToolApprovalPayload']),
 pick(sdk, 'src/hooks/createToolPolicyHook.ts', ['globToRegex', 'compileMatchers', 'formatReason', 'createToolPolicyHook', 'decide']),
 pick(sdk, 'src/utils/truncation.ts', ['sliceWithoutSplittingSurrogates', 'truncateToolResultContent']),
 pick(sdk, 'src/tools/ToolNode.ts', ['buildToolApprovalInterruptPayload', 'normalizeApprovalDecisions']),
].join('\n');
const out = path.resolve(__dirname, '../tests/fixtures/librechat');
fs.mkdirSync(out, { recursive: true });
const js = ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 });
fs.writeFileSync(path.join(out, 'approval_runtime_reference.cjs'),
 '// Original LibreChat/agents functions; licenses beside this fixture.\n' + js +
 '\nObject.assign(exports, {buildToolApprovalInterruptPayload, normalizeApprovalDecisions});\n');
fs.writeFileSync(path.join(out, 'approval_runtime_sources.json'), JSON.stringify(hashes, null, 2) + '\n');
