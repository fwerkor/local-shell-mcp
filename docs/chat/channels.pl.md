<!-- i18n-source-sha256: a40a962d4db93cc0aac03601ffd13b21ab3a504c9bff930ab4b8173c4cfa4537 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Kanały i modele

## Ustawienia kanału

Otwórz moduł wyboru modeli w Chat i wpisz „Zarządzanie kanałami”. Wybierz opcję **Dodaj kanał**, wybierz typ połączenia, wpisz wymagane dane i zachowaj je. Następnie wybierz model odpowiedni dla tego kanału, aby utworzyć nowy czat. Jeśli chcesz użyć specjalnego agenta, wybierz kanał oraz model w konfiguracji agenta.

Kanale są własnością kontrolera, a nie osobistych użytkowników. W przypadku zautentowanej konfiguracji, zarządzanie kanalami wymaga dostępu do skopcji `admin:config`. Administrator może konfigurować wspólne kanale, bez konieczności dystrybucji kluczy API użytkownikom.

![Dodanie modelu do kanala w dialogu konfiguracji kanala](../assets/chat/channel-settings.png)

Normalny kanał API ma nazwę, protokół dostarczyciela danych, bazową adresę URL, kwalifikatory oraz identyfikatory modeli. Należy używać klucza API przyznanego dla wybranego punktu końcowego, a nie hasła z konta LSM. LSM wysyła żądania do Controller; adres URL, który funkcjonuje na laptopie, może nie funkcjonować w środowisku Controller.

| Protokół | Przykład bazowego adresu URL API | Użycie |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Kompatybilne z OpenAI bramki rozmowy i lokalne serwery wyobrażania |
| OpenAI Responses | `https://api.openai.com/v1` | Brama, która umożliwia korzystanie z API „Responses” |
| Antropiczny rodowity | `https://api.anthropic.com/v1` | API kompatybilne z narzędziami Anthropic |
| Natywny Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | API kompatybilne z funkcją generowania treści przez Gemini |

Należy używać podstawowego adresu URL wymaganego przez dostawcę, zamiast kopiowania pełnego adresu żądania generacji, np. adresu kończącego się na `/chat/completions`. Dostawca twierdzący, że jest kompatybilny z OpenAI, może obsługiwać tylko komponenty typu Chat Completions, a nie odpowiedzi, wywoływanie narzędzi, streamowanie danych, wielokomponentowe wejście lub opcje rozumienia tekstu. Należy wybrać protokół, który rzeczywiście jest obsługiwany przez dostawcę. Przykładowe adresy URL są tylko przykładami, a nie gwarancją bezpłatnego dostępu lub dostępności.

## Lokalne i specjalne punkty końcowe

Dla serwera kompatybilnego z OpenAI, który słucha na samej serwerce Controller, adres bazowy może być `http://127.0.0.1:8080/v1`Podczas uruchamiania w Docker, słowo „loopback” odnosi się do tego kontejnera, a nie do fizycznego hosta. Należy używać adresu dostępnego z sieci nazwowej kontrolera. Samo rejestracja bieżącego pracownika w domenie nie gwarantuje dostępu do jego API.

Validator adresu modelu wymaga protokołu HTTPS, z wyjątkiem przypadków, gdy chodzi o adresy typu HTTP na lokalnych hostach (`localhost`, `127.0.0.1`, `::1`). Adresy typu HTTP na lokalnych adresach lub nazwy usług w Docker muszą być udostępniane poprzez gateway HTTPS. Funkcja sterująca prywatnym adresem Chatu nie jest już dostępna. Podstawowe adresy URL nie mogą zawierać żadnych danych logowania, fragmentów tekstu ani ciągów zapytań.

Używaj protokołu TLS przy komunikacji z dalekimi końcówkami. Ogranicz dostęp do wiarygodnych, prywatnych serwerów. Sprawdź identyfikatory modeli przed ich użyciem na serwerze do wykonywania wykładni. Nigdy nie umieszczaj kluczy API w tekstach, screenshotach, ciągach zapytań czy publikowanych konfiguracjach. Pozostaw klucz API pusty podczas edycji istniejącego kanału, aby zachować jego dane przechowywane. Używaj połączeń bez klucza tylko wtedy, gdy usługa to umożliwia.

## Domynowe ustawienia środowiska

Wbudowany profil OpenAI można konfigurować przed uruchomieniem za pomocą `LOCAL_SHELL_MCP_MODEL_BASE_URL` (lub `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` oraz `LOCAL_SHELL_MCP_MODEL_API_KEY` (lub `OPENAI_API_KEY`). Wbudowane profile Anthropic i Google mogą korzystać z `ANTHROPIC_API_KEY` i `GOOGLE_KEY` / `GOOGLE_API_KEY`. Wbudowane profile mają pierwszeństwo nad domynowymi ustawieniami środowiska. Używaj kanałów nazwanych dla wielu niezależnych końcówek. Domynowe ustawienia środowiska nie są alternatywą dla ochrony tajemnic usługi.

## Autoryzacja konta ChatGPT

Kanał „Account/Codex” wykorzystuje autoryzację za pomocą aktywowanego konta ChatGPT, a nie zwykłego klucza API. Autoryzacę należy przeprowadzić poprzez zarządzanie kanałami i logowanie się na oficjalnej stronie autoryzacji. W przypadku lokalnego wdrożenia, zwrot danych może zostać zrealizowany automatycznie. Jeśli przeglądarce nie uda się dotrzeć do odbiornika danych, należy kopić całą adresę URL zwrotu danych i wkleić ją do okna dialogowego związanego z autoryzacją. W tym manualnym procesie może wystąpić błąd połączenia na stronie odbiornika danych.

Traktuj URL wywołania zwrotnego jak dane uwierzytelniające: nigdy nie przesyłaj go w rozmowie ani nie publikuj. Controller przechowuje autoryzację na serwerze i w miarę możliwości odnawia dane uwierzytelniające. Ponownie autoryzuj konto po wygaśnięciu lub cofnięciu dostępu. Dostępne modele, limity planu i dozwolone użycie określa nadrzędna usługa konta; LSM nie zapewnia dodatkowego limitu subskrypcji.

## Oznaczanie modeli i ograniczenia kontekstowe

Włącz automatyczne odkrywanie, aby uzyskać informacje o modelach od dostawcy. Kontroler aktualizuje te dane regularnie (obecnie co dziesięć minut); możliwe jest również manualne aktualizowanie danych. W przypadku niepowodzenia w odkrywaniu, dane z wcześniej zapisanych modeli pozostają zachowane. Jeśli dostawca nie posiada kompatybilnego endpointu do przesyłania listy modeli, wyłącz funkcję odkrywania i wprowadź identyfikatory modeli ręcznie, po jednym na wiersz.

Wykrywanie rozpoznaje jawne metadane okna kontekstu, w tym zagnieżdżone `limit.context` OpenCode Go/Zen, `context_length` OpenRouter, `max_model_len` vLLM i `inputTokenLimit` Gemini. Jeśli podano jedynie maksymalną długość wejścia, jest ona wartością zastępczą; limity wyjścia i nazwy modeli nie określają pojemności kontekstu. Bez obu informacji okno kontekstu pozostaje nieznane.

Należy określić okno kontekstowe dla każdego modelu, gdy jest to konieczne. Wartość wyraźnie określona dla każdego modelu zastępuje metadane znalezione wcześniej lub uzupełnia brakującą wartość. Edytor akceptuje te dane. 1 do 2,000,000 To jest tylko zakres konfiguracji, a nie gwarancja, że dany dostawca będzie w stanie obsłużyć taką liczbę użytkowników. Należy uwzględnić efektywny limit dostępny dla danej konfiguracji, a także ograniczenia związane z samym modelem.

## Próbkowanie, rozumowanie i wykorzystanie danych

Domynowe ustawienia kanału/modułu wpływają na parametry żądań obsługiwane przez wybrany dostawcę. Komponent do tworzenia czatów może ułatwić proces rozumowania, jeśli taki jest dostępny. Różne protokoły realizują procesy próbkowania i rozumowania na różny sposób. Może być tak, że dana opcja nie jest obsługiwana przez konkretny model. Należy zacząć od domynowych ustawień dostawcy, a następnie zmieniać jedną opcję na raz.

LSM może żądać dokładnych danych dotyczących zużycia tokenów, a także mogą być używane metody reagowania na sytuacje, gdy dostawca wyraźnie odrzuca tę opcję. Enpointy, które nie zwracają żadnych danych dotyczących zużycia zasobów, nie mogą dostarczyć dokładnych informacji o kosztach obsługi lub statystykach przechowywania danych w pamięci. Zobacz [Memory and context](context.md) dla informacji na temat różnicy pomiędzy skumulowanym zużyciem zasobów a aktualną pojemnością urządzenia.

## Zmiana i usunięcie kanałów

Rozmowa zachowuje swój wybrany model/agent oraz historię rozmowy. Model ten należy celowo zmieniać podczas zmian końców lub debugowania problemów z dostawcą usług. Przezwyciężenie kanału, który jest aktualnie używany, jest ograniczone w celu zachowania referencji do tego kanału. Usunięcie kanału wymaga dodatkowej potwierdzenia: historia rozmowy pozostaje, ale agenci i rozmowy odnoszące się do usuniętego kanala muszą wybrać inne kanał na wzór tym.

Ustawienia kanałów znajdują się na stronie serwera, a nie są to ustawienia dostępne tylko w przeglądarce. Dane logowania nie są przekazywane poprzez standardowe odpowiedzi z katalogu kanałów. Należy chronić katalog stanu kontrolera oraz pliki z plikami zastępczymi jako dane, które zawierają dane logowania.

## Lista spraw do sprawdzenia podczas połączenia

1. Upewnij się, że kontroler może dotrzeć do hosta API, a także że protokół TLS jest prawidłowo włączony.
2. Sprawdź nazwę ścieżki bazowej, protokół, dane logowania oraz dokładną identyfikator modelu.
3. Odśwież informacje o kanałach lub wprowadź manualnie informacje o modelu.
4. Wyślij krótkie powiadomienie w formie tekstu, a następnie sprawdź funkcjonalność małego polecenia.
5. Sprawdź szczegóły błędów: status HTTP, przerwanie połączenia, niezgodne opcje. Nie należy ponownie próbować logowania z nieprawidłowymi danymi.

Zobacz [Informacje dotyczące administracji i rozwiązywania problemów](administration.md) w celu uzyskania informacji na temat limitów przepływu danych, przerwań w streamowaniu oraz błędów autoryzacji.
