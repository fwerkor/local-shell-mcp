<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Połącz Gemini Spark / aplikacje niestandardowe

Funkcja **niestandardowych połączonych aplikacji** firmy Gemini (wcześniej opisana jako **Spark**) umożliwia uprawnionemu użytkownikowi Gemini połączenie się ze zdalnym serwerem MCP. LSM może zapewnić punkt końcowy MCP. Jest to **alternatywne połączenie klienta** z klientami [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) i innymi klientami MCP; nie zastępuje ani nie wdraża kontrolera LSM.

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

## Ograniczenia i rozwiązywanie problemów

- **Brak opcji aplikacji niestandardowych:** potwierdź uprawnienia konta, regionu, wieku, języka i funkcji Zachowaj aktywność. Jest to ograniczenie dostępności po stronie Gemini, a nie błąd konfiguracji LSM.
- **URL został odrzucony:** użyj zewnętrznego punktu końcowego HTTPS `/mcp`; sprawdź wykrywanie OAuth i odwrotne proxy.
- **OAuth nie powiódł się:** sprawdź ekran autoryzacji LSM, rejestrację klienta, adres URL wywołania zwrotnego i przyznane zakresy. Nie publikuj nieuwierzytelnionego punktu końcowego MCP.
- **Brak narzędzia lub jego awaria:** Obsługa narzędzi/schematów MCP po stronie klienta może się różnić. Wypróbuj proste połączenie tylko do odczytu i sprawdź audyt i dzienniki LSM; pełna kompatybilność z każdą funkcją klienta Gemini nie jest gwarantowana.
- **Rozłączanie:** wróć do **Połączonych aplikacji**, aby wyłączyć, odłączyć lub usunąć LSM, gdy nie jest już potrzebny.

[official guide](https://support.google.com/gemini/answer/17209137) firmy Google opisuje przepływ i dostępność najnowszych aplikacji niestandardowych. Zamiast tego, aby zapoznać się z lokalną integracją Gemini opartą na CLI, zobacz [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). LSM [ChatGPT connector tutorial](chatgpt-connector.md) pozostaje dostępny niezależnie.
