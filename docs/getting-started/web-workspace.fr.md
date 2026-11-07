<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
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

1. [Install and start an LSM Controller](quickstart.md) avec OAuth, un espace de travail correctement isolé et un stockage d'état persistant `file` ou `redis`. Installez Docker Compose et clonez le référentiel sur l'hôte exécutant la pile Web.
2. Fournissez **deux origines HTTPS sur le même site**, telles que `https://lsm.example.org` pour le contrôleur et `https://chat.example.org` pour l'espace de travail. Le service de chat n'est pas exposé directement sur un réseau non fiable.
3. Générez un secret de pont avec `openssl rand -hex 32`. Configurez ces variables d'environnement sur le **service Controller**, à l'aide de ce secret, puis redémarrez-le :

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Lors de la récupération du référentiel, configurez la pile Web facultative. Utilisez un fichier d'environnement privé ou exportez les valeurs indiquées ci-dessous ; générer des secrets forts uniques, et ne les commettez pas :

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Rendu la configuration privée, puis créez et démarrez la pile de discussion déployée séparément :

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Lors de l'utilisation du déploiement Docker Compose racine, les variables du contrôleur ci-dessus appartiennent à la racine `.env` et sont transmises au conteneur. Les valeurs du service de discussion peuvent être fournies via des exportations shell ou un fichier d'environnement privé. Le conteneur Controller doit être accessible à partir du conteneur de discussion à `http://local-shell-mcp:8765` sur le réseau Docker nommé. Portez le proxy inverse `127.0.0.1:3080` vers l'origine HTTPS du chat, conservez l'hôte externe et suivez le [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) dans le référentiel. La pile Web exécute Node.js, MongoDB, Meilisearch et SearXNG ; ils ne sont **pas** inclus dans les travailleurs. Ce déploiement distinct n'est pas démarré par un simple `docker compose up -d` à la racine du référentiel.

## Connectez-vous et utilisez le chat

1. Ouvrez `https://lsm.example.org/ui`, authentifiez-vous à l'aide de la connexion **LSM Controller** et suivez le transfert unique dans l'espace de travail Web. Vous ne créez pas de deuxième compte utilisateur LibreChat.
2. Configurez un fournisseur LLM disponible ou un point de terminaison de modèle pour le service de chat. L'espace de travail fournit l'interface de discussion et le pont d'outils ; **il n'inclut pas de modèle ni de crédits API**.
3. Créez une conversation. Les outils de recherche Web et LSM sont activés par défaut, sous réserve des autorisations du contrôleur. Utilisez les contrôles **Web**, **LSM**, **External MCP** et **Memory** par conversation selon vos besoins.
4. Commencez par une requête en lecture seule : "Vérifiez l'état du contrôleur et répertoriez la racine de l'espace de travail. Ne modifiez pas les fichiers. "
5. Accédez à **Fichiers**, **Terminaux**, **Desktop**, **Sessions**, **Remotes** ou **Audit** pour une inspection et un contrôle directs.

Les téléchargements de chat (jusqu'à 32 Mio) sont stockés dans l'espace de travail du contrôleur et leurs chemins absolus sont fournis au modèle. Les téléchargements via le navigateur n'accordent pas d'autorisations de fichiers supplémentaires. Les appels aux outils orientés modèle passent par l’autorisation LSM, l’audit et le routeur du travailleur distant.

## MCP externe, sécurité et données

Utilisez la barre latérale MCP de l’espace de travail pour gérer les serveurs MCP externes imbriqués. Cela prend en charge les serveurs stdio locaux et les serveurs HTTP, y compris les variables d'environnement privées distinctes et les en-têtes de requête. Les secrets ne sont pas renvoyés au navigateur. Le bouton de discussion **External MCP** permet la recherche, l'inspection et l'invocation d'outils imbriqués ; il n'accorde pas le modèle `mcp_manage` lorsque les outils LSM natifs sont désactivés. La gestion de l'interface utilisateur est protégée par l'autorisation normale du contrôleur.

Les messages de discussion, les projets et les archives sont stockés côté serveur dans MongoDB de la pile Web ; la recherche utilise Meilisearch. Le contrôleur possède séparément les autorisations des outils, les identités des travailleurs, l'état de la session et l'audit. Sauvegardez les deux magasins de données si vous devez conserver tout l'historique. Le backend de chat est mono-utilisateur sous la connexion LSM ; n’exposez pas son API interne ou ses bases de données au public.

L'interface utilisateur est une application de niveau supérieur, **pas une iframe**. Si le service de discussion facultatif n'est pas configuré, `/ui` continue de servir l'interface Web LSM d'origine. Les clients natifs OpenTUI et externes restent pris en charge.

## Dépannage

- **La redirection reste sur l'interface utilisateur d'origine :** vérifiez `LOCAL_SHELL_MCP_LIBRECHAT_URL`, un backend d'état de contrôleur persistant et le proxy inverse HTTPS de la pile Web.
- **La connexion ou le transfert échoue :** vérifiez exactement le même secret de pont de 32 octets ou plus des deux côtés, correspondant aux origines du même site, au HTTPS et aux horloges du serveur.
- **Le chat se charge mais ne peut pas répondre :** configurez un point de terminaison de modèle réel ou des informations d'identification API et vérifiez les journaux du conteneur de chat.
- **Les outils MCP sont manquants :** vérifiez les étendues du contrôleur et les bascules par conversation ; le registre du serveur imbriqué est distinct de la base de données LibreChat MCP.
- **Les fichiers ou les sessions apparaissent vides :** vérifiez que le chat atteint le contrôleur et l'espace de travail corrects, et inspectez ses journaux d'authentification API.

Pour les détails de mise en œuvre et les mises à jour, consultez [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) et [human interface guide](../guides/human-interface.md).
