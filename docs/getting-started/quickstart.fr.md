<!-- i18n-source-sha256: 51bfe29de540492ab1da2df9479464641bb335796b0538357235fac5b4a2e446 -->
# Démarrage rapide

Ce guide utilise Docker Compose comme premier runtime et ChatGPT comme premier client. Ce sont deux choix indépendants : Docker, VS Code extension, binary, Python et stdio sont des options de runtime ; ChatGPT et les clients MCP génériques sont des options de client. Consultez [les choix de runtime et le modèle de déploiement](../guides/deployment.md) pour la vue complète.

## Prérequis

- Docker Engine avec Compose v2.
- Un endpoint HTTPS public si ChatGPT doit se connecter depuis le Web.
- Un répertoire de workspace dédié.
- Un OAuth admin PIN et JWT secret longs et aléatoires.

!!! warning
    Le modèle connecté peut agir sur le workspace configuré. Exécutez le service dans un container ou une VM jetable et évitez de monter des ressources de contrôle de l’hôte.

## 1. Cloner et configurer

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
```

Modifiez `.env` :

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
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

Pour le sidecar Cloudflare Tunnel :

```bash
docker compose --profile tunnel up -d
```

Dans Cloudflare Zero Trust, pointez le public hostname vers :

```text
http://local-shell-mcp:8765
```

Avec Caddy, Nginx, Traefik, Nginx Proxy Manager ou un autre reverse proxy, transférez le trafic HTTPS vers `127.0.0.1:8765` ou vers l’adresse réseau du container.

## 4. Connecter ChatGPT

Utilisez l’endpoint MCP :

```text
https://your-public-host.example.com/mcp
```

Suivez le [guide du connecteur ChatGPT](chatgpt-connector.md) pour terminer OAuth et l’approbation des outils.

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
| Ajouter ChatGPT comme client | [ChatGPT connector](chatgpt-connector.md) |
| Choisir les outils et écrire de meilleurs prompts | [Modes d’utilisation](../guides/usage-patterns.md) |
| Connecter une machine HPC, NPU/GPU ou NAT | [Workers distants](../guides/remote-workers.md) |
| Comprendre tous les outils MCP | [Référence des outils](../reference/tools.md) |
