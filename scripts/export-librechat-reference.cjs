#!/usr/bin/env node
/** Generate development-only reference fixtures from pinned upstream source.
 * Usage: node scripts/export-librechat-reference.cjs LIBRECHAT_ROOT AGENTS_ROOT
 * The generated JavaScript contains original functions, transpiled without
 * importing Node services, model providers, telemetry or database adapters.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const ts = require('../ui/workspace/node_modules/typescript');
const [lc, agents] = process.argv.slice(2);
if (!lc || !agents) throw new Error('Both pinned source roots are required');
const out = path.resolve(__dirname, '../tests/fixtures/librechat');
fs.mkdirSync(out, { recursive: true });
const provenance = {};
function pick(root, file, names) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  provenance[file] = crypto.createHash('sha256').update(source).digest('hex');
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  return tree.statements.filter(node => {
    if (ts.isFunctionDeclaration(node)) return names.includes(node.name?.text);
    return ts.isVariableStatement(node) && node.declarationList.declarations.some(d => names.includes(d.name.text));
  }).map(node => node.getText(tree)).join('\n');
}
const constants = pick(agents, 'src/hitl/askUserQuestionsInterrupt.ts',
  ['MAX_ASK_USER_QUESTIONS', 'ASK_USER_QUESTION_ID_PATTERN']);
const definition = pick(lc, 'packages/api/src/agents/hitl/askUserQuestionTool.ts',
  ['ASK_USER_QUESTION_TOOL_NAME', 'QUESTION_MAX', 'DESCRIPTION_MAX', 'HEADER_MAX', 'OPTION_LABEL_MAX', 'OPTION_VALUE_MAX',
   'OPTIONS_MAX', 'OPTION_LABEL_DESCRIPTION', 'ASK_USER_QUESTION_DESCRIPTION', 'AskUserQuestionToolDefinition']);
function transpile(source) {
  return ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 });
}
const context = { exports: {} };
vm.runInNewContext(transpile(constants + '\n' + definition), context);
fs.writeFileSync(path.join(out, 'ask_user_definition.json'), JSON.stringify(context.exports.AskUserQuestionToolDefinition, null, 2) + '\n');
const manifestPath = 'api/app/clients/tools/manifest.json';
const manifestText = fs.readFileSync(path.join(lc, manifestPath), 'utf8');
provenance[manifestPath] = crypto.createHash('sha256').update(manifestText).digest('hex');
fs.writeFileSync(path.join(out, 'ask_user_manifest.json'), JSON.stringify(
  JSON.parse(manifestText).find(tool => tool.pluginKey === 'ask_user_question'), null, 2) + '\n');
const resume = pick(lc, 'packages/api/src/agents/hitl/resume.ts',
 ['MAX_ASK_ANSWER_LENGTH', 'ASK_QUESTION_ID_PATTERN', 'MAX_ASK_QUESTIONS',
  'mapAskUserAnswer', 'mapAskUserAnswers', 'resolveAskUserQuestionResume',
  'mapToolApprovalResolutions', 'toSdkDecision', 'findUndecidedToolCalls',
  'hasInvalidToolApprovalResolutions', 'findDisallowedDecisions', 'findIncompleteDecisions',
  'resolveToolApprovalResume']);
const policyValidation = pick(lc, 'packages/api/src/agents/hitl/policy.ts', ['isToolApprovalPayloadValid']);
fs.writeFileSync(path.join(out, 'hitl_reference.cjs'), '// Original LibreChat functions; see LICENSE.LibreChat and source_hashes.json.\n' + transpile(policyValidation + '\n' + resume));
const protocol = fs.readFileSync(path.join(lc, 'api/server/controllers/agents/protocol.js'));
fs.writeFileSync(path.join(out, 'protocol.cjs'), protocol);
provenance['api/server/controllers/agents/protocol.js'] = crypto.createHash('sha256').update(protocol).digest('hex');
const toolBatch = pick(agents, 'src/tools/ToolNode.ts', ['directReplayKey']);
const argumentEquality = pick(agents, 'src/tools/eagerEventExecution.ts', ['stableStringify', 'recordArgsEqual']);
fs.writeFileSync(path.join(out, 'tool_batch_reference.cjs'),
  '// Original agents functions; see LICENSE.agents and source_hashes.json.\n' +
  transpile(toolBatch + '\n' + argumentEquality + '\nexports.directReplayKey = directReplayKey;'));
fs.writeFileSync(path.join(out, 'source_hashes.json'), JSON.stringify(provenance, null, 2) + '\n');
fs.copyFileSync(path.join(lc, 'LICENSE'), path.join(out, 'LICENSE.LibreChat'));
fs.copyFileSync(path.join(agents, 'LICENSE'), path.join(out, 'LICENSE.agents'));
console.log('Exported original schema, HITL functions and protocol reference fixtures.');
