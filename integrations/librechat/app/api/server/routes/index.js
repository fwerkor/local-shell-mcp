const accessPermissions = require('./accessPermissions');
const assistants = require('./assistants');
const categories = require('./categories');
const endpoints = require('./endpoints');
const staticRoute = require('./static');
const messages = require('./messages');
const memories = require('./memories');
const presets = require('./presets');
const projects = require('./projects');
const prompts = require('./prompts');
const schedules = require('./schedules');
const skills = require('./skills');
const banner = require('./banner');
const search = require('./search');
const models = require('./models');
const convos = require('./convos');
const traces = require('./traces');
const config = require('./config');
const agents = require('./agents');
const roles = require('./roles');
const files = require('./files');
const tags = require('./tags');
const auth = require('./auth');
const keys = require('./keys');
const user = require('./user');
const mcp = require('./mcp');

module.exports = {
  mcp,
  auth,
  keys,
  user,
  tags,
  roles,
  files,
  banner,
  agents,
  convos,
  traces,
  search,
  config,
  models,
  prompts,
  projects,
  schedules,
  skills,
  presets,
  messages,
  memories,
  endpoints,
  assistants,
  categories,
  staticRoute,
  accessPermissions,
};
