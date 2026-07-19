# Często zadawane pytania

Ta strona opisuje powtarzające się problemy z Client i odwrotnym proxy, które mogą wyglądać jak awarie LSM, mimo że serwer działa prawidłowo.

## Dlaczego po aktualizacji LSM niektóre narzędzia są niedostępne w ChatGPT?

### Objawy

- Nowe narzędzia nie pojawiają się w ChatGPT.
- ChatGPT nadal próbuje wywołać narzędzie usunięte, przemianowane lub połączone.
- Narzędzie istnieje, ale wywołanie kończy się błędem, ponieważ ChatGPT wysyła starszy schemat wejściowy.
- Restart LSM lub nowa rozmowa nie rozwiązują problemu.

### Przyczyna

ChatGPT może zachować zamrożony snapshot narzędzi i schematów wejściowych dostępnych podczas skanowania, zatwierdzania lub publikowania MCP App. Gdy wydanie LSM zmienia `tools/list`, automatyczne odświeżenie tego snapshotu nie jest gwarantowane. Nie jest to krótkotrwały cache z udokumentowanym czasem wygaśnięcia.

### Rozwiązanie

=== "Tryb deweloperski lub połączenie osobiste"

    1. Otwórz **ChatGPT Settings → Apps**.
    2. Otwórz LSM App i użyj **Refresh**, aby ponownie przeskanować narzędzia.
    3. Jeśli Refresh nie jest dostępny, usuń starą App i ponownie dodaj ten sam endpoint MCP.
    4. Po zaakceptowaniu nowej listy narzędzi rozpocznij nową rozmowę.

=== "App opublikowana w ChatGPT Business"

    Opublikowana niestandardowa App nie może obecnie zaktualizować narzędzi ani metadanych w miejscu. Administrator musi utworzyć nową App, przeskanować bieżący endpoint LSM, opublikować zamiennik i wycofać starą App.

=== "ChatGPT Enterprise lub Edu"

    Administrator może otworzyć **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, przejrzeć różnice i w razie potrzeby włączyć nowe actions.

Zobacz [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) oraz [dokumentację OpenAI dotyczącą MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Dlaczego WebUI za Nginx stale łączy się ponownie?

### Objawy

- Strona WebUI i logowanie OAuth ładują się prawidłowo.
- TUI nie pojawia się.
- Stan przełącza się między `Connecting`, `Connection error` i `Reconnecting`.
- Bezpośrednie połączenie z portem `8765` działa.

### Przyczyna

Interfejs przeglądarki renderuje natywne TUI przez PTY WebSocket. Domyślny endpoint to `/ui/ws`; przy niestandardowym `ui_path` jest to `${ui_path}/ws`. Zwykły `proxy_pass` Nginx nie przekazuje automatycznie nagłówków hop-by-hop wymaganych do aktualizacji WebSocket.

### Rozwiązanie

Włącz HTTP/1.1 i przekaż nagłówki `Upgrade` oraz `Connection`:

```nginx
# Umieść map w bloku http.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

Sprawdź konfigurację i przeładuj Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

W Nginx Proxy Manager włącz **Websockets Support** dla Proxy Host. Jeśli ponowne łączenie trwa nadal, dodaj równoważne nagłówki w Advanced.

### Weryfikacja

Otwórz narzędzia deweloperskie, przeładuj WebUI i sprawdź żądanie `/ui/ws`. Działające połączenie zwraca:

```text
101 Switching Protocols
```

Zobacz [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
