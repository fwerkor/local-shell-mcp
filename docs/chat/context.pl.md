<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Pamięć, kontekst i zużycie tokenów

## Trzy różne rodzaje stanu

| Stan | Cel |
|---|---|
| Historia rozmów | Oryginalne wiadomości i informacje o działaniu narzędzi przechowywane przez Kontrolera |
| Okno kontekstowe | Podzbiorek instrukcji, schematów narzędzi, historii, podsumowań i innych danych przesyłanych w ramach konkretnego zapytania modelu |
| Pamięć przetwarzana | Fakty i preferencje, które mogą być wykorzystywane w różnych rozmowach, w obrębie odpowiedniej pamięci |

Długa historia rozmowy może przekraczać limit okna kontekstowego modelu, bez utraty całej historii rozmowy. Pamięć nie oznacza, że cała historia konta jest przesyłana do każdego zapytania modelu.

## Zarządzanie pamięcią

![Panel zarządzania pamięcią z przykładowym wpisem](../assets/chat/memory-management.png)

Pamięć jest włączona podstawowo, chyba że użytkownik jej wyłączy według ustawień, opcji konta czatu lub ograniczeń związanych z funkcjami Agent. Można korzystać z strony zarządzania pamięcią, aby przeglądać i edytować przechowywane dane. Prosić Agent, aby zapamiętał przydatne informacje, zasady projektowe lub preferencje użytkownika. Następnie sprawdzić wyniki w interfejsie pamięci.

Podczas edycji wpisów związanych z pamięcią, należy używać kluczy składających się wyłącznie z liter małych i podkresekowanych liter (np. `repository_conventions`). Limit długości wpisu wynosi 10 000 znaków; instalacja może ustalić inne ograniczenia dotyczące przechowywania danych w pamięci. Jeśli jakiś wpis zostanie odrzucony, należy sprawdzić przyczynę błędu, zamiast rozkładać poufne informacje na kilka kluczy.

Pamięć może korzystać z wspólnego zbioru danych dla wszystkich agentów, lub z specjalnego obszaru dostępnego tylko dla danego agenta, w zależności od konfiguracji agenta. Nie przechowywaj kluczy API, hasel ani innych niepotrzebnych danych wraz z pamięcią. Wyłączenie pamięci uniemożliwia jej wykorzystanie w odpowiednim obszarze; to nie jest to samo co usunięcie istniejących wpisów z pamięci lub wykreślenie informacji z historii rozmów.

Gdy model jest eksponowany, używa funkcji `set_memory` do tworzenia lub aktualizowania danych; pusta wartość usuwa te dane. Funkcja `find_memory` pobiera dane na podstawie zapytania lub dokładnego klucza, a puste zapytanie pokazuje wszystkie zapisane dane. Opcjonalny flag `include_conversations` umożliwia wyszukiwanie tekstu z innych rozmów. Paginacja odbywa się za pomocą parametrów `page` (domyślnie 1) i `limit` (domyślnie 10, maksymalnie 50). W tym przypadku wyszukiwanie odbywa się na podstawie tekstu rozmowy, a nie na podstawie zapisanych danych. Wyniki są sortowane według wagi relevancji, więc należy używać precyzyjnych nazw lub terminów oraz dostosować zapytanie w razie potrzeby.

Automatyczne wstawianie informacji o pamięci i umiejętnościach pozostaje stabilne w trakcie rozmowy, aby zachować możliwość ponownego używania prefiksów poleceń dostarczanych przez dostawcę usług. Edycja zapisanych informacji nie powoduje rejestracji nowych danych w formie „snapshot”. Wyjście na nową rozmowę jest możliwe, jeśli potrzebny jest nowy kontekst.

## Pojemność kontekstu

Należy określić rzeczywiste ograniczenia kontekstowe dla każdego modelu w jego kanałach. Kontroler szacuje wartość wejściowych danych widocznych dla modelu i rezerwuje miejsce na wyjściowe dane. Obecna implementacja budżetu przyjmuje domyślnie współczynnik skompresowania wynoszący 85%, a współczynnik rezerwy – 5%. Wartość ta może być aproksymowana w przypadku nieznanych algorytmów tokenizacji, złożonych żądań lub specyficznych składni dostawców.

Kompozycja kontekstu może obejmować instrukcje systemowe, konfigurację agentów, definicje narzędzi, pliki dodatkowe, wcześniejsze wiadomości oraz wyniki działania narzędzi. Dostawca może używać innego algorytmu do rozpoznawania znaków lub liczyć dodatkowe elementy wewnętrzne. Traktuj to wyświetlenie jako instrukcje operacyjne, a nie jako gwarancję dostawcy.

## Automatyczna kompresja

Gdy budżet kontekstu wymaga usprawnienia, kontroler tworzy lub aktualizuje streszczenie danych z wcześniejszych operacji, a także zachowuje najnowsze informacje na potrzeby późniejszych żądań modelu. Streszczenie to starannie przechowuje cele, ograniczenia, decyzje, postępy, relevantne identyfikatory, wyniki operacji oraz kolejne kroki wdrożenia. Oryginalne dane są nadal dostępne do sprawdzenia; streszczenie jest natomiast aproksymacją generowaną przez model, a nie doskonałym odwzorowaniem rzeczywistości.

Przetwarzanie danych odbywa się przed następnym żądaniem, w którym potrzebny jest zmniejszony kontekst. Jeśli proces przetwarzania nie udaje się, narzędzie próbuje ponownie wykonać operację zgodnie z mechanizmem obsługi błędów. Nie należy po prostu kontynuować procesu przetwarzania przy użyciu już nadmiernie dużego obrazu danych. Należy sprawdzić status przetwarzania i szczegółowe informacje o błędach, jeśli proces nie może kontynuować. Ostatnie wiadomości oraz relacje pomiędzy narzędziami i wynikami muszą pozostać spójne. Wyniki wcześniej ukończonych operacji nie powinny być ponownie przetwarzane tylko po to, aby zmniejszyć rozmiar kontekstu.

Jedno duże pliku lub wynik działania narzędzia może nadal przekraczać ustaloną granicę. Prosimy o ograniczenie ilości danych, zakresy plików lub dostarczenie tylko podstawowych informacji. Wyniki powinny być przechowywane w oddzielnych plikach, a konkretne informacje mogą być pobrane po upływie czasu.

## Kumulatywna ilość wykorzystywanych danych oraz liczba odniesionych sukcesów w przechowywaniu danych są istotne.

Wyświetlanie informacji o zużyciu zasobów i okna kontekstowego odpowiadają różnym pytaniom. Zużycie danych przyczynia się do gromadzenia się informacji w ramach poszczególnych żądań, w tym także powtarzających się elementów kontekstu. Wskaźniki przechowywania danych opisują tęczę danych przechowywanych przez dostawcę, jeśli są dostępne. Liczba wykorzystanych danych określa poziom aktywności modelu, a nie liczbę żądań z przeszłości.

Na przykład żądanie zawierające 20 000 tokenów, po którym następuje kolejne żądanie z 25 000 tokenami, zużywa 45 000 tokenów. Natomiast drugie żądanie wykorzystuje około 25 000 tokenów z aktualnego kontekstu modelu. Tokeny przechowywane w pamięci nie są darmowe, chyba że dostawca określa inaczej. Większy limit kontekstu modelu zmienia poziom aktywności modelu, ale nie zmienia ilości danych wykorzystanych wcześniej.

Compaction może zmniejszyć aktualną liczbę użytkowników, jednocześnie zwiększając zużycie zasobów modelu. Zmiana modelu zmienia ograniczenia dotyczące jego funkcjonowania; nie usuwane są jednak dane dotyczące wcześniejszego zużycia zasobów. Jeśli dostawca opisuje dokładne dane dotyczące zużycia lub metadanych pamięci przetwarzającej, szacunki i wskaźniki mogą być niekompletne. W celach rozliczeń finansowych należy używać danych billingowych oraz cen dostawcy, a nie tylko informacji przedstawionych w wykresach LSM.

## Zmniejszyć koszty i zachować przydatne informacje.

Należy utrzymać stabilną strukturę instrukcji agenta, unikać niepotrzebnego wydawania dużych ilości danych i korzystać z efektywnych metod przechowywania informacji. Należy również otworzyć osobne rozmowy na tematy, które nie są ze sobą powiązane. Gdy konieczna jest przekazanie informacji innemu użytkownikowi, należy zapisać skrót pliku zawierający dokładne informacje o drodze postępowania, identyfikatory obiektów, uzyskane wyniki oraz pozostałe informacje. Ważne jest, aby sprawdzić ważne fakty na podstawie oryginalnych danych lub wyników generowanych przez narzędzie, a nie polegać wyłącznie na sporządzonym streszczeniu.
