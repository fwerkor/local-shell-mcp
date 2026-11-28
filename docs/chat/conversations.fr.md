<!-- i18n-source-sha256: af41013e98ff8fbebf496514fd0034d1c97f3177d7e73f77f7c0c21f6022047b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Conversations et projets

## Créez et continuez une conversation.

Ouvrez une nouvelle conversation, choisissez un canal/modèle ou un agent, puis inscrivez un message. La conversation se déroule sur le navigateur, et les mises à jour sont affichées dans le navigateur lui-même. Réactualiser la page ou fermer une fiche n’équivaut pas à annuler l’exécution de l’opération. Utilisez le bouton « Arrêter » pour interrompre l’exécution, et vérifiez l’état de l’opération avant de commencer une autre opération.

Un chat sauvegardé conserve son association avec le modèle/Agent correspondant. Vous pouvez choisir un modèle différent si vous le souhaitez. Une conversation n’est pas une session logique : elle contient les messages des utilisateurs et des modèles concernés. En revanche, une session logique contient plutôt les objectifs de tâches, les progrès réalisés et les plans liés à ces tâches. Il est important de conserver les identifiants pertinents lors du transfert d’une longue tâche.

## Organisez-vous et trouvez un travail.

Les projets permettent de regrouper les conversations liées entre elles et d’établir des permissions partagées pour l’ensemble des machines concernées. Un projet peut contenir plusieurs chats distincts. Il est possible de déplacer ou de créer des chats dans le projet approprié, plutôt que de supposer que toutes les conversations partagent le même contexte. Le projet actif peut informer l’Agent sur l’organisation de la conversation.

Les tags permettent de classer les conversations ; les marques de messages indiquent les messages individuels, et permettent également de naviguer vers des résultats utiles. Ces fonctionnalités sont distinctes de l’option de “pinage” des conversations. Utilisez les titres des messages, la recherche, les archives et les indicateurs de messages non lus pour maintenir une barre latérale facile à gérer.

L’archivage consiste à placer une conversation hors de la liste normale, sans supprimer son historique enregistré. Il est possible de la récupérer via l’interface d’archivage lorsque cela est nécessaire. La suppression d’une conversation est une action destructrice ; ne utilisez donc pas cette méthode pour remplacer l’archivage. La mise en œuvre actuelle utilise le format de stockage des conversations fourni par SQLite. Ne supposez pas que le format ancien, compressé, reste valable.

## Opérations de message et exécution de tâches

Les contrôles disponibles pour les messages dépendent du message en question et de son état actuel d’exécution. Il est possible de modifier ou de réessayer une action lorsque cela est nécessaire, ou de supprimer un tour de dialogue sélectionné si celui-ci n’est plus nécessaire. La suppression modifie le historique des conversations enregistrées, et peut avoir des conséquences sur les contextes ultérieurs. Il n’est pas possible d’annuler les commandes shell, les écritures depuis la console, les télétransferts de données via Git, ou autres effets externes.

Lors du réexécution d’une opération qui a échoué, il est nécessaire de lire les erreurs détaillées et d’examiner d’abord les appels aux outils qui ont déjà été effectués. Si une opération de écriture a pu se dérouler avant la coupure du réseau, il convient de vérifier l’état externe avant de répéter l’opération. Si d’autres messages sont en attente ou si une autre opération est déjà en cours, il est préférable d’utiliser les contrôles et les informations affichées, plutôt que de supposer que plusieurs opérations se déroulent simultanément dans le même chat. Le panneau des messages en attente permet d’examiner les opérations en cours ; le contrôle de direction tente de fournir des instructions de manière sécurisée, après que les outils actuellement en cours d’exécution se soient achevés. Aucune de ces opérations ne permet de revenir en arrière après que les outils ont été exécutés.

## Attaches, prévisions et artefacts

Utilisez le contrôle des fichiers pour télécharger des fichiers ou des images compatibles. La mise en œuvre du téléchargement limite les fichiers individuels à 32 Mo. Les limites de déploiement/requêtes peuvent toutefois réduire cette capacité effective. Les fichiers téléchargés sont stockés dans le Controller, et peuvent être référencés par le modèle correspondant. L’interprétation des images nécessite un modèle et un fournisseur capable d’accepter les données image. Le téléchargement ne confère pas le droit d’accéder à des fichiers locaux ou distants qui ne sont pas liés au modèle concerné.

Lors de la demande d’un fichier généré, veuillez indiquer le chemin de stockage souhaité, le format et le contenu du fichier. Vérifiez que le fichier existe avant de le partager. Téléchargez ou consultez les fichiers et documents supportés depuis la conversation, si ils sont disponibles. Un fichier généré par un Worker peut nécessiter une transmission vers le Controller, ou bien un lien vers le fichier correspondant. Veuillez consulter [Liens vers les fichiers](../guides/file-links.md).

La représentation des artefacts peut afficher React, HTML, SVG, Markdown et Mermaid dans une fenêtre latérale, plutôt que uniquement sous forme de code. Dans les paramètres d’artefact de l’agent, la option « Normal » utilise les instructions standard. La option « shadcn/ui » ajoute des instructions spécifiques pour les composants et bibliothèques. Enfin, l’option « Custom » permet de continuer à afficher le contenu généré, sans les instructions intégrées dans l’artefact. Considérez le code généré ou le contenu affiché comme étant non fiable ; vérifiez-le avant de l’utiliser en dehors de la vue prévisualisée. Les prévisualisations et téléchargements basés sur des fichiers sont distincts des artefacts UI générés.

Ne téléversez pas de credences, de clés privées ou de documents pour lesquels vous n’avez pas l’autorisation de les envoyer au fournisseur de modèles sélectionné. La suppression des fichiers attachés et celle des messages de chat sont distinctes de la suppression des fichiers source sur le système informatique.

## Préférences

Les conversations et les préférences des utilisateurs, comme les options de configuration et les raccourcis clavier, sont gérées via l’interface Web. Ces informations sont également stockées sur le serveur où elles sont implémentées. Vous pouvez ouvrir les Paramètres pour configurer le comportement du clavier ; il est important de distinguer entre l’envoi d’un message et l’insertion d’une ligne de séparation dans le texte envoyé. Configurez également les options de configuration liées aux conversations, indépendamment des permissions accordées à l’agent. Consultez les sections [Outils et permissions](permissions.md) et [Mémoire et contexte](context.md).

### Nommage automatique des conversations

Dans Paramètres → Chat → Conversations, choisissez de ne pas nommer automatiquement les discussions, de nommer une fois les nouvelles discussions ou de les renommer après chaque réponse terminée. Par défaut, les nouvelles discussions sont nommées une fois avec leur propre modèle. Vous pouvez choisir un autre modèle d’un canal configuré. Le nom est généré seulement après la fin de la réponse principale ; une réponse échouée ou annulée ne le déclenche pas. Le titre décrit brièvement la tâche dans la langue de l’utilisateur. La requête de nommage est distincte du contexte et n’ajoute aucun message.
