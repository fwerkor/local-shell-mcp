<!-- i18n-source-sha256: 53d1b81800534bc6d5334883b7de74660c988088c66f492ddbd68aced8797379 -->
# Chat hébergé (facultatif)

Hosted Chat est un client de chat BYOK auto-hébergé et d'applications MCP intégré à l'interface humaine de LSM. Il ne s'agit **pas** d'un mode de session logique : les conversations ont des identités indépendantes et peuvent éventuellement attacher une session logique LSM existante. ChatGPT et d'autres clients externes continuent de travailler avec les mêmes sessions et outils LSM.

## Activer

Le chat hébergé est désactivé par défaut. Définir :

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Redémarrez le contrôleur et ouvrez **Hosted Chat** immédiatement sous le sélecteur Web UI/TUI. La fonctionnalité dispose également d’une entrée mobile dans la barre supérieure. L'hôte de discussion utilise l'identité et les étendues LSM OAuth existantes. Le même contrôleur exploite le serveur MCP utilisé par la boucle d'outils du modèle ; Les travailleurs ne peuvent pas lancer l'exécution.

## Profils de modèles

Choisissez **Profils de modèle** pour créer/modifier un profil avec un nom, une URL de base d'API compatible HTTPS OpenAI, un ID de modèle et une clé API facultative. Plusieurs profils peuvent coexister et les conversations peuvent changer de modèle.

Les profils, les conversations, l'historique complet des messages et les résultats des appels d'outils sont **enregistrés sur le serveur** via le backend d'état LSM configuré. Leur portée est liée au principal authentifié. La clé API est chiffrée avec AES-GCM et n'est jamais renvoyée par les points de terminaison de liste de profils ou de détails de profil. Il n'est pas stocké dans le stockage du navigateur, envoyé au modèle sous forme d'invite ni inclus dans les journaux d'audit. L'hôte du chat le transmet uniquement à l'API du modèle choisi.

Le premier déploiement basé sur un fichier crée `hosted-chat-encryption-key` dans le répertoire d'état avec le mode 0600. ** Sauvegardez ce fichier avec les données d'état. Sans cela, les clés API enregistrées ne peuvent pas être déchiffrées.** Si le contrôleur utilise Redis, plusieurs réplicas ou un autre backend à état non-fichier, configurez une clé URL-safe-base64 stable et partagée de 32 octets :

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Ne modifiez pas ce paramètre sans migrer les profils chiffrés. N'utilisez pas le stockage d'état en mémoire lorsque des conversations durables sont requises.

Par défaut, seuls les points de terminaison du modèle HTTPS avec des noms d'hôte DNS sont acceptés ; les points de terminaison locaux/privés et HTTP sont refusés afin de réduire le risque de falsification de requêtes côté serveur. Les administrateurs hébergeant délibérément une passerelle de modèle privé de confiance peuvent adhérer :

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

N’activez pas cette fonctionnalité sur un contrôleur multi-utilisateurs non fiable, sauf si les utilisateurs sont autorisés à contacter les services internes.

## Conversations et applications MCP

Créez une conversation à l'aide d'un profil de modèle enregistré. Chaque tour soumis devient une tâche en arrière-plan appartenant au serveur ; la fermeture du navigateur n'annule pas la tâche. Les appels de texte et d'outil terminés sont contrôlés de manière durable entre les étapes du modèle/outil. Arrêtez explicitement pour interrompre. Au redémarrage du contrôleur, les exécutions interrompues sont marquées comme telles et peuvent être poursuivies dans un nouveau tour, mais les **appels d'outils à résultat inconnu ne sont jamais automatiquement rejoués**.

L’intégralité de l’historique des messages de la conversation est conservée en stockage. Seule une fenêtre récente limitée est envoyée immédiatement au modèle pour contrôler la taille du contexte. Les appels d'outils sont envoyés via le point de terminaison MCP authentifié de LSM, préservant toutes les autorisations d'outils ordinaires et le comportement d'audit/de contrôle en amont.

L’archivage retire les conversations de la liste ordinaire et les enregistre en `.json.zst` avec le codec zstd déjà utilisé par Audit. Elles sont exclues de l’index de recherche normal. **Archived conversations** permet de les retrouver par titre, de les lire sans modification, de les restaurer ou de les supprimer définitivement. L’écriture précède toujours la suppression pour éviter les pertes.

### Conversations longues et compactage du contexte

Tous les messages et résultats d’outils restent conservés sur le serveur. Chaque profil de modèle configure sa fenêtre de contexte : **32 768 tokens** par défaut, de 8 192 à 1 000 000. Une estimation prudente fondée sur UTF-8 tient compte des définitions des outils. Vers **80 %** de la fenêtre, le même modèle résume les anciens tours terminés : objectifs, contraintes, décisions, fichiers, résultats et tâches restantes. Ce résumé est conservé séparément ; seuls le résumé et les messages récents sont transmis au modèle.

Le contexte est réévalué après chaque appel d’outil. **Compact** lance aussi une opération manuelle hors d’un tour en cours. Un échec ne modifie ni le résumé précédent ni l’historique complet. Le nombre de tokens est estimatif ; un tour actif trop volumineux est rejeté explicitement.

Ouvrez **Live Workspace** pour afficher la ressource d'applications MCP `workspace_open` existante de LSM dans une vue intégrée. L'hôte utilise le pont `@modelcontextprotocol/ext-apps` pour le cycle de vie des applications, le renouvellement des informations d'identification, les appels d'outils et les actions homme-agent. Aucun deuxième gestionnaire de fichiers, terminal, audit ou interface utilisateur de travail n'est implémenté.

Le `session_id` facultatif ci-joint permet au chat hébergé d'utiliser et d'afficher une session logique existante ; il ne reclasse pas la session et n'en donne pas la propriété au chat hébergé. Les identifiants de conversation de chat et les identifiants de session logique sont distincts.

## Limites

- Les requêtes de modèle utilisent des complétions de discussion compatibles OpenAI avec l'appel d'outils ; d'autres protocoles de fournisseur nécessitent un adaptateur.
- Les garanties par tour limitent les itérations du modèle et les appels d’outils. Les tâches plus longues peuvent être poursuivies dans un nouveau tour en utilisant l'historique durable.
- La suppression des conversations de chat est explicite. Aucune expulsion automatique de l’historique n’est effectuée.
- Le contrôleur doit être accessible en réseau par son propre client MCP et le navigateur doit être autorisé pour l'API LSM Live Workspace.
