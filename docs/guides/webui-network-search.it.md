<!-- i18n-source-sha256: 2fb1887d3d0f7ca8ac19f19375829b9269f666b08197e4915c0230669303c8fe -->
# Ricerca web e lettura dei documenti in WebUI

La ricerca web è attiva per impostazione
predefinita nella chat WebUI. Si può
disattivare per ogni conversazione con
l'interruttore sotto il campo del messaggio;
la scelta viene salvata. Non servono chiavi
API del fornitore né permessi shell del
Worker.

L'Agent dispone soltanto di due strumenti di
lettura. `web_search(query)` restituisce
titoli, URL e sintesi dei risultati pubblici.
Usa `ddgs` quando disponibile oppure Bing RSS
senza chiave. I servizi pubblici possono
limitare le richieste o non rispondere.

`web_fetch(url, query?, offset?, limit?)`
legge HTML, testo, JSON, XML, Markdown e PDF.
Per un abstract di arXiv cerca prima il testo
integrale HTML e poi il PDF, senza bisogno di
API specializzate per articoli scientifici.

Alla prima lettura il testo integrale viene
conservato nella cache privata del
Controller, se scrivibile. La cache è
distinta per utente, scade dopo 24 ore e
contiene al massimo 80 file a persona. Una
risposta mostra fino a 8000 caratteri;
ricerca, offset e limite consentono di
proseguire fino a 12000 caratteri per
chiamata.

I download non possono superare 20 MiB, né il
testo estratto 3 MiB. Sono bloccati indirizzi
privati, credenziali negli URL, porte non
standard e reindirizzamenti non sicuri. Le
connessioni usano soltanto IP pubblici
verificati contro il DNS rebinding.

I PDF vengono analizzati tramite PyMuPDF o,
in alternativa, `pypdf`. Le scansioni senza
livello di testo richiedono OCR e producono
un errore esplicito. La codifica HTML
dichiarata viene rispettata e i formati non
supportati sono rifiutati.

I collegamenti appaiono nella scheda dei
risultati. Le risposte dovrebbero citare gli
URL originali e i numeri di pagina PDF quando
possibile. I contenuti esterni non sono
attendibili e non possono sovrascrivere le
istruzioni dell'utente o le impostazioni
dell'Agent.

Le pagine HTML vuote o dipendenti da JavaScript vengono riprovate in un nuovo
contesto Chromium headless, se l'extra browser e Chromium sono installati.
Le pagine statiche e i PDF non avviano il browser. Il rendering usa lo stesso
trasporto HTTP limitato agli IP pubblici, blocca richieste non di lettura
e connessioni dirette del browser, con limite di 25 secondi e 128 richieste.
Pagine con login, CAPTCHA o reindirizzamenti non supportati possono restare illeggibili.
Accessi negati e risultati vuoti vengono segnalati e non salvati nella cache.
