# Extension VS Code

Cette page décrit le scénario « Extension VS Code » et conserve la structure Runtime/Client commune du site.

## Vue d’ensemble

Runtime définit la manière dont le processus serveur s’exécute et l’espace de travail qu’il contrôle. Client définit la manière dont ChatGPT ou un autre client MCP se connecte. Docker, l’extension VS Code, les binaires autonomes, les installations Python/pipx/source et stdio sont des choix de Runtime ; le connecteur ChatGPT, le client MCP HTTP générique et le client MCP stdio sont des connexions Client.

## Quand l’utiliser

- Utilisez cette page lorsque le chemin Runtime ou Client choisi correspond à son titre.
- Gardez cohérents la racine de l’espace de travail, la base URL publique, le MCP endpoint, le mode d’authentification et les outils disponibles sur l’hôte.
- Pour ChatGPT web/app, exposez un MCP endpoint HTTPS se terminant par `/mcp`.
- Pour les clients MCP locaux, utilisez HTTP localhost ou `local-shell-mcp --mode stdio` selon les capacités du client.

## Étapes

1. Choisissez d’abord la page d’installation du Runtime.
2. Démarrez le Runtime et vérifiez `/healthz` lorsque le mode HTTP est utilisé.
3. Choisissez ensuite la page de connexion Client.
4. Enregistrez le MCP endpoint ou la commande stdio dans le Client.
5. Appelez `environment_info` pour vérifier l’espace de travail et les paramètres effectifs.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Vérification

- `environment_info` confirme les paramètres du Runtime et l’espace de travail.
- `tree_view` confirme les fichiers visibles.
- `git_status_tool` confirme le contexte du dépôt.
- `run_shell_tool` confirme l’environnement de commande.

## Notes

Privilégiez les étapes petites et vérifiables : inspecter, modifier, examiner le diff, tester, analyser et valider. Les tâches importantes doivent aussi être décomposées en appels d’outils auditables.
