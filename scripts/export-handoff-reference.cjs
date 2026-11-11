#!/usr/bin/env node
/** Development-only pinned SDK oracle; no Node dependency in production. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ts = require('typescript');
const sourceRoot = process.argv[2];
if (!sourceRoot) throw new Error('Pinned SDK source root required');
const source = fs.readFileSync(path.join(sourceRoot, 'src/graphs/handoff.ts'), 'utf8');
const compiled = ts.transpile(source, {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022});
const adapted = compiled
 .replace('require("nanoid")', '({nanoid: () => "fresh-execution"})')
 .replace('require("@langchain/langgraph")', '({Command: {PARENT: "__parent__"}, Send: class Send {constructor(node,args) {this.lg_name="Send";this.node=node;this.args=args;}}, Annotation: value => value})');
const target = path.resolve(__dirname, '../tests/fixtures/librechat/handoff_reference.cjs');
fs.writeFileSync(target, '// Original SDK handoff.ts; MIT license in LICENSE.agents.\n// SHA256: ' + crypto.createHash('sha256').update(source).digest('hex') + '\n' + adapted);
console.log(target);
