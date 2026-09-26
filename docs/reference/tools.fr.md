<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Référence des outils

Cette page est construite à partir des schémas MCP réels. Exécutez `python scripts/generate-tools-reference.py` après toute modification de la surface publique des tools pour mettre à jour la référence English.

La plupart des outils renvoient un `ToolResult` structuré contenant `ok`, `message` et `data`. `workspace_open` renvoie l’état visible par le modèle utilisé pour rendre la MCP App. La plupart des outils d’exécution et de fichiers acceptent un `machine` optionnel : omettez-le pour le workspace du controller et indiquez-le pour un worker connecté. Les opérations Git utilisent volontairement `run_shell` ou un autre outil shell plutôt que des wrappers Git dédiés.

## Guide de sélection

| Besoin | Tools préférées |
|---|---|
| Surveiller ou collaborer avec l’exécution dans ChatGPT | `workspace_open` |
| Inspecter un environnement | `environment_get`, `file_tree`, `file_read` |
| Exécuter une commande courte ou une opération Git | `run_shell` |
| Exécuter une tâche interactive ou longue | `shell_start` or `job_start` |
| Modifier précisément des fichiers | `file_edit` or `file_patch` |
| Transférer un fichier ou dossier | `remote_transfer` |
| Découvrir une capability MCP externe | `mcp_tool_search`, then `mcp_tool_inspect` |
| Interagir avec une page | `browser_session`, `browser_snapshot`, then `browser_act` |
| Exécuter une logique browser personnalisée | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Travailler sur une machine distante | utilisez la même tool avec `machine` ; utilisez `remote_*` seulement pour administrer les workers |

## Workspace interactif

### `workspace_open`

Ouvre ou réutilise un Live Workspace qui affiche la Logical Session fournie explicitement. Transmettez le session_id actif renvoyé par session_manage. Le Workspace ne déduit jamais l’identité de la tâche du transport MCP ; transmettez explicitement null lorsqu’aucune Logical Session n’est active.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

## Environnement, Skills et état des tâches

### `environment_get`

Renvoie version, workspace, auth, policy et informations d’environnement localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `skill_list`

Liste les Agent Skills installées sans charger leurs instructions. La surface MCP reste fixe ; l’ajout ou suppression de dossiers Skill apparaît au prochain appel.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Charge une Skill installée avec le nom exact renvoyé par `skill_list`. Renvoie les instructions complètes `SKILL.md` et les paths des fichiers liés.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Lit un fichier texte lié à une Skill installée.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Scanne les fichiers texte du workspace local pour les secrets courants avant commit ou push.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Gère une seule Logical Session durable. start crée une nouvelle tâche et renvoie son session_id. resume poursuit uniquement le session_id explicite fourni par l’utilisateur ou déjà présent dans cette conversation. Toutes les actions sauf start exigent session_id. Actions : start, resume, get, report, finish, cancel, delete. report accepte summary/findings/next/blockers/objective/label ; delete exige une Session terminale.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

Gère le Goal mode facultatif de la Logical Session explicite. Un plan actif déclenche la continuation automatique après 15 minutes sans activité de l’agent, dans la limite de 10 tentatives. session_id doit être le même identifiant durable renvoyé par session_manage. Actions : start, get, update, block, resume, finish, cancel. start exige objective et steps ; finish exige que tous les steps soient completed ou skipped.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

Lit les entrées récentes de l’audit log local.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells et jobs

### `run_shell`

Exécute une commande shell non interactive localement ou sur une machine distante. À utiliser pour build, test, package-manager, Git et inspection devant finir rapidement. Pour les processus longs, interactifs ou streaming, utilisez `shell_start` ou `job_start`. Les champs optionnels purpose/explanation permettent d’indiquer pourquoi la commande est exécutée.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `run_python`

Écrit et exécute un petit script Python localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `shell_start`

Démarre un shell interactif persistant localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `shell_send`

Envoie une entrée à une session shell persistante locale ou distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `shell_read`

Lit le output récent d’une session shell persistante locale ou distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `shell_stop`

Termine une session shell persistante locale ou distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `shell_list`

Liste les sessions shell persistantes localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `job_start`

Démarre un job long tracké localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `job_list`

Liste les jobs trackés localement ou sur une machine distante. Les jobs actifs sont renvoyés en premier ; `limit` est borné entre 1 et 1000.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `job_tail`

Lit le output récent d’un job local ou distant tracké.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `job_stop`

Arrête un job local ou distant tracké.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `job_retry`

Redémarre un job local ou distant tracké qui s’est arrêté ou terminé.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

## Fichiers et transferts

### `file_list`

Liste fichiers et dossiers localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_tree`

Renvoie un arbre de dossiers compact localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_glob`

Trouve des paths par glob localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_grep`

Recherche dans le contenu des fichiers localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_read`

Lit un fichier ou une liste de fichiers localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `image_view`

Affiche un PNG, JPEG, GIF ou WebP comme contenu image MCP natif localement ou sur une machine distante. Préférez-le à `file_read` lorsqu’une inspection visuelle est nécessaire. Les images distantes réutilisent le protocole de transfert existant, donc le worker n’a pas besoin d’un RPC spécifique aux images.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_write`

Écrit un fichier texte UTF-8 localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_edit`

Applique un ou plusieurs edits de texte exacts à un fichier local ou distant. Chaque edit contient old, new et `replace_all` optionnel ; old doit correspondre exactement, whitespace et indentation compris.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_delete`

Supprime un fichier ou dossier local ou distant. `recursive=false` supprime les fichiers ou dossiers vides ; `recursive=true` est requis pour les dossiers non vides et doit être utilisé avec prudence.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `file_patch`

Vérifie et applique un unified diff ou une envelope file_patch localement ou à distance.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `remote_transfer`

Démarre un job suivi qui copie un fichier ou répertoire entre le controller et des machines distantes. Les uploads distants utilisent des chunks raw-binary reprenables ; gérez le transfert avec `job_list`, `job_tail`, `job_stop` et `job_retry`.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Au moins l’un de `source_machine` et `destination_machine` doit être fourni. Les endpoints omis désignent le workspace du controller ; la source peut être un fichier ou un répertoire.

### `link_create`

Crée une URL temporaire accessible par browser pour un fichier local. Par défaut la réponse force un téléchargement attachment ; mettez `inline=true` pour un rendu direct dans le browser ou une image Markdown. Les liens sont des bearer URLs publiques protégées par token haute entropie, TTL, limite optionnelle de téléchargements et révocation explicite.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Liste les URLs de téléchargement de fichiers locaux générées.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Révoque une URL de téléchargement de fichier local générée.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Gateway MCP dynamique

### `mcp_manage`

Enregistre, liste, récupère, active, désactive, refresh, supprime ou met à jour l’environment/headers isolés de serveurs MCP dynamiques. Utilisez transport `stdio` avec command/args/cwd, ou `streamable_http` avec url. Les valeurs secret env/header sont persistées en privé et jamais renvoyées.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Recherche des résumés légers cacheés de tools de serveurs MCP dynamiques activés. Les tools dynamiques restent hors de `tools/list` de ce serveur ; utilisez le nom `<server>:<tool>` renvoyé avec `mcp_tool_inspect` avant de l’appeler.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Renvoie le schema complet cacheé d’une tool MCP dynamique nommée `<server>:<tool>`. Refresh le server avec `mcp_manage` si son cache est stale.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Appelle une tool MCP dynamique cacheée nommée `<server>:<tool>`. Découvrez-la avec `mcp_tool_search`, puis inspectez son schema avec `mcp_tool_inspect`. Les connexions MCP externes ne sont ouvertes que pendant cet appel.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Démarre, liste, ferme ou nettoie des sessions browser persistantes de haut niveau localement ou à distance. `start` peut ouvrir une URL, réutiliser un `profile_id` persistant ou charger `storage_state_path` ; `close` peut sauvegarder storage state.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `browser_snapshot`

Capture une page browser persistante : title, URL, texte visible borné, éléments interactifs avec refs courtes stables comme `e1`, erreurs récentes page/network et path optionnel de screenshot. Utilisez directement les refs comme targets `browser_act` jusqu’à navigation ou nouveau snapshot.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `browser_act`

Exécute des actions structurées dans une session browser persistante. Supporte navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text et wait_for_url. `target` peut être une ref `browser_snapshot` comme `e1` ou un sélecteur CSS. Utilisez `browser_run_script` seulement si ces actions de haut niveau ne suffisent pas.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

### `browser_run_script`

Exécute un script Python Playwright complet localement ou sur une machine distante.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.

## Automatisation GUI du bureau

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Administration des remote workers

### `remote_manage`

Gère les remote workers avec action=invite, list, revoke ou rename. invite accepte name/workdir/ttl_s ; revoke exige machine ; rename exige machine et new_name.

| Paramètre | Type | Requis/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session de cet appel d’outil. Pendant le travail sur la tâche, transmettez le session_id renvoyé par session_manage. Utilisez null uniquement lorsqu’aucune Logical Session n’est active. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Lorsque `machine` est fourni, l’appel requiert aussi `remote:use` et s’exécute via le protocole remote worker.
