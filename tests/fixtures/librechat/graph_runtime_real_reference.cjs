/* Differential oracle: pinned LibreChat integration npm @langchain/langgraph 1.4.8,
 * @langchain/core 1.2.8, checkpoint 1.1.3. Uses actual message instances,
 * not a hand-written stand-in for coerceMessageLikeToMessage. */
const path = require('node:path');
const { createRequire } = require('node:module');
const requirePinned = createRequire(path.resolve(process.env.LSM_JS_ORACLE_ROOT || process.cwd(), 'package.json'));
const { Annotation, StateGraph, START, END, Command, Send, messagesStateReducer } = requirePinned('@langchain/langgraph');
const { HumanMessage, AIMessage, ToolMessage, SystemMessage, RemoveMessage } = requirePinned('@langchain/core/messages');
const { MemorySaver } = requirePinned('@langchain/langgraph');

function fromDTO(m) {
  const fields = { ...(m.id == null ? {} : {id:m.id}), content: m.content ?? '' };
  if (m.role === 'user') return new HumanMessage(fields);
  if (m.role === 'assistant') return new AIMessage(fields);
  if (m.role === 'system') return new SystemMessage(fields);
  if (m.role === 'tool') return new ToolMessage({ ...fields, tool_call_id:m.tool_call_id || 'tool-1' });
  if (m.role === 'remove') return new RemoveMessage({ id: m.id });
  throw new Error(`Unsupported test message role ${m.role}`);
}
function toDTO(m) {
  return {role: ({human:'user', ai:'assistant'}[m.getType()] || m.getType()),id:m.id,content:m.content,
    ...(m.getType() === 'tool' ? {tool_call_id:m.tool_call_id} : {})};
}
function normalize(output) {
  const assigned = new Map(); let number = 0;
  for (const m of output) if (!/^(known_|__remove_all__)/.test(m.id)) {
    if (!assigned.has(m.id)) assigned.set(m.id,'auto:'+number++);
  }
  return output.map(x=>({ ...x, id:assigned.get(x.id) ?? x.id }));
}
function messageOracle(cases) {
  return cases.map(c=>{
    try {const output = messagesStateReducer(c.left.map(fromDTO),c.right.map(fromDTO));
      return {messages: normalize(output.map(toDTO))};}
    catch(error) {return {error:error.message};}
  });
}
function getSchema() {
  return Annotation.Root({messages:Annotation({reducer:messagesStateReducer,default:()=>[]}),
   agentMessages:Annotation({reducer:(a,b)=>b,default:()=>[]})});
}
async function traceGraph() {
  const traces=[];
  async function fanout() {
    const builder=new StateGraph(getSchema());
    const node=(name)=>(state)=>{traces.push(name+':'+state.messages.map(x=>x.id).join(','));return {messages:[new AIMessage({id:'known_'+name,content:name})]};};
    for(const name of ['root','left','right','join']) builder.addNode(name,node(name));
    builder.addEdge(START,'root');builder.addEdge('root','left');builder.addEdge('root','right');
    builder.addEdge(['left','right'],'join');builder.addEdge('join',END);
    const result=await builder.compile().invoke({messages:[new HumanMessage({id:'known_user',content:'hello'})]});
    return {messages:result.messages.map(toDTO), trace:traces.splice(0)};
  }
  async function command() {
    const builder=new StateGraph(getSchema());
    builder.addNode('start', state=>{traces.push('start');return new Command({update:{messages:[new AIMessage({id:'known_start',content:'start'})]},goto:['left','right']});},{ends:['left','right']});
    for(const name of ['left','right']) builder.addNode(name,state=>{traces.push(name);return {messages:[new AIMessage({id:'known_'+name,content:name})]};});
    builder.addEdge(START,'start');
    const result=await builder.compile().invoke({messages:[new HumanMessage({id:'known_user',content:'hello'})]});
    return {messages:result.messages.map(toDTO), trace:traces.splice(0)};
  }
  async function sends() {
    const builder=new StateGraph(getSchema());
    builder.addNode('start',state=>new Command({update:{messages:[new AIMessage({id:'known_start',content:'start'})]},goto:[
      new Send('recipient',{messages:[new HumanMessage({id:'known_a',content:'a'})]}),
      new Send('recipient',{messages:[new HumanMessage({id:'known_b',content:'b'})]})]}),{ends:['recipient']});
    builder.addNode('recipient',state=>{traces.push(state.messages.at(-1).content);return {messages:[new AIMessage({id:'known_reply_'+state.messages.at(-1).content,content:'reply_'+state.messages.at(-1).content})]};});
    builder.addEdge(START,'start');
    const result=await builder.compile().invoke({messages:[new HumanMessage({id:'known_user',content:'hello'})]});
    return {messages:result.messages.map(toDTO),trace:traces.splice(0)};
  }
  return {fanout:await fanout(),command:await command(),sends:await sends()};
}
const cases = [
  {left:[{role:'user',id:'known_u',content:'u'}],right:[{role:'assistant',id:'known_a',content:'a'}]},
  {left:[{role:'assistant',id:'known_a',content:'old'},{role:'tool',id:'known_tool',content:'tool',tool_call_id:'t'}],right:[{role:'assistant',id:'known_a',content:'new'}]},
  {left:[{role:'user',id:'known_u',content:'u'},{role:'assistant',id:'known_a',content:'a'}],right:[{role:'remove',id:'known_u'}]},
  {left:[{role:'user',id:'known_u',content:'u'},{role:'assistant',id:'known_a',content:'a'}],right:[{role:'remove',id:'known_a'},{role:'assistant',id:'known_a',content:'again'}]},
  {left:[{role:'user',id:'known_u',content:'u'}],right:[{role:'remove',id:'known_missing'}]},
  {left:[{role:'user',id:'known_u',content:'u'}],right:[{role:'remove',id:'__remove_all__'},{role:'assistant',id:'known_new',content:'new'}]},
  {left:[{role:'user',id:'known_u',content:'u'}],right:[{role:'remove',id:'__remove_all__'},{role:'assistant',id:'known_new',content:'new'},{role:'remove',id:'known_new'}]},
  {left:[],right:[{role:'assistant',content:'auto'}]},
  {left:[{role:'user',content:'auto'}],right:[{role:'assistant',content:'auto2'}]},
  {left:[],right:[{role:'tool',id:'known_t',content:'result',tool_call_id:'tc'}]},
  {left:[],right:[{role:'remove',id:'known_missing'}]},
];
async function main() {
  const packageVersion=(name)=>requirePinned(name+'/package.json').version;
  process.stdout.write(JSON.stringify({
    provenance:{sdk_commit:'c4ffb9b1b78421bf63eba3e56993017f922387f3',
      langgraph:packageVersion('@langchain/langgraph'),
      core:packageVersion('@langchain/core'),
      checkpoint:packageVersion('@langchain/langgraph-checkpoint'),
      actual_message_classes:true},
    cases, expected:messageOracle(cases), traces: await traceGraph(),
  },null,2)+'\n');
}
if (require.main===module) main().catch(e=>{console.error(e);process.exitCode=1});
module.exports={messageOracle,traceGraph};
