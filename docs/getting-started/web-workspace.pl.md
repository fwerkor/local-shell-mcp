<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# Ujednolicony internetowy obszar roboczy

**Ujednolicony internetowy obszar roboczy LSM** to zalecany sposób codziennego korzystania z local-Shell-mcp. Łączy czat AI, historię projektu i płaszczyznę kontroli LSM w jednym responsywnym interfejsie, opartym na zmodyfikowanym, dostarczanym przez dostawcę interfejsie LibreChat. Nadal możesz podłączać zewnętrznych klientów MCP, takich jak [ChatGPT](chatgpt-connector.md) lub [Gemini](gemini-spark.md).

Obszar roboczy jest **samodzielny i można go zainstalować opcjonalnie**: jest oddzielną usługą internetową, a nie częścią minimalnego obrazu kontrolera, samodzielnego pliku wykonywalnego lub pakietu zdalnego pracownika. Wdrożenia oparte wyłącznie na kontrolerze zachowują oryginalny interfejs przeglądarki i OpenTUI.

## Co znajduje się w obszarze roboczym?

| Obszar | Co możesz zrobić |
|---|---|
| Czat i projekty | Wybierz skonfigurowany model, twórz rozmowy, organizuj projekty, odnajduj wcześniejsze czaty i archiwizuj rozmowy. Historia pozostaje na serwerze. |
| Przegląd kontrolera | Wyświetl stan, ostatnią aktywność i podłączone komputery. |
| Pliki | Przeglądaj i zarządzaj plikami lokalnymi lub zdalnymi. |
| Terminale | Pracuj ze stałymi terminalami na kontrolerze lub pracownikach. |
| Pulpit | Sprawdzaj i kontroluj zdalne sesje GUI. |
| Sesje | Sprawdź trwałe zadania LSM i ich cykl życia. |
| Piloty | Łącz i zarządzaj pracownikami wychodzącymi. |
| Audyt | Sprawdź działanie narzędzia pochodzącego z modelu. |
| Zagnieżdżone MCP | Zarejestruj, edytuj, włączaj, wyłączaj, odświeżaj i usuwaj zewnętrzne serwery MCP za LSM. |

Trasy kontrolera to `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` i `/control/audit`. Czat otwiera się pod adresem `/c/new`. Menedżer LSM MCP kontroluje **zagnieżdżony rejestr MCP LSM**; nie tworzy drugiego rejestru w LibreChat.

## Wdróż opcjonalny stos czatu

1. [Install and start an LSM Controller](quickstart.md) z OAuth, odpowiednio izolowanym obszarem roboczym i trwałą pamięcią stanu `file` lub `redis`. Zainstaluj Docker Compose i sklonuj repozytorium na hoście, na którym działa stos internetowy.
2. Podaj **dwa źródła HTTPS w tej samej witrynie**, takie jak `https://lsm.example.org` dla kontrolera i `https://chat.example.org` dla obszaru roboczego. Usługa czatu nie jest widoczna bezpośrednio w niezaufanej sieci.
3. Wygeneruj jeden sekret mostu za pomocą `openssl rand -hex 32`. Skonfiguruj te zmienne środowiskowe w **usłudze kontrolera**, używając tego klucza tajnego, a następnie uruchom ją ponownie:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. W kasie repozytorium skonfiguruj opcjonalny stos internetowy. Użyj pliku środowiska prywatnego lub wyeksportuj wartości pokazane poniżej; generuj unikalne, silne sekrety i nie popełniaj ich:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Wyrenderuj prywatną konfigurację, a następnie zbuduj i uruchom oddzielnie wdrożony stos czatów:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

W przypadku korzystania z głównego wdrożenia Docker Compose powyższe zmienne kontrolera należą do katalogu głównego `.env` i są przekazywane do kontenera. Wartości usługi czatu można dostarczyć poprzez eksport powłoki lub plik środowiska prywatnego. Kontener kontrolera musi być osiągalny z kontenera czatu pod adresem `http://local-shell-mcp:8765` w nazwanej sieci Docker. Odwróć port proxy `127.0.0.1:3080` do źródła protokołu HTTPS czatu, zachowaj host zewnętrzny i postępuj zgodnie z [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) w repozytorium. Stos sieciowy obsługuje Node.js, MongoDB, Meilisearch i SearXNG; nie są** zaliczani do pracowników. To oddzielne wdrożenie nie jest rozpoczynane przez zwykły kod `docker compose up -d` w katalogu głównym repozytorium.

## Zaloguj się i korzystaj z czatu

1. Otwórz `https://lsm.example.org/ui`, uwierzytelnij się przy użyciu loginu **LSM Controller** i wykonaj jednorazowe przekazanie do internetowego obszaru roboczego. Nie tworzysz drugiego konta użytkownika LibreChat.
2. Skonfiguruj dostępnego dostawcę LLM lub modelowy punkt końcowy dla usługi czatu. Obszar roboczy udostępnia interfejs czatu i mostek narzędziowy; **nie obejmuje modelu ani kredytów API**.
3. Utwórz rozmowę. Wyszukiwarka internetowa i narzędzia LSM są domyślnie włączone, w zależności od uprawnień Kontrolera. W razie potrzeby użyj opcji **Sieć**, **LSM**, **Zewnętrzny MCP** i **Pamięć** dla poszczególnych rozmów.
4. Zacznij od żądania tylko do odczytu: "Sprawdź status kontrolera i wyświetl katalog główny obszaru roboczego. Nie modyfikuj plików. "
5. Przejdź do **Pliki**, **Terminale**, **Pulpit**, **Sesje**, **Pliki zdalne** lub **Audyt**, aby uzyskać bezpośrednią kontrolę i kontrolę.

Przesyłane czaty (do 32 MiB) są przechowywane w obszarze roboczym Kontrolera, a ich ścieżki bezwzględne są dostarczane do modelu. Przesyłanie przez przeglądarkę nie przyznaje dodatkowych uprawnień do plików. Wywołania narzędzi skierowanych do modelu przechodzą przez autoryzację LSM, audyt i router pracownika zdalnego.

## Zewnętrzny MCP, bezpieczeństwo i dane

Użyj paska bocznego MCP obszaru roboczego, aby zarządzać zagnieżdżonymi zewnętrznymi serwerami MCP. Obsługuje to lokalne serwery stdio i serwery HTTP, w tym oddzielne prywatne zmienne środowiskowe i nagłówki żądań. Sekrety nie są zwracane do przeglądarki. Przełącznik czatu **zewnętrznego MCP** umożliwia wyszukiwanie, sprawdzanie i wywoływanie zagnieżdżonych narzędzi; nie przyznaje modelu `mcp_manage`, gdy natywne narzędzia LSM są wyłączone. Zarządzanie interfejsem użytkownika jest chronione zwykłą autoryzacją kontrolera.

Wiadomości czatu, projekty i archiwa są przechowywane po stronie serwera w MongoDB stosu internetowego; wyszukiwanie wykorzystuje Meilisearch. Kontroler oddzielnie posiada uprawnienia do narzędzi, tożsamość pracowników, stan sesji i audyt. Jeśli chcesz zachować całą historię, wykonaj kopię zapasową obu magazynów danych. Backend czatu jest przeznaczony dla jednego użytkownika z loginem LSM; nie udostępniaj publicznie swoich wewnętrznych interfejsów API ani baz danych.

Interfejs użytkownika to aplikacja najwyższego poziomu, **nie element iframe**. Jeśli opcjonalna usługa czatu nie jest skonfigurowana, `/ui` nadal obsługuje oryginalny interfejs internetowy LSM. Obsługiwane są natywne klienci OpenTUI i klienci zewnętrzni.

## Rozwiązywanie problemów

- **Przekierowanie pozostaje w oryginalnym interfejsie użytkownika:** sprawdź `LOCAL_SHELL_MCP_LIBRECHAT_URL`, trwały backend stanu kontrolera i odwrotne proxy HTTPS stosu internetowego.
- **Logowanie lub przekazanie nie powiodło się:** sprawdź dokładnie ten sam klucz tajny mostu o długości 32 bajtów lub więcej po obu stronach, pasujący do źródeł tej samej witryny, protokołu HTTPS i zegarów serwera.
- **Czat ładuje się, ale nie może odpowiedzieć:** skonfiguruj rzeczywisty punkt końcowy modelu lub dane uwierzytelniające API i sprawdź dzienniki kontenera czatu.
- **Brak narzędzi MCP:** sprawdź zakresy kontrolera i przełączniki dla poszczególnych konwersacji; zagnieżdżony rejestr serwerów jest oddzielony od bazy danych LibreChat MCP.
- **Pliki lub sesje wydają się puste:** sprawdź, czy czat dociera do właściwego kontrolera i obszaru roboczego oraz sprawdź dzienniki uwierzytelniania API.

Szczegóły implementacji i aktualizacje można znaleźć w plikach [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) i [human interface guide](../guides/human-interface.md).
