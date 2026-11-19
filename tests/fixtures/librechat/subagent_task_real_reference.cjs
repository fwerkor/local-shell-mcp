/* @librechat/agents@4.0.1 original InMemorySubagentTaskStore oracle.
 * Uses the package's real runtime, message classes, control receipts and
 * state transitions. Only nondeterministic IDs/timestamps are projected.
 */
const path = require('node:path');
const {createRequire} = require('node:module');
const load = createRequire(path.resolve(process.env.LSM_JS_ORACLE_ROOT || process.cwd(), 'package.json'));
const {InMemorySubagentTaskStore} = load('@librechat/agents');
const {HumanMessage, AIMessage} = load('@langchain/core/messages');
const store = new InMemorySubagentTaskStore();
const observed = {};
let release;
const gate = new Promise(resolve => {release = resolve;});
const request = {
  scopeId:'trusted-parent', idempotencyKey:'["run","parent","call"]',
  parentRunId:'run', parentAgentId:'parent', parentToolCallId:'call',
  requestFingerprint:'fixed', input:'Review source', subagentKind:'agent', subagentType:'reviewer',
  run:async runtime=>{
    await gate;
    observed.injectedAtTool = runtime.drain('tool').map(m=>({role:m.role,content:m.content,source:m.source}));
    observed.injectedAtTurn = runtime.drain('turn').map(m=>({role:m.role,content:m.content,source:m.source}));
    return {content:'reviewed', messages:[new HumanMessage('Review source'),new AIMessage('reviewed')]};
  },
};
async function main(){
  const first=store.start(request);
  const duplicate=store.start(request);
  const conflict=store.start({...request,requestFingerprint:'changed'});
  const id=first.task.taskId;
  const queued=store.control('trusted-parent',id,{action:'queue',message:'ignore this'});
  const withdrawn=store.control('trusted-parent',id,{action:'cancel_message',controlId:queued.controlId});
  const steered=store.control('trusted-parent',id,{action:'steer',message:'focus on safety'});
  observed.start = first.task.status;
  observed.duplicate = duplicate.accepted && !duplicate.isNew && duplicate.task.taskId===id;
  observed.conflict=conflict.reason;
  observed.queue = queued.status;
  observed.withdraw = withdrawn.status;
  observed.steer = steered.status;
  observed.pending = store.get('trusted-parent',id).pendingControls;
  observed.foreign=store.claim('another-parent',id).status;
  release();
  for(let i=0;i<300 && store.get('trusted-parent',id).status==='running';i++){
    await new Promise(resolve=>setTimeout(resolve,2));
  }
  const finished=store.get('trusted-parent',id);
  observed.settled=finished.status;
  observed.receipts=finished.controlReceipts.map(x=>[x.action,x.status,x.boundary||'',x.reason||'']);
  const claimed=store.claim('trusted-parent',id);
  observed.claim=claimed.status;
  observed.claimResult=claimed.result;
  observed.claimedFlag=claimed.task.resultClaimed;
  observed.claimAvailable=claimed.task.resultAvailable;
  observed.claimAgain=store.claim('trusted-parent',id).status;
  observed.snapshotAfter=store.get('trusted-parent',id).status;
  process.stdout.write(JSON.stringify({source:'@librechat/agents@4.0.1',trace:observed}));
}
main().catch(e=>{console.error(e);process.exitCode=1});
