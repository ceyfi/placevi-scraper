# Context za code review — Stanovi Scraper
**Datum: 9. jul 2026** | Model koji čita ovo: Opus / Fable

---

## Šta je ovo

Python scraper koji automatski pretražuje srpske sajtove za nekretnine i šalje Telegram notifikacije za stanove i zemljišta u Beogradu ispod zadatih cena. Pokreće se svakog sata via GitHub Actions.

**Repo:** https://github.com/ceyfi/stanovi-scraper  
**Lokacija fajlova:** `I:\Apps\STANOVI SCRAPING\`  
**Glavni fajl:** `scraper.py` (~870 linija)

---

## Šta treba da uradiš

1. **Pročitaj kompletan `scraper.py`** i napravi code review
2. **Proveri sveže popravljen bug** (opisan dole) — da li je fix ispravan i potpun
3. **Napravi listu svih problema** koje primećuješ — logičkih grešaka, edge caseova, krhkih mesta
4. **Predloži konkretne popravke** sa kodom, ne samo opisima
5. **Opciono:** implementiraj šta možeš direktno

---

## Arhitektura (kratko)

```
scraper.py
├── load_config()          — config.json + env varijable (env ima prednost)
├── load_seen/save_seen()  — seen.json: set ID-ova viđenih oglasa
├── send_telegram()        — šalje HTML poruku, bypass proxy
├── format_message()       — formatira listing u Telegram poruku
├── fetch_json()           — urllib opener: bez proxy-ja, bez SSL verifikacije
├── scrape_halooglasi()    — HTML scraping, lokalno radi, GitHub Actions 403
├── scrape_halooglasi_zemljiste()  — HTML scraping zemljišta
├── scrape_4zida()         — JSON API, pagina 15 strana, filtrira u Pythonu
├── scrape_cityexpert()    — JSON API sa ?req=JSON_encoded parametrom
├── scrape_nekretnine()    — HTML + __NEXT_DATA__ JSON parsing
└── main()                 — orchestracija, filteri, slanje
```

### CLI
```bash
python scraper.py                  # normalan run
python scraper.py --debug          # svi scrapers, prikazuje matches bez Telegram
python scraper.py --clear-seen     # briše seen.json
python scraper.py --test-telegram  # testira Telegram konekciju
```

---

## Config (config.json)

```json
{
  "max_price_per_m2": 2000,
  "max_total_price": 250000,
  "max_total_price_zemljiste": 60000,
  "max_price_per_ar": 7000,
  "target_locations": [
    "Novi Beograd", "Zemun", "Bezanija", "Ledine",
    "Surčin", "Jakovo", "Bečmen",
    "Stari Grad", "Savski Venac", "Vračar"
  ]
}
```

Telegram token i chat ID su **samo u GitHub Secrets** (public repo), nikad u config.json.

### Env varijable (GitHub Secrets)
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_EXTRA_CHAT_IDS` — lista ID-ova razdvojena zarezom, za više primaoca

---

## Bug koji je upravo popravljen (9.7.2026) — PROVERI ISPRAVNOST

### Problem
U `main()` na sve oglase se primenjivao isti `is_good_price(ppm2, max_ppm2=2000)` filter.  
Ali za `Halo Zemljište` oglase, polje `price_per_m2` čuva **cenu po aru** (ne po m²).  
Zemljište od 5.000 €/ar (ispod limita od 7.000) bivalo je odbačeno jer 5000 > 2000.  
Korisnik nije dobijao notifikacije za gotovo nijedno zemljište.

### Popravka (linija ~765 u main())
```python
# PRE (bug):
price_ok = is_good_price(listing.get('price_per_m2'), max_ppm2)
price_val = listing.get('price')
total_ok = max_total is None or (price_val is not None and price_val <= max_total)

# POSLE (fix):
if listing.get('source') == 'Halo Zemljište':
    price_ok = True   # filtrirano unutar scrape_halooglasi_zemljiste()
    total_ok = True   # idem
else:
    price_ok = is_good_price(listing.get('price_per_m2'), max_ppm2)
    price_val = listing.get('price')
    total_ok = max_total is None or (price_val is not None and price_val <= max_total)
```

Isti fix je dodat i u `--debug` grani (helper `debug_price_ok()` funkcija).

**Pitanje za tebe:** Da li je ovo dovoljan fix? Da li ima drugih mesta u kodu gde se primenjuju stanovski filteri na zemljišta?

---

## Poznati problemi koje treba pregledati

### 🔴 Visoki prioritet

**1. Halo Oglasi 403 na GitHub Actions**  
`scrape_halooglasi()` radi lokalno ali GitHub Actions IP je blokiran sa 403.  
Halo stanovi su izbačeni iz `main()` scrapers liste, ali su u `--debug` listi.  
Halo Zemljište ima isti problem — u main() je, ali verovatno ne prolazi na Actions.  
Treba rešiti: rotacija User-Agent, proxy relay, ili prihvatiti da Halo radi samo lokalno.

**2. SSL_VERIFY = False globalno**  
```python
SSL_VERIFY = False
os.environ['NO_PROXY'] = '*'
```
Ovo je workaround za lokalni korporativni antivirus koji interceptuje HTTPS.  
Ali na GitHub Actions je nepotrebno i predstavlja security rizik.  
Bolje rešenje: `SSL_VERIFY = os.environ.get('CI') != 'true'`

**3. seen.add(lid) se dešava PRE filtera**  
```python
is_new = lid not in seen
seen.add(lid)   # ← ovde, pre loc_ok/price_ok provere
if not is_new:
    continue
```
Oglas viđen jednom (dok je filter bio stroži) nikad više neće biti prijavljen.  
Posle promene filtera korisnik mora ručno da pokrene `--clear-seen`.  
Pitanje: da li ovo menjati (seen samo za one koji prođu filter)?

### 🟡 Srednji prioritet

**4. Nekretnine.rs ne vraća uvek price**  
API ponekad ne vraća `price` polje za oglas, pa `max_total_price` filter propušta skuplje oglase.  
Potrebno istražiti koji su alternativni API fieldi za cenu.

**5. City Expert — samo prva strana (60 oglasa)**  
`scrape_cityexpert()` radi samo jednu API stranicu, bez paginacije.  
4zida pravi 15 strana; City Expert bi trebalo slično.

**6. 4zida probira 3 URL kandidata svaki run**  
```python
url_candidates = [
    "https://api.4zida.rs/v6/search/apartments",
    "https://api.4zida.rs/v6/search/apartments?for=sale",
    "https://api.4zida.rs/v5/search/apartments",
]
```
3 HTTP request-a pre svakog scraping runa. Treba keširiti koji radi.

**7. seen.json raste neograničeno**  
Svaki oglas ID se čuva zauvek. Posle godinu dana biće hiljade unosa.  
Predlog: `{id: timestamp}` dict i brisanje starijih od 30 dana.

### 🟢 Niski prioritet

**8. Dupliran session setup kod**  
`scrape_halooglasi()` i `scrape_halooglasi_zemljiste()` imaju identičan session setup (~10 linija).  
Refaktorisati u `make_halo_session()`.

**9. Jedan fajl od 870 linija**  
Još uvek OK, ali na sledećem novom scraperu treba podeliti u `scrapers/` direktorijum.

**10. format_message() uvek pokazuje €/m² za zemljišta**  
Za `Halo Zemljište` oglase, `price_per_m2` sadrži cenu PO ARU.  
Poruka prikazuje "Cena/m²: 5.000 €/m²" što je zbunjujuće — trebalo bi "5.000 €/ar".

---

## Tehničke zamke koje treba znati

### fetch_json() — urllib, ne requests
API pozivi koriste urllib umesto requests jer requests re-enkodira uglaste zagrade u URL-u (`[]` → `%5B%5D`) što je razbijalo neke API-je. urllib šalje raw URL.

### Brotli encoding na Halo Oglasi
Halo šalje brotli-compressed HTML. Fix: `Accept-Encoding: gzip, deflate` (bez `br`).  
Python requests ne podržava brotli out-of-the-box.

### 4zida API — ne prima filtere
`https://api.4zida.rs/v6/search/apartments?cityId=1` vraća 422 "extra fields".  
Jedino `page=N` radi. Svo filtriranje je u Pythonu.

### GitHub Actions seen.json race condition
Kad Actions pokušava da pushne seen.json, a drugi run je u međuvremenu pushao:
```bash
git add seen.json
git diff --staged --quiet || git commit -m "chore: update seen.json [skip ci]"
for attempt in 1 2 3; do
  git pull --rebase origin main  # pull POSLE commita, ne pre
  git push && break
  sleep 5
done
```
`continue-on-error: true` na ovom koraku — push greška ne ubija workflow.

---

## GitHub Actions workflow

**Fajl:** `.github/workflows/scraper.yml`  
**Raspored:** `0 6-22 * * *` = svaki sat, 08:00–00:00 Beograd (UTC+2)  
**Permissions:** `contents: write` (za commitovanje seen.json)

---

## Lokalne specifičnosti (ne menjati bez razloga)

- `os.environ['NO_PROXY'] = '*'` — zaobilazi korporativni antivirus proxy lokalno
- `session.trust_env = False` — requests neće čitati system proxy settings
- `proxies={'http': '', 'https': ''}` — prazan proxy u send_telegram()
- Windows UTF-8 fix na kraju fajla:
  ```python
  if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
      sys.stdout.reconfigure(encoding='utf-8', errors='replace')
  ```

---

## Šta NIJE urađeno (potencijalni dalji razvoj)

- [ ] Filter po broju soba (min/max rooms)
- [ ] Zemljišta na 4zida.rs i Nekretnine.rs (trenutno samo Halo)
- [ ] Dnevni digest umesto pojedinačnih poruka (manje spama)
- [ ] Web dashboard za pregled svih oglasa
- [ ] Rešiti Halo Oglasi 403 na GitHub Actions

---

## Gde početi

1. Pročitaj kompletan `scraper.py`
2. Proveri da li je bug fix za zemljišta (opisan gore) ispravan i kompletan
3. Napravi prioritizovanu listu problema sa konkretnim fix predlozima
4. Implementiraj fixeve direktno u scraper.py, počev od najkritičnijeg

Sačekaj instrukcije od korisnika pre nego što menjaš fajlove — možda hoće samo review, možda hoće i implementaciju.
