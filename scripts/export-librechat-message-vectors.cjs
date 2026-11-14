#!/usr/bin/env node
/* Generate differential vectors with original LibreChat source and locked
 * @langchain/core@1.2.8 message classes. Node is ONLY an offline test tool.
 * Usage: node scripts/export-librechat-message-vectors.cjs <source-root> [node-modules]
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const Module = require('node:module');
const sourceRoot = path.resolve(process.argv[2] || '/root/librechat-reference-e8f3be08');
const dependencyRoot = path.resolve(process.argv[3] || '.reference-node');
const realRequire = Module.createRequire(path.join(dependencyRoot, 'package.json'));
const actual = realRequire('@langchain/core/messages');
if (realRequire('@langchain/core/package.json').version !== '1.2.8') throw Error('Must use pinned @langchain/core@1.2.8');
const source = path.join(sourceRoot, 'api/app/clients/prompts/formatMessages.js');
const reference = fs.readFileSync(source);
const original = Module._load;
Module._load = function(request, parent, isMain) {
  if (parent?.filename === source && request === '@librechat/api') {
    return {ATTACHMENT_ONLY_TEXT: 'Please refer to the attached file(s).'};
  }
  if (parent?.filename === source && request === 'librechat-data-provider') {
    return {EModelEndpoint: {anthropic: 'anthropic'}, ContentTypes: {TEXT:'text', TOOL_CALL:'tool_call', THINK:'think', STEER:'steer', ERROR:'error', AGENT_UPDATE:'agent_update', ACTIVITY_LABEL:'activity_label'}};
  }
  if (parent?.filename === source && request === '@librechat/agents/langchain/messages') return actual;
  return original.call(this, request, parent, isMain);
};
let converter;
try {converter=require(source);} finally {Module._load=original;}
const fixtures=[
  {name:'multi_step_steer_signatures', messages:[{role:'assistant',metadata:{thoughtSignatures:{one:'sig-one',two:'sig-two'}},content:[
    {type:'text',text:'First',tool_call_ids:['one']},
    {type:'tool_call',tool_call:{id:'one',name:'file_read',args:'{"path":"a"}',output:'result A'}},
    {type:'steer',steer:'Use B'},
    {type:'text',text:'Second',tool_call_ids:['two']},
    {type:'tool_call',tool_call:{id:'two',name:'file_read',args:'{"path":"b"}',output:'result B'}},
    {type:'text',text:'Finished'}]}]},
  {name:'parallel_tools',messages:[{role:'assistant',content:[
    {type:'text',text:'Calling both',tool_call_ids:['one','two']},
    {type:'tool_call',tool_call:{id:'one',name:'a',args:'{}',output:'A'}},
    {type:'tool_call',tool_call:{id:'two',name:'b',args:'{}',output:'B'}}]}]},
  {name:'rich_image_steer',messages:[{role:'user',image_urls:[{type:'image_url',image_url:{url:'data:image/png;base64,AA=='}}],text:''},
    {role:'assistant',content:[{type:'text',text:'Preview'}, {type:'steer',steer:'Photo detail',media:[{type:'text',text:'inspect'},{type:'image_url',image_url:{url:'data:image/png;base64,AA=='}}]},{type:'text',text:'Final'}]}]},
  {name:'user_empty',messages:[{role:'user',text:''},{role:'user',content:'',files:[{file_id:'a'}]}]},
  {name:'assistant_multimodal_and_reasoning',messages:[{role:'assistant',content:[
    {type:'text',text:'Hello'},{type:'image_url',image_url:{url:'data:image/png;base64,AA=='}},
    {type:'think',text:'Private thought'}, {type:'text',text:'World'}]}]},
];
function shape(msg) {
  const kind=msg._getType?.() ?? msg.getType?.() ?? msg.role ?? ''; 
  return {role:kind==='human'?'user':kind==='ai'?'assistant':kind,
    content:msg.content, ...(msg.tool_calls?.length?{tool_calls:msg.tool_calls}:{}),
    ...(msg.tool_call_id?{tool_call_id:msg.tool_call_id}:{}),
    ...(msg.name?{name:msg.name}:{}),
    ...(Object.keys(msg.additional_kwargs||{}).length?{additional_kwargs:msg.additional_kwargs}:{})};
}
const result={commit:'e8f3be08623663d4ad7f7241e693c94469b63bb0',
  source:'api/app/clients/prompts/formatMessages.js', sha256:crypto.createHash('sha256').update(reference).digest('hex'),
  dependency:'@langchain/core@1.2.8',vectors:fixtures.map(v=>({name:v.name,input:v.messages,
    expected:converter.formatAgentMessages(structuredClone(v.messages)).map(shape)}))};
const dest=path.resolve('tests/fixtures/librechat/message_history_vectors.json');
fs.writeFileSync(dest,JSON.stringify(result,null,2)+'\n');
console.log(`${result.vectors.length} real-source vectors written: ${dest}`);
