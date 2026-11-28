<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Administracja i rozwiązywanie problemów

## Architektura wdrożenia

Frontend WebUI jest obsługiwany przez Python Controller, który znajduje się w tym samym originie co jego endpointy REST i MCP. Tła backendu jest przygotowane za pomocą biblioteki SQLite. Binary i wheels zostają udostępnione wraz z kompilowanymi plikami frontendu. Budowanie frontendu od podstaw wymaga użycia narzędzi do budowy JavaScripta, a nie uruchamiania instalowanego Controllera. Nie są potrzebne Node.js, MongoDB, Meilisearch ani backend LibreChat.

Użyj instrukcji [Quickstart](../getting-started/quickstart.md) oraz [Reference dotyczące konfiguracji](../reference/configuration.md). W przypadku budowy od podstaw, prosimy o skorzystanie z instrukcji dostarczonych w [WebUI](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Zabezpiecz wdrożenie

Należy używać wiarygodnego zaszyfrowanego proxy’a lub tunelu HTTPS, a także systemu do autencjalizacji i przechowywania silnych hasel. Kontroler powinien być przechowywany w odpowiednim konteynerze lub wirtualnej maszynie. Ogranicz dostęp do danych wejściowych, a także chronić dane wyjściowe. Nie eksponuj żadnych punktów dostępu bez autencjalizacji na publicznym Internetie.

Proxy musi móc obsługiwać streamowanie odpowiedzi bez konieczności przechowywania ich w buforze, a także obsługiwać aktualizacje protokołu WebSocket dla interfejsów, które tego wymagają. Użyj odpowiednich czasów oczekiwania na dane i dopuszcza rozmiary plików do załadunku. Utrzymuj publiczny adres URL zgodny z originie przeglądarki oraz parametrami OAuth. Unikaj problemów z TLS poprzez globalne wykluczanie kontroli certyfikatów.

Prosimy o zgłoszenie żądań na poziomie Controllera. Informacje widoczne w modelu, pliki przesyłane w formie plików oraz wyniki pracy narzędzia mogą być przesyłane do wybranej API. Należy sprawdzić warunki obsługi danych dostawcy przed użyciem poufnych informacji. Ponadto należy chronić sekrety zewnętrznych mechanizmów oraz tokeny użytkowników.

## Stany, kopie zapasowe i aktualizacje

Domyślana katalogowa struktura to `.local-shell-mcp` znajdujący się w skonfigurowanym obszarze roboczym; `LOCAL_SHELL_MCP_STATE_DIR` może zmienić tę strukturę. Dane przechowywane w bazie danych to `lsm.sqlite3`. Rozmowy, projekty, ustawienia, agenty, pamięć, harmonogramy oraz stan wykonywania zadań są przechowywane na serwerze; pliki zawierające załączniki, pliki z obszaru roboczego oraz inne dane mogą być przechowywane poza bazą danych.

Przechowuj kopię całego katalogu stanów, a także kopie stanów znajdujących się poza tym katalogiem, środowiska wystawania zgodności/sekretów oraz odpowiednich plików w obszarze pracy. Uważaj na kopie danych – kopia tylko bazy danych może pominąć załączniki i informacje dotyczące konfiguracji. Użyj mechanizmu kopiowania danych w sposób ciągły i bezproblemowy; kopiowanie tylko pliku głównego bazy danych SQLite może pominąć treść zapisaną w formacie WAL. Sprawdź kopie danych poprzez ich odzyskanie na izolowanym testowym systemie.

Przed aktualizacją zapisz obecną wersję programu, ścieżkę wykonywania, konfigurację, lokalizację stanu i aktywne zadania. Zatrzymaj lub bezpiecznie usuń odpowiednie pliki, zrobić kopię danych, aktualizować instalację i sprawdzić autentyfikację, historię rozmów, generowanie modeli, streamowanie danych, pracowników oraz zadania planowane. Migracja do SQLite jest możliwa podczas uruchomienia; pliki starsze należy zachować, dopóki nie sprawdzi się efekty migracji. Nie zastępuj katalogu z danymi produkcyjnymi pustym katalogiem testowym.

Rollback nie polega jedynie na zmianie binarnego pliku, jeśli migracja bazy danych zmieniła stan danych przechowywanych w bazie. Należy przywrócić kompatybilny stan danych, gdy to konieczne, oraz unikać uruchamiania dwóch kontrolerów o różnych parametrach na tym samym nośniku przechowywania danych.

## Diagnozowanie nieudanego działania chatu.

| Objawy problemu. | Sprawdzenie najpierw. |
|---|---|
| Brak możliwości załadowania interfejsu użytkownika. | Proces kontroler, pakiet frontend, poprawne adres URL, proxy i autencjacja |
| Brak modelu. | Konfiguracja kanału, identyfikacja modelu, identyfikator modelu, autoryzacja konta. |
| Błąd HTTP 401/403 od dostawcy usług. | Klucz API/konto, uprawnienia dostawcy, wybrany kanał i protokół. |
| HTTP 429 | Ograniczenia w przepływie danych, liczba jednocześnie realizowanych żądań, status konta/planu. |
| HTTP 400/413/422 | Kompatybilność żądań, rozmiar wejściowych danych, ograniczenia dotyczące załączników, parametry modelu. |
| Błąd HTTP 5xx lub przerwanie czasu wykonania zadania | Stan dostawcy, sieć, możliwości serwowania danych, przerwy w działaniu proxy’ów |
| Przerwanie streamingu wyjściowego | Ponowne połączenie z dostawcą; sprawdzenie statusu generowania danych oraz szczegółowych informacji o błędzie |
| Narzędzie nie jest dostępne | Opcje funkcjonalne, Możliwości agenta, Zasady dostępu do danych maszynowych, Obszary dostępu w systemie OAuth, Przełączniki kontrolerów |
| Pracownik poza czasem pracy | Rejestracja pracowników, połączenia wyjściowe, logi Controllera |
| Sprawa w trakcie aprobatacji/rozpatrywania | Otwórz konwersację i sprawdź żądaną akcję |
| Plan nie jest realizowany | Stan aktywowany, czas regionalny, Agent/warunki komunikacji, cel, zapisane uprawnienia, ostatnie wykonanie poleceń |

Nie zakłaniaj się, że wszystkie błędy HTTP pochodzą z tego samego serwisu. Należy odróżnić błędy logowania typu LSM, błędy w API modelu upstream, błędy zewnętrzne dotyczące MCP oraz błędy w transporcie danych przez Workera. Sprawdź szczegółowe informacje o błędach oraz logi kontrolerów. Przed udostępnianiem tych informacji należy usunąć klucze, tokeny i adresy URL-ów powrotu.

## Ponowne próby i proces naprawczy przez dostawcę usług.

Przed rozpoczęciem odpowiedzi modelu przejściowe błędy połączenia i wybrane błędy HTTP (408, 429, 500, 502, 503, 504) można ponawiać z ograniczonymi opóźnieniami. Obecne zwykłe opóźnienia wynoszą 1, 2, 4, 8, 16, 30, 30 i 30 sekund (osiem ponowień po pierwszym żądaniu). HTTP Retry-After może wydłużyć opóźnienie do 120 sekund; niektóre błędy strumieniowania dodają losowe odchylenie. Limit ponowień dotyczy pojedynczego żądania modelu, a nie całego czasu trwania rozmowy. Kompaktowanie ma własną ścieżkę odzyskiwania. Ograniczenie szybkości spowodowane wyczerpaniem kredytów może trwać do uzupełnienia limitu przez dostawcę. Automatyczne ponawianie nie gwarantuje powodzenia ani nie czyni subskrypcji nieograniczoną.

Przerwanie procesu w trakcie jego trwania różni się od błędu, który wystąpił przed pierwszym momentem wydania odpowiedzi. Nie należy polegać na automatycznym powtórzeniu częściowo wykonanej operacji. Sprawdź zapisy historii i stan zewnętrzny przed ponownymi próbami. Jeśli proces nadal jest aktywny, należy połączyć się ponownie, a nie rozpocząć nową pracę. Jeśli proces zakończył się niepowodzeniem, należy użyć kontrolerów naprawy/ponownego prób w odpowiedni sposób, lub rozpocząć nowy proces, jeśli pierwszy nie może kontynuować.

Błędy związane z kompresacją kontekstu należy badać osobno od zwykłych błędów w generowaniu modeli. Sprawdź ograniczenia dotyczące efektywności kontekstu, kompatybilność modeli, nadmiernie duże wyniki narzędzia oraz dostępną kwotę pamięci. Zobacz [Pamięć i kontekst](context.md).

## Co należy wpisać w raporcie o błędzie?

Proszę podać informacje o wersji LSM, metodzie instalacji, systemie operacyjnym, typie protokołu, typie elementu bezpiecznego, identyfikatorze modelu, przybliżonym czasie, krokach rekonfiguracji, statusie rozmowy/operacji oraz szczegółowych informacjach o błędach. W przypadku problemów zdalnych, należy podać wersję programu, nazwę komputera oraz status czujnika/odprawy. Jeśli to możliwe, proszę również przedstawić krótki przykład rekonfiguracji. Nigdy nie należy wysyłać kluczy API, tokenów OAuth, prywatnych danych lub innych niepotrzebnych informacji osobistych.
