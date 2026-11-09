#!/usr/bin/env node
/** Extract unchanged MultiAgentGraph construction methods as a development oracle. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {createRequire}=require('node:module');
const [root,modules=path.resolve(__dirname,'../ui/workspace/node_modules')]=process.argv.slice(2);
if(!root) throw new Error('Pinned SDK source root required');
const ts=createRequire(path.resolve(modules,'../package.json'))('typescript');
const relative='src/graphs/MultiAgentGraph.ts';
const source=fs.readFileSync(path.join(root,relative),'utf8');
const tree=ts.createSourceFile(relative,source,ts.ScriptTarget.Latest,true);
const names=new Set(['validateHandoffScopes','resolveEntryReachability','validateEdgeAgents','categorizeEdges',
 'validateCommandRoutedDirectEdges','analyzeGraph','computeParallelCapability']);
const fields=new Set(['edges','startingNodes','directEdges','handoffEdges','handoffSourceIds','resultAgentId',
 'memberRecursionLimit','reachableAgentIds','agentParallelGroups']);
let graph;
function visit(node) {if(ts.isClassDeclaration(node)&&node.name?.text==='MultiAgentGraph')graph=node;ts.forEachChild(node,visit);}
visit(tree);if(!graph)throw new Error('Original MultiAgentGraph class missing');
const selected=graph.members.filter(member=>ts.isConstructorDeclaration(member)||
 ts.isMethodDeclaration(member)&&names.has(member.name.getText(tree))||
 ts.isPropertyDeclaration(member)&&fields.has(member.name.getText(tree)));
for(const name of names)if(!selected.some(member=>member.name?.getText(tree)===name))throw new Error('Missing '+name);
const declarations='class MultiAgentGraph extends StandardGraph {\n'+selected.map(member=>member.getText(tree)).join('\n')+
 '\ncreateHandoffTools() {}\n}\n';
const js=ts.transpileModule(declarations,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const out=path.resolve(__dirname,'../tests/fixtures/librechat');
fs.writeFileSync(path.join(out,'graph_topology_reference.cjs'),
 '// Original SDK source; see LICENSE.agents. Construction only, not StateGraph execution.\n'+
 'class StandardGraph { constructor(input) {if(!input.agentIds.length)throw new Error("At least one agent configuration is required");this.agentContexts=new Map(input.agentIds.map(id=>[id,{}]));this.defaultAgentId=input.agentIds[0];} }\n'+
 'class HandoffRouting { constructor(entry,limit,parallel){this.parallel=parallel;} }\n'+js+
 '\nmodule.exports = input => {const graph=new MultiAgentGraph(input);return {starts:[...graph.startingNodes],default:graph.defaultAgentId??null,direct:graph.directEdges,handoff:graph.handoffEdges,parallelGroups:Object.fromEntries(graph.agentParallelGroups),reachable:graph.reachableAgentIds?[...graph.reachableAgentIds]:null,parallel:graph.handoffRouting.parallel};};\n');
fs.writeFileSync(path.join(out,'graph_topology_sources.json'),JSON.stringify({
 commit:'c4ffb9b1b78421bf63eba3e56993017f922387f3',files:{[relative]:crypto.createHash('sha256').update(source).digest('hex'),'src/graphs/Graph.ts':crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'src/graphs/Graph.ts'))).digest('hex')},
 methods:['constructor',...names],boundary:'Only original construction/categorization/validation/reachability/parallel-group analysis. StandardGraph nonempty agent-context initialization (non-summarizeOnly inputs) and HandoffRouting constructor are storage-free test adapters. createHandoffTools is deliberately a no-op: no graph scheduler parity claim.'
},null,2)+'\n');
