# Placevi Scraper — Project Overview

## Cilj projekta

Automatski pratiti oglase za PLACEVE/ZEMLJIŠTA (ne stanove) u Beogradu i slati
Telegram notifikaciju čim se pojavi plac koji odgovara zadatim kriterijumima
(lokacija, ukupna cena). Zamenjuje ručno pretraživanje sajtova.

Ovo je odvojen projekat od "stanovi scraping" repoa i koristi sopstveni
Telegram bot (drugi token/chat ID).

---

## Tech stack

| Tehnologija | Uloga |
|---|---|
| Python 3.11 | Scraping, filtriranje, logika |
| `requests` + `BeautifulSoup` | HTML scraping (sva 3 izvora) |
| Telegram Bot API | Slanje notifikacija |
| GitHub Actions | Automatsko pokretanje svakog sata |
| `seen.json` | Pamćenje već viđenih oglasa (sprečava duplikate) |
| `config.json` | Lokalna konfiguracija (cena, lokacije) |
| GitHub Secrets | Čuvanje Telegram tokena i chat ID-ova (NOVI bot) |

---

## Sajtovi koji se scrape-uju (samo placevi/zemljišta)

| Sajt | Metoda | Status |
|---|---|---|
| **Halo Oglasi — Zemljišta** | HTML (`.product-item`), URL sa 10 location ID-ova | ✅ Radi (nasleđeno iz stanovi projekta) |
| **Nekretnine.rs — Zemljišta** | HTML, podaci u `__NEXT_DATA__` JSON bloku | ✅ Radi (ista tehnika kao stanovi, nova URL putanja) |
| **4zida.rs — Placevi** | HTML scraping preko href regexa (nema JSON API za zemljišta) | ⚠️ Eksperimentalno — nije testirano na pravim podacima, testiraj sa `--debug` |
| **City Expert** | — | ❌ Izbačen: nema kategoriju zemljišta (probano ptId 1–7, nema je u navigaciji) |

---

## Funkcionalnosti

### Filteri za placeve (config.json)
- `max_total_price` — maksimalna ukupna cena placa (trenutno **50.000 €**)
- `target_locations` — 10 lokacija: Novi Beograd, Zemun, Bežanija, Ledine,
  Surčin, Jakovo, Bečmen, Stari Grad, Savski Venac, Vračar

Nema više €/m² ni €/ar ograničenja — samo ukupna cena + lokacija.

### Telegram notifikacije
- Šalje poruku za svaki **novi** plac koji prođe filter (cena, površina u
  arima, €/ar, link)
- Podržava više primaoca (`TELEGRAM_CHAT_ID` + `TELEGRAM_EXTRA_CHAT_IDS`)
- Automatska deduplikacija — isti ID se ne šalje dva puta
- `/svi` i `/svi<broj>` komande preko `--listen` (lokalno, Task Scheduler)

### CLI komande
```
python scraper.py                  # normalan run
python scraper.py --debug          # testiranje, prikazuje matches bez slanja
python scraper.py --clear-seen     # briše seen.json (sledeći run šalje sve)
python scraper.py --test-telegram  # testira Telegram konekciju
python scraper.py --listen         # Telegram /svi komande (lokalno)
```

---

## Kako app radi

1. GitHub Actions pokreće `scraper.py` svaki sat (08:00–00:00 po Beogradu)
2. Scraper dohvata placeve sa sva 3 izvora
3. Svaki oglas se poredi sa `seen.json` — ako je nov, prolazi kroz filter
   (lokacija + ukupna cena ≤ 50.000 €)
4. Ako prolazi → šalje Telegram poruku (NOVI bot, ne stanovi bot)
5. ID oglasa se upisuje u `seen.json` da se ne ponovi
6. `seen.json` se commituje nazad u GitHub repo

---

## GitHub Secrets (Settings → Secrets → Actions)

| Secret | Opis |
|---|---|
| `TELEGRAM_TOKEN` | Bot token — **NOVI bot, napravljen preko @BotFather posebno za placeve** |
| `TELEGRAM_CHAT_ID` | Chat ID za taj novi bot |
| `TELEGRAM_EXTRA_CHAT_IDS` | Dodatni chat ID-ovi, razdvojeni zarezom (opciono) |

Vidi `HANDOFF.md` → "Setup novog Telegram bota" za korak-po-korak uputstvo.

---

## Šta je urađeno (prerada 17.7.2026)

- [x] Uklonjeni svi scraperi za stanove (Halo stanovi, 4zida JSON API, City Expert)
- [x] Halo Zemljište proširen na svih 10 lokacija (ranije samo 4)
- [x] Novi scraper za Nekretnine.rs zemljišta (`__NEXT_DATA__`, potvrđeno da URL postoji)
- [x] Novi scraper za 4zida.rs placeve (HTML, eksperimentalno, netestirano uživo)
- [x] City Expert izbačen (nema kategoriju zemljišta)
- [x] Filter pojednostavljen na samo ukupnu cenu (50.000 €), bez €/ar capa
- [x] config.json, workflow, .bat fajlovi ažurirani (nazivi, env varijable)
- [x] `seen.json`/Telegram/retry logika nasleđena bez izmena

## Šta nedostaje / poznati problemi

- [ ] **4zida.rs placevi scraper nije testiran na pravim podacima** — sandbox
  u kom je kod pisan nema mrežni pristup 4zida.rs; testirati sa `--debug`
- [ ] **4zida.rs default sortiranje** verovatno nije "najnoviji prvo" (ima
  promovisane oglase na vrhu) — treba naći pravi query parametar
- [ ] Marko treba da napravi i podesi NOVI Telegram bot (vidi HANDOFF.md)
- [ ] Nema web interfejsa — sve ide samo na Telegram

---

## Repo

https://github.com/ceyfi/stanovi-scraper (isti repo folder je iskopiran za
ovaj placevi projekat — proveri da li treba novi, odvojen GitHub repo pre
podešavanja Actions secrets).
