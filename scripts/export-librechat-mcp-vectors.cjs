#!/usr/bin/env node
/* Exact pinned LibreChat TS parser + actual TypeScript 5.9 transformer, no
 * application runtime dependency on Node. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),Module=require('node:module');
const root=path.resolve(process.argv[2]||'/root/librechat-reference-e8f3be08');
const dir=path.resolve(process.argv[3]||'.reference-node');
const originalRequire=Module.createRequire(path.join(dir,'package.json'));
const ts=originalRequire('typescript');
const filename=path.join(root,'packages/api/src/mcp/parsers.ts');
const source=fs.readFileSync(filename,'utf8');
const moduleCode=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
const oracle=new Module(filename,module);
oracle.filename=filename;oracle.paths=Module._nodeModulePaths(path.dirname(filename));
oracle.require=function(name){
 if(name==='librechat-data-provider')return {Tools:{ui_resources:'ui_resources'}};
 return originalRequire(name);
};
oracle._compile(moduleCode,filename);
const examples=[
 {name:'empty',provider:'openai',result:{content:[]}},
 {name:'texts',provider:'openai',result:{content:[{type:'text',text:'A'},{type:'text',text:'B'}]}},
 {name:'image_png',provider:'openai',result:{content:[{type:'image',data:'AA==',mimeType:'image/png'}]}},
 {name:'image_remote',provider:'anthropic',result:{content:[{type:'image',data:'https://cdn.example.org/img.png',mimeType:'image/png'}]}},
 {name:'rich_ui',provider:'google',result:{content:[{type:'text',text:'A'}, {type:'resource',resource:{uri:'ui://screen',mimeType:'text/html',text:'<div>hello</div>'}}]}},
 {name:'resource_text',provider:'openai',result:{content:[{type:'resource',resource:{uri:'file:///a',mimeType:'text/plain',text:'hello\nworld'}}]}},
 {name:'resource_utf8_blob',provider:'openai',result:{content:[{type:'resource',resource:{uri:'file:///a',mimeType:'text/plain',blob:Buffer.from('hello').toString('base64')}}]}},
 {name:'resource_binary_blob',provider:'openai',result:{content:[{type:'resource',resource:{uri:'file:///binary',mimeType:'application/octet-stream',blob:Buffer.from([0,255]).toString('base64')}}]}},
 {name:'resource_image_blob',provider:'google',result:{content:[{type:'resource',resource:{uri:'file:///image',mimeType:'image/png',blob:'AA=='}}]}},
 {name:'resource_link',provider:'openai',result:{content:[{type:'resource_link',uri:'file://a\nBAD',mimeType:'text/plain',name:'Name\nInjected',size:1024,description:'notes'}]}},
 {name:'unknown_content',provider:'openai',result:{content:[{type:'audio',data:'AA=='}]}},
 {name:'unrecognized_provider',provider:'other',result:{content:[{type:'image',data:'AA==',mimeType:'image/png'}]}},
 {name:'image_and_text',provider:'openrouter',result:{content:[{type:'text',text:'Here'}, {type:'image',data:'AA==',mimeType:'image/png'}, {type:'text',text:'Look'}]}},
];
const vectors=examples.map(example=>({...example,expected:oracle.exports.formatToolContent(example.result,example.provider)}));
const result={commit:'e8f3be08623663d4ad7f7241e693c94469b63bb0', source:'packages/api/src/mcp/parsers.ts',sha256:crypto.createHash('sha256').update(source).digest('hex'),dependency:`typescript@${originalRequire('typescript/package.json').version}`,vectors};
fs.writeFileSync('tests/fixtures/librechat/mcp_content_vectors.json',JSON.stringify(result,null,2)+'\n');
console.log(`${vectors.length} pinned TypeScript MCP parser vectors written`);
