/* Dev-only source oracle generator; requires ts-node, zod, axios and js-yaml.
 * Usage:
 * NODE_PATH=ui/workspace/node_modules TS_NODE_COMPILER_OPTIONS='{"module":"CommonJS","moduleResolution":"node"}' \
 * TS_NODE_TRANSPILE_ONLY=true node -r ts-node/register/transpile-only \
 * scripts/generate-actions-oracle.cjs > tests/fixtures/librechat/actions_source_oracle.json
 *
 * Reads exact LibreChat v0.8.8 vendored source; nothing here runs in production.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const dir = path.resolve(__dirname, '../ui/workspace/packages/data-provider/src');
const source = path.join(dir, 'actions.ts');
const actionTools = path.join(dir, 'agentToolOptions.ts');
const actionTypes = path.join(dir, 'types/tools.ts');
const ref = require(source);
const tools = require(actionTools);
const types = require(actionTypes);

const base = 'https://api.example.org';
const cases = [];
const doc = (paths, extra = {}) => ({
  openapi: '3.0.0',
  servers: [{ url: base + '/v1' }],
  info: { title: 'Action Example', version: '1.0.0' },
  paths, ...extra,
});
cases.push(doc({ '/hello': { get: { operationId: 'hello', summary: 'Hello world' } } }));
cases.push(doc({ '/users/{id}': { get: {
  operationId: 'getUser', description: 'Get user',
  parameters: [
    { name: 'id', in: 'path', required: true, schema: { type: 'string' } },
    { name: 'page', in: 'query', schema: { type: 'integer', minimum: 0 } },
    { name: 'X-Region', in: 'header', schema: { type: 'string', enum: ['us','eu'] } },
  ],
} } }));
cases.push(doc({ '/users': { post: {
  operationId: 'createUser', summary: 'Create user',
  requestBody: { required: true, content: {'application/json': {schema: {
    type: 'object', properties: { firstName: { type: 'string' }, age: {type:'integer'} },
    required: ['firstName'] }}} },
} } }));
cases.push(doc({
  '/products': { get: { operationId: 'listProducts', summary: 'Products' }},
  '/products/{sku}': { patch: { operationId: 'updateProduct',
    parameters: [{ name: 'sku', in: 'path', required: true, schema:{type:'string'}}],
    requestBody: {content: {'application/json': {schema: {type:'object',
      properties:{quantity:{type:'integer'}}, required:['quantity']}}}},
  } },
  '/products-new': { delete: {operationId:'deleteProducts'} },
}));
cases.push(doc({ '/with-hyphen/{thing}': { get: {
  summary:'No provided ID', 'x-strict': true, 'x-openai-isConsequential': true,
  parameters:[{name:'thing',in:'path',required:true,schema:{type:'string'}}],
} } }));
cases.push(doc({ '/ref': { put: {
  operationId:'putReference', parameters:[{'$ref':'#/components/parameters/RefId'}],
  requestBody: {content: {'application/json': {schema:{'$ref':'#/components/schemas/RefBody'}}}},
} } }, {components:{
  parameters: { RefId: {name:'id',in:'query',schema: {'$ref':'#/components/schemas/RefId'}}},
  schemas:{RefId:{type:'string',pattern:'^[a-z]+$'},
           RefBody:{type:'object',properties:{enabled:{type:'boolean'}},required:['enabled']}},
}}));
cases.push(doc({ '/empty': { get: { operationId:'empty' }} }));
cases.push(doc({ '/option': { options: { operationId:'options' }} }));
cases.push(doc({ '/health': { get: { operationId:'health', 'x-strict': false,
  parameters:[{name:'verbose',in:'query',schema:{type:'boolean'}}] } } }));
cases.push(doc({ '/legacy': { get: {
  operationId:'legacy', parameters:[{name:'a',in:'notset',schema:{type:'string'}}],
} } }));

const outputs = cases.map(spec => {
  const result = ref.validateAndParseOpenAPISpec(JSON.stringify(spec));
  if (!result.status) {
    return {spec, error:result.message};
  }
  const mapping = ref.openapiToFunction(result.spec);
  return {
    spec,
    functions: mapping.functionSignatures.map(signature => signature.toObjectTool()),
    builders: Object.fromEntries(Object.entries(mapping.requestBuilders).map(
      ([name, builder]) => [name, builder.config]
    )),
  };
});
const names = [
  'get_action_swapi---tech', 'get_foo---bar_action_swapi---tech',
  'get_action_data---x_mcp_srv', 'tool_mcp_foo', 'prefix_mcp_x_action_a---b',
  'simple_action_local---io', 'get_action_mcp_docs', 'get_mcp_docs_action_c---d',
  'get_action_foo_action_bar---baz', 'ab___action_foo_mcp_srv',
];
const tool_vectors = names.map(name => ({
  name, isAction: types.isActionTool(name),
  normalized: tools.normalizeActionToolName(name),
}));
const domains = [
  ['https://api.example.org', base + '/v1'], ['api.example.org', base + '/v1'],
  ['http://api.example.org', base + '/v1'], ['https://api.example.org:443', base + '/v1'],
  ['https://api.example.org:8443', base + '/v1'], ['https://example.org', base + '/v1'],
  ['http://127.0.0.1', 'http://127.0.0.1:8900'], ['127.0.0.1', 'http://127.0.0.1:8900'],
  ['http://localhost', 'http://localhost:8080'], ['https://api.example.org', 'ftp://api.example.org'],
].map(([domain, server]) => ({
  domain, server, isValid: ref.validateActionDomain(domain, server).isValid,
}));
const hashes = Object.fromEntries([source,actionTools,actionTypes].map(file => [
  path.relative(path.resolve(__dirname, '..'), file).replaceAll(path.sep, '/'),
  crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
]));
process.stdout.write(JSON.stringify({
  source: 'LibreChat v0.8.8 e8f3be08623663d4ad7f7241e693c94469b63bb0',
  hashes, outputs, tool_vectors, domains,
}, null, 2) + '\n');
