<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Agentes et compétences

## Quand créer un agent ?

Un chat de modèle direct est utile pour des questions ou des tâches ponctuelles. Un Agent représente une configuration prédéfinie qui peut être sélectionnée à plusieurs reprises, utilisée dans des conversations programmées ou déléguée à d’autres agents. Différents Agents peuvent utiliser différents canaux, modèles, instructions et politiques d’accès. Ils partagent tous le même contrôleur, mais pas nécessairement la même zone de mémoire ou les mêmes outils.

## Configurer un agent

Gérez l’agent depuis l’interface web. Créez un agent, donnez-lui un nom identifiable et choisissez son modèle. Écrivez également les instructions nécessaires pour décrire la tâche à accomplir, les résultats souhaités, les contraintes et les exigences de vérification. Configurez les capacités requises pour l’agent. Ensuite, sauvegardez et commencez une nouvelle conversation avec lui.

![Agent Builder avec instructions, outils, autorisations et paramètres de Skill](../assets/chat/agent-builder.png)

Par exemple, un réviseur de dépôt de code pourrait avoir les instructions suivantes :

```text
Vérifier les modifications par rapport à la branche principale actuelle.
Examiner le dépôt et les résultats des tests avant de tirer des conclusions.
Ne pas modifier les fichiers, ne pas envoyer de commits, ni déployer quoi que ce soit.
Signaler les problèmes concrets, en indiquant les emplacements et les preuves correspondantes.
```

Les instructions sont utiles pour guider le comportement des utilisateurs, mais elles ne constituent pas une limite autorisant les actions. Assurez-vous que l’accès à la machine soit limité au seul lecteur ; omettez également les fonctionnalités externes inutiles si le réviseur ne souhaite pas modifier quoi que ce soit. Voir [Outils et permissions](permissions.md).

Il est préférable de disposer d’agents distincts pour des tâches différentes, comme l’examen du code, la mise en œuvre et les opérations liées au système. Donner à chaque agent un accès minimal mais suffisant, ainsi qu’un modèle adapté à sa fonction. Si un agent ne peut pas démarrer, il est nécessaire de vérifier son canal de communication et son modèle avant de modifier des paramètres qui ne sont pas liés à sa fonction.

## Skills

Les paquets de compétences contiennent des instructions réutilisables ainsi que des fichiers associés. Ces fichiers sont généralement nommés `SKILL.md`. Les compétences peuvent être gérées via l’interface web ; il est possible d’activer les compétences pertinentes et de les rendre disponibles pour l’Agent ou pour le chat. Le modèle peut découvrir et charger le contenu des compétences lorsque cela est nécessaire. Une compétence peut décrire un flux de travail, citer des exemples ou contenir des scripts. Cependant, cette compétence ne met pas automatiquement en œuvre les scripts, ni ne donne des autorisations supplémentaires au système.

Vérifiez les compétences importées avant de les activer. Traitez leurs instructions et fichiers comme n’importe quel autre code ou instruction fournie par un tiers. Assurez-vous que les noms et descriptions des compétences soient suffisamment spécifiques pour que le modèle puisse les reconnaître. Gardez les références importantes distinctes, et privilégiez les workflows plus petits mais utiles de manière indépendante. Le registre côté contrôleur et les appels aux outils sont expliqués dans [Skills](../guides/skills.md).

Les compétences automatiques et le contexte de la mémoire sont enregistrés de manière automatique, afin d’éviter de devoir réécrire les instructions du système à chaque tour. Les changements dans les compétences peuvent avoir un impact significatif ; il est donc conseillé d’utiliser une nouvelle conversation lors du test des contextes automatiques modifiés. Une compétence chargée de manière délibérée est différente de l’image automatique initiale.

## Délégation et sous-agents

Les agents peuvent déléguer des tâches limitées à des sous-agents, lorsque cette capacité est disponible. Un enfant peut utiliser un agent configuré, tout en conservant son propre flux d’exécution de l’activité. Le parent coordonne la tâche, lit les résultats obtenus par le sous-agent, et peut continuer à exploiter le flux d’exécution sauvegardé par le sous-agent. Il est possible d’inspecter les activités du sous-agent depuis la conversation principale ; cette vue n’est pas un chat indépendant pouvant être modifié.

Il est conseillé de déléguer des tâches distinctes, comme des révisions indépendantes, des zones de fichiers séparées ou l’examen de différentes hypothèses. Il convient de donner au sous-agent un objectif précis, un champ d’action et un résultat attendu. Il est déconseillé de écrire simultanément sur les mêmes fichiers, à moins que la tâche ne soit explicitement coordonnée.

La délégation doit rester dans les limites autorisées par l’utilisateur parent. Elle ne donne pas accès à des machines ou aux services MCP que l’utilisateur parent ne peut pas utiliser. La politique d’approbation de la délégation ne peut pas affaiblir la politique de l’utilisateur parent. Les tâches déléguées peuvent consommer des jetons de modèle et du temps de manière indépendante. Il est donc important d’examiner leurs activités et résultats lors de l’évaluation des coûts et du progrès réalisé.

## Outils, actions et artefacts

Le constructeur Agent expose sa bibliothèque de outils disponibles ainsi que les paramètres de configuration avancés. Il est conseillé de ne sélectionner que les fonctionnalités dont vous avez besoin. Pour une action HTTP définie par un schéma OpenAPI, il est important de vérifier l’endroit où l’action est exécutée, les exigences d’authentification et les opérations autorisées avant de la connecter au système. Les actions peuvent avoir leurs propres méthodes d’authentification ; une permission d’ordinateur ne permet ni d’autoriser ni de refuser l’accès à des informations liées aux API tierces. Il est également important de vérifier la réponse de l’action avant de considérer que la mutation en question est complète.

Pour le contenu UI généré, configurez la rendu des artefacts comme décrit dans [Conversations et projets](conversations.md). Le code généré n’est pas une extension fiable du Controller.

## Modèles pratiques d’agents

- **Enquêteur à accès uniquement pour lecture :** Vérifier les journaux d’activité et les sources d’information, comparer les preuves, déterminer les causes des problèmes. Aucune modification n’est autorisée.
- **Agent d’implémentation :** Il s’agit de modifier un répertoire, de exécuter des tests ciblés, de signaler les différences entre les versions et les échecs non résolus. L’approbation est nécessaire pour effectuer des opérations sensibles, si cela est approprié.
- **Agent de surveillance :** Inspect les machines spécifiées et rapporte l’état de celles-ci, ainsi que tout écart ou progrès mesuré. Ne relancez pas les tâches, à moins d’y être explicitement autorisé.
- **Recherche Agent:** Permet la recherche sur le réseau, cite les documents originaux, distingue les preuves des inférences, et utilise des outils informatiques uniquement lorsque c’est nécessaire.

Les modèles proposés ne sont que des instructions, et non des préconfigurations prêtes à l’emploi. Il est nécessaire de configurer les permissions et capacités réelles de chaque agent, afin qu’ils correspondent à leurs fonctions prévues.
