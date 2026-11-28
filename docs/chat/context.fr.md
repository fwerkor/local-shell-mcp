<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Mémoire, contexte et utilisation des tokens

## Trois types différents d’états

| État | Objectif |
|---|---|
| Historique des conversations | Les messages originaux et les activités liées aux outils sont sauvegardés par le contrôleur. |
| Fenêtre de contexte | Le sous-ensemble d’instructions, de schémas d’outils, d’historiques, de résumés et autres données envoyées dans une demande de modèle particulière. |
| Mémoire persistante | Des informations et des préférences qui peuvent être réutilisées, et qui sont accessibles lors de toutes les conversations dans la zone de mémoire correspondante. |

Une longue conversation enregistrée peut dépasser la capacité de stockage du modèle, sans que l’historique de cette conversation ne soit perdu. La mémoire ne signifie pas que toute l’histoire de l’utilisateur est transmise à chaque demande faite au modèle.

## Gérer la mémoire

![Barre latérale de gestion de la mémoire avec une entrée de démonstration](../assets/chat/memory-management.png)

La mémoire est activée par défaut, à moins que l’utilisateur ne la désactive via ses paramètres, le réglage de l’option de chat ou les restrictions liées aux capacités d’agent. Vous pouvez utiliser la page de gestion de la mémoire pour examiner et modifier les informations stockées. Demandez à l’agent de mémoriser des informations utiles, des conventions de projet ou des préférences, puis vérifiez le résultat dans l’interface de la mémoire.

Lors de la modification d’une entrée de mémoire, utilisez des caractères de petite taille et uniquement des sous-titres (par exemple, `repository_conventions`). La limite de longueur par défaut est de 10 000 caractères ; une installation peut configurer ses propres limites pour le stockage en mémoire. Si une entrée est rejetée, vérifiez l’erreur plutôt que de diviser les secrets entre différentes clés.

La mémoire peut utiliser un pool personnel partagé ou un espace spécifique dédié à chaque agent, en fonction de la configuration de l’agent lui-même. Il est déconseillé de stocker des clés API, des mots de passe ou d’autres données sensibles dans la mémoire. Éteindre la mémoire empêche son utilisation dans le cadre pertinent ; cela ne signifie pas pour autant que les données stockées soient supprimées ou que les mentions issues des conversations soient effacées.

Lorsqu’un élément est exposé, le modèle utilise `set_memory` pour créer ou mettre à jour une entrée ; une valeur vide permet de supprimer cette entrée. `find_memory` récupère les entrées en utilisant une requête ou une clé exacte. Une requête vide liste toutes les informations stockées. Le paramètre optionnel `include_conversations` permet de rechercher des textes provenant d’autres conversations. La pagination utilise les valeurs `page` (par défaut 1) et `limit` (par défaut 10, maximum 50). Cette recherche de l’historique se base sur le texte des conversations, plutôt que sur les enregistrements raw liés aux invocations des outils. La récupération des données est basée sur la pertinence des informations trouvées ; il est donc conseillé d’utiliser des noms ou des termes précis, et de affiner la requête si nécessaire.

L’injection automatique de mémoire et de compétences reste constante au cours des différentes phases d’une conversation, afin de permettre l’utilisation répétée des préfixes de commandes fournis par le fournisseur de services. L’édition de la mémoire stockée ne modifie pas le contenu déjà inséré dans la mémoire. La récupération explicite de la mémoire permet d’accéder aux données stockées en cours ; il est possible de débuter une nouvelle conversation si nécessaire.

## Capacité de contexte

Il convient de définir la limite de contexte réelle de chaque modèle dans son canal correspondant. Le Controller est chargé d’estimer l’entrée visible pour le modèle, et de réserver de l’espace pour la sortie. La mise en œuvre du budget actuel se fait par défaut avec un taux de compression de 85 % et un taux de réserve de 5 %. Ces valeurs peuvent varier en fonction des configurations effectives du modèle et de l’environnement de exécution. Le nombre de caractères peut être approximatif pour des tokenizer inconnus, des demandes multimodales ou des schémas spécifiques au fournisseur.

La composition du contexte peut inclure des instructions système, des configurations d’agents, des définitions de outils, des fichiers attachés, des messages précédents ainsi que les résultats obtenus par les outils. Un fournisseur peut utiliser un tokenizer différent ou compter des tokens internes supplémentaires. Considérez cette présentation comme une indication opérationnelle, et non comme une garantie de la part du fournisseur.

## Compaction automatique

Lorsqu’un budget de contexte nécessite une compression des données, le Controller crée ou met à jour un résumé du contexte antérieur. Ce résumé conserve les informations pertinentes, y compris les objectifs, les contraintes, les décisions prises, les progrès réalisés, les identifiants utilisés, ainsi que les résultats obtenus par les outils. L’historique original est toujours disponible pour inspection ; le résumé est en fait une approximation générée par le modèle, et non une reproduction exacte de l’historique original.

La compression se fait avant la prochaine demande, ce qui nécessite que le contexte soit réduit. Si la compression échoue, l’engin réessaye en fonction de sa gestion des erreurs. Il ne faut pas continuer sans tenir compte de l’enregistrement déjà trop volumineux des données. Vérifiez l’état de compression et les erreurs rencontrées si la compression échoue. Les messages récents ainsi que les relations entre les outils et les résultats doivent rester cohérents. Les résultats des anciens outils ne doivent pas être réécrits pour réduire le volume de données.

Un seul fichier très volumineux peut toujours dépasser le budget prévu. Demandez une sortie limitée, des plages de fichiers ou un format compact. Conservez les résultats importants dans des fichiers distincts, et récupérez uniquement les parties pertinentes, plutôt que d’insérer continuellement ces données dans le contexte du modèle.

## L’utilisation cumulée et les hits en mémoire cache sont également importants.

L’affichage de l’utilisation de la session et la fenêtre de contexte répondent à des questions différentes. L’utilisation d’entrées/sorties se accumule au fil des demandes, y compris les contextes répétés. Les métriques de mémoire cache décrivent le stockage des données par le fournisseur, si celui-ci le permet. La capacité du contexte actif est mesurée, et elle ne s’ajoute pas à l’utilisation totale des demandes précédentes.

Par exemple, une demande contenant 20 000 tokens d’entrée, suivie d’une autre demande contenant 25 000 tokens d’entrée, consomme au total 45 000 tokens d’entrée. Mais la deuxième demande ne utilise que environ 25 000 tokens de sa capacité actuelle. Les tokens en mémoire cache ne sont pas gratuits, à moins que le fournisseur ne le prévoie dans ses tarifs. Une plus grande capacité du contexte modèle modifie la capacité disponible, mais l’utilisation totale des données reste inchangée.

La compression peut réduire la capacité d’occupation actuelle, tout en augmentant la consommation du modèle. Le changement de modèle modifie les limites du contexte applicable ; cela ne supprime pas les données de consommation précédentes. Si un fournisseur omet des informations sur l’utilisation ou les métadonnées de la mémoire cache, les estimations et les indicateurs peuvent être incomplètes. Pour les vérifications financières, il est nécessaire d’utiliser les données de facturation et les prix fournies par le fournisseur, et non seulement les informations affichées dans LSM.

## Réduire les coûts et préserver le contexte utile

Maintenez les instructions de l’agent stables. Évitez les résultats trop volumineux des outils utilisés, et utilisez des méthodes de recherche ciblées. Initiez une conversation distincte pour traiter les tâches non liées. Lorsqu’il est nécessaire de transférer les données, sauvegardez un point de contrôle détaillé, contenant les chemins exacts, les identifiants des objets, les résultats observés et les questions restantes. Vérifiez les informations importantes en comparant avec la source originale ou les résultats obtenus par l’outil, plutôt que de vous fier uniquement à un résumé généré automatiquement.
