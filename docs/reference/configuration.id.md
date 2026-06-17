# Konfigurasi

Halaman ini menjelaskan skenario “Konfigurasi” dan mengikuti struktur Runtime/Client yang sama di situs.

## Ringkasan

Runtime menentukan bagaimana proses server berjalan dan workspace mana yang dikendalikan. Client menentukan bagaimana ChatGPT atau client MCP lain terhubung. Docker, ekstensi VS Code, biner mandiri, instalasi Python/pipx/sumber, dan stdio adalah pilihan Runtime; konektor ChatGPT, client MCP HTTP generik, dan client MCP stdio adalah koneksi Client.

## Kapan digunakan

- Gunakan halaman ini ketika jalur Runtime atau Client yang dipilih cocok dengan judulnya.
- Jaga agar root workspace, base URL publik, MCP endpoint, mode autentikasi, dan alat host yang tersedia tetap konsisten.
- Untuk ChatGPT web/app, ekspos MCP endpoint HTTPS yang berakhir dengan `/mcp`.
- Untuk client MCP lokal, gunakan HTTP localhost atau `local-shell-mcp --mode stdio` sesuai dukungan client.

## Langkah

1. Pilih halaman instalasi Runtime terlebih dahulu.
2. Mulai Runtime dan periksa `/healthz` saat menggunakan mode HTTP.
3. Pilih halaman koneksi Client berikutnya.
4. Daftarkan MCP endpoint atau perintah stdio di Client.
5. Panggil `environment_info` untuk memeriksa workspace dan pengaturan efektif.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Verifikasi

- `environment_info` mengonfirmasi pengaturan Runtime dan workspace.
- `tree_view` mengonfirmasi file yang terlihat.
- `git_status_tool` mengonfirmasi konteks repositori.
- `run_shell_tool` mengonfirmasi lingkungan perintah.

## Catatan

Utamakan langkah kecil yang dapat diverifikasi: inspeksi, edit, diff, test, scan, dan commit. Tugas besar juga harus dipecah menjadi panggilan alat yang dapat diaudit.
