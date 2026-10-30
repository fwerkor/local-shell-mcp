<!-- i18n-source-sha256: 53d1b81800534bc6d5334883b7de74660c988088c66f492ddbd68aced8797379 -->
# Hostowany czat (opcjonalnie)

Hosted Chat to hostowany samodzielnie klient czatu BYOK i aplikacji MCP zintegrowany z interfejsem LSM. Nie jest to **nie** tryb sesji logicznej: konwersacje mają niezależne tożsamości i opcjonalnie mogą dołączać istniejącą sesję logiczną LSM. ChatGPT i inni klienci zewnętrzni kontynuują pracę z tymi samymi sesjami i narzędziami LSM.

## Włącz

Hostowany czat jest domyślnie wyłączony. Zestaw:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Uruchom ponownie kontroler i otwórz **Hosted Chat** bezpośrednio pod selektorem Web UI / TUI. Ta funkcja umożliwia również wpis na górnym pasku telefonu komórkowego. Host czatu korzysta z istniejącej tożsamości i zakresów LSM OAuth. Ten sam kontroler obsługuje serwer MCP używany przez pętlę narzędzi modelu; Pracownicy nie mogą inicjować wykonania.

## Profile modeli

Wybierz **Profile modeli**, aby utworzyć/edytować profil z nazwą, podstawowym adresem URL API zgodnym z HTTPS OpenAI, identyfikatorem modelu i opcjonalnym kluczem API. Wiele profili może współistnieć, a rozmowy mogą zmieniać modele.

Profile, rozmowy, pełna historia wiadomości i wyniki wywołań narzędzi są **zapisywane na serwerze** poprzez skonfigurowany backend stanu LSM. Ich zakres jest powiązany z uwierzytelnionym podmiotem głównym. Klucz API jest szyfrowany za pomocą AES-GCM i nigdy nie jest zwracany z punktów końcowych zawierających listę profili lub szczegółowe informacje o profilu. Nie są one przechowywane w pamięci przeglądarki, wysyłane do modelu jako monit ani uwzględniane w dziennikach audytu. Host czatu przekazuje go tylko do wybranego modelu API.

Pierwsze wdrożenie oparte na plikach tworzy `hosted-chat-encryption-key` w katalogu stanu w trybie 0600. **Utwórz kopię zapasową tego pliku wraz z danymi stanu. Bez tego zapisanych kluczy API nie można odszyfrować.** Jeśli kontroler korzysta z Redis, wielu replik lub innego zaplecza stanu innego niż plik, skonfiguruj stabilny, współdzielony 32-bajtowy klucz bezpieczny dla adresu URL-base64:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Nie zmieniaj tego ustawienia bez migracji zaszyfrowanych profili. Nie używaj przechowywania stanu w pamięci, gdy wymagane są trwałe rozmowy.

Domyślnie akceptowane są tylko punkty końcowe modelu HTTPS z nazwami hostów DNS; lokalne/prywatne punkty końcowe i protokół HTTP są odrzucane, aby zmniejszyć ryzyko fałszowania żądań po stronie serwera. Administratorzy celowo hostujący zaufaną bramę prywatnego modelu mogą zdecydować się na:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Nie włączaj tej opcji na niezaufanym kontrolerze wielu użytkowników, chyba że użytkownicy są upoważnieni do kontaktowania się z usługami wewnętrznymi.

## Rozmowy i aplikacje MCP

Utwórz rozmowę, korzystając z zapisanego profilu modelki. Każda przesłana tura staje się zadaniem w tle należącym do serwera; zamknięcie przeglądarki nie anuluje zadania. Ukończony tekst i wywołania narzędzi są trwale sprawdzane pomiędzy krokami modelu/narzędzia. Zatrzymaj się wyraźnie, aby przerwać. Po ponownym uruchomieniu kontrolera przerwane przebiegi są oznaczone jako takie i można je kontynuować w nowej turze, ale **wywołania narzędzi o nieznanym wyniku nigdy nie są automatycznie odtwarzane**.

Cała historia wiadomości rozmowy jest przechowywana w pamięci. Do modelu wysyłane jest jednocześnie tylko ograniczone ostatnie okno, aby kontrolować rozmiar kontekstu. Wywołania narzędzi są wysyłane przez uwierzytelniony punkt końcowy MCP LSM, zachowując wszystkie zwykłe uprawnienia narzędzi i zachowanie audytu/weryfikacji wstępnej.

Archiwizacja usuwa rozmowę ze zwykłej listy i zapisuje ją jako `.json.zst` przy użyciu istniejącego kodeka zstd z Audit. Archiwum nie trafia do normalnego indeksu wyszukiwania. W **Archived conversations** można szukać po tytule, czytać bez edycji, przywracać i usuwać trwale. Najpierw zapisywana jest nowa kopia, aby zapobiec utracie danych.

### Długie rozmowy i kompresja kontekstu

Pełna historia wiadomości i narzędzi pozostaje na serwerze. Okno kontekstu konfiguruje się w profilu modelu: domyślnie **32 768 tokenów**, zakres 8 192–1 000 000. Ostrożne oszacowanie na podstawie UTF-8 uwzględnia definicje narzędzi. Przy około **80%** tego limitu ten sam model podsumowuje starsze zakończone tury, zachowując cele, ograniczenia, decyzje, pliki, wyniki i zadania do wykonania. Podsumowanie jest przechowywane osobno, a model otrzymuje je wraz z niedawnymi oryginalnymi wiadomościami.

Budżet jest sprawdzany także po użyciu narzędzi. **Compact** umożliwia ręczne skrócenie kontekstu poza aktywną turą. Błąd nie zmienia poprzedniego podsumowania ani historii. Liczba tokenów jest przybliżona; zbyt długa bieżąca tura zostanie odrzucona zamiast cicho ucięta.

Otwórz **Live Workspace**, aby wyrenderować istniejący zasób aplikacji MCP `workspace_open` LSM w osadzonym widoku. Host korzysta z mostu `@modelcontextprotocol/ext-apps` na potrzeby cyklu życia aplikacji, odnawiania poświadczeń, wywołań narzędzi i działań między człowiekiem a agentem. Nie zaimplementowano drugiego menedżera plików, terminala, interfejsu audytu ani zadania.

Opcjonalnie dołączony `session_id` umożliwia Hostowanemu Czatowi używanie i wyświetlanie istniejącej sesji logicznej; nie powoduje to zmiany klasyfikacji Sesji ani przekazania jej na własność Hostowanemu Czatowi. Identyfikatory konwersacji na czacie i identyfikatory sesji logicznej są oddzielne.

## Granice

- Żądania modeli korzystają z uzupełnień czatu zgodnych z OpenAI z wywoływaniem narzędzi; inne protokoły dostawców wymagają adaptera.
- Na obrót zabezpiecza iteracje modelu czapki i wywołania narzędzi. Dłuższe zadania można kontynuować w nowej turze, korzystając z trwałej historii.
- Usunięcie rozmowy na czacie jest jednoznaczne. Nie jest wykonywane automatyczne usuwanie historii.
- Kontroler musi być dostępny w sieci za pośrednictwem własnego klienta MCP, a przeglądarka musi mieć autoryzację dla interfejsu API LSM Live Workspace.
