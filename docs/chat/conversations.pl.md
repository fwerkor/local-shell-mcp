<!-- i18n-source-sha256: 012f0d9f7b350fcf47e3fd6afdf2fc9e7044ff28cb2eca7c029c3d6af35f3b04 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Rozmowy i projekty

## Utworzyć i kontynuować rozmowę

Otwórz nową rozmowę, wybierz kanał/model lub agenta, a następnie wpisz wiadomość. Rozmowa odbywa się na serwerze Controller, a aktualne informacje są przesyłane do przeglądarki. Ponowne przygotowanie strony lub zamknięcie okna nie oznacza zakończenia wykonywania operacji. Użyj opcji „stop” aby przerwać wykonywanie operacji, a także sprawdź stan sytuacji po tym, jak rozpocznie się kolejna operacja.

Zachowany chat zachowuje swoją powiązanie z modelem/agentem. Można je zmienić, jeśli chce się użyć innego modelu. Rozmowa nie jest logiczną sesją – zawiera wiadomości od użytkownika oraz informacje o modelu. Natomiast logiczna sesja zawiera informacje dotyczące zadań realizowanych przez narzędzie, postępu i planu działań. Należy zachować odpowiednie identyfikatory podczas przekazywania długich zadań.

## Organizować i znajdować odpowiednie zadania

Używaj projektów do grupowania powiązanych rozmów oraz ustawiania domyślnych uprawnień dla wszystkich urządzeń, które korzystają z tego projektu. Projekt może zawierać kilka oddzielnych czatów. Przenoszę lub tworzę czaty w odpowiednim projekcie, zamiast zakładać, że wszystkie rozmowy mają takie same uprawnienia. Aktywny projekt może informować agenta o strukturze tej rozmowy.

Tagi służą do klasyfikowania rozmów; znakowanie wiadomości pozwala na łatwe wyszukiwanie konkretnych informacji. To różni się od umieszczania rozmów w określonych miejscach na ekranie. Używaj tytułów rozmów, funkcji wyszukiwania, archiwizacji oraz oznaczeń „nieprzeczytanych” wiadomości, aby utrzymać uporządkowany wygląd ekranu.

Archyfikacja polega na przeniesieniu rozmowy z normalnej listy, bez usuwania jej zapisanej historii. Rozmowę można przywrócić z interfejsu archiwum, gdy to konieczne. Usunięcie rozmowy jest destruktywne; nie należy używać usunięcia jako alternatywy dla archyfikacji. Obecna implementacja korzysta z narzędzia SQLite do przechowywania informacji o rozmowach. Nie należy zakładać, że stary format archiwum Hosted Chat jest nadal używany.

## Operacje związane z wiadomościami oraz wykonywanie zadań

Dostępne opcje kontroli wiadomości zależą od tego, jakie są warunki realizacji danej wiadomości. W razie potrzeby można edytować lub ponownie wykonać określoną operację, albo usunąć wybrany użytkownik/assistenta, jeśli nie jest już potrzebny. Usuwanie zmienia historię rozmowy i może wpłynąć na późniejszy kontekst rozmowy. Usuwanie wiadomości nie może cofnąć wykonywanych poleceń, pisania zdalnego, aktualizacji w Git itp.

Podczas ponownego wykonania nieudanego zadania, należy najpierw przeczytać szczegółowe informacje o błędach i sprawdzić już wykonane operacje. Jeśli jakieś operacje mogły się powieść przed rozłąką, należy sprawdzić stan zewnętrzny przed ponownym wykonaniem tych operacji. Jeśli jest jeszcze jakieś wiadomości w kolejce do przetworzenia, lub jeśli proces generowania już trwa, należy użyć dostępnych kontroli i informacji o statusie, zamiast zakładać, że kilka operacji odbywa się jednocześnie w tym samym czasie. Panel z wiadomościami w kolejce pozwala na sprawdzenie będących w kolejce operacji; kontrola sterowania próbuje wprowadzić odpowiednie korekty po tym, jak obecnie wykonywane operacje się zakończą. Żadna z tych operacji nie powoduje cofnięcia efektów już wykonanych operacji.

## Pliki załączone, preview’y i inne pliki

Użyj narzędzia do kontrolowania plików w celu ich załadowania. Implementacja tego narzędzia ogranicza rozmiar pojedynczych plików do 32 MiB. Ograniczenia wynikające z procesu wydajania i żądań proxy mogą przeważnie ograniczyć rozmiar plików do mniejszej wartości. Załadowane pliki są przechowywane na serwerze Controller, a można do nich uzyskać dostęp za pomocą odpowiednich modeli. Do interpretacji obrazów potrzebny jest model oraz zespół narzędzi umożliwiających obsługę obrazów. Załadowanie plików nie oznacza udzielenia uprawnień do dostępu do lokalnych lub dalszych plików.

Podczas żądania pliku generowanego należy określić docelowy kierunek, format i treść pliku. Należy sprawdzić, czy plik już istnieje, zanim go udostępni się innym osobom. Można pobrać lub przesłuchać załączniki i inne pliki dostępne w chacie. Plik generowany na serwerze może być przekazany do kontrolera lub może istnieć jako odpowiedni link do pliku. Zobacz [Linki do plików](../guides/file-links.md).

Reprezentacja artefaktów może polegać na wyświetleniu elementów takich jak React, HTML, SVG, Markdown i Mermaid w specjalnym panelu bocznym, a nie tylko jako kod. W ustawieniach artefaktów typu „Normal” stosuje się standardowe instrukcje; w ustawieniach typu „shadcn/ui” dodaje się instrukcje dotyczące komponentów i bibliotek; w ustawieniach typu „Custom” kod jest reprezentowany bez użycia wbudowanej instrukcji. Kod generowany lub treść wyświetlana powinna być traktowana jako niepowierzona – należy ją przejrzeć przed jej wykorzystaniem poza okresem prezentacji. Prezentacje i pobrania plików związanych z biurami są odrębne od artefaktów interfejsu użytkownika generowanych przez system.

Nie wysyłaj żadnych danych, kluczy prywatnych ani dokumentów, których nie masz uprawnień do przesyłania do wybranego dostawcy modeli. Usunięcie załączników i danych komunikacyjnych jest odrębne od usunięcia plików źródłowych na komputerze.

## Preferencje

Preferencje użytkowników, takie jak przełączniki narzędzi i skróty klawiaturowe, są zarządzane za pomocą interfejsu WebUI. Te dane są przechowywane na serwerze, gdzie są one implementowane. W opcjach ustawień można konfigurować zachowanie klawiatury; należy odróżniać wysyłanie wiadomości od wpisywania spacji. Przełączniki narzędzi w czacie należy konfigurować osobno, w odniesieniu do uprawnień agenta. Zobacz [Narzędzia i uprawnienia](permissions.md) oraz [Pamięć i kontekst](context.md).
