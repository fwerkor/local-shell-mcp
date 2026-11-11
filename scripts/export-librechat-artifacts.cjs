/** Export the pinned original module; no handwritten reference algorithm. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const root = process.argv[2];
const ts = require(process.argv[3] || 'typescript');
const commit = 'e8f3be08623663d4ad7f7241e693c94469b63bb0';
if (execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim() !== commit) throw new Error('Wrong LibreChat source commit');
const sourcePath = 'packages/api/src/artifacts/update.ts';
const source = fs.readFileSync(path.join(root, sourcePath), 'utf8');
const fixture = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const dest = path.join(__dirname,'../tests/fixtures/librechat');
fs.writeFileSync(path.join(dest,'artifacts_reference.cjs'),fixture);
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
const latexPath = 'packages/api/src/utils/latex.ts';
const latexSource = fs.readFileSync(path.join(root, latexPath), 'utf8');
const latexFixture = ts.transpileModule(latexSource, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
fs.writeFileSync(path.join(dest, 'artifacts_latex_reference.cjs'), latexFixture);
const manifest = {commit,source:sourcePath,sourceSha256:sha256(source),fixtureSha256:sha256(fixture),
  latexSource:latexPath,latexSourceSha256:sha256(latexSource),latexFixtureSha256:sha256(latexFixture)};
fs.writeFileSync(path.join(dest,'artifacts_sources.json'),JSON.stringify(manifest,null,2)+'\n');
const original = require(path.join(dest, 'artifacts_reference.cjs'));
const latex = require(path.join(dest, 'artifacts_latex_reference.cjs'));
const cases = [];
for (const prefix of ['', 'before 😀\n']) for (const fence of ['', '```html\n', '~~~~js\n', '    ```txt\n'])
for (const close of ['\n:::', '\n::: tail\nmore', '']) for (const body of ['old','old\n\nold','😀 old','::: inside\nold','a\r\nold']) {
  const end = fence ? '\n'+(fence.includes('~') ? '~~~~' : '```') : '';
  const text = prefix+':::artifact{identifier="a"}\n'+fence+body+end+close;
  for (const [before, after] of [['old','new'],['old\n',''],['missing','value'],['','empty'],['😀','🚀']])
    cases.push({message:{text},original:before,updated:after});
}
for (const value of ['', ':::artifact', ':::artifact\n', ':::artifact\nold\n:::', ':::artifact\n```\nold\n:::', ':::artifact\n```\nold\n::: in fence\n```\n:::'])
for (const content of [null, [], [{type:'image',text:value}], [{type:'text',text:value}], [{type:'text',text:value},{type:'text',text:':::artifact\nold\n:::'}]])
  cases.push({message:{text:value,content},original:'old',updated:'new'});
const expected = cases.map(c => {
  const artifacts = original.findAllArtifacts(c.message);
  return {artifacts,replaced:artifacts.map(a=>original.replaceArtifactContent(a.text,a,c.original,c.updated))};
});
const latexCases = [null, '', false, 12, {}, '$14', String.raw`\$14`, String.raw`\\$14`, String.raw`$$\\ce{H2O}$$`, String.raw`$$\\pu{kg}$$`, String.raw`\$2 $$\\ce{H2O}$$`];
fs.writeFileSync(path.join(dest, 'artifacts_vectors.json'), JSON.stringify({source:manifest,cases,expected,latex:{cases:latexCases,expected:latexCases.map(latex.unescapeLaTeX)}})+'\n');
console.log(`Exported ${cases.length} artifact vectors from ${commit}`);
