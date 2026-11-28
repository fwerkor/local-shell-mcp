<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat est un espace de travail basé sur l’IA, hébergé en interne, et intégré au Controller. Vous pouvez utiliser votre propre point d’accès pour l’implémentation du modèle, ou bien une compte supporté. Le modèle dispose alors d’accès à vos propres outils et machines. Aucun client MCP externe n’est nécessaire. Les clients externes peuvent toujours se connecter au même Controller de manière indépendante.

## Comment les pièces s’assemblent entre elles

- **Contrôleur :** C’est le service Python qui héberge l’application web, gère les demandes des utilisateurs, exécute les tâches nécessaires, et stocke les informations relatives à l’état permanent de l’application.
- **Canal** : Il s’agit d’une connexion via une API de modèle ou d’une autorisation pour un compte supporté. Ce canal dispose de ses propres informations de connexion, protocole, liste de modèles et paramètres.
- **Modèle :** Un identifiant qui désigne un modèle au sein d’un canal. Le même identifiant sur deux canaux ne signifie pas nécessairement que les deux canaux correspondent à des endpoints identiques.
- **Agent** : une configuration réutilisable qui combine un modèle, des instructions, des outils, des compétences et des autorisations.
- **Conversation :** Messages sauvegardés, paramètres, historique d’exécution, ainsi que l’association entre le modèle et l’agent.
- **Projet :** Un groupe de conversations ayant des paramètres partagés.
- **Worker** : c’est un objectif d’exécution connecté à l’extérieur du système. Il ne s’agit pas d’un fournisseur de modèles, ni d’un serveur de chat distinct.
- **Séance logique** : c’est une identité de tâche côté outil, distincte de l’identité d’une conversation. Un chat peut utiliser cette identité pour suivre les objectifs, les progrès et le travail effectué avec l’outil.

L’API de modèle reçoit le contexte visible pour le modèle, ainsi que les résultats obtenus par les outils utilisés. Le Controller exécute les outils autorisés ; le modèle ne se connecte pas directement à un Worker, ni ne peut obtenir la clé d’accès de l’API de modèle. Le navigateur gère la conversation et contrôle le Controller.

## Choisissez un guide.

| Je veux… | Lire |
|---|---|
| Installer, se connecter et exécuter une première tâche. | [Démarrage rapide](../getting-started/web-workspace.md) |
| Connecter une API ou un compte de modèle. | [Canaux et modèles](channels.md) |
| Créer des agents réutilisables et déléguer des tâches. | [Agents et compétences](agents.md) |
| Gérer les conversations, les fichiers et les projets. | [Conversations](conversations.md) |
| Comprendre le fonctionnement de la récupération d’informations historiques et des budgets contextuels. | [Mémoire et contexte](context.md) |
| Restreindre l'exécution et gérer les outils MCP | [Outils et permissions](permissions.md) |
| Exécuter des tâches et des schémas de travail de longue durée. | [Objectifs et automatisation](automation.md) |
| Rechercher sur Internet et lire des documents. | [Recherche sur le réseau](../guides/webui-network-search.md) |
| Gérer, faire des sauvegardes et débuguer une mise en œuvre. | [Administration et résolution de problèmes](administration.md) |

## Principes fondamentaux.

Commencer par une demande de type “seulement lecture” sur un machine connu. Vérifier les résultats de l’outil avant de permettre des modifications. Un modèle peut être incorrect, même si l’outil fonctionne correctement. Les informations relatives aux identifiants, au stockage des données, à l’accès au machine et aux autorisations de l’outil sont des éléments distincts ; changer l’un ne garantit pas automatiquement l’autorisation pour l’autre. En particulier, un endpoint de chat public doit être protégé comme une plateforme de contrôle de l’exécution à distance.

Pour le chemin de connexion du client MCP externe, voir [Connexion au client](../clients/connectivity.md). Pour les arguments des outils, voir [Référence des outils](../reference/tools.md).
