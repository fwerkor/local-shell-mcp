// Original LibreChat source; see LICENSE.LibreChat.
module.exports = function resourceOperators(mongoose, getAgent, withCodeEnvironmentReference) {
const hasOperatorKeys = (value) => typeof value === 'object' && value !== null && Object.keys(value).length > 0;
function resolveDocumentPath(source, path) {
    let current = source;
    for (const segment of path.split('.')) {
        if (typeof current !== 'object' || current === null) {
            return undefined;
        }
        current =
            current instanceof Map ? current.get(segment) : current[segment];
    }
    return current;
}
function deleteDocumentPath(source, path) {
    const segments = path.split('.');
    const leaf = segments.pop();
    if (leaf == null)
        return;
    let current = source;
    for (const segment of segments) {
        const next = current[segment];
        if (typeof next !== 'object' || next === null || next instanceof Map)
            return;
        current = next;
    }
    delete current[leaf];
}
function addToSetCandidates(spec) {
    if (typeof spec === 'object' &&
        spec !== null &&
        Array.isArray(spec.$each)) {
        return spec.$each;
    }
    return [spec];
}
function operatorsMutateDocument(currentObject, $push, $pull, $addToSet, $unset) {
    if (hasOperatorKeys($push) || hasOperatorKeys($pull)) {
        return true;
    }
    if (hasOperatorKeys($unset)) {
        for (const path of Object.keys($unset)) {
            if (resolveDocumentPath(currentObject, path) !== undefined)
                return true;
        }
    }
    if (!hasOperatorKeys($addToSet)) {
        return false;
    }
    for (const [path, spec] of Object.entries($addToSet)) {
        const existing = resolveDocumentPath(currentObject, path);
        const stored = Array.isArray(existing) ? existing : [];
        for (const candidate of addToSetCandidates(spec)) {
            if (typeof candidate === 'object' && candidate !== null) {
                return true;
            }
            if (!stored.includes(candidate)) {
                return true;
            }
        }
    }
    return false;
}
function isDuplicateVersion(updateData, currentData, versions, actionsHash = null) {
    if (!versions || versions.length === 0) {
        return null;
    }
    const excludeFields = [
        '_id',
        'id',
        'createdAt',
        'updatedAt',
        'author',
        'updatedBy',
        'created_at',
        'updated_at',
        '__v',
        'versions',
        'actionsHash',
    ];
    const { $push: _$push, $pull: _$pull, $addToSet: _$addToSet, $unset, ...directUpdates } = updateData;
    if (Object.keys(directUpdates).length === 0 && !hasOperatorKeys($unset) && !actionsHash) {
        return null;
    }
    const wouldBeVersion = { ...currentData, ...directUpdates };
    if (hasOperatorKeys($unset)) {
        for (const path of Object.keys($unset)) {
            deleteDocumentPath(wouldBeVersion, path);
        }
    }
    const lastVersion = versions[versions.length - 1];
    if (actionsHash && lastVersion.actionsHash !== actionsHash) {
        return null;
    }
    const allFields = new Set([...Object.keys(wouldBeVersion), ...Object.keys(lastVersion)]);
    const importantFields = Array.from(allFields).filter((field) => !excludeFields.includes(field));
    let isMatch = true;
    for (const field of importantFields) {
        const wouldBeValue = wouldBeVersion[field];
        const lastVersionValue = lastVersion[field];
        if (!wouldBeValue && !lastVersionValue) {
            continue;
        }
        // Handle arrays
        if (Array.isArray(wouldBeValue) || Array.isArray(lastVersionValue)) {
            let wouldBeArr;
            if (Array.isArray(wouldBeValue)) {
                wouldBeArr = wouldBeValue;
            }
            else if (wouldBeValue == null) {
                wouldBeArr = [];
            }
            else {
                wouldBeArr = [wouldBeValue];
            }
            let lastVersionArr;
            if (Array.isArray(lastVersionValue)) {
                lastVersionArr = lastVersionValue;
            }
            else if (lastVersionValue == null) {
                lastVersionArr = [];
            }
            else {
                lastVersionArr = [lastVersionValue];
            }
            if (wouldBeArr.length !== lastVersionArr.length) {
                isMatch = false;
                break;
            }
            if (wouldBeArr.length > 0 && typeof wouldBeArr[0] === 'object' && wouldBeArr[0] !== null) {
                const sortedWouldBe = [...wouldBeArr].map((item) => JSON.stringify(item)).sort();
                const sortedVersion = [...lastVersionArr].map((item) => JSON.stringify(item)).sort();
                if (!sortedWouldBe.every((item, i) => item === sortedVersion[i])) {
                    isMatch = false;
                    break;
                }
            }
            else {
                const sortedWouldBe = [...wouldBeArr].sort();
                const sortedVersion = [...lastVersionArr].sort();
                if (!sortedWouldBe.every((item, i) => item === sortedVersion[i])) {
                    isMatch = false;
                    break;
                }
            }
        }
        // Handle objects
        else if (typeof wouldBeValue === 'object' && wouldBeValue !== null) {
            const lastVersionObj = typeof lastVersionValue === 'object' && lastVersionValue !== null ? lastVersionValue : {};
            const wouldBeKeys = Object.keys(wouldBeValue);
            const lastVersionKeys = Object.keys(lastVersionObj);
            if (wouldBeKeys.length === 0 && lastVersionKeys.length === 0) {
                continue;
            }
            if (JSON.stringify(wouldBeValue) !== JSON.stringify(lastVersionObj)) {
                isMatch = false;
                break;
            }
        }
        // Handle primitive values
        else {
            if (wouldBeValue !== lastVersionValue) {
                if (typeof wouldBeValue === 'boolean' &&
                    wouldBeValue === false &&
                    lastVersionValue === undefined) {
                    continue;
                }
                if (typeof wouldBeValue === 'string' &&
                    wouldBeValue === '' &&
                    lastVersionValue === undefined) {
                    continue;
                }
                isMatch = false;
                break;
            }
        }
    }
    return isMatch ? lastVersion : null;
}
async function updateAgent(searchParameter, updateData, options = {}) {
    const Agent = mongoose.models.Agent;
    const { updatingUserId = null, forceVersion = false, skipVersioning = false } = options;
    const mongoOptions = { new: true, upsert: false };
    /** Set when the update would snapshot a version identical to the newest one. The write
     *  still lands; only the `versions` entry is dropped. */
    let suppressedVersionEntry = false;
    const currentAgent = await Agent.findOne(searchParameter);
    const currentRevision = currentAgent?.updatedAt;
    if (currentAgent) {
        const currentObject = currentAgent.toObject();
        const { __v, _id, id: __id, versions, author: _author, ...versionData } = currentObject;
        const { $push, $pull, $addToSet, $unset, ...directUpdates } = updateData;
        /** Self-heal: drop allowlist ids whose skill no longer exists in the
         *  database or the external registry.
         *  A dangling id keeps the allowlist non-empty while scoping the
         *  runtime catalog to an empty intersection, silently disabling
         *  skills for the agent. When pruning empties a non-empty allowlist,
         *  fail closed and disable skills: empty + enabled means the full
         *  catalog, and hygiene must never widen scope. (An explicit user
         *  `skills: []` submission skips this branch and keeps the
         *  full-catalog semantics.)
         *
         *  An `all` or `selected` scope opts out, from the payload or the
         *  stored document, because it already defines what an empty allowlist
         *  means. See `requiresSkillsDisable`. */
        if (Array.isArray(directUpdates.skills) && directUpdates.skills.length > 0) {
            const prunedSkills = await filterExistingSkillIds(mongoose, directUpdates.skills, isExternalSkillId);
            directUpdates.skills = prunedSkills;
            updateData.skills = prunedSkills;
            const effectiveScope = directUpdates.skills_scope ?? currentObject.skills_scope;
            if (prunedSkills.length === 0 && requiresSkillsDisable(effectiveScope)) {
                directUpdates.skills_enabled = false;
                updateData.skills_enabled = false;
            }
        }
        // Sync mcpServerNames when tools are updated
        if (directUpdates.tools !== undefined) {
            /** Callers that authorized the tools pass resolved names; deriving from the key
             * alone cannot tell a config server's suffix from a real DB server name. */
            const supplied = directUpdates.mcpServerNames;
            const mcpServerNames = supplied ??
                rebuildMCPServerNames(directUpdates.tools, currentAgent.mcpServerNames ?? []);
            directUpdates.mcpServerNames = mcpServerNames;
            updateData.mcpServerNames = mcpServerNames;
        }
        let actionsHash = null;
        // Generate actions hash if agent has actions
        if (currentAgent.actions && currentAgent.actions.length > 0) {
            const actionIds = currentAgent.actions
                .map((action) => {
                const parts = action.split(actionDelimiter);
                return parts[1];
            })
                .filter(Boolean);
            if (actionIds.length > 0) {
                try {
                    const actions = await getActions({ actionId: actionIds }, true);
                    actionsHash = await generateActionMetadataHash(currentAgent.actions, actions);
                }
                catch (error) {
                    logger.error('Error fetching actions for hash generation:', error);
                }
            }
        }
        const shouldCreateVersion = !skipVersioning &&
            (forceVersion ||
                Object.keys(directUpdates).length > 0 ||
                $push ||
                $pull ||
                $addToSet ||
                $unset);
        if (shouldCreateVersion) {
            const duplicateVersion = isDuplicateVersion(updateData, versionData, versions, actionsHash);
            /** A duplicate snapshot adds no history, but the write itself must still land: the
             *  document is regularly not equal to its newest version, because `$push`/`$pull`/
             *  `$addToSet` snapshot the pre-update state and `skipVersioning` snapshots nothing.
             *  `isDuplicateVersion` compares direct updates only, so it cannot speak for an
             *  update that also carries an operator that lands a change; suppressing there
             *  would apply a change no version records. An operator that changes nothing, the
             *  shape of an idempotent retry, leaves the snapshot a genuine duplicate. */
            const mutatesOutsideSnapshot = operatorsMutateDocument(currentObject, $push, $pull, $addToSet, $unset);
            if (duplicateVersion && !forceVersion && !mutatesOutsideSnapshot) {
                suppressedVersionEntry = true;
                /** Every operator that reaches here was judged unable to change the document,
                 *  and for `$addToSet` that reading came from a document fetched before the
                 *  write, so it cannot bind a concurrent one: a `$pull` landing in between would
                 *  leave this update re-adding the value with no version entry to record it.
                 *  Drop what was judged a no-op rather than race it, so the suppressed write
                 *  carries no operator at all and is true by construction instead of true only
                 *  while nothing else writes first. */
                delete updateData.$addToSet;
                delete updateData.$push;
                delete updateData.$pull;
                delete updateData.$unset;
            }
        }
        const versionEntry = {
            ...versionData,
            ...directUpdates,
            updatedAt: new Date(),
        };
        if (hasOperatorKeys($unset)) {
            for (const path of Object.keys($unset)) {
                deleteDocumentPath(versionEntry, path);
            }
        }
        if (actionsHash) {
            versionEntry.actionsHash = actionsHash;
        }
        if (updatingUserId) {
            versionEntry.updatedBy = new mongoose.Types.ObjectId(updatingUserId);
        }
        if (shouldCreateVersion && !suppressedVersionEntry) {
            updateData.$push = {
                ...($push || {}),
                versions: versionEntry,
            };
        }
    }
    const directEnvironmentId = updateData.code_environment_id;
    const setEnvironmentId = typeof updateData.$set === 'object' && updateData.$set != null
        ? updateData.$set.code_environment_id
        : undefined;
    let nextEnvironmentId;
    if (typeof directEnvironmentId === 'string') {
        nextEnvironmentId = directEnvironmentId;
    }
    else if (typeof setEnvironmentId === 'string') {
        nextEnvironmentId = setEnvironmentId;
    }
    const updatedAgent = await withCodeEnvironmentReference(mongoose, nextEnvironmentId, async () => (await Agent.findOneAndUpdate(currentAgent == null || nextEnvironmentId == null
        ? searchParameter
        : { ...searchParameter, _id: currentAgent._id, updatedAt: currentRevision }, updateData, mongoOptions).lean()), undefined, async (agentAfterUpdate) => {
        if (agentAfterUpdate == null || nextEnvironmentId == null)
            return;
        if (currentAgent == null)
            return;
        await restoreAgentAfterReferenceLoss(Agent, agentAfterUpdate, currentAgent.toObject(), nextEnvironmentId);
    });
    /** `version` is a response-only field holding the count of `versions`. It is reported
     *  here so a suppressed entry keeps the shape callers saw before the write was fixed.
     *  It answers "was a version recorded", never "did the update apply". The two stopped
     *  being the same question once a suppressed update started landing. */
    if (updatedAgent && suppressedVersionEntry) {
        updatedAgent.version = updatedAgent.versions?.length ?? 0;
    }
    return updatedAgent;
}
async function addAgentResourceFile({ agent_id, tool_resource, file_id, updatingUserId, }) {
    const Agent = mongoose.models.Agent;
    const searchParameter = { id: agent_id };
    const agent = await getAgent(searchParameter);
    if (!agent) {
        throw new Error('Agent not found for adding resource file');
    }
    const fileIdsPath = `tool_resources.${tool_resource}.file_ids`;
    await Agent.updateOne({
        id: agent_id,
        [`${fileIdsPath}`]: { $exists: false },
    }, {
        $set: {
            [`${fileIdsPath}`]: [],
        },
    });
    const updateDataObj = {
        $addToSet: {
            tools: tool_resource,
            [fileIdsPath]: file_id,
        },
    };
    const updatedAgent = await updateAgent(searchParameter, updateDataObj, {
        updatingUserId,
    });
    if (updatedAgent) {
        return updatedAgent;
    }
    else {
        throw new Error('Agent not found for adding resource file');
    }
}
async function removeAgentResourceFiles({ agent_id, files, }) {
    const Agent = mongoose.models.Agent;
    const searchParameter = { id: agent_id };
    const filesByResource = files.reduce((acc, { tool_resource, file_id }) => {
        if (!acc[tool_resource]) {
            acc[tool_resource] = [];
        }
        acc[tool_resource].push(file_id);
        return acc;
    }, {});
    const pullAllOps = {};
    for (const [resource, fileIds] of Object.entries(filesByResource)) {
        const fileIdsPath = `tool_resources.${resource}.file_ids`;
        pullAllOps[fileIdsPath] = fileIds;
    }
    const updatePullData = { $pullAll: pullAllOps };
    const agentAfterPull = (await Agent.findOneAndUpdate(searchParameter, updatePullData, {
        new: true,
    }).lean());
    if (!agentAfterPull) {
        const agentExists = await getAgent(searchParameter);
        if (!agentExists) {
            throw new Error('Agent not found for removing resource files');
        }
        throw new Error('Failed to update agent during file removal (pull step)');
    }
    return agentAfterPull;
}

return {addAgentResourceFile,removeAgentResourceFiles};
};
