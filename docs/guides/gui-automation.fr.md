<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Automatisation de l'interface graphique du bureau

`local-shell-mcp` peut observer et contrôler les applications de bureau natives sous Linux, Windows et macOS. La surface publique reste volontairement petite :

| Outil | But |
|---|---|
| `gui_list` | Répertoriez les fenêtres d'application visibles et signalez le backend/les capacités natifs actifs. |
| `gui_state` | Observez une fenêtre. Renvoie un `state_id` de courte durée, des éléments d'accessibilité, la géométrie de la fenêtre et éventuellement une capture d'écran MCP native. |
| `gui_action` | Exécutez des actions sémantiques ou coordonnées par rapport à cette observation exacte. |

Les trois outils acceptent le `machine` en option, de sorte que le même flux de travail peut cibler un employé de bureau connecté.

## Observer, puis agir

Commencez par `gui_list`, sélectionnez un `window_id`, puis appelez `gui_state`. Préférez l'accessibilité renvoyée `element_id` chaque fois que l'on représente le contrôle cible :

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Utilisez les coordonnées `x`/`y` relatives à la fenêtre uniquement lorsque l'interface utilisateur ne comporte aucun élément d'accessibilité utile, tel qu'un canevas ou un contrôle personnalisé. Les limites des éléments renvoyés et les captures d'écran utilisent le même espace de pixels logique relatif à la fenêtre, y compris les bureaux HiDPI/Retina. Les coordonnées brutes en dehors de la fenêtre sélectionnée sont rejetées.

Un `state_id` expire après 30 secondes et est à usage unique. Les actions de coordination vérifient également que la fenêtre cible n'a pas été déplacée ou redimensionnée depuis l'observation. Si l’une ou l’autre des vérifications échoue, appelez à nouveau `gui_state` au lieu de réutiliser des coordonnées obsolètes.

Les actions prises en charge sont `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` et `wait`.

## Contrôle humain dans Native WebUI

L'interface Web native dispose d'une page **Bureau** pour un contrôle humain direct des mêmes backends d'interface graphique natifs. Choisissez une machine et une fenêtre, puis interagissez avec l'image de la fenêtre en direct en cliquant, double-cliquez, cliquez avec le bouton droit, faites glisser, la molette, les raccourcis clavier ou le champ de texte pour la saisie IME/CJK.

Ce chemin est intentionnellement séparé de la sémantique du modèle `state_id`. Chaque image affichée porte la géométrie de la fenêtre observée ; chaque demande d'entrée humaine valide que la fenêtre a toujours exactement cette géométrie avant d'injecter l'entrée. Si la fenêtre est déplacée, redimensionnée ou disparaît, l'action est rejetée et le WebUI actualise l'observation. Les coordonnées brutes restent liées à la fenêtre sélectionnée.

Les actions du clavier et du texte focalisent explicitement la fenêtre native sélectionnée avant l'injection. La WebUI utilise une interrogation de capture d'écran légère plutôt que le streaming vidéo VNC/WebRTC, et le RPC `gui_human_action` à distance uniquement est une opération interne de contrôleur à travailleur plutôt qu'un outil MCP exposé aux modèles.

## Backends natifs

| Plate-forme | Accessibilité / contrôle sémantique | Capture et entrée brute |
|---|---|---|
| Fenêtres | Automatisation de l'interface utilisateur Microsoft | Capture UIA/fenêtre et saisie native de la souris et du clavier Windows |
| macOS | Accessibilité (`AXUIElement`) | `screencapture` pour la fenêtre sélectionnée plus entrée Quartz `CGEvent` |
| Linux | AT-SPI | Entrée/capture native X11 ; Wayland utilise la capture de bureau native et XDG Desktop Portal RemoteDesktop/ScreenCast pour la saisie brute |

Les actions sémantiques sont tentées en premier lorsque cela est possible. Un bouton avec une action d'appel/appui native peut donc être activé sans deviner une coordonnée de pixel. Les coordonnées visuelles restent la solution de repli pour les contenus inaccessibles ou dessinés sur mesure.

## Configuration de la plateforme

### Fenêtres

Exécutez LSM dans la même session de bureau interactive que les applications qu'il doit contrôler. L'installation de base de `local-shell-mcp` reste sécurisée sans tête et ne nécessite pas l'adaptateur Windows UI Automation ; installez le supplément optionnel `local-shell-mcp[gui]` lorsque le contrôle local de l'interface graphique Windows est nécessaire.

### macOS

Accordez au processus hôte LSM :

- Autorisation **Accessibilité** pour le contrôle et la saisie sémantiques.
- Autorisation **Enregistrement d'écran** pour les captures d'écran.

Le package de base ne nécessite pas PyObjC. Installez le supplément optionnel `local-shell-mcp[gui]` lorsque le contrôle local de l'interface graphique macOS est nécessaire ; les machines qui n'utilisent jamais d'outils GUI n'ont pas besoin de ces frameworks.

### Linux

La session de bureau doit exposer AT-SPI. Les systèmes Debian/Ubuntu fournissent normalement les liaisons système requises avec :

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Le package de base ne nécessite pas les adaptateurs Python X11 ou D-Bus. Le supplément facultatif `local-shell-mcp[gui]` les installe pour une utilisation GUI locale. Les travailleurs distants détectent la session Linux active avant tout démarrage de dépendance GUI : X11 n'a besoin que de l'adaptateur X11, Wayland n'a besoin que de l'adaptateur D-Bus et les travailleurs sans tête n'installent ni l'un ni l'autre. Sur Wayland, le remplacement brut du pointeur/clavier utilise l'API RemoteDesktop du portail XDG Desktop, de sorte que le bureau peut afficher un sélecteur d'autorisation/session unique. Les implémentations des portails KDE et GNOME sont prises en charge. Les captures d'écran de fenêtre utilisent le chemin de capture natif du bureau disponible et reviennent au portail de capture d'écran si nécessaire.

Les travailleurs LSM démarrent généralement en dehors de l'environnement de connexion graphique. Le backend Linux récupère `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` et les variables associées de l'environnement systemd de l'utilisateur lorsqu'elles ne sont pas héritées directement.

## Postes de travail distants

Les outils GUI s'exécutent sur la machine sélectionnée, pas sur le contrôleur. Le travailleur distant doit appartenir à l'utilisateur/à la session propriétaire du bureau cible. Les adaptateurs GUI sont paresseux et limités aux appels GUI : le démarrage normal du travailleur et l'utilisation du shell/fichiers/navigateur ne les installent ni ne les importent. Sous Linux, un travailleur sans tête renvoie une interface graphique indisponible avant tout démarrage de pip de l'interface graphique ; un travailleur graphique vérifie ou installe uniquement l'adaptateur requis par sa session X11 ou Wayland active.

Les captures d'écran renvoyées par un `gui_state` distant sont transférées via le chemin de transfert de fichiers de LSM et exposées au modèle en tant que contenu d'image MCP natif ; ils ne sont pas intégrés dans la réponse JSON du travailleur.
