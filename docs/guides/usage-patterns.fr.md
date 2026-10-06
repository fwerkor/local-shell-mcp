<!-- i18n-source-sha256: bfd205813bd40569d489f7e57417eef5098af2388cdb852b1016deb74a2fc0f1 -->
# Modes d’utilisation et guide de prompting

`local-shell-mcp` expose des outils puissants. Les bons résultats dépendent du fait de demander au modèle d’inspecter d’abord, d’agir par petites étapes, de vérifier et de rapporter ce qui a changé.

## Boucle opérationnelle générale

Utilisez cette boucle pour la plupart des tâches de code :

1. Inspecter : `environment_get`, `file_tree`, `file_grep`, `file_read` et `run_shell` pour des commandes comme `git status`.
2. Planifier : demander au modèle d’identifier les fichiers et tests minimaux concernés.
3. Éditer : utiliser `file_edit`, `file_patch` ou des commandes shell.
4. Vérifier : exécuter tests/builds ciblés avec `run_shell` ou des shells persistants.
5. Revoir : exécuter `git diff` via `run_shell`, puis `secret_scan` et `audit_tail` si nécessaire.
6. Commit/export : utiliser des commandes Git CLI explicites via `run_shell` ou `link_create`.

## Choix des outils

| Tâche | Préférer | Éviter |
|---|---|---|
| Commande one-shot rapide | `run_shell` | Démarrer un shell persistant pour chaque commande |
| Dev server, REPL ou watch task longue | `shell_start` + `shell_read` + `shell_send` | Bloquer `run_shell` jusqu’au timeout |
| Analyse structurée ou génération de fichiers | `run_python` | Pipelines shell fragiles pour JSON/texte complexe |
| Petite édition exacte | `file_edit` | Réécrire tout un fichier sans nécessité |
| Une ou plusieurs substitutions dans un fichier | `file_edit` with an `edits` array | Répéter des edits périmés sans relire |
| Patch multi-fichiers | `file_patch` | Éditions shell ad hoc |
| Trouver des fichiers | `file_tree`, `file_glob` | Listage récursif complet de gros repositories |
| Trouver du code | `file_grep` | Lire de nombreux fichiers à l’aveugle |
| Preuves navigateur | `browser_snapshot`, `browser_run_script` | Deviner à partir des noms de page ou routes |
| Artefacts téléchargeables | `link_create` | Coller du contenu binaire volumineux dans le chat |
| Travail sur machine distante | normal tools with `machine`, plus `remote_transfer` | Ouvrir SSH entrant quand outbound worker suffit |

## Appeler des outils depuis la CLI

Pour les scripts shell et la CI, `lsm call <tool>` invoque la même surface d’outils enregistrés via le controller loopback en cours d’exécution, ce qui conserve les remote workers et l’état du controller.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Utilisez `--session s_...` pour rattacher l’appel à une Logical Session. Dans la configuration Docker Compose documentée, le controller et la CLI de l’hôte partagent `LOCAL_SHELL_MCP_UI_LOCAL_TOKEN` via le `.env` du repository aux permissions restreintes ; les autres runtimes séparés peuvent utiliser `--token-file <path>`. `--direct` contourne le controller et reste limité aux appels locaux.

## Modèles de prompt

### Orientation read-only du repository

```text
Utilise local-shell-mcp. Inspecte le layout du repository et git status. Ne modifie aucun fichier. Résume les composants principaux, les commandes de test que tu peux déduire et les risques évidents avant toute modification.
```

### Correction ciblée de bug

```text
Utilise local-shell-mcp pour corriger le bug. Commence par le reproduire ou le localiser avec la plus petite commande pertinente. Lis les fichiers avant de les modifier. Fais un patch minimal, exécute la vérification ciblée, puis montre git diff et les tests exacts exécutés. Ne commit pas avant mon approbation.
```

### Workflow commit et push

```text
Utilise local-shell-mcp. Vérifie git status et diff, exécute les tests pertinents et secret_scan, crée un seul commit ciblé avec un message concis, puis push la branch courante. N’inclus pas caches, artefacts de build ou formatting sans rapport.
```

### Processus long

```text
Démarre le dev server dans une persistent shell session, lis le output jusqu’à ce qu’il soit ready, puis utilise les browser tools pour vérifier la page. Conserve le session id et arrête la session après vérification.
```

### Tâche remote worker

```text
Utilise le remote worker connecté nommé <machine>. Appelle d’abord environment_get avec machine=<machine>, puis file_list avec la même machine. Travaille uniquement dans le remote workdir configuré. Utilise run_shell pour les commandes courtes et shell_start ou job_start pour les tâches longues.
```

## Travail avec les repositories

Séquence recommandée pour des changements open-source :

1. Exécuter `git status --short --branch` via `run_shell`.
2. Fetch et inspecter les branches avec des commandes Git CLI explicites lorsque upstream state compte.
3. Utiliser `file_grep` et `file_read` avant d’éditer.
4. Faire un patch minimal.
5. Exécuter d’abord les tests ciblés, puis des tests plus larges si possible.
6. Exécuter `secret_scan` avant commit ou push.
7. Stage et commit explicitement avec un message concis.

Demandez un commit par changement logique lorsque les maintainers ont besoin d’un historique facilement révisable.

## Travail avec les artefacts générés

Pour PDF, reports, screenshots, archives ou logs :

1. Générer le fichier dans le workspace.
2. Vérifier qu’il existe et a la taille attendue.
3. Utiliser `link_create` avec TTL court et `max_downloads` optionnel.
4. Révoquer le lien lorsqu’il n’est plus nécessaire.

Ne créez pas de liens publics pour private keys, credential directories ou données personnelles sans rapport.

## Travail avec des machines distantes

Remote worker mode est utile quand une machine peut faire des requêtes HTTPS sortantes mais ne peut pas accepter SSH entrant.

Bonnes pratiques :

- Créer ou renommer les machines avec `remote_manage(action="invite", ...)` ou `remote_manage(action="rename", ...)`.
- Appeler `environment_get(machine=...)` avant d’agir.
- Utiliser `remote_transfer` pour lancer des transfer jobs controller/worker ou worker/worker, puis les gérer avec les outils `job_*` normaux.
- Révoquer les workers après la tâche avec `remote_manage(action="revoke", ...)`.

## Anti-patterns

Évitez ces instructions sauf si l’environnement est jetable et les conséquences comprises :

- « Installe globalement tout ce qui est nécessaire » sur un server lancé sur host.
- « Exécute jusqu’à ce que ça marche » sans limite de temps ni critères de vérification.
- « Commit tout » dans un repository contenant des artefacts générés.
- « Expose tout le home directory » par commodité.
- « Crée un file link pour tout le workspace ».
- Exécuter un deployment public avec `LOCAL_SHELL_MCP_AUTH_MODE=none`.
