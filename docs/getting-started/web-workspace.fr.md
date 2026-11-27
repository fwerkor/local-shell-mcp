<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Quickstart pour le chat via WebUI

L’espace de travail web unifié LSM intègre une fonction de chat intelligent, des projets, des agents, ainsi que les pages opérationnelles du contrôleur. Il est géré par le contrôleur Python, qui utilise son système d’authentification et sa base de données SQLite. Aucun serveur de chat séparé n’est nécessaire. Les clients externes tels que [ChatGPT](chatgpt-connector.md) et [Gemini](gemini-spark.md) sont toujours pris en charge.

## 1. Démarrer le Controller

Suivez les instructions de l’[initiation à l’installation](quickstart.md) pour votre environnement de développement préféré. Assurez-vous que la fonctionnalité WebUI est activée, et utilisez un stockage persistant. Les paramètres par défaut sont les suivants :

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Après avoir exporté votre environnement de service, lancez le contrôleur.

```sh
local-shell-mcp --mode mcp
```

Pour la version à une seule file, utilisez l’exécutable téléchargé. Le contrôleur installé sert de serveur pour le frontend compilé ; le chaîne d’outils JavaScript est nécessaire uniquement pour les builds source. Veuillez consulter les instructions de build du WebUI à l’adresse [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Ouvrir l’espace de travail dans le navigateur

Ouvrez la page `http://127.0.0.1:8765/ui` depuis l’hôte Controller. Ou bien, utilisez le URL HTTPS configuré, qui se termine par `/ui`. Connectez-vous avec l’authentification LSM configurée pour cette déploiement. Utilisez l’accès HTTPS pour l’accès à distance. Les pages de chat et de contrôle partagent la même origine.

## 3. Ajouter un canal de modèle

Ouvrez le sélecteur de modèles et la gestion des canaux. Ajoutez un canal API ou connectez un compte compatible. Pour un endpoint OpenAI compatible, entrez un nom de canal, choisissez « Chat Completions », indiquez l’URL de base de l’API ainsi que les informations de connexion nécessaires. Vous pouvez également sélectionner un modèle manuellement ou fournir une ID de modèle connue. Sauvegardez la configuration et choisissez un modèle.

Pour un service d’inférence local, il est nécessaire d’utiliser une adresse accessible depuis le contrôleur, et non simplement depuis votre navigateur. Par exemple, `http://127.0.0.1:8080/v1` est une adresse appropriée si le service d’inférence écoute sur cette adresse, au sein du nom de domaine réseau du contrôleur. Pour plus d’informations sur les protocoles, l’autorisation des comptes, la découverte des modèles et les limites liées au contexte, consultez [Channels and models](../chat/channels.md).

## 4. Exécuter une première tâche

Lancez une conversation et posez une question simple pour vérifier la connectivité du modèle. Ensuite, essayez d’utiliser un outil de lecture uniquement.

```text
Énumérez les fichiers situés dans le répertoire racine du workspace du contrôleur.
Dites-moi quelle machine vous avez inspectée, et résumez les résultats de cette inspection.
Ne modifiez pas les fichiers, ni ne effectuez de transactions de stockage des données.
```

Vérifiez le résultat réel de l’outil utilisé. Si un outil manque, vérifiez les options liées à cet outil dans le chat, les paramètres de l’agent et les autorisations de la machine. Utilisez un agent préchargé pour les tâches répétitives, et configurez son accès de manière explicite. Voir [Outils et autorisations](../chat/permissions.md).

![Chat via l’interface WebUI, avec une conversation de démonstration](../assets/chat/chat-workspace.png)

Les captures d’écran présentées dans cette guide et sur les pages suivantes ont été réalisées à l’aide d’un contrôleur isolé, avec un modèle de démonstration. Ces captures d’écran ne contiennent aucune information concernant les identifiants ou les conversations utilisés dans le produit réel. Les labels de l’interface utilisateur en anglais peuvent différer de ceux du langage sélectionné.

## 5. Explorer l’espace de travail

| Zone | À quoi l’utiliser ? |
|---|---|
| Chats et projets | Démarrer et rechercher des chats, organiser les projets, utiliser des tags et des marqueurs de messages. |
| Agents | Modèles, instructions et configurations de outils réutilisables. |
| Mémoire et compétences | Gérer le savoir et les instructions réutilisables. |
| Chats planifiés. | Exécuter un Agent sauvegardé avec un prompt récurrent. |
| Fichiers et terminaux. | Inspecter ou manipuler les environnements Controller et Worker. |
| Bureau. | Inspecter et contrôler les sessions GUI distantes prises en charge. |
| Sessions, tâches et audit | Vérification des tâches permanentes, du progrès de l’exécution des tâches et des activités liées aux outils utilisés. |
| Machines et services externes MCP. | Gérer les travailleurs et les serveurs MCP imbriqués |

Le ensemble de contrôles nécessaires dépend de votre configuration, de vos comptes et des capacités activées. Fermer la fenêtre de navigateur ne met pas automatiquement fin à la génération de données côté serveur ; utilisez le bouton “Arrêter” lorsque vous avez besoin d’interrompre les opérations.

## Prochaines étapes…

Lisez le [guide du WebUI Chat](../chat/index.md) pour connaître le flux de travail complet. Pour les paramètres liés à l’administration et au dépannage, consultez [Administration et dépannage](../chat/administration.md).
