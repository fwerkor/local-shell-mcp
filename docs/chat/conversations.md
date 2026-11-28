# Conversations and projects

## Create and continue a chat

Open a new conversation, choose a channel/model or Agent and enter a message. The chat runs on the Controller and streams updates to the browser. Reloading the page or closing a tab is not equivalent to cancelling execution. Use the stop control to interrupt a run, and inspect the resulting status before starting another operation.

A saved chat retains its model/Agent association. Switch deliberately if you want a different model. A conversation is not a Logical Session: it holds user and model messages, whereas a Logical Session holds a tool-side task objective, progress and plan. Keep the relevant IDs when handing over a long task.

## Organize and find work

Use projects to group related conversations and set shared machine permission defaults. A project can contain multiple separate chats. Move or create chats in the appropriate project rather than assuming that separate conversations share their entire context. The active project can inform the Agent about the conversation's organization.

Tags classify conversations; message bookmarks point to individual messages and allow navigation back to useful results. These are separate from pinning a conversation. Use chat titles, search, archive and unread indicators to maintain a manageable sidebar.

Archiving moves a conversation out of the normal list without deleting its saved history. Restore it from the archive interface when needed. Deleting a conversation is destructive; do not use deletion as a substitute for archiving. The current implementation uses SQLite conversation state; do not assume the old compressed Hosted Chat archive format.

## Message operations and running tasks

Available message controls depend on the message and its current execution state. Edit or retry a turn when appropriate, or delete a selected user/assistant turn when no longer needed. Deletion changes the saved conversation history and may affect later context; it cannot undo shell commands, remote writes, Git pushes or other external side effects.

When retrying a failed run, read the detailed error and inspect already completed tool calls first. If a write may have succeeded before a disconnection, verify external state before repeating it. If another message is queued or a generation is already running, use the displayed controls and status rather than assuming multiple turns execute concurrently in the same chat. The queued-message panel lets you inspect pending turns; the steer control attempts to inject guidance at a safe boundary, after currently executing tools finish. Neither operation rolls back effects of completed tools.

## Attachments, previews and artifacts

Use the attachment control to upload files or supported images. The upload implementation limits individual attachments to 32 MiB, and deployment/proxy request limits may impose a smaller effective limit. Uploaded files are stored on the Controller and can be referenced by the model. Image interpretation requires a model and provider that accept image inputs. An upload is not a grant to access unrelated local or remote files.

When requesting a generated file, specify the intended path, format and content; verify that the result exists before sharing it. Download or preview supported attachments and artifacts from the chat when available. A generated file on a Worker may need transfer to the Controller or a suitable file link. See [File links](../guides/file-links.md).

Artifact rendering can present React, HTML, SVG, Markdown and Mermaid in a side panel rather than only as code. In Agent artifact settings, Normal uses the standard instructions, shadcn/ui adds component-library guidance, and Custom keeps rendering available without the built-in artifact instructions. Treat generated code or rendered content as untrusted; review it before using it outside the preview. File-based Office previews and downloads are distinct from generated UI artifacts.

Do not upload credentials, private keys or documents you are not authorized to send to the selected model provider. Attachment deletion and chat deletion are separate from deleting source files on a machine.

## Preferences

Chat and user preferences such as tool toggles and keyboard shortcuts are managed through the WebUI and persisted on the server where implemented. Open Settings to configure keyboard behavior; distinguish sending a message from inserting a line break. Configure the chat's tool toggles separately from Agent permissions. See [Tools and permissions](permissions.md) and [Memory and context](context.md).

### Automatic conversation naming

In Settings → Chat → Conversations, choose whether to leave chats unnamed, name new chats once, or rename after every completed reply. The default is to name new chats once using the conversation model. You can select a separate model from a configured channel instead. Naming runs only after the primary model finishes its reply; failed or cancelled primary replies do not trigger naming. The title is a short description of the task in the user's language. The naming request is separate from chat context and does not add a chat message.
