<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat to samodzielna przestrzeń do pracy z agentami AI, która jest wyposażona w narzędzia do zarządzania. Możesz używać własnego punktu dostępu do modelu lub aktywowanego konta. Model ma dostęp do twoich narzędzi i maszyn. Nie jest to konieczne korzystanie z zewnętrznego klienta MCP. Zewnętrzni klienty nadal mogą się połączyć z tym samym kontrolerze.

## Sposób, w jaki poszczególne elementy łączą się ze sobą

- **Controller:** usługa w języku Python, która zarządza aplikacją w przeglądarce, realizuje żądania użytkownika, obsługuje wykonywanie narzędzi, planowanie zadań oraz przechowywanie stałych wartości.
- **Channel:** połączenie API z modelami lub autoryzacja konta, z własnymi danymi logowania, protokołem, listą modeli i ustawieniami.
- **Model:** identyfikator modelu w danym kanalie. Ten sam identyfikator w dwóch kanałach nie oznacza tego samego punktu końcowego.
- **Agent:** Ponownie używalna konfiguracja, która obejmuje model, instrukcje, narzędzia, umiejętności oraz uprawnienia.
- **Rozmowa:** zachowane wiadomości, ustawienia, historia wykonywania zadań oraz informacje o powiązaniu modelu/agenta z danymi związanymi z tym modelem.
- **Project:** grupa konwersacji z wspólnymi ustawieniami.
- **Worker:** obiekt wykonywający zadania. Nie jest to dostawca modeli ani oddzielny serwer czatowy.
- **Logical Session:** identyfikator zadań realizowanych przez narzędzia, odrębny od identyfikatora konwersacji. Czat może używać tego identyfikatora do śledzenia celów, postępów i pracy z narzędziami.

API modelowe otrzymuje kontekst widoczny dla modelu oraz wyniki wykonywania zadań. Controller realizuje uprawnione narzędzia; model nie połącza się bezpośrednio z Worker ani nie uzyskuje klucza API do modelu. Przeglądarka prezentuje konwersację i kontroluje Controller.

## Wybierz przewodnika.

| Chcę… | Czytaj |
|---|---|
| Zainstaluj, zaloguj się i uruchom pierwszą zadanie. | [Wskazówki początkowe](../getting-started/web-workspace.md) |
| Połącz model API lub konta. | [Kanale i modele](channels.md) |
| Tworzenie ponownie używanych agentów oraz delegowanie zadań. | [Agenty i umiejętności](agents.md) |
| Zarządzanie chatami, plikami i projektami. | [Rozmowy](conversations.md) |
| Zrozumienie sposobu odzyskiwania historii oraz kontroli kontekstu. | [Pamięć i kontekst](context.md) |
| Ograniczyć wykonywanie i zarządzać narzędziami MCP | [Narzędzia i uprawnienia](permissions.md) |
| Wykonywanie długich zadań i planów | [Celów i automatyzacji](automation.md) |
| Wyszukiwanie w internecie i czytanie dokumentów | [Wyszukiwanie w sieci](../guides/webui-network-search.md) |
| Operowanie, tworzenie kopii zapasowej i debugowanie implementacji | [Administracja i rozwiązywanie problemów](administration.md) |

## Zasady podstawowe

Zacznij od prostego żądania typu „tylko do czytania” na znanym komputerze. Sprawdź wyniki narzędzia przed udostępnieniem modyfikacji. Model może być błędny, nawet gdy narzędzie funkcjonuje prawidłowo. Kryteria autoryzacji, przechowywanie danych, dostęp do komputera oraz zgoda na wykonywanie operacji są różnymi aspektami; zmiana jednego elementu nie automatycznie otwiera dostęp do drugiego. W szczególności publiczny punkt kontaktu powinien być chroniony jako element kontrolny dla wykonywania operacji w sieci.

W przypadku zewnętrznej ścieżki dostępu do klienta MCP, patrz [Kontakt z klientem](../clients/connectivity.md). Jeśli chodzi o argumenty narzędzia, którym korzysta się przy tym procesie, patrz [Referencja do narzędzi](../reference/tools.md).
