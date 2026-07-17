# CLAUDE.md — PLACEVI SCRAPING

> Globalna pravila su u `~/.claude/CLAUDE.md`. Ovde samo specifičnosti projekta.
> Pun kontekst i istorija: pročitaj `HANDOFF.md` u ovom folderu.

## Projekat
Python scraper (satni, GitHub Actions) ISKLJUČIVO za placeve/zemljišta u Beogradu →
Telegram notifikacije za nove pogotke. Ovo je odvojen projekat od "stanovi
scraping" repoa — nema stanova ovde, samo placevi, i koristi SVOJ SOPSTVENI
Telegram bot (drugi token/chat, ne deli se sa stanovi botom).

## Prioritet sada
- ✅ Prerađen iz "stanovi" verzije (17.7.2026) — City Expert izbačen (nema
  kategoriju zemljišta), 4zida i Nekretnine.rs dobili nove zemljišta scrapere.
- VAŽNO: 4zida.rs Zemljište scraper je EKSPERIMENTALAN — HTML scraping bez
  mogućnosti live testiranja u razvoju (sandbox nema pristup internetu).
  Pokreni `python scraper.py --debug` pre nego što mu veruješ.
- VAŽNO: napravi NOVOG Telegram bota (BotFather) i podesi TELEGRAM_TOKEN/
  TELEGRAM_CHAT_ID (lokalno + GitHub Secrets) — ne koristi stari stanovi bot.
- Filter: samo ukupna cena ≤ 50.000 € (bez €/ar capa), 10 lokacija iz config.json.
- Sledeće po redu: proveriti da li 4zida sort parametar postoji (da se hvataju
  najnoviji oglasi, ne samo promovisani), dnevni digest umesto pojedinačnih poruka.
