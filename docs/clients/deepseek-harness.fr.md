<!-- i18n-source-sha256: 9deaf97f0af15e7af335b40fcf9fe8bc468623d1947e6f8c9afaf7dfaebcc036 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` peut être installé directement dans un profil Web DeepSeek Harness. Le repository fournit un bridge DSH qui conserve toute la surface d’outils LSM, associe chaque DSH Session à une identité logical-session v4 stable et ajoute **Live Workspace** comme vue native de conversation DSH. LSM reste l’autorité de tout l’état d’exécution : machines local/remote, logical Sessions et Goal Plans, terminaux persistants, jobs, browser sessions, Dynamic MCP, file links, audit et timeline Live Workspace.

## Topologie recommandée

Exécutez de préférence DSH et LSM directement sur la même machine. Chaque DSH Session utilise sa propre connexion MCP LSM et se connecte par défaut à `127.0.0.1:8765/mcp`.

```text
DSH Web
  |
  | one LSM MCP connection per DSH Session
  | 127.0.0.1:8765/mcp
  v
local-shell-mcp :8765
  |-- local execution = this LSM host
  |-- /mcp
  |-- /remote/*
  |-- /ui
  |-- Live Workspace / audit / browser / jobs / links
  |
  +--> Remote Workers
```

Dans cette topologie, la machine qui exécute LSM est la cible LSM `local`. Si LSM tourne dans un container, `local` désigne ce container, pas automatiquement le host DSH. LSM écoute par défaut sur `0.0.0.0:8765` tandis que le bundle DSH utilise loopback ; avec réseau, firewall, public URL et authentification correctement configurés, le même controller peut aussi servir Remote Workers et autres clients externes.

## Installation

Démarrez d’abord LSM :

```bash
local-shell-mcp --mode mcp
```

Installez ensuite le package npm DSH dédié dans le profil Web DSH :

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Le package npm DSH utilise la même version de release que LSM. Pour développer depuis un checkout, installez le répertoire courant :

```bash
dsh plugin --profile web add .
```

Le bundle charge `local-shell-mcp-dsh` depuis `cordis.patch.yml`. DSH reçoit les outils LSM orientés modèle sous le namespace MCP normal, par exemple :

```text
mcp__lsm__run_shell
mcp__lsm__file_read
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__mcp_tool_search
mcp__lsm__session_manage
mcp__lsm__plan_manage
...
```

Le bridge conserve volontairement tout le catalogue LSM, y compris Remote Workers. L’outil interne app-only `live_workspace_reconnect` est réservé au bridge et n’est pas exposé au modèle. Pour réduire les outils visibles, appliquez ensuite `ctx.tools.restrict()` côté DSH plutôt que de retirer des capacités du bundle LSM.

## Liaison DSH Session et LSM logical Session

L’intégration repose sur le runtime logical-session v4. Chaque DSH Session possède son propre client MCP Streamable HTTP upstream, et le bridge envoie une session-affinity opaque et déterministe dérivée de l’id DSH Session, produisant cette chaîne d’identité stable :

```text
DSH Session A
  -> stable LSM session affinity A
  -> v4 MCP session key A
  -> LSM logical Session / active run A
  -> Live Workspace A

DSH Session B
  -> stable LSM session affinity B
  -> v4 MCP session key B
  -> LSM logical Session / active run B
  -> Live Workspace B
```

L’activité de conversations DSH différentes ne se mélange donc pas dans une même timeline Live Workspace. Un redémarrage DSH recrée le transport MCP avec la même affinity ; la logical Session et l’active run restent attachés tant que le controller LSM possède la Session. Le bridge ping aussi périodiquement les clients MCP actifs afin que le cleanup idle normal de LSM ne coupe pas les longues conversations.

## Live Workspace dans DSH

Le plugin navigateur DSH ajoute **Live Workspace** à `conversation.view` et réutilise directement l’implémentation v4 existante. La vue est limitée à la DSH Session courante et affiche logical Session, Plan/Goal state, Activity, terminaux, fichiers, diff, jobs, remotes et audit. **Ask** et Goal auto-continuation reviennent dans la même conversation DSH. Les credentials Live Workspace sont obtenues server-side par le DSH host via la connexion MCP propre à cette Session, jamais placées dans la conversation ni dans un tool result visible par le modèle.

## Pourquoi HTTP plutôt que stdio

Remote Workers dépend de plus que des MCP tools : les routes HTTP `/remote/*` du controller gèrent registration, polling, heartbeats, result delivery et transfer traffic. Un child process stdio-only casserait ce service plane et créerait un second domaine d’état. Le service HTTP LSM déjà actif garde une seule autorité pour Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions et Live Workspace.

## Configuration

Le bridge DSH Host accepte les variables suivantes :

| Variable | Défaut | But |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | Endpoint LSM Streamable HTTP MCP utilisé par DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Valeur complète optionnelle du header `Authorization`, par ex. `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout par tool call en millisecondes. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Intervalle ping pour préserver l’identité MCP per-Session longue durée ; minimum 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Origine LSM accessible par le navigateur si différente de l’origine MCP côté Host. |

Les deployments same-host n’ont normalement pas besoin de header authorization car le bypass localhost de LSM est activé par défaut. N’exposez pas un service LSM non authentifié sur un réseau public. Pour un controller distant protégé, configurez endpoint et bearer token :

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Le bridge envoie des upstream headers fixes ; il n’exécute pas de flow OAuth interactif authorization/refresh pour DSH.

### Navigateurs DSH Web distants

`DSH_LSM_MCP_URL` est résolu par le process **Host** DSH, mais les requêtes API Live Workspace s’exécutent dans le navigateur utilisateur. Si DSH est hébergé à distance et que l’URL loopback LSM est inaccessible depuis le navigateur, définissez une origine LSM accessible :

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Le token Live Workspace continue d’autoriser ces requêtes API navigateur.

## Remote Workers

Remote Worker mode reste entièrement disponible via DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` et les outils LSM ordinaires avec `machine` utilisent le même controller et le même état remote-worker que les autres clients. Pour des workers externes au host controller, configurez public URL et exposition réseau LSM normalement ; DSH peut continuer d’utiliser le MCP loopback.

## Cycle de vie et pannes

Le bundle ne lance aucun autre process LSM. Il peut démarrer alors que LSM est indisponible : la connexion catalogue reconnecte avec backoff et synchronise les outils quand LSM apparaît. Les tool calls modèle ne sont pas replay automatiquement après une panne transport ambiguë afin d’éviter une double exécution des appels mutatifs. Affinity stable et keepalive gèrent les recréations normales de transport/idle ; un vrai remplacement du controller suit les règles durable Session recovery du deployment. Retirer le plugin supprime seulement l’intégration DSH-side :

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

Cela n’arrête pas LSM.

## Vérifier l’installation

Inspectez le profil DSH composé :

```bash
dsh --profile web --dump-config
```

La sortie doit contenir une ligne similaire avec `id: local-shell-mcp`, `name: local-shell-mcp-dsh` et `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Une fois LSM online, DSH doit exposer notamment ces outils `mcp__lsm__*` :

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

Dans DSH Web, une conversation non vide expose aussi la vue **Live Workspace**. Si l’intégration manque, vérifiez `DSH_LSM_MCP_URL`, `/healthz`, la reachability de `/mcp`, le log DSH Host et, si seule l’UI embarquée échoue, `DSH_LSM_BROWSER_URL`.
