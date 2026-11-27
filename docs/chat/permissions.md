# Tools, machines and permissions

## Authorization layers

A tool being listed does not guarantee permission to execute it. The effective authorization combines Controller restrictions and authenticated principal scopes, machine policy, Agent capabilities and tool approval. Prompt instructions alone do not enforce access.

Registered machines, including the local Controller target when enabled, default to read/write for the chat machine policy. Restrict the defaults for sensitive deployments. Unknown machine names do not receive implicit grants. The Controller can disable local execution or remote Workers independently.

## Machine access

| Access | Meaning |
|---|---|
| None | Machine operations are unavailable |
| Read only | Only operations classified as read-only are allowed; arbitrary shell/Python execution is not a read-only operation |
| Read/write | Allows authorized read and modifying/execution operations, subject to other limits |
| Inherit | Use the applicable higher-level default rather than an explicit override |

![Machine permissions and approval mode in a conversation](../assets/chat/machine-permissions.png)

Set global defaults, project overrides and per-chat overrides in the machine permission controls. Specific conversation overrides take precedence over project overrides, which take precedence over global defaults. An Agent can further cap access per machine or by its default policy; explicit Agent permissions do not bypass the authenticated principal or Controller restrictions.

Example: a global read/write policy with a project read-only override and an Agent read/write grant yields read-only access in that project's chat unless the conversation policy explicitly overrides it. A conversation read/write override still cannot exceed an Agent's read-only ceiling.

A scheduled run with a named Agent uses that Agent's machine policy and saved execution scopes rather than inheriting ordinary chat machine overrides. See [Goals and automation](automation.md). Use a dedicated restricted Agent for unattended tasks.

## Tool approval

| Mode | Behavior |
|---|---|
| Automatic | Authorized tool calls proceed without an extra approval prompt unless a separate explicit policy requires it |
| Dangerous | The Controller requests review for operations classified as dangerous, including arbitrary shell commands and many external calls |
| All | Requests approval for ordinary tool calls |

Chat approval settings can inherit the Agent and global defaults. Existing explicit denial or approval rules remain applicable. A child Agent cannot weaken the parent's approval mode. Approval is independent of permissions: approving a denied machine action does not grant machine access.

Review the actual arguments, destination and potential side effects before approving. For an unattended workflow, configure the Agent and approval policy deliberately; a human-required approval can stall progress. Do not broaden access merely to remove prompts.

## Native and external MCP tools

Native tools operate on the Controller and registered Workers through LSM. The tool registry includes file operations, shell and jobs, browser and GUI operations, remote discovery, logical sessions and other functions. Use [Tools reference](../reference/tools.md) for exact argument schemas and [Remote workers](../guides/remote-workers.md) for joining machines.

Manage nested MCP servers in the WebUI. Supported configurations include local stdio and remote HTTP transports, with server-specific environment variables or headers. Enable the external MCP capability in chat and the relevant Agent. The Agent can discover, inspect and call available external tools; their authorization and tool approval still apply.

An external MCP tool may operate independently of native machine ACLs: a remote external API can modify resources even if local machine access is disabled. Review the external service's permissions and credentials separately. Do not install untrusted stdio servers on a Controller that holds sensitive files.

## Ask User and feature toggles

Ask User lets an Agent request structured human input instead of guessing. Respond using the presented question control. This is a request for information, not permission to bypass a denied tool. When the task is unattended, instruct the Agent how to handle uncertainty and inspect pending interactions before assuming it finished.

The composer exposes feature controls such as network search, external MCP and memory. These control what capabilities are made available to the model; they are separate from authorization, and disabling a feature does not delete historical results. Network search is enabled by default and uses read-only web tools as described in [Network search](../guides/webui-network-search.md).

## Audit and verification

Inspect tool calls and their results in chat; expand collapsed details when diagnosing failures. The Controller audit log records native tool activity, and jobs/sessions expose ongoing execution. A successful API response means the tool returned a result, not necessarily that the requested external operation achieved its goal. Verify writes, remote job status and deployment health independently. See [Audit log](../guides/audit-log.md).
