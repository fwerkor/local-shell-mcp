<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Espace de travail Web unifié

L'**espace de travail Web LSM unifié** est la méthode recommandée pour utiliser local-shell-mcp au quotidien. Il combine le chat IA, l'historique du projet et le plan de contrôle LSM dans une seule interface réactive, basée sur une interface LibreChat modifiée et vendue. Vous pouvez toujours connecter des clients MCP externes tels que [ChatGPT](chatgpt-connector.md) ou [Gemini](gemini-spark.md).

L'espace de travail est **auto-hébergé et son installation est facultative** : il s'agit d'un service Web distinct, ne faisant pas partie de l'image minimale du contrôleur, de l'exécutable autonome ou du bundle de travail à distance. Les déploiements de contrôleur uniquement conservent l'interface utilisateur du navigateur d'origine et OpenTUI.

## Qu'y a-t-il dans l'espace de travail ?

| Zone | Ce que tu peux faire |
|---|---|
| Chat et projets | Choisissez un modèle configuré, créez des conversations, organisez des projets, recherchez des discussions passées et archivez des conversations. L'historique reste sur le serveur. |
| Présentation du contrôleur | Affichez l’état de santé, l’activité récente et les machines connectées. |
| Fichiers | Parcourez et gérez des fichiers locaux ou distants. |
| Terminaux | Travaillez avec des terminaux persistants sur le contrôleur ou les travailleurs. |
| Bureau | Inspectez et contrôlez les sessions GUI à distance. |
| Séances | Inspectez les tâches LSM durables et leur cycle de vie. |
| Télécommandes | Connectez et administrez les travailleurs sortants. |
| Vérification | Inspectez l’activité de l’outil créé par le modèle. |
| MCP imbriqué | Enregistrez, modifiez, activez, désactivez, actualisez et supprimez les serveurs MCP externes derrière LSM. |

Les routes du contrôleur sont `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` et `/control/audit`. Le chat s'ouvre à `/c/new`. Le gestionnaire MCP LSM contrôle **le registre MCP imbriqué** de LSM ; il ne crée pas de deuxième registre dans LibreChat.

## Déployer la pile de discussion facultative

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Connectez-vous et utilisez le chat

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Les téléchargements de chat (jusqu'à 32 Mio) sont stockés dans l'espace de travail du contrôleur et leurs chemins absolus sont fournis au modèle. Les téléchargements via le navigateur n'accordent pas d'autorisations de fichiers supplémentaires. Les appels aux outils orientés modèle passent par l’autorisation LSM, l’audit et le routeur du travailleur distant.

## MCP externe, sécurité et données

Utilisez la barre latérale MCP de l’espace de travail pour gérer les serveurs MCP externes imbriqués. Cela prend en charge les serveurs stdio locaux et les serveurs HTTP, y compris les variables d'environnement privées distinctes et les en-têtes de requête. Les secrets ne sont pas renvoyés au navigateur. Le bouton de discussion **External MCP** permet la recherche, l'inspection et l'invocation d'outils imbriqués ; il n'accorde pas le modèle `mcp_manage` lorsque les outils LSM natifs sont désactivés. La gestion de l'interface utilisateur est protégée par l'autorisation normale du contrôleur.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Dépannage

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Pour les détails de mise en œuvre et les mises à jour, consultez [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) et [human interface guide](../guides/human-interface.md).
