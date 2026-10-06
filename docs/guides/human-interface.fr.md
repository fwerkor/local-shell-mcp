<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Interface humaine

`local-shell-mcp` fournit deux interfaces humaines compatibles au-dessus de la même API de service, du même workspace, registre de terminaux persistants, registre de workers distants et journal d’audit MCP :

- **Web UI** est un tableau de bord natif du navigateur, optimisé pour une inspection opérationnelle rapide.
- **OpenTUI** est l’application complète orientée terminal et reste disponible à la fois dans le navigateur et sous forme de commande de terminal native.

Aucun mode ne crée de control plane séparé. Changer d’interface ne modifie pas les machines connectées, Sessions, jobs, permissions ni données d’audit.

## Démarrer le service

Démarrez `local-shell-mcp` normalement :

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Lorsque ChatGPT affiche les MCP Apps, `workspace_open(session_id=...)` ouvre une vue collaborative flottante de la **Logical Session explicitement sélectionnée**. La Session possède l’état durable de la tâche — objective, progress, Plan et Activity — tandis que Live Workspace ne fait qu’afficher cet état, l’activité en direct et les contrôles humains. Il ne déduit jamais l’identité de la tâche du transport MCP.

Un handoff explicite typique est le suivant :

```text
session_manage(action="start", objective=...)
        -> session_id
... appels d’outils avec logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
nouvelle conversation ChatGPT
l’utilisateur transmet le session_id précédent
session_manage(action="resume", session_id=...)
        -> progress, Plan et Activity récente existants
workspace_open(session_id=...)
        -> vue de la même Session
```

`session_id` est l’unique identité durable de la tâche. Un agent ne doit ni lister, ni déduire, ni sélectionner automatiquement une Session provenant d’une autre conversation. Pour poursuivre le travail dans une nouvelle conversation, l’utilisateur transmet explicitement le `session_id` existant. L’agent doit indiquer le `session_id` actif après start/resume, aux checkpoints de progression significatifs et avant de terminer un turn afin de permettre un handoff manuel. Les Sessions ne sont liées ni à une machine ni à un working directory ; les paramètres ordinaires des outils continuent de choisir les cibles locales/distantes et les paths.

Un Plan `plan_manage` facultatif active le Goal mode de la Session. Si le Plan est active et qu’aucune agent activity n’a lieu pendant 15 minutes, un Live Workspace associé peut demander à ChatGPT de continuer. La continuation reprend le même `session_id` explicite et est limitée à 10 tentatives, acceptées ou refusées. Les Plans blocked, completed et cancelled ne sont pas poursuivis automatiquement ; un Plan active dont tous les steps sont completed ou skipped reste éligible à une continuation de finalisation afin que l’agent repris puisse terminer le Plan. Les contrôles humains pause/resume/cancel modifient le Plan détenu par la Session plutôt qu’un état éphémère du Live Workspace.

## Interface navigateur

Ouvrez :

```text
http://127.0.0.1:8765/ui
```

Pour un déploiement public, utilisez l’origin HTTPS configurée :

```text
https://your-public-host.example.com/ui
```

L’interface navigateur utilise le même serveur OAuth et les mêmes scopes que MCP. Le shell de page et les ressources statiques sont publics afin que l’écran de connexion puisse se charger, tandis que `/api/ui/*` et le WebSocket du terminal OpenTUI restent protégés. Les jetons d’accès sont stockés uniquement dans le session storage du navigateur.

### Choisir une interface

L’écran OAuth propose deux points d’entrée :

- **Open Web UI** autorise puis ouvre le tableau de bord natif.
- **Continue to OpenTUI** autorise puis ouvre l’interface terminal tout en préservant le comportement navigateur précédent.

Après autorisation, le sélecteur de la barre latérale permet de passer de Web UI à OpenTUI sans nouvelle connexion. La page native courante est mémorisée lors d’un passage temporaire vers OpenTUI.

Les routes peuvent être ajoutées aux favoris :

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` et `#/dashboard` sont des alias d’Overview. `#/tui` et `#/opentui` sont des alias de Console.

## Web UI native

La Web UI native interroge l’API d’interface humaine existante toutes les cinq secondes et affiche des contrôles natifs du navigateur plutôt que des cellules de terminal. Elle ne démarre aucun PTY tant qu’OpenTUI n’est pas sélectionné.

### Overview

Overview affiche d’abord les informations opérationnelles les plus prioritaires :

- Santé du controller et version LSM actuelle.
- Nombre de machines en ligne et hors ligne.
- Tracked jobs actifs et sessions de terminal persistantes.
- CPU, mémoire, disque du workspace, load, débit réseau et uptime.
- Alertes issues de l’état des workers, des seuils de ressources, des jobs en échec et des appels MCP en échec.
- Activité MCP récente initiée par le modèle.

### Machines

Machines liste le controller local et les workers distants connectés avec leur état, plateforme, version, répertoire de travail, capacités et informations last-seen.

### Workloads

Workloads regroupe les tracked jobs actifs et les sessions shell persistantes autonomes. La Web UI reste en lecture seule pour ces enregistrements ; utilisez OpenTUI pour la gestion interactive des sessions.

### Activity

Activity regroupe les alertes actuelles et l’activité d’audit MCP récente. Les commandes saisies par un humain et les opérations de fichiers restent exclues du journal d’audit MCP.

## OpenTUI dans le navigateur

La sélection de **OpenTUI** démarre à la demande la même application OpenTUI que le lanceur de terminal natif. La console navigateur conserve :

- Le transport PTY binaire authentifié sur WebSocket.
- Le redimensionnement automatique du terminal et le backoff de reconnexion.
- L’interaction à la souris avec les contrôles OpenTUI.
- Le mode plein écran et des raccourcis clavier sûrs pour le navigateur.
- Les touches de raccourci mobiles et le contrôle explicite du clavier logiciel.
- La prise en charge de SIXEL et des inline images via xterm.js.

Le navigateur ne crée pas de PTY OpenTUI tant que l’utilisateur reste en mode Web UI natif.

## OpenTUI native

Les exécutables release autonomes intègrent le runtime OpenTUI de la plateforme. Conservez uniquement l’exécutable principal, démarrez le service, puis exécutez :

```bash
local-shell-mcp tui
```

La TUI native ne demande pas à l’opérateur humain de se connecter. Dans la configuration Docker Compose documentée, le lanceur réutilise l’identifiant CLI dédié conservé uniquement sur l’hôte pour l’API Human UI en loopback ; les autres configurations split-runtime peuvent utiliser `--token-file`. Les instances OpenTUI lancées depuis le navigateur utilisent un identifiant propre au processus controller, créé à la demande et jamais persisté dans le state directory ni dans le state backend. Un reverse proxy n’obtient aucun de ces bypass locaux simplement parce qu’il se connecte via loopback.

Un checkout des sources peut également exécuter la TUI après installation des dépendances Bun :

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Utilisez `--api-base` uniquement lorsque le service local utilise un port non standard :

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## Écrans OpenTUI

### Dashboard

Dashboard est la vue d’ensemble opérationnelle d’OpenTUI. Les terminaux larges affichent des zones distinctes pour node, workload, alert, activity, informations système et tendances ; les terminaux plus étroits les replient en résumés compacts sans défilement horizontal.

### Files

Files est un gestionnaire de fichiers LSM natif à trois volets pour les machines locales et distantes. Il permet de créer, éditer, renommer, copier, déplacer, coller, supprimer, afficher/masquer les fichiers cachés, actualiser, prévisualiser du texte, prévisualiser des binaires et afficher des miniatures d’images bornées.

### Terminals

Terminals gère les sessions shell persistantes sur les machines locales et distantes. Il prend en charge la saisie de commandes complètes, la saisie interactive raw, le changement de session, la création et l’arrêt de sessions, la sortie récente et un rail d’audit MCP repliable.

### Audit

Audit lit le journal d’audit JSONL borné et prend en charge les filtres node, operation, event, session, search, time-range et sort, ainsi que l’inspection détaillée des enregistrements.

### Remotes

Remotes affiche les workers distants en ligne et hors ligne, leurs capacités, répertoires de travail et métadonnées système. Il peut créer une invitation join à usage unique, renommer un node ou révoquer son identité persistante.

## Navigation OpenTUI

La barre de catégories supérieure et les actions contextuelles du pied de page peuvent être cliquées à la souris dans les terminaux natifs comme dans la console navigateur.

| Touches | Action |
|---|---|
| `Alt+1` … `Alt+5` | Ouvre Dashboard, Files, Terminals, Remotes ou Audit. |
| `F2` … `F6` | Raccourcis de catégorie alternatifs. |
| `F1` | Ouvrir le guide du clavier. |
| `F9` | Actualiser la liste des machines. |
| `Alt+Q` | Quitter le processus OpenTUI natif sans invoquer un raccourci Ctrl réservé au navigateur. |

Terminals utilise `Alt+N` pour une nouvelle session, `Alt+W` pour arrêter la session sélectionnée, `Alt+A` pour basculer son rail d’audit, `Alt+R` pour actualiser et `Alt+Left/Right` pour changer de session. La console navigateur intercepte ces combinaisons avant la navigation ou les menus du navigateur.

## Configuration

| Clé YAML | Variable d’environnement | Valeur par défaut | Rôle |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Monter ou désactiver les interfaces humaines. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Chemin de montage de l’interface navigateur sur le service MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Remplacer la résolution de l’exécutable OpenTUI natif. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Réglage de fond conservé pour les déploiements de console OpenTUI dans le navigateur. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Fermer un PTY OpenTUI navigateur inactif après ce nombre de secondes ; `0` désactive le délai. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Nombre maximal de sessions PTY OpenTUI navigateur simultanées. |

## Notes de packaging

- Les images Docker incluent les ressources Web UI et le runtime OpenTUI natif.
- Les exécutables autonomes intègrent les ressources Web UI et un runtime OpenTUI de plateforme compressé.
- Les wheels Python incluent les ressources navigateur ; OpenTUI native nécessite un exécutable release ou un checkout des sources avec les dépendances Bun installées.
- Les deux interfaces sont servies par le même processus et le même port que MCP ; aucun service web supplémentaire n’est nécessaire.
