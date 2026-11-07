<!-- i18n-source-sha256: a9820f08198cf8e823f59550928c07346f9669f2dbec46d3b8cd523c34034e01 -->
# Démarrage rapide

Ce guide démarre un contrôleur LSM et ouvre son interface de navigateur. Le [unified web workspace](web-workspace.md) est l'expérience quotidienne recommandée ; il s'agit d'une pile de discussion facultative déployée séparément. ChatGPT, Gemini et d'autres clients MCP externes peuvent se connecter au même contrôleur. Voir [runtime choices and deployment model](../guides/deployment.md).

## Prérequis

- Docker Engine avec Compose v2.
- Un point de terminaison HTTPS public si des utilisateurs distants ou des clients MCP externes doivent se connecter.
- Un répertoire de workspace dédié.
- Un OAuth admin PIN et JWT secret longs et aléatoires.

!!! warning
    Le modèle connecté peut agir sur le workspace configuré. Exécutez le service dans un container ou une VM jetable et évitez de monter des ressources de contrôle de l’hôte.

## 1. Cloner et configurer

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Modifiez `.env` :

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Démarrer le serveur

```bash
mkdir -p workspaces/default
docker compose up -d
```

Vérifiez l’état :

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Une réponse saine renvoie HTTP `200`.

## 3. Exposer en HTTPS

**Recommandé:** Pour un accès public, déployez sur un serveur public ou faites transiter le trafic par un serveur public avec un proxy inverse HTTPS.

**Déconseillé:** Le débit montant côté client de Cloudflare Tunnel peut être très faible et rendre les envois et transferts de fichiers difficilement utilisables. À réserver aux cas où un serveur public ou un relais n'est pas possible. Configure `CLOUDFLARE_TUNNEL_TOKEN` in `.env` only when choosing the optional tunnel sidecar.

Pour le sidecar Cloudflare Tunnel :

```bash
docker compose --profile tunnel up -d
```

Dans Cloudflare Zero Trust, pointez le public hostname vers :

```text
http://local-shell-mcp:8765
```

Avec Caddy, Nginx, Traefik, Nginx Proxy Manager ou un autre reverse proxy, transférez le trafic HTTPS vers `127.0.0.1:8765` ou vers l’adresse réseau du container.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Si vous utilisez le profil tunnel :

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
