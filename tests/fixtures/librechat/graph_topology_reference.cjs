// Original SDK source; see LICENSE.agents. Construction only, not StateGraph execution.
class StandardGraph { constructor(input) {if(!input.agentIds.length)throw new Error("At least one agent configuration is required");this.agentContexts=new Map(input.agentIds.map(id=>[id,{}]));this.defaultAgentId=input.agentIds[0];} }
class HandoffRouting { constructor(entry,limit,parallel){this.parallel=parallel;} }
class MultiAgentGraph extends StandardGraph {
    edges;
    startingNodes = new Set();
    directEdges = [];
    handoffEdges = [];
    handoffSourceIds = new Set();
    resultAgentId;
    memberRecursionLimit;
    reachableAgentIds;
    agentParallelGroups = new Map();
    constructor(input, dependencies) {
        super(input, dependencies);
        this.edges = input.edges;
        this.resultAgentId = input.resultAgentId;
        this.memberRecursionLimit = input.memberRecursionLimit;
        if (this.memberRecursionLimit != null &&
            (!Number.isSafeInteger(this.memberRecursionLimit) ||
                this.memberRecursionLimit <= 0)) {
            throw new Error('MultiAgentGraph: memberRecursionLimit must be a positive safe integer.');
        }
        if (this.resultAgentId != null &&
            !this.agentContexts.has(this.resultAgentId)) {
            throw new Error(`MultiAgentGraph: resultAgentId "${this.resultAgentId}" is not present in agents.`);
        }
        this.validateEdgeAgents();
        this.categorizeEdges();
        this.validateCommandRoutedDirectEdges();
        this.analyzeGraph();
        if (input.entryAgentId != null) {
            if (!this.agentContexts.has(input.entryAgentId)) {
                throw new Error(`MultiAgentGraph: unknown entryAgentId "${input.entryAgentId}"`);
            }
            this.startingNodes = new Set([input.entryAgentId]);
            this.defaultAgentId = input.entryAgentId;
            this.computeParallelCapability();
            this.reachableAgentIds = this.resolveEntryReachability(input.entryAgentId);
        }
        if (input.maxHandoffs != null &&
            (!Number.isSafeInteger(input.maxHandoffs) || input.maxHandoffs < 0)) {
            throw new Error('MultiAgentGraph: maxHandoffs must be a non-negative safe integer');
        }
        const directDestinations = new Map();
        for (const edge of this.directEdges) {
            if (edge.handoffScope != null)
                throw new Error('handoffScope is only valid on handoff edges');
            for (const source of Array.isArray(edge.from) ? edge.from : [edge.from]) {
                const targets = directDestinations.get(source) ?? new Set();
                for (const target of Array.isArray(edge.to) ? edge.to : [edge.to])
                    targets.add(target);
                directDestinations.set(source, targets);
            }
        }
        this.handoffRouting = new HandoffRouting(this.startingNodes.values().next().value ?? this.defaultAgentId, input.maxHandoffs, this.startingNodes.size > 1 ||
            [...directDestinations.values()].some((targets) => targets.size > 1));
        this.validateHandoffScopes();
        this.createHandoffTools();
    }
    validateHandoffScopes() {
        const scopes = new Map();
        for (const edge of this.handoffEdges) {
            const scope = edge.handoffScope ?? 'turn';
            if (!['turn', 'conversation'].includes(scope))
                throw new Error('Invalid handoffScope');
            for (const source of Array.isArray(edge.from) ? edge.from : [edge.from]) {
                const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
                const targets = edge.condition != null ? ['conditional_transfer'] : destinations;
                for (const target of targets) {
                    const key = JSON.stringify([source, target]);
                    const previous = scopes.get(key);
                    if (previous != null && previous !== scope)
                        throw new Error('Conflicting handoffScope for the same transfer tool');
                    scopes.set(key, scope);
                }
            }
        }
    }
    resolveEntryReachability(entryAgentId) {
        const reachable = new Set([entryAgentId]);
        const direct = new Set(this.directEdges);
        const outgoing = new Map();
        const remaining = new Map();
        for (const edge of this.edges) {
            const sources = new Set(Array.isArray(edge.from) ? edge.from : [edge.from]);
            remaining.set(edge, direct.has(edge) ? sources.size : 1);
            for (const source of sources) {
                const edges = outgoing.get(source) ?? [];
                edges.push(edge);
                outgoing.set(source, edges);
            }
        }
        const queue = [entryAgentId];
        for (let i = 0; i < queue.length; i++) {
            for (const edge of outgoing.get(queue[i]) ?? []) {
                const pending = remaining.get(edge) ?? 0;
                if (pending === 0)
                    continue;
                remaining.set(edge, pending - 1);
                if (pending > 1)
                    continue;
                for (const target of Array.isArray(edge.to) ? edge.to : [edge.to]) {
                    if (reachable.has(target))
                        continue;
                    reachable.add(target);
                    queue.push(target);
                }
            }
        }
        for (const edge of this.directEdges) {
            const sources = Array.isArray(edge.from) ? edge.from : [edge.from];
            if (sources.some((source) => reachable.has(source)) &&
                !sources.every((source) => reachable.has(source))) {
                throw new Error('entryAgentId cannot satisfy a grouped direct edge prerequisite');
            }
        }
        return reachable;
    }
    validateEdgeAgents() {
        const known = new Set(this.agentContexts.keys());
        const unknown = new Set();
        for (const edge of this.edges) {
            const participants = [
                ...(Array.isArray(edge.from) ? edge.from : [edge.from]),
                ...(Array.isArray(edge.to) ? edge.to : [edge.to]),
            ];
            for (const id of participants) {
                if (typeof id === 'string' && !known.has(id)) {
                    unknown.add(id);
                }
            }
        }
        if (unknown.size === 0) {
            return;
        }
        const missing = Array.from(unknown)
            .map((id) => `"${id}"`)
            .join(', ');
        throw new Error(`MultiAgentGraph: edges reference agent(s) not present in agents: [${missing}]. ` +
            'Ensure every agent referenced by an edge is also included in the `agents` array, ' +
            'or filter orphaned edges before constructing the graph.');
    }
    categorizeEdges() {
        for (const edge of this.edges) {
            const sources = Array.isArray(edge.from) ? edge.from : [edge.from];
            const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
            const isDefaultDirect = edge.edgeType == null &&
                edge.condition == null &&
                sources.length === 1 &&
                destinations.length > 1;
            if (edge.edgeType === 'direct' || isDefaultDirect) {
                this.directEdges.push(edge);
                continue;
            }
            this.handoffEdges.push(edge);
            for (const source of sources) {
                this.handoffSourceIds.add(source);
            }
        }
    }
    validateCommandRoutedDirectEdges() {
        const destinationGroups = new Map();
        for (const edge of this.directEdges) {
            const sources = Array.isArray(edge.from) ? edge.from : [edge.from];
            const commandSource = sources.find((source) => this.handoffSourceIds.has(source));
            if (commandSource != null && sources.length > 1) {
                throw new Error('MultiAgentGraph: grouped direct edge cannot include command-routed ' +
                    `source "${commandSource}". Split handoff routing from all-of fan-in.`);
            }
            const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
            const hasPrompt = edge.prompt != null && edge.prompt !== '';
            for (const destination of destinations) {
                const group = destinationGroups.get(destination) ?? {
                    hasPrompt: false,
                };
                group.hasPrompt ||= hasPrompt;
                group.commandSource ??= commandSource;
                destinationGroups.set(destination, group);
            }
        }
        for (const { hasPrompt, commandSource } of destinationGroups.values()) {
            if (!hasPrompt || commandSource == null) {
                continue;
            }
            throw new Error('MultiAgentGraph: prompted direct edge cannot include command-routed ' +
                `source "${commandSource}". Move the prompt into the routed node.`);
        }
    }
    analyzeGraph() {
        const hasIncomingEdge = new Set();
        // Track all nodes that have incoming edges
        for (const edge of this.edges) {
            const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
            destinations.forEach((dest) => hasIncomingEdge.add(dest));
        }
        // Starting nodes are those without incoming edges
        for (const agentId of this.agentContexts.keys()) {
            if (!hasIncomingEdge.has(agentId)) {
                this.startingNodes.add(agentId);
            }
        }
        // If no starting nodes found, use the first agent
        if (this.startingNodes.size === 0 && this.agentContexts.size > 0) {
            this.startingNodes.add(this.agentContexts.keys().next().value);
        }
        // Determine if graph has parallel execution capability
        this.computeParallelCapability();
    }
    computeParallelCapability() {
        let groupCounter = 1; // Start at 1, 0 reserved for "no group"
        // Check 1: Multiple starting nodes means parallel from the start (group 1)
        if (this.startingNodes.size > 1) {
            for (const agentId of this.startingNodes) {
                this.agentParallelGroups.set(agentId, groupCounter);
            }
            groupCounter++;
        }
        // Check 2: Traverse direct edges in order to find fan-out patterns
        // Build a simple execution order by following edges from starting nodes
        const visited = new Set();
        const queue = [...this.startingNodes];
        while (queue.length > 0) {
            const current = queue.shift();
            if (visited.has(current))
                continue;
            visited.add(current);
            // Find direct edges from this node
            for (const edge of this.directEdges) {
                const sources = Array.isArray(edge.from) ? edge.from : [edge.from];
                if (!sources.includes(current))
                    continue;
                const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
                // Fan-out: multiple destinations = parallel group
                if (destinations.length > 1) {
                    for (const dest of destinations) {
                        // Only set if not already in a group (first group wins)
                        if (!this.agentParallelGroups.has(dest)) {
                            this.agentParallelGroups.set(dest, groupCounter);
                        }
                        if (!visited.has(dest)) {
                            queue.push(dest);
                        }
                    }
                    groupCounter++;
                }
                else {
                    // Single destination - add to queue for traversal
                    for (const dest of destinations) {
                        if (!visited.has(dest)) {
                            queue.push(dest);
                        }
                    }
                }
            }
            // Also follow handoff edges for traversal (but they don't create parallel groups)
            for (const edge of this.handoffEdges) {
                const sources = Array.isArray(edge.from) ? edge.from : [edge.from];
                if (!sources.includes(current))
                    continue;
                const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
                for (const dest of destinations) {
                    if (!visited.has(dest)) {
                        queue.push(dest);
                    }
                }
            }
        }
    }
    createHandoffTools() { }
}

module.exports = input => {const graph=new MultiAgentGraph(input);return {starts:[...graph.startingNodes],default:graph.defaultAgentId??null,direct:graph.directEdges,handoff:graph.handoffEdges,parallelGroups:Object.fromEntries(graph.agentParallelGroups),reachable:graph.reachableAgentIds?[...graph.reachableAgentIds]:null,parallel:graph.handoffRouting.parallel};};
