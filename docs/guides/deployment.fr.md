<!-- i18n-source-sha256: d699e8855ee01b72db68087e8a5d8f3957c702641e7e6956f268604b8b1f9d2b -->
# Choix du runtime et modèle de déploiement

`local-shell-mcp` a deux décisions complémentaires :

1. **Runtime**: comment le processus serveur s’exécute et quel workspace il contrôle.
2. **Interface** : utilisez le [unified web workspace](../getting-started/web-workspace.md) en option ou connectez un client MCP externe tel que Gemini ou ChatGPT.

L'interface quotidienne recommandée est l'espace de travail web auto-hébergé (chat, projets et pages de contrôle LSM). Il est déployé séparément du contrôleur. Docker, l'extension VS Code, les versions binaires, les installations Python et le mode stdio sont des moyens d'exécuter le contrôleur ; les applications de chat externes restent des clients facultatifs.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose HTTP local uniquement Espace de travail Web unifié
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Une configuration auto-hébergée courante est :

```text
Navigateur -> https://chat.example.com (espace de travail Web unifié)
        -> Contrôleur local-shell-mcp authentifié
        -> espace de travail contrôlé et travailleurs sortants
Client externe facultatif -> https://mcp.example.com/mcp
```

Une configuration avec MCP client local peut être plus simple :

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**Recommandé:** Pour un accès public, déployez sur un serveur public ou faites transiter le trafic par un serveur public avec un proxy inverse HTTPS. **Déconseillé:** Le débit montant côté client de Cloudflare Tunnel peut être très faible et rendre les envois et transferts de fichiers difficilement utilisables. À réserver aux cas où un serveur public ou un relais n'est pas possible. ([Public HTTPS exposure](../clients/connectivity.md))

## Matrice de choix du runtime

| Durée d'exécution | Idéal pour | Limite d'isolement | Source de la chaîne d'outils | Accès MCP externe | Pages |
|---|---|---|---|---|---|
| Docker Composer | La plupart des charges de travail d'agent de codage et des espaces de travail reproductibles | Conteneur | Image du contrôleur Lean ; installer séparément les chaînes d'outils spécifiques à une tâche | Ajouter un proxy ou un tunnel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + side-car tunnel | Déconseillé: Relais via serveur public ; Cloudflare Tunnel uniquement en dernier recours | Conteneur | Image du projet | Relais via serveur public ; Cloudflare Tunnel uniquement en dernier recours | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Démarrer/arrêter le serveur depuis un workspace éditeur | Généralement processus host | Outils host plus executable configuré | Ajouter tunnel/proxy HTTPS externe pour ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts ou VM sans Docker | Host or VM | Outils host plus executable configuré | Ajouter proxy HTTPS ou tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Usage Python-native, debugging, développement | Host virtualenv or VM | Package Python plus outils host | Ajouter proxy HTTPS ou tunnel | [Python install](../installation/python.md) |
| Stdio mode | MCP clients locaux lançant directement des processus | Client process boundary | Outils host plus executable configuré | Inutilisable par ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Matrice de connexion client

| Interface | Nécessite HTTPS public | Utilise `/mcp` | Nécessite OAuth | Durée d'exécution typique |
|---|---:|---:|---:|---|
| Espace de travail Web LSM unifié | Oui pour l'accès à distance ; proxy local également possible | En interne | Connexion LSM | Contrôleur et pile Web séparée |
| Gemini Spark / Applications personnalisées | Oui | Oui | Oui pour un usage public | N'importe quel contrôleur HTTP |
| ChatGPT custom MCP connector | Oui | Oui | Oui pour usage public | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Non | Non | Non | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Généralement non en localhost ; oui entre réseaux | Oui | Recommandé hors localhost | Any HTTP runtime |
| VS Code extension helper flow | Seulement si ChatGPT doit se connecter | Oui lors de la copie URL ChatGPT | Recommandé pour ChatGPT | VS Code-launched runtime |

Voir les codes [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) et [network connectivity](../clients/connectivity.md).

## Ce que contrôle chaque runtime

Chaque runtime lance le même code serveur et expose les mêmes familles d’outils MCP lorsqu’elles sont activées :

- Shell et persistent shell sessions.
- Filesystem, search et patch tools.
- Opérations Git.
- Browser automation via Playwright.
- Audit log et task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle et machine-routed tools.

La différence ne porte pas sur l’API abstraite mais sur l’**operating environment** derrière elle.

| Question | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Où s’exécutent les commandes ? | Dans le container | Généralement sur le workspace host | Dans l’environnement process host ou VM |
| Workspace par défaut ? | Mounted `/workspace` | Dossier VS Code actuel ou path configuré | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Les compilateurs et les navigateurs sont-ils préinstallés ? | Non; installer ce dont la tâche a besoin | Uniquement s'il est installé sur l'hôte | Uniquement s'il est installé sur l'hôte |
| Reset facile ? | Recréer container et volume workspace | Dépend du workspace | Dépend du host/VM |
| Install arbitraire adaptée ? | Oui si jetable | Plus risqué sur host | Plus risqué hors VM |

## Sélection recommandée

Utilisez **Docker Compose** d'abord, sauf si vous avez une raison de ne pas le faire. Il donne une limite de sécurité claire sans nécessiter une grande chaîne d'outils de développement préinstallée.

Utilisez l'**extension VS Code** lorsque le flux de travail démarre à partir d'un éditeur et que vous souhaitez un lanceur local. C'est toujours un runtime. Les clients Web distants ont besoin d’un proxy ou d’un tunnel HTTPS accessible.

Utilisez **standalone binary** lorsque Docker est indisponible mais qu’une VM, container host ou compte dédié fournit déjà la limite.

Utilisez **`pipx` ou source install** pour développer/debugger `local-shell-mcp` ou lorsqu’un environnement Python est plus simple à maintenir.

Utilisez **stdio mode** uniquement avec des MCP clients locaux capables de lancer le processus serveur. Ce n’est pas un déploiement public et ChatGPT web/app ne peut pas l’utiliser directement.

## Règle de l’endpoint public

Pour les clients HTTP MCP externes tels que Gemini et ChatGPT, le point de terminaison MCP est :

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` contient uniquement l’origin :

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

N’ajoutez pas `/mcp` à `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Pages runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Pages client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
