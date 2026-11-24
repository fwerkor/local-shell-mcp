<!-- i18n-source-sha256: 78ec7a5b5dc75473db69b12cf1626f81c3071f52661bf1023047af5d6d24e3ee -->
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
