# WebUI network search and document reading

WebUI Chat has **network search enabled by default**. Use the **Web search** chip
under the message composer to disable it for an individual chat; the choice is
saved for that chat. No provider API key or worker shell permission is needed.

The Agent receives only two first-party read-only web tools:

- `web_search(query)` returns titles, URLs, and snippets from public search results.
  LSM uses `ddgs` when installed (included in the `webui` extra), with a
  no-key Bing RSS fallback. Public search services can throttle or return
  irrelevant results, and availability is not guaranteed.
- `web_fetch(url, query?, offset?, limit?)` downloads and reads HTML, plain text,
  JSON/XML, Markdown, and PDFs. An arXiv abstract URL opens the HTML full text
  when available and otherwise attempts its PDF, without a separate paper API.

The first fetch caches the full extracted text privately on the Controller,
while returning at most 8,000 characters, the document length, and headings
or PDF page markers. The Agent can read more with `offset` / `limit` (up to
12,000 characters per call) or find a passage with `query`. The cache is scoped
to the authenticated user, expires after 24 hours, and is limited to 80 files
per user. The fetcher enforces a 20 MiB download limit and a 3 MiB extracted
text limit; it rejects local/private network targets, credentials in URLs,
nonstandard ports and unsafe redirects.

PDF extraction uses PyMuPDF when available and falls back to `pypdf`.
Scanned PDFs without a text layer require OCR and currently cannot be fully
read by this tool. Unsupported file formats are rejected explicitly.

The WebUI displays the search result links in the existing tool-result card.
AI answers should cite the original URLs and PDF page numbers when possible.
