<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Agenty i umiejętności

## Kiedy należy utworzyć agenta?

Bezpośrednie rozmowy modelowe są przydatne przy jednorazowych pytaniach lub zadaniach. Agent to zapisywana konfiguracja, którą można wybierać wielokrotnie, używać w planowanych rozmowach lub powierzać innym agentom. Różni agenci mogą korzystać z różnych kanałów, modeli, instrukcji oraz zasad dostępu. Wszystkie agenci mają wspólny kontroler, ale niekoniecznie te same zakresy pamięci lub narzędzia.

## Konfiguracja agenta

Zarządzanie agentem z interfejsu wizualnego: utwórz agenta, nadaj mu rozpoznawalną nazwę oraz wybierz jego model. Zapisz instrukcje, które opisują zadanie, pożądaną wynik, ograniczenia oraz wymagania dotyczące weryfikacji. Skonfiguruj potrzebne możliwości agenta, a następnie zapisz i rozpocznij nową konwersację z nim.

![Agent Builder z instrukcjami, narzędziami, ustawieniami i umiejętnościami](../assets/chat/agent-builder.png)

Na przykład recenzent repozytorium może mieć następujące instrukcje:

```text
Sprawdź zmiany w stosunku do obecnej głównej wersji.
Sprawdź repozytorium oraz wyniki testów, zanim wyciągniesz jakieś wnioski.
Nie edytuj plików, nie przesyłaj zmian do repozytorium ani niczego innego.
Zgłaszaj konkretne ustalenia wraz z informacjami o drodze i dowodami.
```

Instrukcje służą do kierowania zachowaniem użytkownika, ale nie stanowią granicy uprawnień. Ustaw dostęp do urządzenia na tylko czytanie i pominij niepotrzebne możliwości eksternie dostępne dla użytkownika, jeśli recenzent nie chce niczego modyfikować. Zobacz [Narzędzia i uprawnienia](permissions.md).

Zaleca się wyznaczenie oddzielnych agentów do wykonywania różnych zadań, np. recenzji kodu, implementacji i obsługi operacyjnej. Należy zapewnić każdemu z nich minimalny poziom dostępu do danych, a także model odpowiedni do jego roli. Jeśli agent nie może się uruchomić, należy sprawdzić jego kanał komunikacyjny oraz model, zanim zmieni się jakieś ustawienia.

## Skills

Pakiet umiejętności zawiera ponownie wykorzystywane instrukcje oraz powiązane pliki. Zwykle są one udostępniane w formie… `SKILL.md` Zarządzanie umiejętnościami w interfejsie WebUI; aktywowanie odpowiednich umiejętności i udostępnianie ich agentowi lub użytkownikom, którzy korzystają z komunikatora. Model może odkrywać i załadowywać treść umiejętności w razie potrzeby. Umiejętność może opisywać procesy wykonywania zadań, zawierać przykłady lub skrypty; jednak nie wykonuje automatycznie tych skryptów ani nie udziela dodatkowych uprawnień maszynie.

Należy sprawdzić importowane umiejętności przed ich włączeniem do modelu. Traktuj instrukcje i pliki zawierające te umiejętności tak samo jak każdy inny kod lub instrukcje dostarczane przez stronę trzecią. Nazwy i opisy umiejętności muszą być wystarczająco specyficzne, aby model mógł je rozpoznać. Duże referencje należy trzymać osobno, natomiast preferujemy małe, niezależne i przydatne struktury działania. Informacje na temat rejestru strony Controller oraz wywoływanych przez narzędzie poleceń znajdują się w dokumentacji [Skills](../guides/skills.md).

Automatyczne umiejętności oraz kontekst pamięciowy są nagrywane w celu uniknięcia konieczności ponownego wpisywania poleceń systemu na każdym ruchu. Zmiany w zakresie umiejętności mogą mieć wpływ na efektywność działania systemu; podczas testowania nowo edytowanego kontekstu automatycznego należy używać nowego rozmowy. Umiejętności zainicjowane celowo różnią się od pierwotnego automatycznego stanu.

## Delegacja i podagenti

Agent może powierzyć zadanie podagentowi, gdy tylko ta możliwość jest dostępna. Dziecko może używać konfigurowanego agenta, ale przy tym zachować własny „wątek rozmowy”. Rodzic koordynuje zadanie, odczytuje wyniki dziecka i może kontynuować zapisaną strukturę wątku rozmowy. Działanie dziecka można sprawdzić z perspektywy rodzica; ta perspektywa nie stanowi osobnego, edytowalnego elementu komunikacji.

Należy korzystać z delegacji w przypadku zadań, które można rozdzielić na części – np. niezależne oceny, oddzielne obszary plików lub badanie różnych hipotez. Należy podać dziecku konkretny cel, zakres zadania i oczekiwany wynik. Unikać jednoczesnego wpisywania danych do tych samych plików, chyba że zadanie jest wyraźnie koordynowane przez rodzica.

Delegacja musi pozostać w granicach uprawnionych przez rodzica. Nie daje dostępu do maszyny ani do usług MCP, których rodzic nie może korzystać. Polityka akceptacji przez dzieci nie może osłabić polityki rodzica. Zadania dzieci mogą zużywać tokeny modelowe oraz czas w sposób niezależny od siebie. Dlatego należy sprawdzać ich działalność i wyniki podczas oceny kosztów i postępu pracy.

## Narzędzia, działania i artefakty

Builder Agent eksponuje swoją dostępną bibliotekę narzędzi oraz możliwości konfiguracji. Wybieraj tylko te funkcje, które są Ci potrzebne. W przypadku akcji HTTP opisanej za pomocą szablony OpenAPI, sprawdź endpolet, wymagania dotyczące autoryzacji oraz dopuszczalne operacje przed połączeniem z tą akcją. Akcje mogą mieć swoją własną metodę autoryzacji; uprawnienia maszyny nie upoważniają ani nie anulują kwalifikacji API strony trzeciej. Sprawdź odpowiedź akcji przed uznaniem zmiany w domenie za kompletną.

W przypadku generowanego treściu interfejsu użytkownika, należy ustawić odpowiednie parametry renderowania artefaktów, zgodnie z instrukcjami znajdującymi się w dokumentacji [Conversations and projects](conversations.md). Generowany kod nie stanowi wiarygodnego elementu struktury Controller.

## Praktyczne szablony agentów

- **Czytelny badacz:** sprawdź logi i źródła danych, porównaj dowody, zgłaszaj przyczyny problemów, bez możliwości modyfikacji.
- **Wdrożenie Agent:** edytowanie repozytorium, przeprowadzanie testów, raportowanie różnic i nierozwiązanych problemów; w przypadku operacji wrażliwych wymagana jest zgoda.
- **Agent monitoringu:** sprawdza określone maszyny i raportuje informacje o statusie, błahachach oraz postępach w realizacji zadań. Nie restartuje zadań, chyba że jest to wyraźnie dozwolone.
- **Agent badawczy:** umożliwia wyszukiwanie w sieci, cytowanie oryginalnych dokumentów, rozróżnianie dowodów od wniosków, a także wykorzystanie maszyn tylko wtedy, gdy to konieczne.

Takie szablony są jedynie instrukcjami, a nie wstępnie ustawionymi parametrami. Należy skonfigurować prawa i możliwości każdego agenta tak, aby pasowały do jego wyznaczonej roli.
