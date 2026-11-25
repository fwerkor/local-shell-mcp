<!-- i18n-source-sha256: 2fb1887d3d0f7ca8ac19f19375829b9269f666b08197e4915c0230669303c8fe -->
# Recherche web et lecture de documents dans WebUI

La recherche web est activée par défaut dans
le chat WebUI. Le bouton situé sous le champ
de saisie permet de la désactiver pour une
conversation donnée et ce choix est
enregistré. Aucune clé API du fournisseur ni
permission de shell du Worker n'est
nécessaire.

L'Agent dispose uniquement de deux outils en
lecture seule. `web_search(query)` renvoie
les titres, URL et extraits des résultats
publics. Il utilise `ddgs` si disponible ou,
à défaut, le flux Bing RSS sans clé. Les
services publics peuvent limiter les requêtes
ou être indisponibles.

`web_fetch(url, query?, offset?, limit?)` lit
les pages HTML, les fichiers texte, JSON,
XML, Markdown et PDF. Sur une page de résumé
arXiv, il essaie le texte intégral HTML puis
le PDF si nécessaire, sans API spécialisée.

Le texte intégral obtenu à la première
lecture est conservé dans le cache privé du
Controller, si celui-ci est accessible en
écriture. Le cache est séparé par
utilisateur, expire après 24 heures et
contient au plus 80 fichiers par personne. La
réponse est limitée à 8 000 caractères; les
paramètres de recherche, de décalage et de
longueur permettent de continuer, jusqu'à 12
000 caractères par appel.

La taille téléchargée est limitée à 20 Mio et
le texte extrait à 3 Mio. Les réseaux privés,
identifiants dans les URL, ports non standard
et redirections dangereuses sont refusés.
Seules les adresses IP publiques validées
sont utilisées, afin d'empêcher le rebinding
DNS.

Les PDF sont analysés avec PyMuPDF, ou
`pypdf` en secours. Les scans sans couche
texte nécessitent une reconnaissance OCR et
produisent une erreur explicite. L'encodage
HTML déclaré est respecté et les formats
inconnus sont rejetés.

Les liens figurent dans la carte du résultat
de l'outil. Les réponses doivent citer les
URL d'origine et les pages PDF si possible.
Les contenus externes ne sont pas fiables et
ne peuvent modifier ni les instructions de
l'utilisateur ni la configuration de l'Agent.

Les pages HTML vides ou dépendantes de JavaScript sont réessayées dans un nouveau
contexte Chromium sans interface si le supplément browser et Chromium sont installés.
Les pages statiques et PDF ne lancent pas de navigateur. Le rendu utilise le même
transport HTTP limité aux IP publiques, bloque les requêtes autres que la lecture
et les connexions directes du navigateur, avec une limite de 25 secondes et 128 requêtes.
Les pages nécessitant une connexion, un CAPTCHA ou des redirections non prises en charge
peuvent rester illisibles. Les refus d'accès et résultats vides ne sont pas mis en cache.
