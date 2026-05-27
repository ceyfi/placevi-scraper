#!/usr/bin/env python3
"""
Scraper za stanove u Beogradu
Prati oglase na Halo Oglasi, Nekretnine.rs, 4zida.rs i City Expert.
Šalje Telegram notifikaciju kad nađe stan u željenim lokacijama ispod zadate cene/m².
"""

import requests
import json
import os
import re
import time
import logging
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# ============================================================
# SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / 'config.json'
SEEN_FILE = BASE_DIR / 'seen.json'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'sr-RS,sr;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# SSL verify: False za lokalne mreže sa proxy/antivirus interceptom
# Na GitHub Actions ovo nema efekta (tamo SSL radi normalno)
SSL_VERIFY = False

# ============================================================
# CONFIG & STATE
# ============================================================

def load_config():
    """Učitaj konfiguraciju iz config.json ili env varijabli (GitHub Actions)."""
    config = {
        'telegram_token': os.environ.get('TELEGRAM_TOKEN', ''),
        'telegram_chat_id': os.environ.get('TELEGRAM_CHAT_ID', ''),
        'max_price_per_m2': int(os.environ.get('MAX_PRICE_PER_M2', 1500)),
        'target_locations': ['Novi Beograd', 'Zemun', 'Ledine', 'Bezanija'],
    }
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding='utf-8') as f:
            file_config = json.load(f)
        config.update(file_config)
        # Env varijable imaju prednost nad config.json
        if os.environ.get('TELEGRAM_TOKEN'):
            config['telegram_token'] = os.environ['TELEGRAM_TOKEN']
        if os.environ.get('TELEGRAM_CHAT_ID'):
            config['telegram_chat_id'] = os.environ['TELEGRAM_CHAT_ID']
    return config

def load_seen():
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE, encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen):
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(list(seen)), f, indent=2)

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }
    try:
        r = requests.post(url, data=data, timeout=10, verify=SSL_VERIFY)
        r.raise_for_status()
        logger.info("✅ Telegram poruka poslata")
        return True
    except Exception as e:
        logger.error(f"❌ Greška pri slanju Telegram poruke: {e}")
        return False

def format_message(listing):
    emoji_source = {
        'Halo Oglasi': '🟡',
        'Nekretnine.rs': '🔵',
        '4zida.rs': '🟢',
        'City Expert': '🔴',
    }
    icon = emoji_source.get(listing.get('source', ''), '🏠')

    lines = [
        f"{icon} <b>{listing.get('title', 'Stan na prodaju')}</b>",
        f"📍 {listing.get('location', 'N/A')}",
    ]
    if listing.get('price'):
        lines.append(f"💶 Cena: <b>{listing['price']:,.0f} €</b>".replace(',', '.'))
    if listing.get('area'):
        lines.append(f"📐 Površina: <b>{listing['area']} m²</b>")
    if listing.get('price_per_m2'):
        lines.append(f"📊 Cena/m²: <b>{listing['price_per_m2']:,.0f} €/m²</b>".replace(',', '.'))
    if listing.get('rooms'):
        lines.append(f"🚪 Sobnost: {listing['rooms']}")
    lines.append(f"🔗 {listing.get('url', '')}")
    lines.append(f"🕐 {listing.get('source', '')} | {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return '\n'.join(lines)

# ============================================================
# HELPERS
# ============================================================

def parse_price(text):
    """Izvuci cenu u evrima iz teksta."""
    if not text:
        return None
    text = text.strip()
    # Ukloni sve osim cifara, tačaka i zareza
    cleaned = re.sub(r'[^\d.,]', '', text)
    # Srpski format: 150.000 ili 150,000 = 150000
    # Detektuj da li je tačka separator hiljada ili decimalna
    if '.' in cleaned and ',' in cleaned:
        # 150.000,00 format → ukloni tačke, zarez je decimalna
        cleaned = cleaned.replace('.', '').replace(',', '.')
    elif cleaned.count('.') == 1 and len(cleaned.split('.')[-1]) == 2:
        # 150000.00 — decimalna tačka
        pass
    else:
        # 150.000 — tačka je separator hiljada
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        val = float(cleaned)
        # Sanity check: cene stanova su između 10.000 i 10.000.000
        if 10_000 <= val <= 10_000_000:
            return val
        # Možda je u hiljadama ili nije EUR
        return None
    except ValueError:
        return None

def parse_area(text):
    """Izvuci površinu u m² iz teksta."""
    if not text:
        return None
    m = re.search(r'(\d+[\.,]?\d*)\s*m[²2]', text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(',', '.'))
            if 10 <= val <= 1000:  # sanity: 10-1000 m²
                return val
        except ValueError:
            pass
    return None

def calc_ppm2(price, area):
    if price and area and area > 0:
        return round(price / area, 0)
    return None

def is_target_location(location_text, targets):
    loc = location_text.lower()
    return any(t.lower() in loc for t in targets)

def is_good_price(ppm2, max_ppm2):
    return ppm2 is not None and ppm2 <= max_ppm2

# ============================================================
# SCRAPER: HALO OGLASI
# ============================================================

HALO_LOCATION_SLUGS = [
    ('novi-beograd', 'Novi Beograd'),
    ('zemun', 'Zemun'),
    ('ledine', 'Ledine'),
    ('bezanija', 'Bezanija'),
]

def scrape_halooglasi(config):
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for slug, location_name in HALO_LOCATION_SLUGS:
        url = f"https://www.halooglasi.com/nekretnine/prodaja-stanova/{slug}?sort=ValidFromMoment_desc"
        logger.info(f"[Halo Oglasi] {url}")
        try:
            r = session.get(url, timeout=20, verify=SSL_VERIFY)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')

            items = soup.select('.product-item')
            logger.info(f"[Halo Oglasi] {location_name}: {len(items)} oglasa")

            for item in items:
                try:
                    # URL i ID
                    link = item.select_one('h3.product-title a, .product-title a, a.ga-title')
                    if not link:
                        link = item.select_one('a[href*="/prodaja-stanova/"]')
                    if not link:
                        continue
                    href = link.get('href', '')
                    raw_id = href.rstrip('/').split('/')[-1].split('?')[0]
                    listing_id = f"halo_{raw_id}"

                    title = link.get_text(strip=True) or f"Stan - {location_name}"

                    # Cena
                    price = None
                    price_el = item.select_one('.price-box-main, [class*="price-main"]')
                    if price_el:
                        price = parse_price(price_el.get_text())

                    # Površina iz features liste
                    area = None
                    for feat in item.select('.product-features li, .features-container li'):
                        txt = feat.get_text(strip=True)
                        a = parse_area(txt)
                        if a:
                            area = a
                            break
                    if not area:
                        area = parse_area(item.get_text())

                    ppm2 = calc_ppm2(price, area)
                    full_url = href if href.startswith('http') else f"https://www.halooglasi.com{href}"

                    results.append({
                        'id': listing_id,
                        'title': title,
                        'location': location_name,
                        'price': price,
                        'area': area,
                        'price_per_m2': ppm2,
                        'url': full_url,
                        'source': 'Halo Oglasi',
                    })
                except Exception as e:
                    logger.debug(f"[Halo Oglasi] oglas greška: {e}")

        except Exception as e:
            logger.error(f"[Halo Oglasi] greška za {slug}: {e}")

        time.sleep(2)

    return results

# ============================================================
# SCRAPER: NEKRETNINE.RS
# ============================================================

NEKRETNINE_LOCATION_SLUGS = [
    ('novi-beograd', 'Novi Beograd'),
    ('zemun', 'Zemun'),
    ('ledine', 'Ledine'),
    ('bezanija', 'Bezanija'),
]

def scrape_nekretnine(config):
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for slug, location_name in NEKRETNINE_LOCATION_SLUGS:
        url = f"https://www.nekretnine.rs/stambeni-objekti/stanovi/{slug}/lista/?sort=new"
        logger.info(f"[Nekretnine.rs] {url}")
        try:
            r = session.get(url, timeout=20, verify=SSL_VERIFY)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')

            # Probaj različite selektore
            items = (
                soup.select('article.real-estate-item') or
                soup.select('li.real-estate-item') or
                soup.select('[class*="property-item"]') or
                soup.select('.offer-body')
            )
            logger.info(f"[Nekretnine.rs] {location_name}: {len(items)} oglasa")

            for item in items:
                try:
                    link = item.select_one('a[href*="/stan"]') or item.select_one('a[href]')
                    if not link:
                        continue
                    href = link.get('href', '')
                    raw_id = href.rstrip('/').split('/')[-1].split('?')[0]
                    listing_id = f"nek_{raw_id}"

                    title_el = item.select_one('h2, h3, .offer-title, [class*="title"]')
                    title = title_el.get_text(strip=True) if title_el else f"Stan - {location_name}"

                    # Cena
                    price = None
                    price_el = item.select_one('[class*="price"]')
                    if price_el:
                        price = parse_price(price_el.get_text())

                    # Površina
                    area = None
                    for sel in ['[class*="size"]', '[class*="area"]', '[class*="kvadrat"]', 'li', 'span']:
                        for el in item.select(sel):
                            a = parse_area(el.get_text())
                            if a:
                                area = a
                                break
                        if area:
                            break
                    if not area:
                        area = parse_area(item.get_text())

                    ppm2 = calc_ppm2(price, area)
                    full_url = href if href.startswith('http') else f"https://www.nekretnine.rs{href}"

                    results.append({
                        'id': listing_id,
                        'title': title,
                        'location': location_name,
                        'price': price,
                        'area': area,
                        'price_per_m2': ppm2,
                        'url': full_url,
                        'source': 'Nekretnine.rs',
                    })
                except Exception as e:
                    logger.debug(f"[Nekretnine.rs] oglas greška: {e}")

        except Exception as e:
            logger.error(f"[Nekretnine.rs] greška za {slug}: {e}")

        time.sleep(2)

    return results

# ============================================================
# SCRAPER: 4ZIDA.RS (JSON API)
# ============================================================

def scrape_4zida(config):
    results = []
    session = requests.Session()
    session.headers.update({**HEADERS, 'Accept': 'application/json'})

    # 4zida ima javni API
    # Lokacije: Novi Beograd = placeId 638, Zemun = 630
    # Bezanija i Ledine su delovi Novog Beograda
    place_configs = [
        (638, 'Novi Beograd'),
        (630, 'Zemun'),
    ]

    for place_id, location_name in place_configs:
        api_url = (
            f"https://api.4zida.rs/v6/search/apartments"
            f"?for=sale&placeIds[]={place_id}&sort=-createdAt&page=1&limit=40"
        )
        logger.info(f"[4zida.rs] {api_url}")
        try:
            r = session.get(api_url, timeout=20)
            r.raise_for_status()
            data = r.json()

            ads = data.get('ads', data.get('results', data if isinstance(data, list) else []))
            logger.info(f"[4zida.rs] {location_name}: {len(ads)} oglasa")

            for ad in ads:
                try:
                    ad_id = str(ad.get('id', ''))
                    listing_id = f"4zida_{ad_id}"

                    price = ad.get('price') or ad.get('totalPrice')
                    area = ad.get('m2') or ad.get('size')

                    # Lokacija
                    addr = ad.get('address', {}) or {}
                    city_part = addr.get('cityPart', {}) or {}
                    street = addr.get('street', {}) or {}
                    nb_name = city_part.get('name', location_name) if isinstance(city_part, dict) else location_name
                    st_name = street.get('name', '') if isinstance(street, dict) else ''
                    location_str = f"{nb_name}, {st_name}".strip(', ')

                    # Sobnost
                    structure = ad.get('structure', {}) or {}
                    rooms = structure.get('name', '') if isinstance(structure, dict) else str(structure)

                    ppm2 = calc_ppm2(price, area)

                    # URL
                    slug = ad.get('slug', '') or ad.get('url', '')
                    if slug:
                        full_url = f"https://4zida.rs/{slug}" if not slug.startswith('http') else slug
                    else:
                        full_url = f"https://4zida.rs/stan-na-prodaju/{ad_id}"

                    title = ad.get('title') or f"Stan {area}m² – {nb_name}"

                    results.append({
                        'id': listing_id,
                        'title': title,
                        'location': location_str,
                        'price': price,
                        'area': area,
                        'price_per_m2': ppm2,
                        'url': full_url,
                        'source': '4zida.rs',
                        'rooms': rooms,
                    })
                except Exception as e:
                    logger.debug(f"[4zida.rs] oglas greška: {e}")

        except Exception as e:
            logger.error(f"[4zida.rs] API greška za placeId {place_id}: {e}")

        time.sleep(2)

    # Fallback: HTML ako API ne radi
    if not results:
        logger.info("[4zida.rs] Probam HTML fallback...")
        for slug, location_name in [('novi-beograd', 'Novi Beograd'), ('zemun', 'Zemun')]:
            try:
                session.headers.update({'Accept': 'text/html'})
                r = session.get(f"https://4zida.rs/prodaja-stanova/{slug}", timeout=20)
                soup = BeautifulSoup(r.text, 'html.parser')
                for item in soup.select('[class*="Card"], article, [class*="listing"]'):
                    link = item.select_one('a[href*="/stan"], a[href*="/prodaja"]')
                    if not link:
                        continue
                    href = link.get('href', '')
                    raw_id = href.rstrip('/').split('/')[-1]
                    text = item.get_text()
                    price = parse_price(re.search(r'[\d\.]+\s*€', text).group(0) if re.search(r'[\d\.]+\s*€', text) else '')
                    area = parse_area(text)
                    ppm2 = calc_ppm2(price, area)
                    results.append({
                        'id': f"4zida_{raw_id}",
                        'title': f"Stan – {location_name}",
                        'location': location_name,
                        'price': price,
                        'area': area,
                        'price_per_m2': ppm2,
                        'url': f"https://4zida.rs{href}" if href.startswith('/') else href,
                        'source': '4zida.rs',
                    })
            except Exception as e:
                logger.error(f"[4zida.rs] HTML fallback greška: {e}")
            time.sleep(2)

    return results

# ============================================================
# SCRAPER: CITY EXPERT (API)
# ============================================================

def scrape_cityexpert(config):
    results = []
    session = requests.Session()
    session.headers.update({**HEADERS, 'Accept': 'application/json', 'Referer': 'https://cityexpert.rs/'})

    # Municipality IDs: Novi Beograd = 7, Zemun = 16
    municipalities = [
        (7, 'Novi Beograd'),
        (16, 'Zemun'),
    ]

    for mun_id, location_name in municipalities:
        api_url = "https://cityexpert.rs/api/Search/"
        params = {
            'ptId': 1,           # tip: stan
            'cityId': 1,         # grad: Beograd
            'rentOrSale': 's',   # prodaja
            'currentPage': 1,
            'resultsPerPage': 50,
            'sort': 'datedesc',
            'municipalities[]': mun_id,
        }
        logger.info(f"[City Expert] {api_url} municipalityId={mun_id}")
        try:
            r = session.get(api_url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()

            # City Expert response: {"result": [...], "info": {...}}
            ads = data.get('result', data.get('results', []))
            logger.info(f"[City Expert] {location_name}: {len(ads)} oglasa")

            for ad in ads:
                try:
                    prop_id = str(ad.get('propId', ad.get('id', '')))
                    listing_id = f"ce_{prop_id}"

                    price = ad.get('price') or ad.get('totalPrice')
                    area = ad.get('size') or ad.get('m2')

                    # Lokacija
                    mun_info = ad.get('municipality', {}) or {}
                    mun_name = mun_info.get('title', location_name) if isinstance(mun_info, dict) else location_name
                    micro = ad.get('microlocation', {}) or {}
                    micro_name = micro.get('title', '') if isinstance(micro, dict) else ''
                    street = ad.get('street', '') or ''
                    location_str = ', '.join(filter(None, [mun_name, micro_name, street]))

                    structure = str(ad.get('structure', '') or '')
                    slug = ad.get('slug', '') or ''
                    full_url = (
                        f"https://cityexpert.rs/prodaja/{slug}" if slug
                        else f"https://cityexpert.rs/prodaja/stan-{prop_id}"
                    )

                    ppm2 = calc_ppm2(price, area)
                    title = f"Stan {area}m² – {mun_name}"

                    results.append({
                        'id': listing_id,
                        'title': title,
                        'location': location_str,
                        'price': price,
                        'area': area,
                        'price_per_m2': ppm2,
                        'url': full_url,
                        'source': 'City Expert',
                        'rooms': structure,
                    })
                except Exception as e:
                    logger.debug(f"[City Expert] oglas greška: {e}")

        except Exception as e:
            logger.error(f"[City Expert] API greška za mun {mun_id}: {e}")

        time.sleep(2)

    return results

# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("=" * 50)
    logger.info("🔍 Pokretanje scrapera za stanove")
    logger.info(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    logger.info("=" * 50)

    config = load_config()
    seen = load_seen()

    telegram_token = config.get('telegram_token', '')
    telegram_chat_id = config.get('telegram_chat_id', '')
    max_ppm2 = int(config.get('max_price_per_m2', 1500))
    targets = config.get('target_locations', ['Novi Beograd', 'Zemun', 'Ledine', 'Bezanija'])

    if not telegram_token:
        logger.warning("⚠️  Telegram token nije podešen!")
    if not telegram_chat_id:
        logger.warning("⚠️  Telegram chat ID nije podešen!")

    logger.info(f"🎯 Lokacije: {', '.join(targets)}")
    logger.info(f"💶 Max cena/m²: {max_ppm2} €")
    logger.info(f"👁️  Već viđeno: {len(seen)} oglasa")

    # ── Pokretanje svakog scrapera ──────────────────────────
    scrapers = [
        ('Halo Oglasi', scrape_halooglasi),
        ('Nekretnine.rs', scrape_nekretnine),
        ('4zida.rs', scrape_4zida),
        ('City Expert', scrape_cityexpert),
    ]

    all_listings = []
    for name, fn in scrapers:
        try:
            found = fn(config)
            logger.info(f"✔ {name}: {len(found)} oglasa")
            all_listings.extend(found)
        except Exception as e:
            logger.error(f"✘ {name} pao: {e}")

    logger.info(f"\n📦 Ukupno: {len(all_listings)} oglasa | Novi: ?")

    # ── Filtriranje i notifikacije ──────────────────────────
    new_total = 0
    sent_total = 0

    for listing in all_listings:
        lid = listing.get('id')
        if not lid:
            continue

        is_new = lid not in seen
        seen.add(lid)

        if not is_new:
            continue

        new_total += 1

        loc_ok = is_target_location(listing.get('location', ''), targets)
        price_ok = is_good_price(listing.get('price_per_m2'), max_ppm2)

        if loc_ok and price_ok:
            ppm2 = listing.get('price_per_m2', 0)
            logger.info(
                f"🎯 MATCH: [{listing['source']}] {listing['title']} | "
                f"{ppm2:.0f}€/m² | {listing['url']}"
            )
            if telegram_token and telegram_chat_id:
                msg = format_message(listing)
                ok = send_telegram(telegram_token, telegram_chat_id, msg)
                if ok:
                    sent_total += 1
                    time.sleep(1.5)  # anti-spam

    logger.info(f"\n📊 Rezultati:")
    logger.info(f"   Novi oglasi: {new_total}")
    logger.info(f"   Notifikacije poslate: {sent_total}")

    save_seen(seen)
    logger.info("✅ Scraping završen.\n")


if __name__ == '__main__':
    import sys

    # --test-telegram : samo pošalji test poruku i izađi
    if '--test-telegram' in sys.argv:
        config = load_config()
        token = config.get('telegram_token', '')
        chat_id = config.get('telegram_chat_id', '')
        print(f"Token: {token[:10]}... | Chat ID: {chat_id}")
        if not token or not chat_id:
            print("❌ Token ili chat ID nisu podešeni u config.json!")
        else:
            ok = send_telegram(token, chat_id, "✅ Test poruka — scraper radi!")
            print("✅ Poruka poslata!" if ok else "❌ Greška pri slanju!")
        sys.exit(0)

    # --clear-seen : resetuj listu viđenih oglasa
    if '--clear-seen' in sys.argv:
        save_seen(set())
        print("✅ seen.json je obrisan — sledeći run će poslati sve oglase koji prođu filter.")
        sys.exit(0)

    # --debug : pokreni scraper ali prikaži SVE oglase (bez Telegrama) da vidiš šta se nalazi
    if '--debug' in sys.argv:
        config = load_config()
        max_ppm2 = int(config.get('max_price_per_m2', 1500))
        targets = config.get('target_locations', ['Novi Beograd', 'Zemun', 'Ledine', 'Bezanija'])
        scrapers = [
            ('Halo Oglasi', scrape_halooglasi),
            ('Nekretnine.rs', scrape_nekretnine),
            ('4zida.rs', scrape_4zida),
            ('City Expert', scrape_cityexpert),
        ]
        all_listings = []
        for name, fn in scrapers:
            try:
                found = fn(config)
                all_listings.extend(found)
            except Exception as e:
                print(f"✘ {name} pao: {e}")

        print(f"\n{'='*60}")
        print(f"Ukupno nađeno: {len(all_listings)} oglasa")
        matches = [l for l in all_listings if
                   is_target_location(l.get('location',''), targets) and
                   is_good_price(l.get('price_per_m2'), max_ppm2)]
        print(f"Prolazi filter (lokacija + cena ≤ {max_ppm2}€/m²): {len(matches)}")
        print(f"{'='*60}")
        for l in matches:
            print(f"  [{l['source']}] {l['title']} | {l.get('price_per_m2',0):.0f}€/m² | {l['url']}")
        if not matches:
            # Prikaži distribuciju cena da vidiš zašto ne prolaze
            print("\nNema oglasa koji prolaze filter. Distribucija cena/m²:")
            loc_listings = [l for l in all_listings if is_target_location(l.get('location',''), targets)]
            print(f"  Oglasi u traženim lokacijama: {len(loc_listings)}")
            prices = [l['price_per_m2'] for l in loc_listings if l.get('price_per_m2')]
            if prices:
                print(f"  Min: {min(prices):.0f}€/m² | Max: {max(prices):.0f}€/m² | Prosek: {sum(prices)/len(prices):.0f}€/m²")
        sys.exit(0)

    main()
