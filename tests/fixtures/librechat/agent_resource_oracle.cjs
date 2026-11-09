/** Test-only Mongo operator adapter for the extracted original functions. */
const fs = require('node:fs');
const create = require('./agent_resource_operators.cjs');
const clone = value => structuredClone(value);
async function execute(operations) {
 const initial = {name:'Resource agent',provider:'openAI',model:null,tools:[],tool_resources:{}};
 let doc = {id:'agent',...clone(initial),versions:[clone(initial)]};
 const get = (value, key) => key.split('.').reduce((item, part) => item?.[part], value);
 function set(value, key, item) {
  const parts=key.split('.'); let parent=value;
  for (const part of parts.slice(0,-1)) parent=parent[part] ??= {};
  parent[parts.at(-1)]=clone(item);
 }
 function matches(filter) {
  return Object.entries(filter).every(([key,value]) => typeof value === 'object' && value !== null && '$exists' in value
   ? (get(doc,key) !== undefined) === value.$exists : get(doc,key) === value);
 }
 function apply(update) {
  for (const [kind,values] of Object.entries(update)) {
   if (!kind.startsWith('$')) {set(doc,kind,values);continue;}
   if (!['$set','$addToSet','$push','$pullAll'].includes(kind)) throw new Error('Unsupported storage operator: '+kind);
   for (const [key,value] of Object.entries(values)) {
    if (kind === '$set') {set(doc,key,value);continue;}
    let current=get(doc,key) ?? [];
    if (kind === '$pullAll') current=current.filter(item=>!value.includes(item));
    else if (kind === '$push') current=[...current,clone(value)];
    else if (!current.includes(value)) current=[...current,clone(value)];
    set(doc,key,current);
   }
  }
 }
 const Model={
  findOne(filter) {return Promise.resolve(matches(filter)?{...clone(doc),toObject:()=>clone(doc)}:null);},
  async updateOne(filter,update) {if(matches(filter)) apply(update);},
  findOneAndUpdate(filter,update) {
   const matched=matches(filter);if(matched) apply(update);
   return {lean:async()=>matched?clone(doc):null};
  },
 };
 const methods=create({models:{Agent:Model}},async filter=>matches(filter)?clone(doc):null,
  async (_mongoose,environment,operation)=>{if(environment !== undefined)throw new Error('Environment boundary not exercised');return await operation();});
 function normalized(value) {return clone({tools:value.tools ?? [],tool_resources:value.tool_resources ?? {}});}
 const results=[];
 for(const operation of operations) {
  if(operation.action === 'add') await methods.addAgentResourceFile({agent_id:'agent',tool_resource:operation.resource,file_id:operation.file});
  else if(operation.action === 'remove') await methods.removeAgentResourceFiles({agent_id:'agent',files:operation.files});
  else throw new Error('Unknown test action');
  results.push({...normalized(doc),version:doc.versions.length,snapshots:doc.versions.map(normalized)});
 }
 return results;
}
(async()=>{
 const cases=JSON.parse(fs.readFileSync(0,'utf8'));
 process.stdout.write(JSON.stringify(await Promise.all(cases.map(execute))));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
