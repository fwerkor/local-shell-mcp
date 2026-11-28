<!-- i18n-source-sha256: 0d50677fe8bd21dbf6f3fff366adea800f15d50fdbc67ed3b77abf84437f73eb -->
# Połączenie Gemini Task / aplikacji niestandardowych

Funkcja **niestandardowych połączonych aplikacji** firmy Gemini umożliwia uprawnionemu użytkownikowi Gemini połączenie się ze zdalnym serwerem MCP. LSM może zapewnić punkt końcowy MCP. Jest to **alternatywne połączenie klienta** z klientami [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) i innymi klientami MCP; nie zastępuje ani nie wdraża kontrolera LSM.

Obecnie Google ogranicza dostęp do aplikacji niestandardowych dla **użytkowników w Stanach Zjednoczonych, którzy ukończyli 18 lat**, zalogowanych na **osobiste konto Google** i z włączoną opcją **Zachowaj włączoną aktywność**. Ta funkcja jest dostępna w **angielskim**. Połączenia należy nawiązać w aplikacji internetowej Gemini, chociaż z połączonych aplikacji można później korzystać na urządzeniach mobilnych. Etykiety dostępności i interfejsu użytkownika mogą ulec zmianie; sprawdź [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Przed podłączeniem

- Uruchom środowisko wykonawcze LSM, na przykład za pomocą [Docker Compose](../installation/docker.md) i sprawdź jego kondycję.
- Ujawnij jego punkt końcowy MCP za pośrednictwem **publicznie osiągalnego protokołu HTTPS** i włącz OAuth.
- Poznaj szczegóły uwierzytelniania Administratora i zatwierdzaj tylko te zakresy, których potrzebujesz.
- Użyj ograniczonego obszaru roboczego lub kontenera. Gemini może żądać operacji mających realny wpływ na pliki, maszyny i terminale.

Punkt końcowy, który należy wprowadzić w Gemini to:

```text
https://your-public-host.example.com/mcp
```

Nie wprowadzaj interfejsu internetowego (`/ui`), adresu URL LibreChat ani źródła witryny bez `/mcp`. Wdrożenia publiczne nie powinny wyłączać uwierzytelniania w celu obejścia błędów połączenia.

## Połącz się w Gemini

1. Na komputerze otwórz [Gemini](https://gemini.google.com/) i zaloguj się przy użyciu kwalifikującego się konta osobistego.
2. Otwórz **Ustawienia i pomoc → Połączone aplikacje**. W zależności od bieżącego interfejsu może znajdować się w obszarze **Inteligencja osobista → Połączone aplikacje**.
3. W sekcji **Aplikacje niestandardowe** wybierz **Dodaj aplikację niestandardową** lub użyj pola adresu URL aplikacji niestandardowej.
4. Wklej adres URL `/mcp` LSM HTTPS, a następnie wybierz **Dalej**.
5. Dokończ proces OAuth i zgody za pomocą kontrolera LSM. LSM obsługuje wykrywanie OAuth i dynamiczną rejestrację klienta. Jeśli zamiast tego Gemini zażąda ręcznych poświadczeń klienta OAuth, przed kontynuowaniem sprawdź jego opcje zaawansowane i konfigurację LSM OAuth.
6. W rozmowie Gemini wpisz `@` i wybierz podłączoną aplikację niestandardową, aby zażądać narzędzia LSM.

Zacznij od: "Użyj połączonej aplikacji LSM, aby sprawdzić środowisko i wyświetlić listę plików obszaru roboczego. Nie modyfikuj niczego. " Przed przystąpieniem do operacji zapisu sprawdź wyniki narzędzia i audyt kontrolera.

## Tryb Task (dawniej Spark)

Do wieloetapowego programowania, debugowania i utrzymania serwerów zalecamy **Task** zamiast zwykłego czatu: pozwala planować pracę, wielokrotnie używać narzędzi i śledzić postępy. Nie jest to gwarancja zmierzonej szybkości ani jakości.

Na stronie głównej Gemini wybierz **Task** pod polem tekstowym i w razie potrzeby ukończ konfigurację. Wpisz `@`, wybierz LSM, jeśli jest dostępny, i podaj cel, maszynę lub obszar roboczy oraz kryteria ukończenia.

Przykład: „Użyj LSM, aby sprawdzić repozytorium, odtworzyć błąd testu, usunąć przyczynę i ponownie uruchomić testy. Podaj zmienione pliki i wyniki”.

Śledź postęp i zatwierdzaj wymagane działania. Sprawdź wywołania LSM w dzienniku audytu Controller: komputer chmurowy Gemini nie jest Twoim obszarem LSM. Controller i potrzebne Worker muszą być online. Task i aplikacje niestandardowe mają odrębne wymagania; jeśli brakuje opcji, sprawdź [oficjalny przewodnik Task](https://support.google.com/gemini/answer/17094507).

## Ograniczenia i rozwiązywanie problemów

- **Brak opcji aplikacji niestandardowych:** potwierdź uprawnienia konta, regionu, wieku, języka i funkcji Zachowaj aktywność. Jest to ograniczenie dostępności po stronie Gemini, a nie błąd konfiguracji LSM.
- **URL został odrzucony:** użyj zewnętrznego punktu końcowego HTTPS `/mcp`; sprawdź wykrywanie OAuth i odwrotne proxy.
- **OAuth nie powiódł się:** sprawdź ekran autoryzacji LSM, rejestrację klienta, adres URL wywołania zwrotnego i przyznane zakresy. Nie publikuj nieuwierzytelnionego punktu końcowego MCP.
- **Brak narzędzia lub jego awaria:** Obsługa narzędzi/schematów MCP po stronie klienta może się różnić. Wypróbuj proste połączenie tylko do odczytu i sprawdź audyt i dzienniki LSM; pełna kompatybilność z każdą funkcją klienta Gemini nie jest gwarantowana.
- **Rozłączanie:** wróć do **Połączonych aplikacji**, aby wyłączyć, odłączyć lub usunąć LSM, gdy nie jest już potrzebny.

[official guide](https://support.google.com/gemini/answer/17209137) firmy Google opisuje przepływ i dostępność najnowszych aplikacji niestandardowych. Zamiast tego, aby zapoznać się z lokalną integracją Gemini opartą na CLI, zobacz [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). LSM [ChatGPT connector tutorial](chatgpt-connector.md) pozostaje dostępny niezależnie.
