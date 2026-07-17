#!/usr/bin/env python3
"""
Scraper za PLACEVE (zemljišta) u Beogradu — nikako stanovi.
Prati oglase na Halo Oglasi, 4zida.rs i Nekretnine.rs.
Šalje Telegram notifikaciju kad nađe plac u željenim lokacijama ispod zadate ukupne cene.

NAPOMENA (jul 2026): ovaj fajl je prerađen iz "stanovi" verzije da radi ISKLJUČIVO
sa zemljištima. City Expert je izbačen — nema pouzdanu kategoriju zemljišta
(probano ptId=1..7 na cityexpert.rs/prodaja-nekretnina/beograd, nađeni su samo
stan/kuća/poslovni prostor/lokal/stan-u-kući, zemljište nigde u navigaciji).
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

# SSL verify: lokalno isključen (antivirus/proxy intercept HTTPS-a),
# na GitHub Actions (CI=true) uključen — tamo nema proxy-ja i SSL radi normalno
SSL_VERIFY = os.environ.get('CI') == 'true'

# Zaobiđi lokalni proxy (antivirus/korporativni) koji blokira HTTPS tunel
# Ovo ne utiče na GitHub Actions gde nema proxy-ja
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

# ============================================================
# CONFIG & STATE
# ============================================================

DEFAULT_LOCATIONS = [
    'Novi Beograd', 'Zemun', 'Bezanija', 'Ledine', 'Surčin',
    'Jakovo', 'Bečmen', 'Stari Grad', 'Savski Venac', 'Vračar',
]

def load_config():
    """Učitaj konfiguraciju iz config.json ili env varijabli (GitHub Actions).
    VAŽNO: ovo je bot ZA PLACEVE — koristi svoj sopstveni TELEGRAM_TOKEN/CHAT_ID,
    ne deli bota sa "stanovi" projektom."""
    config = {
        'telegram_token': os.environ.get('TELEGRAM_TOKEN', ''),
        'telegram_chat_id': os.environ.get('TELEGRAM_CHAT_ID', ''),
        'max_total_price': int(os.environ.get('MAX_TOTAL_PRICE', 50000)),
        'target_locations': DEFAULT_LOCATIONS,
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
        if os.environ.get('TELEGRAM_EXTRA_CHAT_IDS'):
            # Može biti više ID-ova razdvojenih zarezom: "123,456"
            extra = [x.strip() for x in os.environ['TELEGRAM_EXTRA_CHAT_IDS'].split(',') if x.strip()]
            config['telegram_extra_chat_ids'] = extra
    return config

# Koliko dana čuvamo ID u seen.json otkad je POSLEDNJI PUT viđen u feedu.
# Timestamp se osvežava svaki run dok je oglas živ, pa se brišu samo
# oglasi koji su skinuti sa sajta pre više od N dana.
SEEN_MAX_AGE_DAYS = 30

def load_seen():
    """seen.json format: {"listing_id": unix_timestamp}. Stari format (lista) se migrira."""
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return {}
        if isinstance(data, list):  # migracija starog formata
            now = time.time()
            return {str(lid): now for lid in data}
        return {str(k): float(v) for k, v in data.items()}
    return {}

def save_seen(seen):
    cutoff = time.time() - SEEN_MAX_AGE_DAYS * 86400
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    removed = len(seen) - len(pruned)
    if removed:
        logger.info(f"🧹 seen.json: obrisano {removed} unosa starijih od {SEEN_MAX_AGE_DAYS} dana")
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(pruned, f, indent=2, sort_keys=True)

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(token, chat_id, message, retries=3):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, data=data, timeout=10, verify=SSL_VERIFY,
                              proxies={'http': '', 'https': ''})
            r.raise_for_status()
            logger.info("✅ Telegram poruka poslata")
            return True
        except Exception as e:
            logger.error(f"❌ Greška pri slanju Telegram poruke (pokušaj {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    return False

def format_message(listing):
    """Format je uvek za PLAC: površina u arima, cena/ar u €/ar."""
    emoji_source = {
        'Halo Zemljište': '🟡',
        '4zida.rs Zemljište': '🟢',
        'Nekretnine.rs Zemljište': '🔵',
    }
    icon = emoji_source.get(listing.get('source', ''), '🌳')

    lines = [
        f"{icon}🌳 <b>{listing.get('title', 'Plac na prodaju')}</b>",
        f"📍 {listing.get('location', 'N/A')}",
    ]
    if listing.get('price'):
        lines.append(f"💶 Cena: <b>{listing['price']:,.0f} €</b>".replace(',', '.'))
    if listing.get('area'):
        lines.append(f"📐 Površina: <b>{listing['area']} ari</b>")
    if listing.get('price_per_ar'):
        lines.append(f"📊 Cena/ar: <b>{listing['price_per_ar']:,.0f} €/ar</b>".replace(',', '.'))
    lines.append(f"🔗 {listing.get('url', '')}")
    lines.append(f"🕐 {listing.get('source', '')} | {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return '\n'.join(lines)

# ============================================================
# HELPERS
# ============================================================

def parse_price(text):
    if not text:
        return None
    text = text.strip()
    cleaned = re.sub(r'[^\d.,]', '', text)
    if '.' in cleaned and ',' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    elif cleaned.count('.') == 1 and len(cleaned.split('.')[-1]) == 2:
        pass
    else:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        val = float(cleaned)
        if 100 <= val <= 10_000_000:
            return val
        return None
    except ValueError:
        return None

def parse_area_m2(text):
    """m², za plac dozvoljavamo mnogo širi opseg nego za stan (do 20 ha)."""
    if not text:
        return None
    m = re.search(r'(\d+[\.,]?\d*)\s*m[²2]', text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(',', '.'))
            if 5 <= val <= 200_000:
                return val
        except ValueError:
            pass
    return None

def parse_area_ari(text):
    """Ari ('a' na 4zida.rs, 'ari'/'ar' na Halo Oglasi), npr. '58 a', '6 ari', '48.21 a'."""
    if not text:
        return None
    m = re.search(r'(\d+[\.,]?\d*)\s*a(?:ri|r)?\b', text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(',', '.'))
            if 0 < val <= 2000:
                return val
        except ValueError:
            pass
    return None

def calc_price_per_ar(price, area_ar):
    if price and area_ar and area_ar > 0:
        return round(price / area_ar, 0)
    return None

_DIACRITICS_MAP = str.maketrans('čćšžđ', 'ccszd')

def normalize_text(text):
    """Lowercase + skini srpske dijakritike, da 'Bežanija' matchuje 'Bezanija' i obrnuto.
    'dj' → 'd' izjednačava dva zapisa slova đ (Đurđevo == Djurdjevo)."""
    return text.lower().translate(_DIACRITICS_MAP).replace('dj', 'd')

def is_target_location(location_text, targets):
    loc = normalize_text(location_text)
    return any(normalize_text(t) in loc for t in targets)

# ============================================================
# SCRAPER: HALO OGLASI — ZEMLJIŠTA (placevi)
# ============================================================

# Ista lista lokacija (grad_id_l-lokacija_id_l-mikrolokacija_id_l) kao za stanove:
# Novi Beograd, Zemun, Bežanija, Ledine, Surčin, Jakovo, Bečmen, Stari Grad,
# Savski Venac, Vračar. ID šema je ista bez obzira na tip nekretnine.
HALO_ZEMLJISTE_URL = (
    "https://www.halooglasi.com/nekretnine/prodaja-zemljista"
    "?grad_id_l-lokacija_id_l-mikrolokacija_id_l=40574,40787,535592,55297,538989,525206,525208,525211,40776,40772,40784"
    "&sort=ValidFromMoment_desc"
)

def scrape_halooglasi_zemljiste(config):
    """Scrape placeva na prodaju na Halo Oglasi u svim config lokacijama."""
    results = []
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        **HEADERS,
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })

    logger.info(f"[Halo Zemljište] {HALO_ZEMLJISTE_URL}")
    try:
        r = session.get(HALO_ZEMLJISTE_URL, timeout=20, verify=SSL_VERIFY)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        items = soup.select('.product-item')
        logger.info(f"[Halo Zemljište] {len(items)} oglasa")

        for item in items:
            try:
                link = item.select_one('h3.product-title a, .product-title a, a.ga-title')
                if not link:
                    link = item.select_one('a[href*="/prodaja-zemljista/"]')
                if not link:
                    continue
                href = link.get('href', '')
                raw_id = href.rstrip('/').split('/')[-1].split('?')[0]
                listing_id = f"halo_z_{raw_id}"
                title = link.get_text(strip=True) or "Plac na prodaju"

                price = None
                price_el = item.select_one('.price-box-main, [class*="price-main"]')
                if price_el:
                    price = parse_price(price_el.get_text())

                # Površina u arima — tražimo "ar"/"ari" ili "m²" u features
                area_ar = None
                area_m2 = None
                for feat in item.select('.product-features li, .features-container li'):
                    txt = feat.get_text(strip=True)
                    a_ar = parse_area_ari(txt)
                    if a_ar:
                        area_ar = a_ar
                    a_m2 = parse_area_m2(txt)
                    if a_m2:
                        area_m2 = a_m2

                if area_ar is None and area_m2:
                    area_ar = round(area_m2 / 100, 2)

                price_per_ar = calc_price_per_ar(price, area_ar)
                full_url = href if href.startswith('http') else f"https://www.halooglasi.com{href}"

                location_str = 'Beograd'
                loc_el = item.select_one('.subtitle-places, [class*="subtitle"]')
                if loc_el:
                    location_str = loc_el.get_text(strip=True)

                results.append({
                    'id': listing_id,
                    'title': title,
                    'location': location_str,
                    'price': price,
                    'area': area_ar,
                    'price_per_ar': price_per_ar,
                    'url': full_url,
                    'source': 'Halo Zemljište',
                })
            except Exception as e:
                logger.debug(f"[Halo Zemljište] oglas greška: {e}")

    except Exception as e:
        logger.error(f"[Halo Zemljište] greška: {e}")

    return results

# ============================================================
# SCRAPER: 4ZIDA.RS — PRODAJA PLACEVA (HTML, server-rendered)
# ============================================================
# NAPOMENA: 4zida za stanove ima JSON API (api.4zida.rs), ali za placeve nismo
# našli odgovarajući API endpoint (v6/search/land, /plots, /lands, /houses su
# probani i ne postoje). Stranica /prodaja-placeva/beograd JE server-rendered
# (vidljiv sadržaj bez izvršavanja JS-a), pa scrape-ujemo HTML direktno preko
# href regexa (ID oglasa je 24-karakterni hex, kao Mongo ObjectId) — otporn ije
# na promenu CSS klasa nego selektori po klasama.
# EKSPERIMENTALNO — nije testirano uživo (sandbox nema pristup 4zida.rs).
# Testiraj sa `python scraper.py --debug` pre nego što se osloniš na ovaj izvor.

FZIDA_PLACEVI_URL = "https://www.4zida.rs/prodaja-placeva/beograd"
FZIDA_LISTING_HREF_RE = re.compile(r'/prodaja-placeva/[a-z0-9\-]+/[a-z0-9\-]+/([a-f0-9]{24})')


def _fzida_card_container(anchor):
    """Popni se od anchor-a nagore SAMO dok kontejner sadrži href-ove za jedan
    jedini oglas. Čim se u kontejneru pojavi i ID drugog oglasa (znači da smo
    zahvatili i susednu karticu), vraćamo poslednji kontejner koji je sadržao
    isključivo naš oglas — sprečava mešanje cene/površine između kartica."""
    own_match = FZIDA_LISTING_HREF_RE.search(anchor.get('href', ''))
    if not own_match:
        return anchor
    own_id = own_match.group(1)
    last_good = anchor
    current = anchor
    for _ in range(10):
        if current.parent is None:
            break
        current = current.parent
        ids_here = set()
        for tag in current.find_all('a', href=True):
            m = FZIDA_LISTING_HREF_RE.search(tag['href'])
            if m:
                ids_here.add(m.group(1))
        if ids_here - {own_id}:
            break
        last_good = current
    return last_good


def scrape_4zida_zemljiste(config):
    results = []
    targets = config.get('target_locations', DEFAULT_LOCATIONS)

    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        **HEADERS,
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    })

    MAX_PAGES = 5
    seen_ids_this_run = set()

    for page in range(1, MAX_PAGES + 1):
        url = FZIDA_PLACEVI_URL if page == 1 else f"{FZIDA_PLACEVI_URL}?page={page}"
        logger.info(f"[4zida.rs Zemljište] strana {page}: {url}")
        try:
            r = session.get(url, timeout=20, verify=SSL_VERIFY)
            if r.status_code != 200:
                logger.warning(f"[4zida.rs Zemljište] status {r.status_code}, stajem")
                break
            soup = BeautifulSoup(r.text, 'html.parser')

            anchors = [a for a in soup.find_all('a', href=True) if FZIDA_LISTING_HREF_RE.search(a['href'])]
            if not anchors:
                logger.info(f"[4zida.rs Zemljište] strana {page}: nema oglasa, stajem")
                break

            page_new = 0
            for a in anchors:
                href = a['href']
                m = FZIDA_LISTING_HREF_RE.search(href)
                if not m:
                    continue
                raw_id = m.group(1)
                listing_id = f"4zida_z_{raw_id}"
                if raw_id in seen_ids_this_run:
                    continue  # isti oglas se često linkuje iz više <a> tagova (slika + naslov)
                seen_ids_this_run.add(raw_id)
                page_new += 1

                try:
                    # Kontejner ograničen na OVAJ oglas (ne sme da pokupi susednu karticu)
                    container = _fzida_card_container(a)
                    block_text = container.get_text(' ', strip=True)

                    # Naslov: prvo probaj img alt (čist tekst bez cene), pa tek onda
                    # tekst linka posečen pre prve cene (da cena/lokacija ne uđu u naslov)
                    title = None
                    img = container.find('img', alt=True)
                    if img and img.get('alt', '').strip():
                        title = re.sub(r'\s*\|\s*4zida\.rs\s*$', '', img['alt'].strip())
                    if not title:
                        raw = a.get_text(strip=True)
                        cut = re.search(r'\d[\d.,]*\s*€', raw)
                        title = raw[:cut.start()].strip() if cut else raw
                    if not title:
                        title = "Plac na prodaju"

                    # Cena ukupno: prvi "X.XXX €" koji NIJE praćen sa "/a" (cena po aru)
                    price = None
                    for pm in re.finditer(r'([\d.,]+)\s*€', block_text):
                        after = block_text[pm.end():pm.end() + 3]
                        if '/a' in after.replace(' ', ''):
                            continue
                        price = parse_price(pm.group(1) + ' €')
                        if price:
                            break

                    price_per_ar = None
                    pm_ar = re.search(r'([\d.,]+)\s*€\s*/\s*a\b', block_text)
                    if pm_ar:
                        price_per_ar = parse_price(pm_ar.group(1) + ' €')

                    area_ar = parse_area_ari(block_text)
                    if area_ar is None:
                        area_m2 = parse_area_m2(block_text)
                        if area_m2:
                            area_ar = round(area_m2 / 100, 2)

                    if price_per_ar is None:
                        price_per_ar = calc_price_per_ar(price, area_ar)

                    # Lokacija: tekst pre cene, obično "Ulica Naselje, Opština opština, Beograd"
                    loc_match = re.search(r'^(.*?Beograd)', block_text)
                    location_str = loc_match.group(1) if loc_match else block_text[:80]

                    if not is_target_location(location_str, targets):
                        continue

                    full_url = href if href.startswith('http') else f"https://www.4zida.rs{href}"

                    results.append({
                        'id': listing_id,
                        'title': title,
                        'location': location_str,
                        'price': price,
                        'area': area_ar,
                        'price_per_ar': price_per_ar,
                        'url': full_url,
                        'source': '4zida.rs Zemljište',
                    })
                except Exception as e:
                    logger.debug(f"[4zida.rs Zemljište] oglas greška: {e}")

            logger.info(f"[4zida.rs Zemljište] strana {page}: {page_new} novih linkova obrađeno")
            if page_new == 0:
                break

        except Exception as e:
            logger.error(f"[4zida.rs Zemljište] greška strana {page}: {e}")
            break

        time.sleep(1.5)

    logger.info(f"[4zida.rs Zemljište] Ukupno u traženim lokacijama: {len(results)}")
    return results

# ============================================================
# SCRAPER: NEKRETNINE.RS — PRODAJA ZEMLJIŠTA (__NEXT_DATA__)
# ============================================================

def scrape_nekretnine_zemljiste(config):
    """
    Ista tehnika kao za stanove: podaci su u __NEXT_DATA__ JSON-u unutar HTML-a.
    URL: /prodaja-zemljista/beograd/?pag={page}. Struktura JSON-a (realEstate/
    properties/location) je ista za sve kategorije na sajtu — samo je promenjen
    URL sa prodaja-stanova na prodaja-zemljista.
    """
    results = []
    targets = config.get('target_locations', DEFAULT_LOCATIONS)
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        **HEADERS,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })

    MAX_PAGES = 6

    for page in range(1, MAX_PAGES + 1):
        if page == 1:
            url = "https://www.nekretnine.rs/prodaja-zemljista/beograd/"
        else:
            url = f"https://www.nekretnine.rs/prodaja-zemljista/beograd/?pag={page}"

        logger.info(f"[Nekretnine.rs Zemljište] strana {page}: {url}")
        try:
            r = session.get(url, timeout=20, verify=SSL_VERIFY)
            if r.status_code != 200:
                logger.warning(f"[Nekretnine.rs Zemljište] status {r.status_code}")
                break

            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if not m:
                logger.warning("[Nekretnine.rs Zemljište] Nema __NEXT_DATA__")
                break

            page_data = json.loads(m.group(1))
            query_data = page_data['props']['pageProps']['dehydratedState']['queries'][0]['state']['data']
            listings_raw = query_data.get('results', [])

            logger.info(f"[Nekretnine.rs Zemljište] strana {page}: {len(listings_raw)} oglasa")
            if not listings_raw:
                break

            for item in listings_raw:
                try:
                    re_data = item.get('realEstate', {})
                    seo = item.get('seo', {})

                    listing_id = f"nek_z_{re_data.get('id', '')}"
                    price = re_data.get('price', {}).get('value')
                    props = (re_data.get('properties') or [{}])[0]
                    location = props.get('location', {})

                    macrozone = location.get('macrozone', '')
                    microzone = location.get('microzone', '')
                    location_str = ', '.join(filter(None, [macrozone, microzone, location.get('city', '')]))

                    if not is_target_location(location_str, targets):
                        continue

                    # Površina zemljišta: probaj 'surface' (m²) pa 'landArea'/'plotArea' (ari) ako postoje
                    surface_str = props.get('surface', '') or ''
                    area_ar = parse_area_ari(surface_str)
                    if area_ar is None:
                        area_m2 = parse_area_m2(surface_str) or (
                            props.get('landArea') if isinstance(props.get('landArea'), (int, float)) else None
                        )
                        if area_m2:
                            area_ar = round(area_m2 / 100, 2)

                    price_per_ar = calc_price_per_ar(price, area_ar)
                    full_url = seo.get('url', f"https://www.nekretnine.rs/oglasi/{re_data.get('id', '')}/")
                    title = seo.get('anchor') or props.get('caption') or f"Plac – {macrozone or 'Beograd'}"

                    results.append({
                        'id': listing_id,
                        'title': title,
                        'location': location_str,
                        'price': price,
                        'area': area_ar,
                        'price_per_ar': price_per_ar,
                        'url': full_url,
                        'source': 'Nekretnine.rs Zemljište',
                    })
                except Exception as e:
                    logger.debug(f"[Nekretnine.rs Zemljište] oglas greška: {e}")

        except Exception as e:
            logger.error(f"[Nekretnine.rs Zemljište] greška strana {page}: {e}")
            break

        time.sleep(2)

    logger.info(f"[Nekretnine.rs Zemljište] Ukupno u traženim lokacijama: {len(results)}")
    return results

# ============================================================
# ZAJEDNIČKI SPISAK SCRAPERA + FILTER (koristi main, --debug i --listen)
# ============================================================

SCRAPERS_ALL = [
    ('Halo Zemljište', scrape_halooglasi_zemljiste),
    ('4zida.rs Zemljište', scrape_4zida_zemljiste),
    ('Nekretnine.rs Zemljište', scrape_nekretnine_zemljiste),
]
# Nijedan izvor trenutno nije poznat po tome da blokira GitHub Actions IP
# (za razliku od starog "stanovi" projekta gde je Halo Oglasi blokirao Actions).
# Ako se to ispostavi netačno za neki izvor, izbaci ga iz ove liste.
SCRAPERS_ACTIONS = SCRAPERS_ALL


def run_scrapers_collect(config, scrapers):
    """Pokreni listu (naziv, funkcija) scrapera i skupi sve rezultate. Pad jednog ne ruši ostale."""
    all_listings = []
    for name, fn in scrapers:
        try:
            found = fn(config)
            logger.info(f"✔ {name}: {len(found)} oglasa")
            all_listings.extend(found)
        except Exception as e:
            logger.error(f"✘ {name} pao: {e}")
    return all_listings


def filter_match(listing, targets, max_total):
    """Da li plac prolazi lokacijski + cenovni filter (samo ukupna cena, bez €/ar capa)."""
    loc_ok = is_target_location(listing.get('location', ''), targets)
    price_val = listing.get('price')
    total_ok = max_total is None or (price_val is not None and price_val <= max_total)
    return loc_ok and total_ok


# ============================================================
# TELEGRAM KOMANDE (/svi, /svi<broj>) — na zahtev, ne čeka se seen.json
# ============================================================

TELEGRAM_CMD_RE = re.compile(r'^/svi(\d+)?\b')


def get_telegram_updates(token, offset=None, timeout=30):
    """Long-poll Telegram getUpdates. Vraća listu update objekata."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {'timeout': timeout}
    if offset is not None:
        params['offset'] = offset
    try:
        r = requests.get(url, params=params, timeout=timeout + 10, verify=SSL_VERIFY,
                         proxies={'http': '', 'https': ''})
        r.raise_for_status()
        return r.json().get('result', [])
    except Exception as e:
        logger.error(f"❌ Greška pri getUpdates: {e}")
        return []


def handle_svi_command(config, chat_id, telegram_token, override_total=None):
    """/svi → svi trenutni matches po config filterima (bez seen.json ograničenja).
    /svi<N> → isto, ali max ukupna cena = N*1000 €."""
    targets = config.get('target_locations', ['Beograd'])
    max_total = override_total if override_total is not None else config.get('max_total_price')

    cena_txt = f" do {max_total:,.0f} €".replace(',', '.') if max_total else ""
    send_telegram(telegram_token, chat_id, f"🔍 Tražim sve placeve{cena_txt}... (30-60s)")

    all_listings = run_scrapers_collect(config, SCRAPERS_ALL)
    matches = [l for l in all_listings if filter_match(l, targets, max_total)]

    if not matches:
        send_telegram(telegram_token, chat_id, "😕 Nema placeva koji ispunjavaju kriterijume trenutno.")
        return

    matches.sort(key=lambda l: l.get('price') or float('inf'))

    header = f"📋 Nađeno {len(matches)} placeva{cena_txt}"
    send_telegram(telegram_token, chat_id, header)
    time.sleep(1)

    # Kompaktna lista (ne pun format_message po oglasu — previše poruka za spam).
    # Chunk-uje se da ne pređe Telegram limit od 4096 karaktera po poruci.
    chunk = ""
    for l in matches:
        price = f"{l['price']:,.0f}€".replace(',', '.') if l.get('price') else '?'
        ppar_val = l.get('price_per_ar')
        ppar = f" ({ppar_val:,.0f}€/ar)".replace(',', '.') if ppar_val else ''
        title = (l.get('title') or '')[:45]
        line = f"• <b>{price}</b>{ppar} | {title} | {l.get('location', '')}\n{l.get('url', '')}\n"
        if len(chunk) + len(line) > 3500:
            send_telegram(telegram_token, chat_id, chunk)
            time.sleep(1)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        send_telegram(telegram_token, chat_id, chunk)


def run_telegram_listener(config):
    """Beskonačna petlja: long-poll Telegram, odgovori na /svi i /svi<N> komande.
    Namenjeno za lokalno pokretanje (Task Scheduler), ne za GitHub Actions."""
    token = config.get('telegram_token', '')
    if not token:
        logger.error("❌ Telegram token nije podešen — ne mogu da pokrenem listener.")
        return

    allowed_chat_ids = {str(config.get('telegram_chat_id', ''))}
    allowed_chat_ids.update(str(x) for x in config.get('telegram_extra_chat_ids', []))
    allowed_chat_ids.discard('')

    logger.info("🤖 Telegram listener (placevi) pokrenut — komande: /svi, /svi<broj> (npr. /svi80 = do 80.000€)")
    logger.info(f"   Dozvoljeni chat ID-ovi: {', '.join(allowed_chat_ids) or '(nijedan — proveri config!)'}")

    offset = None
    while True:
        try:
            updates = get_telegram_updates(token, offset=offset, timeout=30)
            for upd in updates:
                offset = upd['update_id'] + 1
                msg = upd.get('message') or upd.get('channel_post')
                if not msg:
                    continue
                chat_id = str(msg.get('chat', {}).get('id', ''))
                text = (msg.get('text') or '').strip()

                if chat_id not in allowed_chat_ids:
                    logger.warning(f"⚠️  Ignorišem poruku od nepoznatog chat_id: {chat_id}")
                    continue

                m = TELEGRAM_CMD_RE.match(text)
                if not m:
                    continue

                logger.info(f"📩 Komanda '{text}' od {chat_id}")
                override_total = int(m.group(1)) * 1000 if m.group(1) else None
                try:
                    handle_svi_command(config, chat_id, token, override_total)
                except Exception as e:
                    logger.error(f"❌ Greška u handle_svi_command: {e}")
                    send_telegram(token, chat_id, f"❌ Greška pri pretrazi: {e}")
        except KeyboardInterrupt:
            logger.info("🛑 Listener zaustavljen (Ctrl+C).")
            break
        except Exception as e:
            logger.error(f"❌ Listener greška: {e}")
            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("=" * 50)
    logger.info("🌳 Pokretanje scrapera za PLACEVE")
    logger.info(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    logger.info("=" * 50)

    config = load_config()
    seen = load_seen()

    telegram_token = config.get('telegram_token', '')
    telegram_chat_id = config.get('telegram_chat_id', '')
    max_total = config.get('max_total_price', 50000)
    targets = config.get('target_locations', DEFAULT_LOCATIONS)

    if not telegram_token:
        logger.warning("⚠️  Telegram token nije podešen!")
    if not telegram_chat_id:
        logger.warning("⚠️  Telegram chat ID nije podešen!")

    logger.info(f"🎯 Lokacije: {', '.join(targets)}")
    logger.info(f"💶 Max ukupna cena placa: {max_total} €")
    logger.info(f"👁️  Već viđeno: {len(seen)} oglasa")

    all_listings = run_scrapers_collect(config, SCRAPERS_ACTIONS)

    logger.info(f"\n📦 Ukupno: {len(all_listings)} oglasa")

    new_total = 0
    sent_total = 0

    for listing in all_listings:
        lid = listing.get('id')
        if not lid:
            continue

        is_new = lid not in seen
        if not is_new:
            # Osveži timestamp — oglas je i dalje živ u feedu, ne sme da
            # ispadne iz seen.json posle 30 dana pa da stigne duplikat.
            seen[lid] = time.time()
            continue

        new_total += 1

        if filter_match(listing, targets, max_total):
            ppar = listing.get('price_per_ar') or 0
            logger.info(
                f"🎯 MATCH: [{listing['source']}] {listing['title']} | "
                f"{ppar:.0f}€/ar | {listing['url']}"
            )
            if telegram_token and telegram_chat_id:
                msg = format_message(listing)
                extra = [str(x) for x in config.get('telegram_extra_chat_ids', [])]
                all_chat_ids = list(dict.fromkeys([str(telegram_chat_id)] + extra))  # deduplikacija
                any_sent = False
                for cid in all_chat_ids:
                    ok = send_telegram(telegram_token, cid, msg)
                    if ok:
                        sent_total += 1
                        any_sent = True
                    time.sleep(1.5)
                if any_sent:
                    seen[lid] = time.time()
                else:
                    # Nijedno slanje nije uspelo — NE upisujemo u seen,
                    # sledeći run će ponovo pokušati da pošalje ovaj match.
                    logger.warning(f"⚠️  Slanje nije uspelo, oglas ostaje za sledeći run: {lid}")
            else:
                seen[lid] = time.time()
        else:
            # Nije match — zapamti da ga ne procenjujemo ponovo.
            # (Napomena: posle labavljenja filtera pokreni --clear-seen)
            seen[lid] = time.time()

    logger.info(f"\n📊 Rezultati:")
    logger.info(f"   Novi oglasi: {new_total}")
    logger.info(f"   Notifikacije poslate: {sent_total}")

    save_seen(seen)
    logger.info("✅ Scraping završen.\n")


if __name__ == '__main__':
    import sys

    # Fix za Windows konzolu koja ne podržava UTF-8 po defaultu
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr.encoding and sys.stderr.encoding.lower() not in ('utf-8', 'utf8'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    if '--test-telegram' in sys.argv:
        config = load_config()
        token = config.get('telegram_token', '')
        chat_id = config.get('telegram_chat_id', '')
        print(f"Token: {token[:10]}... | Chat ID: {chat_id}")
        if not token or not chat_id:
            print("❌ Token ili chat ID nisu podešeni u config.json/env varijablama!")
        else:
            ok = send_telegram(token, chat_id, "✅ Test poruka — placevi scraper radi!")
            print("✅ Poruka poslata!" if ok else "❌ Greška pri slanju!")
        sys.exit(0)

    if '--clear-seen' in sys.argv:
        save_seen({})
        print("✅ seen.json je obrisan — sledeći run će poslati sve oglase koji prođu filter.")
        sys.exit(0)

    if '--listen' in sys.argv:
        config = load_config()
        run_telegram_listener(config)
        sys.exit(0)

    if '--debug' in sys.argv:
        config = load_config()
        max_total = config.get('max_total_price', 50000)
        targets = config.get('target_locations', DEFAULT_LOCATIONS)
        all_listings = run_scrapers_collect(config, SCRAPERS_ALL)

        print(f"\n{'='*60}")
        print(f"Ukupno nađeno: {len(all_listings)} oglasa")

        matches = [l for l in all_listings if filter_match(l, targets, max_total)]
        print(f"Prolazi filter (lokacija + cena ≤ {max_total}€ ukupno): {len(matches)}")
        print(f"{'='*60}")
        for l in matches:
            print(f"  [{l['source']}] {l['title']} | {l.get('price_per_ar') or 0:.0f}€/ar | {l['url']}")
        if not matches:
            print("\nNema placeva koji prolaze filter. Distribucija ukupnih cena:")
            loc_listings = [l for l in all_listings if is_target_location(l.get('location', ''), targets)]
            print(f"  Oglasi u tražnim lokacijama: {len(loc_listings)}")
            prices = [l['price'] for l in loc_listings if l.get('price')]
            if prices:
                print(f"  Min: {min(prices):.0f}€ | Max: {max(prices):.0f}€ | Prosek: {sum(prices)/len(prices):.0f}€")
        sys.exit(0)

    main()
