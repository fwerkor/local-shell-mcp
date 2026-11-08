<!-- i18n-source-sha256: f769f579039e6eae80c7c955b80248ae0919448b2f5ca18ea4588ee66b0beba1 -->
# Runtime Docker Compose

Le [binaire unique](binary.md) est recommandé ; Docker Compose reste utile pour les conteneurs isolés.

C’est un choix de runtime. Il peut être connecté à ChatGPT, à un MCP client HTTP générique ou rester local pour les tests.

## Ce que contient l’image Docker

L’image repose sur python:3.12-slim et ne fournit que les utilitaires essentiels. Les toolchains de développement, Playwright/navigateurs et suites bureautiques ne sont pas préinstallés.

Catégories incluses :

| Catégorie | Exemples |
|---|---|
| Shell et inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git et credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | Non inclus ; à installer au besoin |
| Python | Python 3.12, pip, virtualenv |
| JavaScript/TypeScript | Non inclus ; à installer au besoin |
| Autres langages | Non inclus ; à installer au besoin |
| Browser automation | Non inclus ; à installer au besoin |
| Outils documentaires | Non inclus ; à installer au besoin |

Le contenu exact de l’image est une couche de commodité, pas une API stable. Les dépendances propres au projet doivent rester dans le workspace ou les scripts de build du projet.

## Exécution locale de base

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Le token CLI brut reste uniquement dans le `.env` appartenant à l’hôte (mode `0600`). Compose ne transmet au conteneur que son vérificateur SHA-256. Ainsi, `lsm call` peut s’authentifier à travers le pont du port publié par Docker sans exposer de token privilégié réutilisable aux processus shell gérés dans le conteneur.

Le fichier Compose par défaut lie le service à localhost :

```text
127.0.0.1:8765 -> container:8765
```

Cela convient aux tests locaux et à un reverse proxy exécuté sur le même host.

## Layout du workspace

Le runtime Compose par défaut monte :

| Path ou volume host | Path container | Rôle |
|---|---|---|
| `./workspaces/default` | `/workspace` | Workspace contrôlé visible des tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | État persistant des credentials Git/GitHub/SSH/GPG |

Utilisez un répertoire de workspace par trust boundary. Ne montez pas tout votre home directory simplement par commodité.

## Réglages publics requis

Pour ChatGPT ou un autre MCP client HTTP public, configurez `.env` :

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Générez un JWT secret avec une commande telle que :

```bash
openssl rand -hex 32
```

L’URL MCP publique est :

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

**Déconseillé:** Le débit montant côté client de Cloudflare Tunnel peut être très faible et rendre les envois et transferts de fichiers difficilement utilisables. À réserver aux cas où un serveur public ou un relais n'est pas possible. Pour un accès public, déployez sur un serveur public ou faites transiter le trafic par un serveur public avec un proxy inverse HTTPS. ([network connectivity](../clients/connectivity.md))

Le fichier Compose inclut un service `cloudflared` optionnel derrière le profile `tunnel`. Il exécute le tunnel à côté du MCP server.

Configurez `.env` :

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Démarrez les deux services :

```bash
docker compose --profile tunnel up -d
```

Dans Cloudflare Zero Trust, routez le public hostname vers :

```text
http://local-shell-mcp:8765
```

Il s’agit de Cloudflare Tunnel, pas de Cloudflare Access. `local-shell-mcp` continue de gérer son propre OAuth pour ChatGPT.
Le service Compose fait confiance aux forwarded headers car son port publié est limité à localhost ; cela préserve l’adresse publique de l’appelant pour le rate limiting du OAuth PIN. Si vous exposez directement le port du container, remplacez `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` par les adresses explicites de vos reverse proxies de confiance.

## Reverse proxy sans tunnel sidecar

**Recommandé:** Pour un accès public, déployez sur un serveur public ou faites transiter le trafic par un serveur public avec un proxy inverse HTTPS.
Si vous utilisez déjà Caddy, Nginx, Traefik ou Nginx Proxy Manager, gardez le service Compose normal et transférez HTTPS vers :

```text
http://127.0.0.1:8765
```

Le proxy doit transférer ces routes sans retirer les paths :

| Route | Rôle |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | Metadata de ressource OAuth |
| `/.well-known/oauth-authorization-server` | Metadata du serveur d’autorisation OAuth |
| `/oauth/register` | Enregistrement dynamique du client |
| `/oauth/authorize` | Page d’autorisation navigateur |
| `/oauth/token` | Échange de token |
| `/downloads/<token>` | Téléchargements optionnels de fichiers générés |
| `/join/<token>`, `/remote/*` | Bootstrap/polling optionnel du remote worker |

Voir [network connectivity](../clients/connectivity.md) pour les exigences de comportement du proxy.

## Mode full-container

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` garde les opérations filesystem limitées au workspace. C’est le default le plus sûr.

Mettez-le à `true` uniquement lorsque le container est volontairement jetable et que le modèle doit opérer tout son filesystem. L’activation retire les restrictions built-in de command et path denylist.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

N’activez pas full-container mode sur un runtime lancé directement sur le host, comme VS Code extension ou un binary sur votre portable.

## Credentials

Le runtime Docker peut persister les credentials développeur courants dans un volume dédié. C’est utile pour le login GitHub CLI, Git HTTPS credential helpers, `.netrc`, SSH config et l’état GPG.

Traitez le volume de credentials comme sensible. Préférez les deploy keys limitées au repository, tokens fine-grained ou credentials de courte durée. Ne placez pas de credentials personnels larges dans un workspace que le modèle peut lire librement.

Le SSH-agent forwarding est possible en montant le socket de l’agent, mais cela étend la confiance du container à votre agent actif. Utilisez-le uniquement si vous comprenez l’exposition.

## Mises à jour

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Avec tunnel sidecar :

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Après mise à jour, demandez d’abord au client un check read-only :

```text
Utilise local-shell-mcp. Appelle environment_get et exécute file_list sur la racine du workspace. Ne modifie aucun fichier.
```

## Dépannage

| Symptôme | Vérifier |
|---|---|
| `/healthz` échoue localement | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT ne découvre pas les tools | L’URL publique doit finir par `/mcp` ; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` ne doit pas contenir `/mcp` |
| La page OAuth échoue | Admin PIN et JWT secret doivent être définis pour les deployments OAuth publics |
| Les tools ne voient pas les fichiers | Confirmez que le bon répertoire host est monté sur `/workspace` |
| Les browser tools échouent | Confirmez que l’image Playwright est à jour ; essayez `run_shell` pour le browser cible |
| Git auth a disparu | Vérifiez le volume de credentials et que le container recréé utilise le même volume |
