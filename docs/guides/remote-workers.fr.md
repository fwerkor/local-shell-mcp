<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Workers distants

Les remote workers permettent à `local-shell-mcp` de contrôler des machines capables d’émettre des requêtes HTTP(S) sortantes mais incapables d’accepter des connexions SSH entrantes.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Workflow de base

1. Créez une invitation avec `remote_manage(action="invite", ...)`.
2. Exécutez la commande générée sur la machine distante.
3. Confirmez l’enregistrement avec `remote_manage(action="list")`.
4. Appelez les outils normaux avec `machine="<worker-name>"`, par exemple `environment_get`, `run_shell`, `file_read` ou `browser_run_script`.
5. Utilisez `remote_transfer` pour démarrer un transfert suivi controller-to-worker, worker-to-controller ou worker-to-worker de fichier ou répertoire. Suivez-le avec `job_list` ou `job_tail` ; arrêtez ou relancez avec `job_stop` ou `job_retry`.
6. Renommez ou révoquez les workers avec `remote_manage(action="rename", ...)` ou `remote_manage(action="revoke", ...)`.

Seule l’administration des workers utilise des noms `remote_*`. Les opérations execution, shell, job, filesystem, patch et browser partagent le même schema localement et à distance. Fournir une machine nécessite en plus le OAuth scope `remote:use`.

## Workers persistants

Le résultat de l’invitation contient des commandes propres à chaque plateforme :

- `persistent_command` installe et démarre un service utilisateur sous Linux ou macOS.
- `powershell_persistent_command` installe et démarre une tâche utilisateur Windows depuis PowerShell.

Sous Windows, `local-shell-mcp worker install-service` enregistre la tâche `local-shell-mcp-worker` pour l’utilisateur actuel. Elle démarre immédiatement, redémarre lorsque cet utilisateur se reconnecte après un reboot, autorise le fonctionnement sur batterie, ignore les démarrages en double et réessaie les exécutions échouées. Aucun droit administrateur n’est requis et elle ne s’exécute pas avant la connexion de l’utilisateur.

Utilisez les mêmes commandes de lifecycle sur toutes les plateformes :

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Le log du worker est stocké dans le worker state directory sous `worker.log`.

## Capacités

Les workers prennent en charge les shell/persistent shell sessions, tracked jobs, opérations filesystem, transfer internals, exécution Python, patches et Playwright lorsque les dépendances sont installées. Git utilise des commandes standard via `run_shell(machine=...)`.

## Sécurité et versionnement

Un worker joint donne au MCP client le contrôle de son environnement configuré. Utilisez des invite TTL courts, des work directories ou comptes dédiés, examinez les audit logs et révoquez les workers après la tâche. L’invitation générée installe un code worker correspondant à la version du control server.

## Dépannage

Si un worker n’apparaît pas, vérifiez l’accès HTTPS sortant, l’accessibilité du public base URL, l’expiration de l’invitation, l’heure système et les logs du control server.
