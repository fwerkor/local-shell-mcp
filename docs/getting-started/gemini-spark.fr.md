<!-- i18n-source-sha256: 0d50677fe8bd21dbf6f3fff366adea800f15d50fdbc67ed3b77abf84437f73eb -->
# Connecter Gemini Task / applications personnalisées

La fonctionnalité **Applications connectées personnalisées** de Gemini permet à un utilisateur Gemini éligible de se connecter à un serveur MCP distant. LSM peut fournir le point de terminaison MCP. Il s'agit d'une **connexion client alternative** aux clients [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) et autres clients MCP ; il ne remplace ni ne déploie le contrôleur LSM.

Google restreint actuellement les applications personnalisées aux **utilisateurs âgés de 18 ans ou plus aux États-Unis**, connectés avec un **compte Google personnel** et **Garder l'activité activée**. La fonctionnalité est disponible en **anglais**. Les connexions doivent être créées sur l'application Web Gemini, bien que les applications connectées puissent ensuite être utilisées sur mobile. Les étiquettes de disponibilité et d’interface utilisateur peuvent changer ; consultez le [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Avant de vous connecter

- Démarrez un runtime LSM, par exemple avec [Docker Compose](../installation/docker.md), et vérifiez son intégrité.
- Exposez son point de terminaison MCP sur **HTTPS accessible publiquement** et gardez OAuth activé.
- Connaissez les détails d’authentification du contrôleur et approuvez uniquement les étendues dont vous avez besoin.
- Utilisez un espace de travail ou un conteneur contraint. Gemini peut demander des opérations ayant des effets réels sur les fichiers, les machines et les terminaux.

Le point final à saisir dans Gemini est :

```text
https://your-public-host.example.com/mcp
```

N'entrez pas l'interface utilisateur Web (`/ui`), l'URL LibreChat ou l'origine du site sans `/mcp`. Les déploiements publics ne doivent pas désactiver l'authentification pour contourner les erreurs de connexion.

## Connectez-vous en Gémeaux

1. Sur un ordinateur, ouvrez [Gemini](https://gemini.google.com/) et connectez-vous avec un compte personnel éligible.
2. Ouvrez **Paramètres et aide → Applications connectées**. Selon l'interface actuelle, il peut se trouver sous **Personal Intelligence → Connected Apps**.
3. Sous **Applications personnalisées**, sélectionnez **Ajouter une application personnalisée** ou utilisez le champ URL de l'application personnalisée.
4. Collez l'URL LSM HTTPS `/mcp`, puis choisissez **Suivant**.
5. Complétez le flux OAuth et de consentement avec le contrôleur LSM. LSM prend en charge la découverte OAuth et l'enregistrement dynamique des clients. Si Gemini demande à la place les informations d'identification manuelles du client OAuth, vérifiez ses options avancées et votre configuration LSM OAuth avant de continuer.
6. Dans une conversation Gemini, tapez `@` et sélectionnez l'application personnalisée connectée pour demander un outil LSM.

Commencez par : "Utilisez l'application LSM connectée pour inspecter l'environnement et répertorier les fichiers de l'espace de travail. Ne modifiez rien." Vérifiez les résultats de l'outil et l'audit du contrôleur avant de tenter des opérations d'écriture.

## Utiliser le mode Task (anciennement Spark)

Pour le développement en plusieurs étapes, le débogage et la maintenance de serveurs, privilégiez **Task** au chat ordinaire : il permet de planifier le travail, d'utiliser plusieurs fois les outils connectés et de suivre la progression. Ce conseil ne garantit aucune performance mesurée.

Sur la page d'accueil de Gemini, sélectionnez **Task** sous la zone de saisie et terminez la configuration si nécessaire. Saisissez `@`, sélectionnez LSM si proposé, puis indiquez l'objectif, la machine ou l'espace de travail cible et les critères de réussite.

Exemple : « Utilise LSM pour examiner le dépôt, reproduire le test en échec, corriger la cause et relancer les tests. Indique les fichiers modifiés et les résultats. »

Suivez la progression et confirmez les actions nécessaires. Vérifiez les appels LSM dans le journal d'audit du Controller : l'ordinateur cloud de Gemini n'est pas votre espace LSM. Gardez le Controller et les Workers nécessaires en ligne. Task et les applications personnalisées ont des critères d'accès distincts ; consultez le [guide Task officiel](https://support.google.com/gemini/answer/17094507) si une option manque.

## Limites et dépannage

- **Aucune option d'applications personnalisées :** confirmez le compte, la région, l'âge, la langue et l'éligibilité au maintien de l'activité. Il s'agit d'une restriction de disponibilité côté Gemini, et non d'une erreur de configuration LSM.
- **L'URL est rejetée :** utilisez un point de terminaison HTTPS `/mcp` accessible de l'extérieur ; vérifiez la découverte OAuth et votre proxy inverse.
- **OAuth échoue :** vérifiez l'écran d'autorisation LSM, l'enregistrement du client, l'URL de rappel et les étendues accordées. Ne publiez pas de point de terminaison MCP non authentifié.
- **Un outil est manquant ou échoue :** La prise en charge des outils/schémas MCP côté client peut différer. Essayez un simple appel en lecture seule et inspectez l'audit et les journaux LSM ; la compatibilité totale avec toutes les fonctionnalités du client Gemini n'est pas garantie.
- **Déconnexion :** revenez aux **Applications connectées** pour désactiver, dissocier ou supprimer LSM lorsqu'il n'est plus nécessaire.

Le [official guide](https://support.google.com/gemini/answer/17209137) de Google décrit le dernier flux et la disponibilité des applications personnalisées. Pour une intégration Gemini locale basée sur CLI, voir [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). Le LSM [ChatGPT connector tutorial](chatgpt-connector.md) reste disponible indépendamment.
