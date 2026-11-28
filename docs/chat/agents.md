# Agents and Skills

## When to create an Agent

A direct model chat is useful for a one-off question or task. An Agent is a saved configuration that can be selected repeatedly, used by scheduled chats or delegated to by other agents. Different Agents may use different channels, models, instructions and access policies. They share the same Controller, not necessarily the same memory scope or tools.

## Configure an Agent

Open Agent management from the WebUI, create an Agent, give it a recognizable name and choose its model. Write its instructions to describe the task, desired output, constraints and verification requirements. Configure the capabilities it needs, then save and start a new conversation with it.

![Agent Builder with instructions, tools, approval and Skill settings](../assets/chat/agent-builder.png)

For example, a repository reviewer might have these instructions:

```text
Review the changes against the current main branch.
Inspect the repository and test results before drawing conclusions.
Do not edit files, push commits or deploy anything.
Report concrete findings with paths and evidence.
```

Instructions are useful for directing behavior but are not an authorization boundary. Set machine access to read only and omit unnecessary external MCP capabilities if the reviewer should not modify anything. See [Tools and permissions](permissions.md).

Prefer separate Agents for distinct duties, such as code review, implementation and operations. Give each the smallest practical access and a model appropriate to its role. If an Agent cannot start, verify its referenced channel and model before changing unrelated settings.

## Skills

A Skill packages reusable instructions and related files, conventionally with a `SKILL.md` entry. Manage Skills in the WebUI; enable the relevant Skills and make them available to the Agent or chat. The model can discover and load Skill content when needed. A Skill may describe a workflow, reference examples or contain scripts; it does not automatically execute scripts or grant additional machine permissions.

Inspect imported Skills before enabling them. Treat their instructions and files like any other third-party code or prompt. Make Skill names and descriptions specific enough for the model to discover them, keep large references separate, and prefer small independently usable workflows. The Controller-side registry and the tool calls are explained in [Skills](../guides/skills.md).

Automatic Skill and memory context is snapshotted for a conversation to avoid rewriting the system prompt on every turn. Explicit Skill scope changes can take effect; use a fresh conversation when testing newly edited automatic context. A deliberately loaded Skill is distinct from the initial automatic snapshot.

## Delegation and subagents

Agents can delegate bounded work to subagents when that capability is available. A child may use a configured Agent and retain its own conversation-like execution thread. The parent coordinates the task, reads the child result and can continue the saved child thread. Inspect child activity from the parent conversation; that view is not an independent editable chat.

Use delegation for separable tasks such as independent reviews, separate file areas or investigation of different hypotheses. Provide the child with a concrete objective, scope and expected result. Avoid concurrent writes to the same files unless the work is explicitly coordinated.

Delegation must remain within the parent's authorized execution boundaries. It does not grant access to a machine or MCP service that the parent cannot use; child approval policy cannot weaken the parent's policy. Child tasks can consume model tokens and time independently, so inspect their activity and results when evaluating cost and progress.

## Tools, actions and artifacts

The Agent Builder exposes its available tool library and advanced configuration. Select only capabilities you need. For an HTTP Action described by an OpenAPI schema, review the endpoint, authentication requirements and permitted operations before connecting the Action. Actions can have their own authentication; a machine permission does not authorize or revoke a third-party API credential. Inspect the Action response before treating a remote mutation as complete.

For generated UI content, configure artifact rendering as described in [Conversations and projects](conversations.md). Generated code is not a trusted extension of the Controller.

## Practical Agent templates

- **Read-only investigator:** inspect logs and source, compare evidence, report causes, no modification.
- **Implementation Agent:** edit a repository, run targeted tests, report diffs and unresolved failures; require approval for sensitive operations if appropriate.
- **Monitoring Agent:** inspect specified machines and report status, errors and measured progress; do not restart jobs unless explicitly authorized.
- **Research Agent:** enable network search, cite original documents, distinguish evidence from inference, and use machine tools only if needed.

The templates are instructions, not built-in presets. Configure each Agent's actual permissions and capabilities to match its intended duty.
