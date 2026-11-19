/* Run pinned template code with Node for source differential; production is Python-only.
 * Usage: node scripts/check-librechat-artifact-prompt-diff.cjs UPSTREAM_PATH DEDENT_PATH
 * The component data is checked against pinned SHA-256 by Python exporter tests.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const upstream = process.argv[2];
const dedent = require(process.argv[3]);
if (!upstream) throw new Error('Pinned LibreChat root required');
const snapshot = require(path.resolve('src/local_shell_mcp/webui/artifact_prompt_snapshot.json'));
const src = fs.readFileSync(path.join(upstream, 'packages/api/src/prompts/artifacts/index.ts'), 'utf8');
const generate = fs.readFileSync(path.join(upstream, 'packages/api/src/prompts/artifacts/generate.ts'), 'utf8');
const begin = generate.indexOf('  const { components, useXML = false } = options;');
const ending = '  return systemPrompt;\n}';
const end = generate.indexOf(ending) + ending.length;
if (begin < 0 || end < ending.length) throw new Error('Original generateShadcnPrompt changed');
const generateJS = 'function generateShadcnPrompt(options) {\n' + generate.slice(begin, end);
const indexJS = src.replace(/^import .*?;\n/gm, '').replace(
  /export function generateArtifactsPrompt\(params: \{[\s\S]*?\}\): string \| null \{/,
  'function generateArtifactsPrompt(params) {',
);
if (!indexJS.includes('function generateArtifactsPrompt(params)')) throw new Error('Source function conversion failed');
const components = {};
for (const entry of snapshot.components) {
  components[entry.name] = {componentName:entry.name, importDocs:entry.import, usageDocs:entry.usage};
}
const context = vm.createContext({
  dedent,
  generateShadcnPrompt: undefined,
  components,
  ArtifactModes: {CUSTOM:'custom',SHADCNUI:'shadcnui',DEFAULT:'default'},
  EModelEndpoint: {anthropic:'anthropic'},
});
vm.runInContext(generateJS + '\n' + indexJS + '\nthis.generateArtifactsPrompt = generateArtifactsPrompt;',context);
const result={};
for (const endpoint of ['openai','anthropic','google']) {
  for (const artifacts of ['default','shadcnui','custom','unknown','']) {
    result[endpoint + '|' + artifacts] = context.generateArtifactsPrompt({endpoint,artifacts});
  }
}
process.stdout.write(JSON.stringify(result));
