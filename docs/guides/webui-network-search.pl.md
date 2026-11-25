<!-- i18n-source-sha256: 2fb1887d3d0f7ca8ac19f19375829b9269f666b08197e4915c0230669303c8fe -->
# Wyszukiwanie w sieci i odczyt dokumentów w WebUI

W czacie WebUI wyszukiwanie internetowe jest
domyślnie włączone. Można je wyłączyć dla
osobnej rozmowy przełącznikiem pod polem
wiadomości; wybór zostaje zapisany. Nie
potrzeba klucza API dostawcy ani dostępu
Workera do powłoki.

Agent otrzymuje wyłącznie dwa narzędzia do
odczytu. `web_search(query)` zwraca tytuły,
adresy URL i fragmenty publicznych wyników.
Używa `ddgs`, jeśli jest zainstalowany, a w
przeciwnym razie próbuje Bing RSS bez klucza.
Usługi publiczne mogą ograniczać ruch lub nie
odpowiadać.

`web_fetch(url, query?, offset?, limit?)`
odczytuje HTML, zwykły tekst, JSON, XML,
Markdown i PDF. Dla strony streszczenia arXiv
najpierw próbuje pełnego tekstu HTML, a jeśli
go nie ma, pliku PDF. Nie wymaga osobnego API
do publikacji naukowych.

Podczas pierwszego pobrania cały tekst trafia
do prywatnej pamięci podręcznej Controllera,
jeśli katalog jest zapisywalny. Pamięć jest
oddzielna dla każdego użytkownika, wygasa po
24 godzinach i przechowuje najwyżej 80 plików
na osobę. Zwykła odpowiedź ma do 8000 znaków;
kolejne fragmenty można pobierać za pomocą
wyszukiwania, przesunięcia lub limitu, do
12000 znaków na wywołanie.

Pobieranie ograniczono do 20 MiB, a
wyodrębniony tekst do 3 MiB. Odrzucane są
sieci prywatne, dane logowania w URL,
nietypowe porty i niebezpieczne
przekierowania. Połączenia kierowane są
wyłącznie do zweryfikowanych publicznych IP,
co chroni przed DNS rebinding.

PDF jest analizowany przez PyMuPDF lub
awaryjnie `pypdf`. Skany bez warstwy
tekstowej wymagają OCR i powodują wyraźny
komunikat błędu. Uwzględnia się deklarowane
kodowanie HTML i odrzuca nieobsługiwane
formaty.

Linki pojawiają się w karcie wyników
narzędzia. Odpowiedzi powinny podawać
oryginalne URL i numery stron PDF, gdy to
możliwe. Zewnętrzne treści nie są zaufane i
nie mogą zastępować poleceń użytkownika ani
ustawień Agent.

Puste strony HTML lub zależne od JavaScript są ponawiane w nowym kontekście
Chromium bez interfejsu, jeśli zainstalowano opcjonalny dodatek browser i Chromium.
Strony statyczne i PDF nie uruchamiają przeglądarki. Renderowanie używa tego samego
transportu HTTP ograniczonego do publicznych IP, blokuje żądania inne niż odczyt
i bezpośrednie połączenia przeglądarki; limit to 25 sekund i 128 żądań.
Logowanie, CAPTCHA i nieobsługiwane przekierowania mogą nadal uniemożliwiać odczyt.
Odmowy dostępu i puste wyniki są zgłaszane, a nie zapisywane w pamięci podręcznej.
