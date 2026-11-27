<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Narzędzia, komputery i uprawnienia

## Warunki autoryzacji

Lista dostępnych narzędzi nie gwarantuje uprawnień do ich wykonywania. Efektywne uzyskanie uprawnień wymaga uwzględnienia ograniczeń związanych z kontrolerami, dostępów danej osoby, polityki urządzenia, możliwości narzędzia oraz zgody innych osób. Samych instrukcji nie wystarczy, aby zapewnić dostęp do narzędzi.

Zarejestrowane maszyny, w tym również lokalny cel kontrolera, gdy jest aktywny, mają podstawowo możliwość czytania i zapisu danych w ramach polityki maszyny do komunikacji. Należy ograniczyć te domyślne możliwości w przypadku potencjalnie niebezpiecznych implementacji. Nazwy nieznanych maszyn nie uzyskują żadnych uprawnień. Kontroler może wyłączyć realizację zadań lokalnie lub w odległych miejscach.

## Dostęp do maszyny

| Access | Znaczenie |
|---|---|
| Żadne | Operacje związane z maszyną są niedostępne |
| Tylko do odczytu | Dozwolone są tylko te operacje, które są klasyfikowane jako tylko czytelne; dowolne wykonywanie poleceń w shellu lub Python nie jest operacją tylko czytelną. |
| Czytaj/pisz | Dostępne są operacje czytania, modyfikowania i wykonywania danych, pod warunkiem przestrzegania innych ograniczeń. |
| Dziedzicz | Należy użyć odpowiedniej polityki o wyższym poziomie niż wyraźne przekierowanie uprawnień. |

![Uprawnienia i tryb akceptacji maszyny w kontekście rozmowy](../assets/chat/machine-permissions.png)

Ustaw globalne wartości domyślne oraz nadpisania dla projektu i poszczególnych rozmów w ustawieniach uprawnień maszyn. Nadpisania rozmowy mają pierwszeństwo przed ustawieniami projektu, a te przed wartościami globalnymi. Agent może dodatkowo ograniczyć dostęp do poszczególnych maszyn lub przez własną politykę domyślną; jawne uprawnienia Agenta nie omijają ograniczeń uwierzytelnionej tożsamości ani Controllera.

Przykład: globalna polityka odczytu i zapisu, nadpisanie projektu na tylko odczyt i uprawnienia Agenta do odczytu i zapisu dają dostęp tylko do odczytu w rozmowie projektu, chyba że polityka rozmowy jawnie go nadpisze. Nadpisanie rozmowy na odczyt i zapis nadal nie może przekroczyć ograniczenia Agenta do odczytu.

Planowany wykonanie zadania przy użyciu określonego agenta polega na wykorzystaniu polityki maszyny tego agenta oraz zapisanych zakresów wykonywania zadań, zamiast dziedziczenia standardowych ustawień maszyny do komunikacji. Zobacz [Cel i automatyzacja](automation.md). Użyj specjalnego agenta do wykonywania zadań bez nadzoru.

## Akceptacja narzędzia

| Tryb | Zachowanie |
|---|---|
| Automatyczny | Wyrażone żądania są realizowane bez dodatkowego potwierdzenia, chyba że istnieje inna polityka wymagająca takiego potwierdzenia. |
| Przejrzyj ryzykowne operacje | Controller prosi o zrecenzowanie operacji uznanych za niebezpieczne, w tym dowolnych poleceń w środowisku i wielu wywołań z zewnątrz. |
| Przejrzyj wszystkie narzędzia | Prosimy o zatwierdzenie standardowych działań narzędzi. |

Ustawienia zatwierdzania rozmowy mogą dziedziczyć wartości domyślne Agenta i globalne. Istniejące jawne reguły odmowy lub zatwierdzania pozostają w mocy. Agent podrzędny nie może złagodzić trybu zatwierdzania Agenta nadrzędnego. Zatwierdzanie jest niezależne od uprawnień: zatwierdzenie zabronionej operacji na maszynie nie nadaje dostępu do niej.

Należy dokładnie przemyśleć argumenty, cel realizacji procesu oraz potencjalne negatywne skutki po jego zatwierdzeniu. W przypadku niezabezpieczonego procesu realizacji, należy starannie ustalić parametry agenta i politykę aprobaty. Aprobaty wymagane przez ludzi mogą utrudniać postęp w realizacji procesu. Nie należy rozszerzać uprawnień tylko po to, aby usunąć potencjalne problemy.

## Pouwno i zewnętrzne narzędzia MCP

Narodowe narzędzia pracują z Controller oraz z zarejestrowanymi Workers za pośrednictwem LSM. Rejestr narzędzi obejmuje operacje związane z plikami, operacje w środowisku shell i jobów, operacje w przeglądarce i interfejsie graficznym, rozwiązywanie problemów na odległość, sesje logiczne oraz inne funkcje. Aby dowiedzieć się szczegółowych informacji o schemacie argumentów, proszę skorzystać z [Referencji narzędzi](../reference/tools.md). Jeśli chcesz dowiedzieć się, jak połączyć maszyny, proszę skorzystać z [Remote workers](../guides/remote-workers.md).

Zarządzanie zamkniętymi serwerami MCP w interfejsie WebUI. Wspierane konfiguracje obejmują lokalne środki przesyłania danych typu stdio oraz odległe środki przesyłania danych typu HTTP. Serwery te mogą mieć specjalne zmienne środowiskowe lub nagłówki. Możliwe jest włączenie funkcji MCP zewnętrznej w czatach oraz w odpowiednim agentach. Agent może odkrywać, inspektować i wykorzystywać dostępne narzędzia zewnętrzne; autoryzacja i aprobatacja tych narzędzi nadal obowiązują.

Zewnętrzne narzędzie MCP może działać niezależnie od natywnych ACL maszyn: zewnętrzny zdalny interfejs API może modyfikować zasoby nawet przy wyłączonym dostępie do maszyn lokalnych. Sprawdź osobno uprawnienia i dane uwierzytelniające zewnętrznej usługi. Nie instaluj niezaufanych serwerów stdio na Controllerze zawierającym poufne pliki.

## Prośba użytkownika i ustawienia funkcji

Ask User umożliwia agentowi składanie strukturyzowanych zapytań, zamiast próbowania przewidywania odpowiedzi. Wszystko to jest prośbą o informacje, a nie pozwoleniem na obejście odmownej reakcji narzędzia. Gdy zadanie pozostaje bez opieki, należy instruować agenta, jak radzić sobie z niepewnością i sprawdzać potencjalne interakcje, zanim przyjmiemy, że zadanie zostało ukończone.

Compozytor opisuje różne funkcje kontrolne, takie jak wyszukiwanie w sieci, dostęp do zewnętrznych danych MCP oraz pamięci. Te funkcje określają, które możliwości są dostępne dla modelu. Są one oddzielone od procesu autoryzacji. Wyłączenie jakiejś funkcji nie usuwa historii wyników. Wyszukiwanie w sieci jest włączone podstawowo i wykorzystuje tylko narzędzia do czytania danych, jak opisano w [Wyszukiwanie w sieci](../guides/webui-network-search.md).

## Audyt i verifikacja

Sprawdź wywoływania narzędzi oraz ich rezultaty w chacie komunikacyjnej; rozszerzaj szczegóły wtedy, gdy diagnozujesz błędy. Log kontrolera zapisuje aktywność narzędzi, a zadania/sesje pokazują proces realizacji zadań. Udział narzędzia w procesie realizacji zadań oznacza, że narzędzie oddało jakieś rezultaty, ale to nie koniec sprawy – nie musi to oznaczać, że zamierzony efekt został osiągnięty. Sprawdź również informacje dotyczące zapisów, statusu zadań w domenie remote oraz stanu rozwiązania problemów. Zobacz [Log kontrolera](../guides/audit-log.md).
