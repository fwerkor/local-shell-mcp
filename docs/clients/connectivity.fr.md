<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Connectivité réseau

Les MCP client HTTP situés hors de la machine ont besoin d’un HTTPS origin accessible. Cette page traite du routage réseau, pas du choix du runtime.

Le client endpoint se termine normalement par `/mcp` :

```text
https://your-public-host.example.com/mcp
```

Le réglage public base URL du serveur contient uniquement l’origin :

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

N’incluez pas `/mcp` dans cette base URL.

## Options de connectivité

**Recommandé:** Pour un accès public, déployez sur un serveur public ou faites transiter le trafic par un serveur public avec un proxy inverse HTTPS.

**Déconseillé:** Le débit montant côté client de Cloudflare Tunnel peut être très faible et rendre les envois et transferts de fichiers difficilement utilisables. À réserver aux cas où un serveur public ou un relais n'est pas possible.


| Option | Quand l’utiliser |
|---|---|
| Caddy | TLS automatique simple |
| Nginx ou Nginx Proxy Manager | Infrastructure Nginx existante |
| Traefik | Routage container-native existant |
| Relais via serveur public | Pour un accès public, déployez sur un serveur public ou faites transiter le trafic par un serveur public avec un proxy inverse HTTPS. |
| Cloudflare Tunnel (déconseillé) | Relais via serveur public ; Cloudflare Tunnel uniquement en dernier recours |

## Chemins

Transmettez l’ensemble de l’origin au serveur en cours d’exécution. Les chemins importants comprennent :

| Chemin | Rôle |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Contrôles de santé |
| `/.well-known/...` | Métadonnées de découverte du client |
| `/oauth/...` | Flux d’autorisation du client |
| `/downloads/...` | Liens facultatifs vers les fichiers générés |
| `/join/...`, `/remote/...` | Flux remote-worker facultatif |

## Comportement du proxy

Le proxy doit préserver les chemins, transmettre les request bodies, prendre en charge les responses longues et éviter des timeouts trop courts.

## Vérifications

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Erreurs courantes

| Erreur | Correction |
|---|---|
| Utiliser `https://host` dans ChatGPT au lieu de `https://host/mcp` | Ajouter `/mcp` uniquement au client endpoint |
| Définir `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Définir uniquement l’origin |
| Router uniquement `/mcp` | Router tout l’origin afin que la découverte et l’autorisation fonctionnent aussi |
| Utiliser un host runtime avec un workspace trop large | Utiliser un workspace étroit ou Docker |

## Combinaisons suggérées

| Runtime | Modèle réseau |
|---|---|
| Docker Compose sur un serveur | Proxy inverse HTTPS |
| Docker Compose sur une machine domestique | Relais via serveur public ; Cloudflare Tunnel uniquement en dernier recours |
| VS Code extension sur un portable | Relais via serveur public |
| Binary sur une VM | Reverse proxy sur la VM ou à la périphérie du réseau |
| Serveur de développement Python/source | Généralement localhost uniquement |
| Stdio mode | Aucun chemin HTTP ; utiliser un MCP client local |
