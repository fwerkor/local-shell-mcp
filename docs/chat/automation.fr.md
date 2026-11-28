<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Objectifs, conversations planifiées et travaux à long terme

## Choisissez le bon mécanisme.

| Mécanisme | Objectif |
|---|---|
| Génération de conversations ordinaires | Réponse aux instructions actuelles, y compris l’utilisation d’outils spécifiques |
| Objectifs à atteindre dans la conversation | Continuation d’une session logique active, même au-delà des limites de la modélisation du modèle |
| Conversations planifiées à l’avance | Lancez un agent avec une instruction préenregistrée, en respectant un rythme de répétition déterminé. |
| Tâches persistantes ou terminaux continus | Exécution de commandes indépendamment d’une seule demande de modèle |
| Subagents | Confiez une tâche spécifique à un autre agent. |

Une conversation planifiée n’est pas un travail en temps réel. Une session logique n’est pas non plus une conversation ou un processus système. Annuler une telle session ne met pas nécessairement fin à tout ce qui a été lancé par les outils associés.

## Objectifs à atteindre dans la conversation

Pour une tâche longue, demandez à l’Agent de définir un objectif concret et de maintenir un plan utilisant les outils de session logique. Ce plan contient des étapes et leurs états respectifs. Le runtime de la conversation peut continuer à exécuter ce plan même lorsque le modèle est en train de tourner, sans avoir besoin d’attendre une nouvelle demande de l’utilisateur ou que le timer externe de l’espace de travail en ligne se termine.

Vérifiez le plan et les progrès réalisés. Pendant l’exécution du plan, vous pouvez interrompre, reprendre ou annuler certaines étapes. La poursuite du plan nécessite un plan actif et une exécution valide ; il ne faut donc pas continuer avec un plan déjà terminé, bloqué ou annulé. Des réponses identiques répétées sans aucun progrès entraînent une interruption plutôt qu’une boucle infinie (actuellement, après trois étapes inchangées). Résolvez le problème qui empêche la poursuite du plan avant de continuer.

Definissez les critères de réussite. Par exemple : examiner le dépôt, mettre en œuvre les corrections nécessaires, exécuter l’ensemble des tests correspondants, et signaler tout échec. Demandez à l’Agent de consigner les identifiants exacts des commits ainsi que les résultats des tests. Ne déclarez pas la réussite uniquement sur la base de votre propre plan.

Le mécanisme de gestion des objectifs du client MCP externe est distinct. Pour plus d’informations sur le flux de travail lié à la passerelle Logical Session et au transfert des données dans l’espace de travail en temps réel, veuillez consulter [Human interface](../guides/human-interface.md).

## Créer un chat programmé

![Barre latérale des chats planifiés avec un exemple désactivé](../assets/chat/scheduled-chats.png)

Ouvrez la gestion des conversations programmées. Créez un calendrier avec un nom descriptif, un agent préenregistré, une zone horaire et une fréquence de communication. Choisissez l’objet de la conversation ; vous pouvez également sélectionner un projet pour une nouvelle conversation. Sauvegardez et activez le calendrier. Utilisez le contrôle manuel pour vérifier la configuration avant de l’utiliser.

Les cadences supportées incluent les heures, les jours de la semaine, la semaine entière, le calendrier à cinq dates, ainsi que l’exécution continue des tâches. L’exécution continue commence après un délai configuré ; un délai nul peut entraîner une charge continue sur le serveur et les machines. Les horaires de répétition ordinaires exigent un intervalle minimum de cinq minutes. Utilisez un fuseau horaire spécifique fourni par IANA, comme `Asia/Shanghai` ou `UTC`. Vérifiez l’horaire affiché après avoir enregistré les données.

Exemple cron pour 09:00 les jours ouvrés :

```text
0 9 * * 1-5
```

Cela prend en compte le fuseau horaire sélectionné, mais pas nécessairement celui du système du contrôleur. Vérifiez les changements d’heure liés au rythme de la journée si le fuseau horaire choisi respecte ces changements.

## Cibles de la conversation

- **Nouvelle conversation à chaque exécution:** Il est utile de créer une conversation distincte pour chaque cas ; cela permet de tenir des rapports indépendants.
- **Réutiliser une conversation:** Créez une conversation lors de la première utilisation, et réutilisez cette conversation pour les occurrences suivantes. Cela est utile pour le suivi cumulatif des événements.
- **Utiliser une conversation existante:** Choisissez une conversation déjà en cours, afin que les participants puissent prendre part à cette conversation de manière programmée.

Une conversation déjà utilisée ou existante peut être développée davantage, mais cela nécessite également une certaine compression des informations. Il est préférable de choisir des conversations indépendantes lorsque le contexte historique n’est pas nécessaire. Les opérations programmées dépendent de l’agent sélectionné et du canal de communication qui reste disponible et utilisable.

## Autorisations non surveillées

L’exécution planifiée appartient au Controller et utilise les noms des scopes autorisés enregistrés, plutôt qu’un jeton de connexion du navigateur conservé. Enregistrez ou lancez manuellement une planification pour l’autoriser si nécessaire. Les permissions machine de l’Agent désigné s’appliquent ; les dérogations ordinaires du projet ou de la conversation ne constituent pas la politique machine de la planification. Les restrictions du Controller, l’autorisation enregistrée, les capacités et les approbations des outils restent applicables.

Pour un serveur MCP externe nécessitant une authentification, une connexion interactive n’implique pas automatiquement une autorisation renouvelable pour l’exécution sans surveillance. Si l’interface de planification exige une nouvelle authentification ou un accès sans surveillance, réglez les identifiants propres à ce serveur ou supprimez cette dépendance avant d’activer la planification. Ne réutilisez pas les jetons du navigateur à la place.

Utilisez un agent de lecture uniquement destiné à la surveillance. Décrivez clairement les cibles autorisées, les résultats souhaités et les actions à éviter. Si une tâche planifiée nécessite l’intervention humaine ou l’approbation, vérifiez les interactions en cours. Ne supposez pas que l’exécution sans surveillance signifie un accès illimité. Un exemple de message de surveillance :

```text
Vérifiez le travail de formation spécifié, ainsi que les fichiers de logs associés.
Rapportez l’étape actuelle, les pertes, le débit, l’horaire estimé de livraison, ainsi que tout nouvel incident qui pourrait survenir.
Ne modifiez pas les fichiers, ne relancez pas l’opération, ni ne lancez de nouveaux travaux.
Si les données ne sont pas disponibles, indiquez précisément la raison pour laquelle cela est le cas.
```

## Cycle de vie et récupération

Le Controller gère les horaires de mise en œuvre des tâches, ainsi que l’état et les événements liés à ces tâches. Cela permet d’éviter que des tâches ne soient exécutées deux fois. Une fiche de navigateur ne doit pas rester ouverte indéfiniment. Ne supposez pas que les événements manqués seront toujours réexécutés, ni que tout travail externe survivra à un redémarrage du Controller. Vérifiez l’état de la dernière exécution, de la prochaine exécution, ainsi que les conversations associées après une panne.

Désactivez les calendriers afin d’éviter que des actions automatiques ne se produisent à l’avenir. Vérifiez également chaque action en cours de réalisation individuellement. Arrêter la planification future n’est pas garantie de pouvoir annuler une tâche en cours ou une opération en cours. Supprimez les calendriers qui ne sont plus nécessaires, et révoquez les permissions inutilisées pour l’agent.

Un travail ou un terminal créé par un agent WebUI peut survivre même après l’achèvement normal de la réponse au modèle. Un redémarrage du contrôleur ne suffit pas nécessairement pour mettre fin à cet état. Une interruption explicite, une perte des droits d’accès à la machine, ou l’expiration des autorisations peuvent entraîner l’annulation des tâches gérées par l’agent. Si le travailleur est hors ligne, l’annulation peut rester en attente jusqu’à ce qu’il puisse être récupéré. Il est nécessaire d’inspecter le travail ou le terminal lui-même avant de déclarer que l’exécution s’est arrêtée. L’agent ne peut envoyer ou arrêter les tâches/gestions liées à sa propre conversation qu’à travers la voie d’accès protégée du WebUI. Les clients MCP externes conservent leur semantics native.

Les outils liés aux agents et les tâches subordonnées ont chacun leur propre cycle de vie. Un résultat peut rester en attente de livraison, même après l’exécution de la tâche. Il est donc nécessaire de consulter le panneau des tâches en cours et de récupérer le résultat correspondant. Ne lancez pas de tâches doubles simplement parce que le résultat n’est pas encore visible.

Pour les commandes qui doivent durer plus longtemps que la durée d’utilisation d’un seul outil, utilisez les tâches gérées par LSM ou des terminaux permanents. Sauvegardez les résultats dans un fichier de log, enregistrez les identifiants des tâches, et vérifiez l’avancement réel du travail. Voir [Schémas d’utilisation](../guides/usage-patterns.md).
