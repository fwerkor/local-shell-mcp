<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Démarrage rapide

Ce guide démarre un contrôleur LSM et ouvre son interface de navigateur. Le [unified web workspace](web-workspace.md) est l'expérience quotidienne recommandée ; il s'agit d'une pile de discussion facultative déployée séparément. ChatGPT, Gemini et d'autres clients MCP externes peuvent se connecter au même contrôleur. Voir [runtime choices and deployment model](../guides/deployment.md).

Le **fichier exécutable unique du Controller** de [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) est recommandé, sans Python, Docker ou dépôt de sources. Exemple pour **Linux x86_64** ; autres systèmes : [installation binaire](../installation/binary.md).

## Prérequis

- Exécutable compatible et `curl` (exemple Linux x86_64).
- HTTPS public seulement pour les utilisateurs distants ou clients MCP externes.
- Répertoire de travail dédié et limité.
- PIN administrateur OAuth fort et secret JWT aléatoire.

!!! warning
    Le modèle connecté peut agir sur le workspace configuré. Exécutez le service dans un container ou une VM jetable et évitez de monter des ressources de contrôle de l’hôte.

## 1. Télécharger et configurer le binaire

Téléchargez le fichier unique et générez un secret JWT :

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Créez `.env` et remplacez le PIN et secret JWT d’exemple (utilisez `openssl rand -hex 32`). Le binaire **ne charge pas automatiquement** `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Démarrer le serveur

Démarrez directement l’exécutable :

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Vérifiez depuis un autre terminal :

```bash
curl -i http://127.0.0.1:8765/healthz
```

La réponse attendue est HTTP `200`. Pour un service permanent utilisez un superviseur et un compte restreint.

## 3. Exposer en HTTPS

Pour un accès distant, utilisez un serveur public ou un proxy inverse HTTPS (Caddy, Nginx, Traefik). Transmettez tout le site, y compris les transferts, vers :

```text
http://127.0.0.1:8765
```

Vérifiez HTTPS :

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel est déconseillé** pour les transferts de fichiers : les téléversements du client peuvent être lents. Préférez un serveur public ou un proxy inverse/redirection de port. Gardez OAuth actif sur les points publics. Option : [Docker](../installation/docker.md).

## 4. Ouvrez l'espace de travail du navigateur

Ouvrez la connexion du contrôleur :

```text
https://votre-public-host.example.com/ui
```

Pour le chat, les projets et les pages de contrôle intégrées, suivez le [unified web workspace guide](web-workspace.md). L'interface Web légère d'origine est disponible lorsque le chat n'est pas installé.

## 5. Vérifier en sécurité l’accès aux outils

Demandez au modèle :

```text
Utilise local-shell-mcp. Appelle d’abord environment_get, puis liste la racine du workspace. Ne modifie pas encore les fichiers.
```

Outils de lecture seule attendus :

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Commencer par une tâche de code bornée

Une bonne première tâche :

```text
Inspecte ce repository, résume la structure du projet, exécute la suite de tests existante si elle est évidente et ne modifie aucun fichier.
```

Une fois la connectivité confirmée, donnez des instructions plus précises :

```text
Corrige le test en échec. Lis d’abord les fichiers concernés, applique le patch minimal, exécute le test ciblé puis affiche git diff. Ne fais pas de commit avant mon approbation.
```

## Mise à jour

Remplacez le binaire puis redémarrez le Controller :

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Pour Docker Compose, mettez à jour le conteneur ; pour les sources : [guide Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Pages suivantes

| Besoin | Page |
|---|---|
| Comprendre les choix de runtime et de client | [Choix de runtime et modèle de déploiement](../guides/deployment.md) |
| Exécuter avec Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Exécuter depuis VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Exécuter avec un binary de release | [Runtime binary autonome](../installation/binary.md) |
| Exécuter avec Python ou un source checkout | [Python runtimes](../installation/python.md) |
| Utilisez l'interface de chat et de contrôle unifiée | [Unified web workspace](web-workspace.md) |
| Ajouter Gemini Spark en tant que client | [Gemini Custom Apps](gemini-spark.md) |
| Ajouter ChatGPT comme client | [ChatGPT connector](chatgpt-connector.md) |
| Choisir les outils et écrire de meilleurs prompts | [Modes d’utilisation](../guides/usage-patterns.md) |
| Connecter une machine HPC, NPU/GPU ou NAT | [Workers distants](../guides/remote-workers.md) |
| Comprendre tous les outils MCP | [Référence des outils](../reference/tools.md) |
