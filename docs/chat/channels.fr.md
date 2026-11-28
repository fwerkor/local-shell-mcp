<!-- i18n-source-sha256: bb7b6aa220cafcc7318d2cc50e01ae98fb5ea2f1ff04c87d5cc7b90a7b322134 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Canaux et modèles

## Configurer un canal

Ouvrez le sélecteur de modèles dans Chat et entrez dans la section gestion des canaux. Sélectionnez **Ajouter un canal**, choisissez le type de connexion souhaité, entrez les informations nécessaires, puis sauvegardez. Choisissez ensuite un modèle pour créer une nouvelle conversation. Pour un agent personnalisé, sélectionnez plutôt le canal et le modèle dans la configuration de l’agent.

Les canaux sont gérés par le Controller, et non par les paramètres de chat personnels. Dans les déploiements authentifiés, la gestion des canaux nécessite le champ d’autorisation `admin:config`. Un administrateur peut configurer des canaux partagés sans avoir besoin de distribuer des clés API aux utilisateurs du chat.

![Ajouter un canal de modèle dans la boîte de dialogue de configuration du canal](../assets/chat/channel-settings.png)

Un canal API normal possède un nom, un protocole, une URL de base, des informations d’authentification et des identifiants de modèles. Utilisez une clé API délivrée pour l’endroit sélectionné, et non la mot de passe de votre compte LSM. LSM effectue les requêtes depuis le Controller ; une URL fonctionnant sur votre ordinateur portable ne fonctionnera peut-être pas depuis le Controller.

| Protocole | Exemple d’URL de base API | Utilisation |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Porteurs de chat compatibles avec OpenAI et serveurs de déduction locaux |
| OpenAI Responses | `https://api.openai.com/v1` | Un porteur qui expose l’API Responses |
| Indigène anthropique | `https://api.anthropic.com/v1` | APIs compatibles avec les messages d’Anthropic |
| Natif de Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | APIs compatibles avec Gemini generateContent |

Utilisez le URL de base requis par le fournisseur, plutôt que de copier un URL complet contenant une demande de génération, comme un URL se terminant par `/chat/completions`. Un fournisseur prétendant être compatible avec OpenAI peut bien supporter les fonctionnalités de Chat Completions, mais pas celles liées aux réponses, aux appels d’outils, à l’utilisation en streaming, aux entrées multimodales ou aux options de raisonnement. Choisissez le protocole qu’il supporte réellement. Les exemples de URL sont des exemples de protocole, et ne garantissent pas l’accès gratuit ou la disponibilité des services.

## Endpoints locaux et personnalisés

Pour un serveur compatible avec OpenAI qui écoute sur le Controller lui-même, le URL de base pourrait être `http://127.0.0.1:8080/v1`. Lorsque l’on exécute l’application dans Docker, “loopback” fait référence à ce conteneur, et non au hôte physique. Utilisez une adresse accessible depuis le nom de domaine réseau du Controller. Une simple inscription d’un Worker distant ne suffit pas pour rendre son API de raisonnement accessible.

Le validateur de URL du modèle nécessite HTTPS, sauf pour les cas où l’endroit est un serveur HTTP local (`localhost`, `127.0.0.1`, `::1`). Un endpoint HTTP situé sur une adresse LAN ou un nom de service Docker doit être exposé via un gateway HTTPS. La fonctionnalité de configuration du point de terminaison privé n’est plus disponible. Les URLs de base ne doivent pas contenir de credences intégrées, de fragments ou de chaînes de requêtes.

Utilisez TLS pour les endpoints distants. Restreignez l’accès aux gateways privés fiables. Vérifiez également que les identifiants des modèles correspondent bien à ceux du serveur d’inférence. Ne mettez jamais les clés API dans des messages, des captures d’écran, des chaînes de requêtes ou dans les configurations publiées. Laissez la clé API vide lors de l’édition d’un canal existant, afin de conserver sa clé sauvegardée. Utilisez une connexion sans clé uniquement si le service le permet.

## Paramètres par défaut configurés par l’environnement

Le profil OpenAI intégré peut être configuré avant l’exécution du programme, en utilisant `LOCAL_SHELL_MCP_MODEL_BASE_URL` (ou `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` et `LOCAL_SHELL_MCP_MODEL_API_KEY` (ou `OPENAI_API_KEY`). Les profils intégrés d’Anthropic et Google peuvent lire `ANTHROPIC_API_KEY` et `GOOGLE_KEY` / `GOOGLE_API_KEY`, respectivement. Les profils intégrés pris en charge ont la priorité sur les paramètres par défaut dérivés de l’environnement. Utilisez des canaux nommés pour plusieurs endpoints indépendants. Les paramètres par défaut configurés par l’environnement ne constituent pas une alternative à la protection des secrets du service.

## Autorisation de l’accès au compte ChatGPT

Le canal de gestion des comptes/Codex utilise un flux d’autorisation basé sur un compte ChatGPT supporté, plutôt qu’une clé API ordinaire. Il est nécessaire de commencer l’autorisation depuis la gestion des canaux, puis de se connecter à la page d’autorisation officielle. Dans une déploiement local, le processus d’autorisation peut se dérouler automatiquement. Si le navigateur ne parvient pas à se connecter au serveur de callback, il suffit de copier l’ensemble de l’adresse URL du callback dans la barre d’adresse et de la coller dans la boîte de dialogue d’autorisation. Une erreur de connexion au serveur de callback est attendue dans ce flux manuel.

Traitez l’URL de retour comme un identifiant secret : ne l’envoyez jamais dans une conversation et ne la publiez pas. Le Controller conserve l’autorisation côté serveur et renouvelle les identifiants lorsque c’est possible. Autorisez à nouveau le compte s’il expire ou si l’accès est révoqué. Les modèles disponibles, les limites de l’offre et les usages autorisés dépendent du service de compte en amont ; LSM ne fournit aucun quota d’abonnement supplémentaire.

## Découverte de modèles et limites liées au contexte

Activer la découverte automatique afin de demander des informations sur le modèle au fournisseur. Le Controller met à jour ces informations périodiquement (actuellement tous les dix minutes) ; il est également possible de procéder à une mise à jour manuelle. En cas d’échec de la découverte, les données du modèle sauvegardées précédemment sont conservées. Si le fournisseur ne dispose pas d’un endpoint correspondant pour afficher la liste des modèles, désactiver la fonction de découverte et entrer manuellement les identifiants des modèles, un par ligne.

La découverte reconnaît les métadonnées explicites de fenêtre de contexte, notamment `limit.context` imbriqué d’OpenCode Go/Zen, `context_length` d’OpenRouter, `max_model_len` de vLLM et `inputTokenLimit` de Gemini. Si seule la longueur maximale d’entrée est indiquée, elle sert de valeur de repli ; les limites de sortie et les noms de modèles ne déterminent pas la capacité de contexte. Sans ces deux informations, la fenêtre reste inconnue.

Spécifiez la fenêtre de contexte pour chaque modèle, lorsque ce contexte est connu. Une valeur spécifique par modèle peut remplacer les métadonnées découvertes ou combler des valeurs manquantes. L’éditeur accepte de 1 à 2 000 000 de tokens ; il s’agit donc d’une plage de configuration, et non d’une garantie que le fournisseur prend en charge cette capacité. Utilisez la limite effective adaptée à votre déploiement, en tenant compte des configurations côté serveur ainsi que des limites propres au modèle lui-même.

Pour les points d’accès officiels reconnus, les valeurs de contexte manquantes peuvent être complétées à partir du catalogue public models.dev en utilisant les identifiants exacts du fournisseur et du modèle. Les métadonnées du fournisseur priment sur ce repli, et les réglages manuels priment sur les deux. Le contrôleur partage un cache en mémoire du catalogue valable six heures ; en cas d’échec, il conserve le dernier cache valide et réessaie après dix minutes. Aucun identifiant d’accès de canal, URL ou identifiant de modèle n’est envoyé à models.dev. Les points d’accès inconnus et identifiants sans correspondance restent sans limite connue si le fournisseur n’en indique pas.

## Échantillonnage, raisonnement et utilisation

Les paramètres par défaut du canal et du modèle contrôlent les paramètres de demande pris en charge par le fournisseur sélectionné. Le composant de chat peut indiquer les méthodes utilisées pour effectuer les calculs, si celles-ci sont disponibles. Les différents protocoles mettent en œuvre les calculs de manière différente ; une option peut ne pas être supportée par un modèle particulier. Commencez par les paramètres par défaut du fournisseur, puis modifiez un paramètre à la fois.

Les LSM peuvent demander des informations précises sur l’utilisation des jetons de streaming. Ils peuvent également se tourner vers une autre solution lorsque le fournisseur rejette explicitement cette option d’utilisation. Un endpoint qui ne renvoie pas d’informations sur l’utilisation ne peut pas fournir de données de facturation précises ou des statistiques relatives au cache. Pour plus d’informations, veuillez consulter la section [Memory and context](context.md) pour comprendre la différence entre la consommation cumulée et la capacité actuelle du système.

## Changer et supprimer des canaux

Une conversation conserve son modèle d’agent et son historique associé. Il est conseillé de changer le modèle lors du passage à des endpoints différents ou lors du débogage d’un problème lié au fournisseur de services. Le renommer d’un canal en cours d’utilisation est limité afin de protéger les références liées à ce canal. La suppression d’un canal en cours d’utilisation nécessite une confirmation supplémentaire : l’historique de la conversation reste intact, mais les agents et les conversations qui font référence à ce canal doivent choisir un autre canal pour continuer à fonctionner correctement.

Les paramètres de canal sont gérés par le serveur, et ne sont pas des préconfigurations uniquement destinées au navigateur. Les identifiants ne sont pas retournés dans les réponses ordinaires du catalogue de canaux. Il est donc nécessaire de protéger le dossier d’État du Controller ainsi que les copies de sauvegarde, car ces données contiennent des identifiants.

## Vérification de la connexion

1. Vérifiez que le Controller peut se connecter à l’hôte de l’API, et que la sécurité TLS est bien activée.
2. Confirmez le chemin de base, le protocole, les informations de connexion et l’identifiant exact du modèle.
3. Réactualisez les découvertes ou entrez manuellement dans un modèle connu.
4. Envoyez une brève instruction en texte simple, puis essayez d’utiliser cette instruction pour appeler un petit outil.
5. Vérifiez les détails des erreurs liées à l’état HTTP, au temps de réponse ou aux options non supportées. Ne répète pas les tentatives de connexion avec des informations de connexion invalides.

Pour plus d’informations sur la gestion des limites de débit, les interruptions de streaming et les erreurs d’autorisation, veuillez consulter la section [Administration et résolution des problèmes](administration.md).
