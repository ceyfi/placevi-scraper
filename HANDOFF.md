# HANDOFF — PLACEVI SCRAPING
**Poslednje ažuriranje: 17. jul 2026** · Prerada iz "stanovi" projekta u isključivo placevi/zemljišta.

## Šta se promenilo 17.7.2026 (prerada iz stanovi u placevi)
1. **Ukinuti stanovi u potpunosti.** `scrape_halooglasi()` (stanovi), `scrape_4zida()`
   (stanovi, JSON API), `scrape_cityexpert()` su obrisani iz `scraper.py`.
2. **City Expert izbačen kao izvor.** Probano `ptId=1..7` na
   `cityexpert.rs/prodaja-nekretnina/beograd` — nađeni su samo stan (1), kuća (2),
   poslovni prostor (3), lokal (4), stan u kući (5); ptId 6 i 7 vraćaju 0 rezultata
   i zemljište se ne pojavljuje nigde u navigaciji sajta. Zaključak: City Expert
   nema (aktivnu) kategoriju zemljišta u Beogradu — nije vredno održavati scraper za nju.
3. **Halo Zemljište zadržan i proširen.** `HALO_ZEMLJISTE_URL` sad koristi ISTU
   listu od 11 location ID-ova (grad_id_l-lokacija_id_l-mikrolokacija_id_l) kao
   stari stanovi scraper — sve 10 lokacija iz config-a su sad pokrivene (ranije
   je zemljišta URL imao samo 4-5 ID-ova za Surčin/Jakovo/Bečmen/Ledine).
4. **Novo: `scrape_4zida_zemljiste()`.** 4zida nema JSON API za placeve (probano
   `/v6/search/land`, `/plots`, `/lands`, `/houses` — ništa od toga ne postoji).
   Umesto toga: `https://www.4zida.rs/prodaja-placeva/beograd` je server-rendered
   HTML (vidljiv sadržaj bez JS-a), pa se parsira direktno — traže se `<a href>`
   koji odgovaraju regexu `/prodaja-placeva/.../.../{24 hex karaktera}` (isti
   format kao Mongo ObjectId), pa se cena/površina/lokacija izvlače regexom iz
   teksta najmanjeg kontejnera koji sadrži TAČNO taj jedan oglas (funkcija
   `_fzida_card_container`, sprečava mešanje podataka između susednih kartica).
   **EKSPERIMENTALNO** — testirano samo sa sintetičkim HTML-om u razvoju, sandbox
   nije imao mrežni pristup 4zida.rs da se proveri na pravim podacima. Pokreni
   `--debug` i pogledaj da li izgleda smisleno pre nego što veruješ notifikacijama.
   Poznato ograničenje: 4zida stranica nije nužno sortirana po najnovijem (ima
   promovisane/"Premijum"/"Top" oglase na vrhu) — nismo našli sort parametar za
   "najnoviji prvo", pa je moguće da neki novi organski oglasi kasne dok ne
   probamo da nađemo pravi query param (proveriti u browseru Network tab).
5. **Novo: `scrape_nekretnine_zemljiste()`.** Ista `__NEXT_DATA__` JSON tehnika
   kao stari stanovi scraper, samo je URL promenjen sa `/prodaja-stanova/beograd/`
   na `/prodaja-zemljista/beograd/` (potvrđeno da postoji i radi — 1.685 oglasa,
   9 strana). Structure realEstate/seo/properties/location je ista za sve
   kategorije na sajtu.
6. **Filter pojednostavljen.** Samo ukupna cena ≤ `max_total_price` (50.000 €
   default) + lokacijski match. Nema više €/m² ni €/ar capa (korisnik je tako
   odlučio — ranije je zemljišta imala i `max_price_per_ar: 7000`, sad ukinuto).
7. **`price_per_m2` polje preimenovano u `price_per_ar`** kroz ceo kod — nema više
   dvosmislenosti oko jedinice pošto je SVE sada zemljište.
8. **NOV Telegram bot.** Ovaj projekat namerno NE deli bota sa "stanovi" repoom.
   `config.json` i dalje ne sadrži token (isto kao pre) — token/chat ID idu kroz
   env varijable (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) lokalno ili GitHub Secrets.
   **Marko treba da napravi NOVI bot preko @BotFather i podesi NOVE secrets/env
   varijable za ovaj repo** — vidi sekciju "Setup novog bota" dole.

## Setup novog Telegram bota (obavezno pre prvog runa)
1. U Telegramu otvori `@BotFather` → `/newbot` → daj mu ime i username (mora se
   završavati na "bot", npr. `PlaceviBeogradBot`).
2. BotFather vrati TOKEN (izgleda kao `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxx`).
3. Pošalji bilo koju poruku novom botu (mora prvi kontakt da krene od tebe).
4. Nađi svoj `chat_id`: otvori u browseru
   `https://api.telegram.org/bot<TOKEN>/getUpdates` (zameni `<TOKEN>`) posle što
   si poslao poruku botu — u JSON odgovoru je `message.chat.id`.
5. Lokalno: postavi env varijable `TELEGRAM_TOKEN` i `TELEGRAM_CHAT_ID` pre
   pokretanja (`set TELEGRAM_TOKEN=...` u cmd, ili trajno kroz Windows System
   Properties → Environment Variables).
6. GitHub Actions: Settings → Secrets and variables → Actions → New repository
   secret, dodaj `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (i opciono
   `TELEGRAM_EXTRA_CHAT_IDS`) — **različite vrednosti od stanovi repoa.**
7. Test: `python scraper.py --test-telegram`.

## Šta projekat radi
Python scraper koji svakog sata (GitHub Actions, 08–00h po Beogradu) skuplja
oglase za PLACEVE/ZEMLJIŠTA u Beogradu (Halo Oglasi, 4zida.rs, Nekretnine.rs),
filtrira po lokaciji i ukupnoj ceni (≤ 50.000 €), i šalje Telegram notifikacije
za nove pogotke. `seen.json` pamti viđene oglase i commit-uje se nazad u repo.

## Filteri (config.json)
- `target_locations`: Novi Beograd, Zemun, Bežanija, Ledine, Surčin, Jakovo,
  Bečmen, Stari Grad, Savski Venac, Vračar (isto kao stari stanovi projekat).
- `max_total_price`: 50.000 € (samo ukupna cena, bez €/ar ograničenja).

## CLI pomoćnici (isto kao pre)
```
python scraper.py                  # normalan run
python scraper.py --debug          # testiranje, prikazuje matches bez slanja
python scraper.py --clear-seen     # briše seen.json (sledeći run šalje sve)
python scraper.py --test-telegram  # testira Telegram konekciju
python scraper.py --listen         # Telegram komande /svi, /svi<broj> (lokalno)
```

## Nasleđeno iz stanovi projekta (i dalje važi)
- `seen.json` je `{id: unix_timestamp}` format, auto-migracija starog (listnog)
  formata pri prvom runu, čišćenje unosa starijih od 30 dana pri svakom save-u.
- SSL verifikacija: isključena lokalno (antivirus/proxy intercept), uključena
  na GitHub Actions (`CI=true`).
- Telegram retry (3 pokušaja), seen.json upis tek posle uspešnog slanja.
- `--listen` radi samo lokalno (Task Scheduler preko `start_telegram_listener.bat`),
  GitHub Actions se gasi posle svakog run-a i ne može da "sluša".

## Savet za dalje
1. **Prvo pokreni `--debug` lokalno** pre nego što veruješ da 4zida.rs Zemljište
   scraper radi ispravno — nije testiran na pravim podacima (samo sintetički).
2. Ako 4zida scraper ne nalazi ništa ili nalazi pogrešne podatke, otvori
   `https://www.4zida.rs/prodaja-placeva/beograd` u browseru → View Source →
   potraži da li i dalje postoji `/prodaja-placeva/.../.../<24-hex-id>` href
   šema; ako se promenila, treba ažurirati `FZIDA_LISTING_HREF_RE`.
3. Razmisli o dnevnom "digest" rezimeu (1 poruka uveče sa svim placevima koji
   su prošli filter) — manje spama od pojedinačnih poruka.
4. Ne dodavati bazu/framework — JSON fajl + Actions je tačno prava veličina
   rešenja za ovo.

## Kako se pokreće
- Lokalno: `python scraper.py` (config iz `config.json`), test: `--debug`,
  `--test-telegram`
- Automatski: GitHub Actions svaki sat (`.github/workflows/scraper.yml`),
  secrets: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_EXTRA_CHAT_IDS`
  (NOVI bot, ne stanovi bot)

## Stari fajlovi u ovom folderu (nasleđeno, nisu ažurirani)
`CONTEXT_ZA_OPUS.md` i `KONTAKTI_AGENCIJE.md` još uvek referenciraju stari
stanovi projekat (code review prompt, odnosno lični kontakti agencija za
stanove) — nisu obrisani ni menjani jer su to Markove lične beleške, ne kod.
