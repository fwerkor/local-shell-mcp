<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Szybki start w usłudze WebUI Chat

Jednolite środowisko robocze LSM integruje funkcję rozmowy za pomocą AI, projekty, agentów oraz strony operacyjne kontrolera. Środowisko to jest obsługiwane przez kontroler w języku Python, który wykorzystuje jego mechanizmy autencjalizacji i bazę danych SQLite. Nie jest potrzebny żaden oddzielny serwer do obsługi rozmów. Klienty zewnętrzne, takie jak [ChatGPT](chatgpt-connector.md) i [Gemini](gemini-spark.md), nadal są obsługiwane.

## 1. Uruchom Controller

Korzystaj z instrukcji [instalacji w prosty sposób](quickstart.md) według Twoich preferencji. Upewnij się, że interfejs WebUI jest aktywny, a także użyj danych przechowywanych na stałe. Poniżej przedstawiono standardowe ustawienia.

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Po eksportowaniu środowiska serwisowego, uruchom kontroler.

```sh
local-shell-mcp --mode mcp
```

W przypadku używania wersji z jedną kolejnością uruchomienia, należy użyć pobranego pliku wykonywalnego. Zainstalowany Controller służy jako element kompilowanego frontendu; narzędzie do budowy kodu JavaScript jest potrzebne tylko przy tworzeniu kodów źródłowych. Zobacz instrukcje dotyczące budowy WebUI: [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Otwórz przestrzeń roboczą w przeglądarce

Otwórz stronę `http://127.0.0.1:8765/ui` z hosta kontrolera, lub konfigurowanej adresy HTTPS kończącej się na `/ui`. Loguj się za pomocą autencji LSM przygotowanej dla tej implementacji. Użyj autoryzowanego dostępu przez HTTPS do uzyskania dostępu zdalnego. Strony czatu i kontroli mają tę samą pochodną.

## 3. Dodaj kanał modelu

Otwórz menu sterujące kanałami modelowymi. Dodaj kanał API lub połącz z aktywnym kontem. Aby uzyskać dostęp do typowego endpointu OpenAI, wpisz nazwę kanału, wybierz opcję Chat Completions, podaj bazową URL-ową i kwalifikacje API, a następnie sprawdź modele lub podaj identyfikator modelu. Zapisz konfigurację i wybierz model.

Dla usługi wnioskowania lokalnego należy użyć adresu dostępnego z Controller, a nie tylko adresu twojego przeglądarki. Na przykład `http://127.0.0.1:8080/v1` jest odpowiedniym adresem, jeśli usługa wnioskowania słucha na tym adresie w lokalnym nazewnictwie sieciowego Controller. Zobacz [Kanale i modele](../chat/channels.md) w celu informacji o protokole, autoryzacji konta, odkrywaniu modeli oraz ograniczeniach kontekstu.

## 4. Wykonaj pierwsze zadanie

Uruchom rozmowę i zadaj proste pytanie, aby sprawdzić połączenie z modelem. Następnie spróbuj wykorzystać narzędzie tylko do czytania:

```text
Wszystkie pliki znajdują się w korzeniu środowiska Controller.
Podaj informacje o maszynie, na której przeprowadzono inspekcję, oraz podsumuj wyniki.
Nie modyfikuj plików ani nie wykonuj żadnych operacji zapisu danych.
```

Sprawdź rzeczywisty wynik użycia narzędzia. Jeśli jakieś narzędzia brakuje, sprawdź ustawienia narzędzi w chacie, ustawienia agenta oraz uprawnienia maszyny. Użyj zapisanego agenta do wykonywania powtarzających się zadań i konfiguruj jego dostęp wyraźnie. Zobacz [Narzędzia i uprawnienia](../chat/permissions.md).

![Rozmowa w interfejsie WebUI z demonstracyjną konwersacją](../assets/chat/chat-workspace.png)

Przykładowe zrzuty ekranu w tym przewodzie oraz na kolejnych stronach zostały uzyskane przy użyciu izolowanego Controller z modelem demonstracyjnym. Zrzuty te nie zawierają żadnych danych osobowych ani informacji dotyczących produkcji. Nacięcia na interfejsie w języku angielskim mogą się różnić od nacięgów w wybranym języku.

## 5. Poznaj przestrzeń roboczą

| Obszar | Na co można go używać |
|---|---|
| Chaty i projekty | Uruchomienie i wyszukiwanie chatek, organizowanie projektów, tagów oraz znaków informacyjnych w wiadomościach |
| Agents | Ponownie wykorzystywane modele, instrukcje oraz konfiguracje narzędzi |
| Pamięć i umiejętności | Zarządzanie ponownie wykorzystywaną wiedzą i instrukcjami |
| Chaty planowane do realizacji | Prowadź zachowany agenta przy wielokrotnych powtórzeniach polecenia. |
| Pliki i terminale | Sprawdzanie lub operacja w środowiskach Controller i Worker. |
| Biurko komputerowe | Inspekcja i kontrola obsługiwanych sesji graficznych na dalekiej odległości |
| Sesje, zadania i audyt | Inspekcja trwałych zadań, postępu w realizacji oraz aktywności narzędzi |
| Maszyny i zewnętrzne MCP | Zarządzanie pracownikami oraz serwerami MCP zamkniętymi w strukturze MCP. |

Sposób realizacji kontroli zależy od sposobu rozpowszechnienia systemu, konta użytkownika oraz dostępnych możliwości. Zamykanie przeglądarki nie wymawia samoistnie procesu generowania danych na stronie serwera; należy użyć funkcji zamykania, gdy chcemy przerwać pracę.

## Kolejne kroki

Aby poznać pełny przepływ informacji, prosimy o zapoznanie się z [przewodnikiem dotyczącym interfejsu WebUI Chat](../chat/index.md). Informacje dotyczące administracji i rozwiązywania problemów znajdziesz w [Administration and troubleshooting](../chat/administration.md).
