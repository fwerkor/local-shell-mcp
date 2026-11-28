<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Outils, machines et permissions.

## Niveaux d’autorisation.

L’existence d’un outil listé ne garantit pas l’autorisation de l’exécuter. L’autorisation effective repose sur une combinaison de restrictions liées au contrôleur, des droits définis pour le principal authentifié, des politiques de machine, des capacités de l’agent, ainsi que l’approbation de l’outil lui-même. Des instructions claires ne suffisent pas à garantir l’accès à cet outil.

Les machines enregistrées, y compris le contrôleur local lorsqu’il est activé, ont par défaut des droits de lecture/écriture pour la politique concernant les machines de chat. Il est conseillé de restreindre ces droits pour les déploiements sensibles. Les noms de machines inconnus ne bénéficient pas de ces droits implicites. Le contrôleur peut désactiver l’exécution locale ou les travailleurs distants indépendamment.

## Accès à la machine

| Accès | Signification |
|---|---|
| Aucun | Les opérations sur la machine sont indisponibles |
| Lecture seule | Seules les opérations classées comme seules de lecture sont autorisées ; l’exécution de commandes shell ou Python n’est pas considérée comme une opération seule de lecture. |
| Lire/écrire | Permet la lecture, la modification et l’exécution des opérations autorisées, sous réserve d’autres restrictions. |
| Hériter | Utiliser les valeurs par défaut applicables, plutôt que de modifier explicitement les paramètres. |

![Autorisations et mode d’approbation des machines lors d’une conversation](../assets/chat/machine-permissions.png)

Définissez les valeurs globales, les dérogations du projet et celles de chaque conversation dans les contrôles des permissions machine. Les dérogations d’une conversation priment sur celles du projet, qui priment sur les valeurs globales. Un Agent peut restreindre davantage l’accès par machine ou via sa politique par défaut ; ses permissions explicites ne contournent ni les restrictions de l’identité authentifiée ni celles du Controller.

Exemple : une politique globale de lecture/écriture, une dérogation du projet en lecture seule et une autorisation de lecture/écriture de l’Agent donnent un accès en lecture seule dans la conversation du projet, sauf dérogation explicite de cette conversation. Une dérogation de lecture/écriture ne peut toutefois pas dépasser une limite de lecture seule de l’Agent.

Une exécution planifiée avec un agent spécifique utilise la politique de l’agent lui-même, ainsi que les paramètres d’exécution sauvegardés. L’agent hérite donc des paramètres de l’agent standard, plutôt que de ceux des machines de chat ordinaires. Voir [Objectifs et automatisation](automation.md). Utilisez un agent spécifique pour les tâches non supervisées.

## Approbation de l’outil

| Mode | Comportement |
|---|---|
| Automatique | Les appels effectués avec l’outil autorisé se déroulent sans qu’il soit nécessaire d’obtenir une approbation supplémentaire, à moins que des politiques spécifiques ne le prévoient autrement. |
| Revoir les opérations à risque | Le Controller demande une révision des opérations considérées comme dangereuses, y compris les commandes shell arbitraires et de nombreux appels externes. |
| Passez en revue tous les outils | Il est nécessaire de demander l’autorisation pour les appels aux outils ordinaires. |

Les paramètres d’approbation d’une conversation peuvent hériter des paramètres de l’Agent et des valeurs globales. Les règles explicites de refus ou d’approbation restent applicables. Un Agent enfant ne peut pas assouplir le mode d’approbation de son parent. L’approbation est indépendante des permissions : approuver une action machine refusée ne donne pas accès à la machine.

Veuillez réexaminer les arguments, la destination et les effets secondaires possibles avant d’approuver. Pour un flux de travail non géré, il est important de configurer correctement l’agent et la politique d’approbation. Une approbation manuelle peut ralentir le processus. Ne déploierez pas l’accès aux informations uniquement pour supprimer les messages d’aide.

## Outils MCP natifs et externes

Les outils natifs fonctionnent sur le Controller et les travailleurs enregistrés, via LSM. Le registre d’outils comprend des opérations de fichiers, des actions liées au shell et aux tâches, des opérations liées à la navigation dans les navigateurs et aux interfaces graphiques, ainsi que des fonctionnalités de découverte à distance, des sessions logiques, etc. Pour connaître les schémas d’argumentation exacts, consultez la section [Référence sur les outils](../reference/tools.md). Pour savoir comment joindre des machines, veuillez consulter la section [Travailleurs distants](../guides/remote-workers.md).

Gérer des serveurs MCP imbriqués dans l’interface WebUI. Les configurations supportées incluent l’utilisation de transports local standard et HTTP à distance, avec des variables d’environnement ou des en-têtes spécifiques au serveur. Activer la fonctionnalité MCP externe dans le chat et dans l’agent correspondant. L’agent peut découvrir, examiner et utiliser les outils externes disponibles ; l’autorisation et l’approbation des outils restent valables.

Un outil MCP externe peut fonctionner indépendamment des ACL machine natives : une API distante externe peut modifier des ressources même si l’accès aux machines locales est désactivé. Examinez séparément les permissions et les identifiants du service externe. N’installez pas de serveurs stdio non fiables sur un Controller contenant des fichiers sensibles.

## Demander aux utilisateurs et activer les fonctionnalités selon leurs besoins.

Ask User permet à un agent de demander une réponse structurée de la part de l’utilisateur, plutôt que de devoir faire des suppositions. Il s’agit donc d’une demande d’informations, et non d’une autorisation pour contourner un outil qui a été refusé. Lorsque la tâche est laissée sans surveillance, il est nécessaire d’indiquer à l’agent comment gérer les situations incertaines, ainsi que de vérifier les interactions en cours avant de considérer que la tâche est terminée.

Le compositeur expose les contrôles liés aux différentes fonctionnalités, telles que la recherche sur le réseau, les outils externes et la mémoire. Ces contrôles déterminent quelles capacités sont disponibles pour le modèle. Ils sont distincts de l’autorisation nécessaire pour utiliser ces fonctionnalités. Éteindre une fonctionnalité ne supprime pas non plus les résultats historiques obtenus. La recherche sur le réseau est activée par défaut, et elle utilise des outils en mode lecture seule, comme décrit dans [Recherche sur le réseau](../guides/webui-network-search.md).

## Audit et vérification

Vérifiez les appels aux outils et leurs résultats dans le chat ; déploiez les détails lors de la détection des erreurs. Le journal d’audit du contrôleur enregistre les activités liées aux outils natifs, tandis que les tâches/sessions indiquent l’exécution en cours. Une réponse API positive signifie que l’outil a retourné un résultat, mais cela ne garantit pas que l’opération demandée a été réussie. Vérifiez également les écritures, l’état des tâches à distance et l’état du déploiement de manière indépendante. Consultez [Journal d’audit](../guides/audit-log.md).
