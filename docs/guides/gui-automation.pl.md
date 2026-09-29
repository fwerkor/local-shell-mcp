<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Automatyzacja GUI pulpitu

`local-shell-mcp` może obserwować i sterować natywnymi aplikacjami desktopowymi w Linux, Windows i macOS. Publiczny interfejs celowo pozostaje niewielki:

| Narzędzie | Zastosowanie |
|---|---|
| `gui_list` | Wyświetla widoczne okna aplikacji oraz aktywny natywny backend i jego możliwości. |
| `gui_state` | Obserwuje jedno okno. Zwraca krótkotrwały `state_id`, elementy dostępności, geometrię okna i opcjonalnie natywny zrzut ekranu MCP. |
| `gui_action` | Wykonuje akcje semantyczne lub współrzędnościowe względem dokładnie tej obserwacji. |

Wszystkie trzy narzędzia przyjmują opcjonalny parametr `machine`, dzięki czemu ten sam przepływ może działać na podłączonym workerze z pulpitem.

## Najpierw obserwuj, potem działaj

Zacznij od `gui_list`, wybierz `window_id`, a następnie wywołaj `gui_state`. Jeśli zwrócony `element_id` dostępności odpowiada docelowemu kontrolkowi, używaj go w pierwszej kolejności:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Współrzędnych `x`/`y` względem okna używaj tylko wtedy, gdy interfejs nie udostępnia użytecznego elementu dostępności, np. dla canvas lub własnoręcznie rysowanego kontrolka. Zwracane granice elementów i zrzuty ekranu używają tej samej przestrzeni logicznych pikseli względem okna, także na pulpitach HiDPI/Retina. Surowe współrzędne poza wybranym oknem są odrzucane.

`state_id` wygasa po 30 sekundach i jest jednorazowy. Akcje współrzędnościowe sprawdzają również, czy od chwili obserwacji okno nie zostało przesunięte ani przeskalowane. Jeśli którykolwiek warunek nie jest spełniony, wywołaj `gui_state` ponownie zamiast używać starych współrzędnych.

Obsługiwane akcje to `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` i `wait`.

## Sterowanie ręczne w Native WebUI

Native WebUI zawiera stronę **Desktop** do bezpośredniego sterowania tymi samymi natywnymi backendami GUI. Wybierz maszynę i okno, a następnie używaj obrazu okna do klikania, podwójnego kliknięcia, prawego przycisku, przeciągania, kółka, skrótów klawiaturowych lub pola tekstowego dla wejścia IME/CJK.

Ta ścieżka jest celowo oddzielona od semantyki modelowego `state_id`. Każda wyświetlana klatka zawiera zaobserwowaną geometrię okna; każde żądanie wejścia użytkownika sprawdza przed wstrzyknięciem, czy geometria nadal jest identyczna. Jeśli okno zostało przesunięte, zmieniono jego rozmiar lub zniknęło, akcja jest odrzucana, a WebUI odświeża obserwację. Surowe współrzędne pozostają ograniczone do wybranego okna.

Akcje klawiatury i tekstu jawnie ustawiają fokus na wybranym natywnym oknie przed wstrzyknięciem. WebUI używa lekkiego odpytywania zrzutów ekranu zamiast transmisji VNC/WebRTC; zdalny RPC `gui_human_action` jest wewnętrzną operacją controller-worker, a nie narzędziem MCP udostępnianym modelom.

## Natywne backendy

| Platforma | Dostępność / sterowanie semantyczne | Przechwytywanie i surowe wejście |
|---|---|---|
| Windows | Microsoft UI Automation | Przechwytywanie okna oraz natywne wejście myszy i klawiatury Windows |
| macOS | Accessibility (`AXUIElement`) | `screencapture` dla wybranego okna oraz wejście Quartz `CGEvent` |
| Linux | AT-SPI | Natywne wejście/przechwytywanie X11; Wayland używa natywnego przechwytywania pulpitu oraz XDG Desktop Portal RemoteDesktop/ScreenCast |

Jeśli to możliwe, najpierw próbowane są akcje semantyczne. Przycisk z natywną akcją invoke/press można więc aktywować bez zgadywania współrzędnej piksela. Współrzędne wizualne pozostają rozwiązaniem awaryjnym dla niedostępnej lub własnoręcznie rysowanej zawartości.

## Konfiguracja platformy

### Windows

Uruchamiaj LSM w tej samej interaktywnej sesji pulpitu co aplikacje, którymi ma sterować. Podstawowa instalacja `local-shell-mcp` jest bezpieczna w trybie headless i nie wymaga adaptera Windows UI Automation; opcjonalne `local-shell-mcp[gui]` instaluj tylko wtedy, gdy potrzebne jest lokalne sterowanie GUI Windows.

### macOS

Nadaj procesowi hosta LSM:

- uprawnienie **Dostępność** do sterowania semantycznego i wejścia;
- uprawnienie **Nagrywanie ekranu** do zrzutów ekranu.

Pakiet podstawowy nie wymaga PyObjC. Opcjonalne `local-shell-mcp[gui]` instaluj tylko dla lokalnego sterowania GUI macOS; maszyny, które nigdy nie używają narzędzi GUI, nie potrzebują tych frameworków.

### Linux

Sesja pulpitu musi udostępniać AT-SPI. W Debian/Ubuntu wymagane bindingi systemowe są zwykle dostępne po:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Pakiet podstawowy nie wymaga adapterów Python X11 ani D-Bus. Opcjonalne `local-shell-mcp[gui]` instaluje je do lokalnego użycia GUI. Zdalne workery wykrywają aktywną sesję Linux przed bootstrapem zależności GUI: X11 wymaga tylko adaptera X11, Wayland tylko adaptera D-Bus, a worker headless nie instaluje żadnego z nich. Na Wayland awaryjne surowe wejście wskaźnika/klawiatury używa API XDG Desktop Portal RemoteDesktop, dlatego pulpit może jednorazowo wyświetlić wybór uprawnienia/sesji. Obsługiwane są implementacje portalu KDE i GNOME. Zrzuty okna korzystają z dostępnej natywnej ścieżki przechwytywania, a w razie potrzeby z portalu Screenshot.

Workery LSM często uruchamiają się poza środowiskiem graficznego logowania. Backend Linux odzyskuje `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` i powiązane zmienne ze środowiska systemd użytkownika, jeśli nie zostały bezpośrednio odziedziczone.

## Zdalne pulpity

Narzędzia GUI działają na wybranej maszynie, a nie na controllerze. Zdalny worker musi należeć do użytkownika/sesji będącej właścicielem docelowego pulpitu. Adaptery GUI są ładowane leniwie i dotyczą tylko wywołań GUI: zwykły start workera oraz użycie shell/files/browser nie instalują ich ani nie importują. W Linux worker headless zgłasza niedostępność GUI przed jakimkolwiek bootstrapem pip GUI, a worker graficzny sprawdza lub instaluje tylko adapter wymagany przez aktywną sesję X11 lub Wayland.

Zrzuty zwracane przez zdalne `gui_state` są przesyłane ścieżką transferu plików LSM i udostępniane modelowi jako natywna zawartość obrazu MCP; nie są osadzane w odpowiedzi JSON workera.
