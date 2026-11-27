<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Gestion et résolution des problèmes

## Architecture de déploiement

Le frontend WebUI est hébergé par le contrôleur Python, au même endroit que ses endpoints REST et MCP. Le backend par défaut est SQLite. Les fichiers binaires distribués incluent les ressources compilées du frontend ; pour construire le frontend depuis le code source, il est nécessaire d’utiliser l’outil de compilation JavaScript. Il n’est pas nécessaire d’utiliser Node.js, MongoDB, Meilisearch ou un backend LibreChat déployé séparément.

Utilisez les instructions de démarrage rapide [](../getting-started/quickstart.md) et la documentation de configuration [](../reference/configuration.md). Pour les builds source, consultez les instructions de construction du WebUI [](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Protégez le déploiement

Utilisez un proxy inverse HTTPS fiable, ou un tunnel de communication sécurisé. Assurez-vous que le Controller soit protégé dans un environnement approprié, par exemple dans un conteneur ou une machine virtuelle. Limitez l’accès en entrée et protégez les informations utilisées pour la communication sortante. Ne exposez pas de point d’exécution non authentifié sur Internet publique.

Le proxy doit permettre la réception des réponses sans avoir besoin de bufferiser les données jusqu’à leur fin. Il doit également supporter les mises à jour via WebSocket pour les interfaces qui en nécessitent. Utilisez des temps d’attente appropriés pour les requêtes longues, et autorisez les tailles de fichiers souhaitées. Assurez-vous que le URL public configuré soit cohérent avec l’origine du navigateur et les appelants OAuth. Ne corrigez pas les erreurs de TLS en désactivant globalement les vérifications des certificats.

Les demandes de modèle proviennent du contrôleur. Les messages visibles par le modèle, les pièces jointes et les résultats obtenus grâce aux outils utilisés peuvent être envoyés à l’API concernée. Il est important d’évaluer les conditions relatives au traitement des données par le fournisseur avant de utiliser des informations confidentielles. De plus, il convient de protéger les secrets externes liés au MCP ainsi que les tokens d’invitation utilisés par les travailleurs.

## État, sauvegarde et mise à niveau

Le dossier par défaut est `.local-shell-mcp`, situé dans le domaine de travail configuré. La valeur `LOCAL_SHELL_MCP_STATE_DIR` permet de modifier ce chemin. La base de données partagée se trouve dans le fichier `lsm.sqlite3`. Les conversations, les projets, les paramètres, les agents, la mémoire, les calendriers et l’état d’exécution sont stockés sur le serveur. Les fichiers attachés, les fichiers du domaine de travail et autres éléments peuvent être stockés en dehors de la base de données.

Faites des sauvegardes complètes du répertoire d’État, ainsi que des informations relatives à l’environnement de déploiement et aux fichiers liés au travail en cours. Considérez les sauvegardes comme des éléments sensibles. Une sauvegarde uniquement basée sur la base de données peut omettre les fichiers attachés ou les configurations associées. Utilisez un contrôleur en état de repos, ou un mécanisme de sauvegarde SQLite cohérent. En copiant uniquement le fichier principal de la base de données SQLite, on peut éviter d’emporter le contenu des transactions WAL. Vérifiez les sauvegardes en les restaurant dans un environnement de test isolé.

Avant une mise à jour, enregistrez la version actuelle du système, le chemin de l’exécution, les configurations, l’emplacement des données et les tâches en cours d’exécution. Arrêtez ou évacuez sécuritairement les tâches en cours d’exécution. Faites une sauvegarde cohérente, puis effectuez la mise à jour de l’installation. Vérifiez également l’authentification, le historique des conversations, la génération des modèles, les fonctionnalités de streaming, les tâches en cours d’exécution, ainsi que les Workers et les tâches planifiées. La migration vers SQLite est possible à l’échelle du système lors de la récupération ; conservez les fichiers anciens jusqu’à ce que vous ayez vérifié que la migration s’est bien effectuée. Ne remplacez pas le dossier contenant les données de production par un dossier vide destiné aux tests.

Le rollback ne consiste pas simplement en modifiant le fichier binaire, lorsque la migration de base de données a modifié l’état persistant du système. Il est nécessaire de restaurer l’état compatible avec celui précédent, et d’éviter d’utiliser deux contrôleurs configurés indépendamment sur le même stockage en temps réel.

## La diagnose montre qu’il s’agit d’un échec du chat.

| Symptôme | Vérifiez d’abord |
|---|---|
| Ne peut pas charger l’interface utilisateur. | Processus de gestion par le biais du Controller, bundle frontend, adresse URL correcte, proxy et authentification. |
| Le modèle manque. | Configuration du canal, découverte des modèles, identifiant du modèle, autorisation de l’accès à l’interface |
| Résultat HTTP 401/403 du fournisseur | Clé/ compte API, autorisations du fournisseur, canal et protocole sélectionnés |
| HTTP 429 | Limites de taux/quotas en amont, demandes simultanées, statut de l’accord/du plan |
| HTTP 400/413/422 | Demander des informations concernant la compatibilité, la taille des données entrées/contextuales, les limites liées aux attaches, ainsi que les paramètres du modèle. |
| Erreur HTTP 5xx ou échec de la connexion. | Santé du fournisseur, réseau, capacité de service du modèle, temps d’attente des proxy. |
| La diffusion de l’output s’arrête. | Réconnexion/redémarrage ; vérification de l’état de la génération et des erreurs détaillées. |
| L’outil n’est pas disponible. | Options de configuration, Capacités des agents, ACL des machines, Scopes OAuth, Switches de contrôleur |
| Le travailleur est hors ligne. | Enregistrement des travailleurs, connexion sortante, signalisation de bon fonctionnement et logs du Controller |
| Autorisation en attente d’approbation/questionnement. | Ouvrir la conversation et examiner l’action demandée. |
| Le calendrier ne s’exécute pas. | État activé, fuseau horaire, agent/chaîne, cible, autorisation sauvegardée, dernière exécution |

Ne supposez pas que tous les erreurs HTTP proviennent du même service. Il est important de distinguer entre des échecs liés au login LSM, des erreurs liées aux API de l’upstream, des erreurs externes liées au MCP, et des erreurs liées au transport des données par le Worker. Vérifiez les erreurs détaillées ainsi que les fichiers de logs correspondants. Masquez les clés, les tokens de portage et les URL de retour avant de les partager.

## Les tentatives de réparation du fournisseur et la reprise après les erreurs

Avant le début d’une réponse du modèle, les erreurs de connexion temporaires et certaines erreurs HTTP (408, 429, 500, 502, 503, 504) peuvent être réessayées avec un délai borné. Les délais ordinaires actuels sont de 1, 2, 4, 8, 16, 30, 30 et 30 secondes (huit nouvelles tentatives après la requête initiale). HTTP Retry-After peut prolonger un délai jusqu’à 120 secondes ; certaines erreurs de streaming ajoutent une variation aléatoire. Le budget de tentatives s’applique à chaque requête au modèle, et non à toute la durée de la conversation. La compaction possède son propre mécanisme de récupération. Une limitation due à des crédits épuisés peut persister jusqu’au renouvellement du quota par le fournisseur. Les nouvelles tentatives automatiques ne garantissent pas le succès et ne rendent pas un abonnement illimité.

Une interruption au milieu de l’exécution est différente d’une erreur survenue avant le premier événement de réponse. Ne vous fiez pas à la répétition automatique d’une séquence d’actions qui n’a pas été complètement exécutée. Vérifiez l’historique des actions et l’état externe avant de réessayer. Si l’exécution est toujours active, reconnectez-vous plutôt que de recommencer le travail. Si l’exécution s’est soldée par un échec, utilisez les contrôles de récupération/redémarrage appropriés, ou commencez une nouvelle session avec un transfert explicite des données si la première session ne peut pas continuer.

Les erreurs de compression du contexte doivent être étudiées séparément des erreurs ordinaires liées à la génération des modèles. Vérifiez la limite effective du contexte, la compatibilité des modèles, les résultats trop volumineux des outils, ainsi que le quota disponible. Consultez la section [Mémoire et contexte](context.md).

## Qu’il convient d’inclure dans un rapport de bogue…

Indiquez la version et l’auteur de l’application LSM, le mode d’installation, le système d’exploitation utilisé, le type du protocole, le type de point de terminaison sécurisé, l’identifiant du modèle, l’heure approximative, les étapes nécessaires pour reproduire l’incident, ainsi que les informations pertinentes concernant les conversations ou l’exécution de l’application. Il est également important d’indiquer les erreurs rencontrées. En cas de problème à distance, indiquez la version du Worker, le nom de l’ordinateur et l’état des notifications/requêtes. Si possible, fournissez également une petite explication sur la manière de reproduire l’incident. Ne transmettez jamais les clés API, les tokens OAuth, les informations privées ou toute autre donnée personnelle.
