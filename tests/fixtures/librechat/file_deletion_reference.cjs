var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __hasOwnProp = Object.prototype.hasOwnProperty;
function __accessProp(key) {
  return this[key];
}
var __toCommonJS = (from) => {
  var entry = (__moduleCache ??= new WeakMap).get(from), desc;
  if (entry)
    return entry;
  entry = __defProp({}, "__esModule", { value: true });
  if (from && typeof from === "object" || typeof from === "function") {
    for (var key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(entry, key))
        __defProp(entry, key, {
          get: __accessProp.bind(from, key),
          enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
        });
  }
  __moduleCache.set(from, entry);
  return entry;
};
var __moduleCache;
var __returnValue = (v) => v;
function __exportSetter(name, newValue) {
  this[name] = __returnValue.bind(null, newValue);
}
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: __exportSetter.bind(all, name)
    });
};

// ../librechat-reference-e8f3be08/packages/api/src/files/deletion.ts
var exports_deletion = {};
__export(exports_deletion, {
  partitionAgentResourceFiles: () => partitionAgentResourceFiles,
  deleteAgentResourceFiles: () => deleteAgentResourceFiles,
  buildDeleteFilesResponse: () => buildDeleteFilesResponse,
  PARTIAL_FILE_DELETION_MESSAGE: () => PARTIAL_FILE_DELETION_MESSAGE
});
module.exports = __toCommonJS(exports_deletion);
var PARTIAL_FILE_DELETION_MESSAGE = "Some files could not be deleted";
var buildDeleteFilesResponse = (result, successMessage) => {
  const deletedFileIds = result?.deletedFileIds ?? [];
  const failedFileIds = result?.failedFileIds ?? [];
  return {
    message: failedFileIds.length > 0 ? PARTIAL_FILE_DELETION_MESSAGE : successMessage,
    deletedFileIds,
    failedFileIds
  };
};
var partitionAgentResourceFiles = ({
  requestedFileIds,
  attachedFileIds,
  files,
  toolResource,
  userId
}) => {
  const attached = new Set(attachedFileIds);
  const inputsById = new Map(files.map((input) => [input.file_id, input]));
  const seen = new Set;
  const ownedFiles = [];
  const unlinkOnlyFiles = [];
  for (const fileId of requestedFileIds) {
    if (!attached.has(fileId) || seen.has(fileId)) {
      continue;
    }
    seen.add(fileId);
    const input = inputsById.get(fileId);
    if (input != null && input.owner === userId) {
      ownedFiles.push(input);
      continue;
    }
    unlinkOnlyFiles.push({ tool_resource: toolResource, file_id: fileId });
  }
  return { ownedFiles, unlinkOnlyFiles };
};
var deleteAgentResourceFiles = async ({
  agentId,
  agentObjectId,
  toolResource,
  requestedFileIds,
  attachedFileIds,
  files,
  userId
}, deps) => {
  const { ownedFiles, unlinkOnlyFiles } = partitionAgentResourceFiles({
    requestedFileIds,
    attachedFileIds,
    files,
    toolResource,
    userId
  });
  const sharedFileIds = ownedFiles.length === 0 ? new Set : new Set(await deps.getSharedResourceFileIds({
    file_ids: ownedFiles.map((input) => input.file_id),
    excludeAgentObjectId: agentObjectId,
    excludeToolResource: toolResource
  }));
  const destroyable = [];
  const unlinkOnly = [...unlinkOnlyFiles];
  for (const input of ownedFiles) {
    if (sharedFileIds.has(input.file_id)) {
      unlinkOnly.push({ tool_resource: toolResource, file_id: input.file_id });
      continue;
    }
    destroyable.push(input);
  }
  const outcome = destroyable.length === 0 ? null : await deps.deleteFiles(destroyable.map((input) => input.file));
  if (unlinkOnly.length > 0) {
    await deps.removeAgentResourceFiles({ agent_id: agentId, files: unlinkOnly });
  }
  return {
    outcome,
    unlinkedFileIds: unlinkOnly.map((ref) => ref.file_id),
    destroyedFileIds: outcome?.deletedFileIds ?? []
  };
};
