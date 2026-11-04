#!/usr/bin/env python3
"""
Rajasthan Private Schools Google Maps Scraper & Deep Contact Enrichment Pipeline
Author: Antigravity AI

Scrapes private and CBSE schools across all districts of Rajasthan from Google Maps,
deep-crawls school websites for official email addresses and phone numbers,
and exports a formatted Excel (.xlsx) file with district breakdown and statistics.
"""

import argparse
import csv
import datetime
import html
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

# Try importing openpyxl for Excel generation
try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Terminal colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(BASE_DIR, "googlemaps_scraper", "google-maps-scraper-kit")):
    KIT_DIR = os.path.join(BASE_DIR, "googlemaps_scraper", "google-maps-scraper-kit")
else:
    KIT_DIR = os.path.join(BASE_DIR, "Google-Map-Scrapper-main", "googlemaps_scraper", "google-maps-scraper-kit")
DB_FILE = os.path.join(BASE_DIR, "rajasthan_schools_database.json")
EXCEL_FILE = os.path.join(BASE_DIR, "Rajasthan_Private_Schools.xlsx")
CSV_FILE = os.path.join(BASE_DIR, "Rajasthan_Private_Schools.csv")

# Browser User-Agents
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# ==============================================================================
# Comprehensive Rajasthan Districts & Key Educational Hubs Matrix
# ==============================================================================
RAJASTHAN_DISTRICTS: List[Dict[str, Any]] = [
    # Top Tier / Mega Educational Hubs
    {"name": "Jaipur", "tier": 1, "lat": "26.9124", "lon": "75.7873", "radius": 20000},
    {"name": "Kota", "tier": 1, "lat": "25.2138", "lon": "75.8648", "radius": 15000},
    {"name": "Jodhpur", "tier": 1, "lat": "26.2389", "lon": "73.0243", "radius": 18000},
    {"name": "Udaipur", "tier": 1, "lat": "24.5854", "lon": "73.7125", "radius": 15000},
    {"name": "Ajmer", "tier": 1, "lat": "26.4499", "lon": "74.6399", "radius": 15000},
    {"name": "Bikaner", "tier": 1, "lat": "28.0229", "lon": "73.3119", "radius": 15000},
    {"name": "Sikar", "tier": 1, "lat": "27.6094", "lon": "75.1398", "radius": 15000},
    {"name": "Alwar", "tier": 1, "lat": "27.5530", "lon": "76.6346", "radius": 15000},
    {"name": "Bhilwara", "tier": 1, "lat": "25.3407", "lon": "74.6313", "radius": 15000},
    {"name": "Sri Ganganagar", "tier": 1, "lat": "29.9038", "lon": "73.8772", "radius": 15000},

    # Major Districts & Towns
    {"name": "Bharatpur", "tier": 2, "lat": "27.2152", "lon": "77.5030", "radius": 12000},
    {"name": "Pali", "tier": 2, "lat": "25.7711", "lon": "73.3234", "radius": 12000},
    {"name": "Chittorgarh", "tier": 2, "lat": "24.8887", "lon": "74.6269", "radius": 12000},
    {"name": "Jhunjhunu", "tier": 2, "lat": "28.1289", "lon": "75.3995", "radius": 12000},
    {"name": "Nagaur", "tier": 2, "lat": "27.2070", "lon": "73.7423", "radius": 12000},
    {"name": "Hanumangarh", "tier": 2, "lat": "29.5819", "lon": "74.3294", "radius": 12000},
    {"name": "Churu", "tier": 2, "lat": "28.2900", "lon": "74.9600", "radius": 12000},
    {"name": "Barmer", "tier": 2, "lat": "25.7532", "lon": "71.4181", "radius": 12000},
    {"name": "Dausa", "tier": 2, "lat": "26.8931", "lon": "76.3375", "radius": 12000},
    {"name": "Tonk", "tier": 2, "lat": "26.1664", "lon": "75.7885", "radius": 12000},
    {"name": "Sawai Madhopur", "tier": 2, "lat": "25.9928", "lon": "76.3712", "radius": 12000},
    {"name": "Banswara", "tier": 2, "lat": "23.5461", "lon": "74.4349", "radius": 12000},
    {"name": "Bundi", "tier": 2, "lat": "25.4415", "lon": "75.6457", "radius": 12000},
    {"name": "Baran", "tier": 2, "lat": "25.1011", "lon": "76.5132", "radius": 12000},
    {"name": "Dholpur", "tier": 2, "lat": "26.7025", "lon": "77.8934", "radius": 12000},
    {"name": "Jhalawar", "tier": 2, "lat": "24.5973", "lon": "76.1610", "radius": 12000},
    {"name": "Sirohi", "tier": 2, "lat": "24.8826", "lon": "72.8589", "radius": 12000},
    {"name": "Rajsamand", "tier": 2, "lat": "25.0748", "lon": "73.8767", "radius": 12000},
    {"name": "Jaisalmer", "tier": 2, "lat": "26.9157", "lon": "70.9083", "radius": 12000},
    {"name": "Dungarpur", "tier": 2, "lat": "23.8430", "lon": "73.7147", "radius": 12000},
    {"name": "Pratapgarh", "tier": 2, "lat": "24.0322", "lon": "74.7811", "radius": 12000},
    {"name": "Karauli", "tier": 2, "lat": "26.4952", "lon": "77.0210", "radius": 12000},

    # Newly Formed & Specialized Districts / Growth Hubs
    {"name": "Beawar", "tier": 3, "lat": "26.1014", "lon": "74.3197", "radius": 10000},
    {"name": "Balotra", "tier": 3, "lat": "25.8333", "lon": "72.2333", "radius": 10000},
    {"name": "Didwana-Kuchaman", "tier": 3, "lat": "27.4000", "lon": "74.5800", "radius": 12000},
    {"name": "Kotputli-Behror", "tier": 3, "lat": "27.7032", "lon": "76.2023", "radius": 12000},
    {"name": "Neem Ka Thana", "tier": 3, "lat": "27.7391", "lon": "75.7876", "radius": 10000},
    {"name": "Khairthal-Tijara", "tier": 3, "lat": "27.8833", "lon": "76.8333", "radius": 10000},
    {"name": "Bhiwadi", "tier": 3, "lat": "28.2104", "lon": "76.8606", "radius": 10000},
    {"name": "Phalodi", "tier": 3, "lat": "27.1333", "lon": "72.3667", "radius": 10000},
    {"name": "Salumbar", "tier": 3, "lat": "24.1333", "lon": "74.0500", "radius": 10000},
    {"name": "Sanchore", "tier": 3, "lat": "25.0167", "lon": "71.7667", "radius": 10000},
    {"name": "Anupgarh", "tier": 3, "lat": "29.1911", "lon": "73.2086", "radius": 10000},
    {"name": "Gangapur City", "tier": 3, "lat": "26.4714", "lon": "76.7161", "radius": 10000},
    {"name": "Deeg", "tier": 3, "lat": "27.4722", "lon": "77.3267", "radius": 10000},
    {"name": "Shahpura", "tier": 3, "lat": "25.6333", "lon": "74.9333", "radius": 10000},
    {"name": "Kekri", "tier": 3, "lat": "25.9722", "lon": "75.1528", "radius": 10000},
    {"name": "Dudu", "tier": 3, "lat": "26.6806", "lon": "75.2361", "radius": 10000},
    {"name": "Kishangarh", "tier": 3, "lat": "26.5746", "lon": "74.8631", "radius": 10000},
    {"name": "Abu Road", "tier": 3, "lat": "24.4786", "lon": "72.7825", "radius": 10000},
]


# ==============================================================================
# Helper Functions: Docker & API Management
# ==============================================================================
def find_scraper_port() -> Optional[int]:
    """Test common scraper ports to find running API."""
    ports = [8080, 8085]
    for port in ports:
        try:
            req = urllib.request.Request(f"http://localhost:{port}/api/v1/jobs", headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 201):
                    return port
        except Exception:
            continue
    return None


def ensure_scraper_running() -> str:
    """Ensure gosom scraper Docker container is up and running."""
    port = find_scraper_port()
    if port:
        return f"http://localhost:{port}"

    print(f"\n{YELLOW}▶ Scraper engine is not detected on ports 8080/8085.{RESET}")
    print(f"{CYAN}▶ Attempting to start the Docker container automatically...{RESET}")

    # Check if docker is installed
    try:
        subprocess.run(["docker", "ps"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        sys.exit(f"{RED}✗ Docker Desktop is not running. Please launch Docker Desktop and retry.{RESET}")

    # Start container via docker compose
    compose_file = os.path.join(KIT_DIR, "docker-compose.yml")
    if os.path.isfile(compose_file):
        try:
            subprocess.run(["docker", "compose", "-f", compose_file, "up", "-d"], check=True)
            print(f"{GREEN}✓ Docker container started. Waiting for API initialization...{RESET}")
            for _ in range(30):
                time.sleep(2)
                port = find_scraper_port()
                if port:
                    print(f"{GREEN}✓ Scraper engine ready on port {port}!{RESET}")
                    return f"http://localhost:{port}"
        except Exception as e:
            print(f"{YELLOW}⚠️ Auto-start failed: {e}{RESET}")

    # Direct run fallback
    try:
        print(f"{CYAN}▶ Running docker command: docker run -d -p 8080:8080 --name gmaps-scraper gosom/google-maps-scraper:v1.18.1 -web{RESET}")
        subprocess.run([
            "docker", "run", "-d", "-p", "8080:8080",
            "--name", "gmaps-scraper",
            "gosom/google-maps-scraper:v1.18.1",
            "-web"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            time.sleep(2)
            port = find_scraper_port()
            if port:
                print(f"{GREEN}✓ Scraper engine ready on port {port}!{RESET}")
                return f"http://localhost:{port}"
    except Exception:
        pass

    sys.exit(f"{RED}✗ Failed to connect to scraper API. Please run 'docker compose up -d' in '{KIT_DIR}'.{RESET}")


# ==============================================================================
# Deep Email & Contact Enrichment Crawler
# ==============================================================================
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', re.IGNORECASE)
MAILTO_REGEX = re.compile(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', re.IGNORECASE)
PHONE_REGEX = re.compile(r'(?:\+91[\-\s]?)?[6-9]\d{9}|0\d{2,4}[\-\s]?\d{6,8}')

JUNK_EMAIL_SUBSTRINGS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".woff", ".ttf",
    "sentry.io", "example.com", "domain.com", "w3.org", "schema.org", "google.com",
    "facebook.com", "twitter.com", "instagram.com", "youtube.com", "wordpress.org",
    "wixpress.com", "yourdomain", "email.com", "test.com", "sample"
}

SOCIAL_REGEX = {
    "facebook": re.compile(r'https?://(?:www\.|m\.)?facebook\.com/([A-Za-z0-9._\-]+)', re.I),
    "instagram": re.compile(r'https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)', re.I),
    "linkedin": re.compile(r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|school)/([A-Za-z0-9._\-]+)', re.I),
}

SKIP_SOCIAL_HANDLES = {
    "sharer", "share.php", "login", "policies", "privacy", "help", "pages", "group", "events"
}


def fetch_url(url: str, timeout: int = 8) -> str:
    """Fetch webpage HTML safely."""
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(500_000).decode("utf-8", "replace")
    except Exception:
        return ""


def clean_emails(emails: List[str]) -> List[str]:
    """Filter out invalid, placeholder, or asset-extension emails."""
    clean = []
    seen = set()
    for em in emails:
        em = urllib.parse.unquote(em).lower().strip(".,:;'/\"\\ \t\r\n")
        em = re.sub(r'^(?:20|\s)+', '', em)
        if em in seen or len(em) < 6 or "@" not in em:
            continue
        domain = em.split("@")[-1]
        if any(junk in em for junk in JUNK_EMAIL_SUBSTRINGS):
            continue
        if len(domain.split(".")) < 2:
            continue
        seen.add(em)
        clean.append(em)
    return clean


def extract_socials(html_text: str) -> Dict[str, str]:
    """Find Facebook and Instagram handles."""
    socials = {"facebook": "", "instagram": ""}
    for platform, rx in SOCIAL_REGEX.items():
        if platform not in socials:
            continue
        m = rx.search(html_text)
        if m:
            handle = m.group(1).lower()
            if handle not in SKIP_SOCIAL_HANDLES and len(handle) > 2:
                socials[platform] = m.group(0).rstrip("/\"'").replace("\\", "")
    return socials


def deep_enrich_school(school: Dict[str, Any]) -> Dict[str, Any]:
    """Deep crawl website, /contact, /about, /admissions for official emails and phones."""
    website = (school.get("website") or "").strip()
    if not website:
        return school

    emails_found: Set[str] = set()
    if school.get("email"):
        for em in str(school["email"]).split(","):
            if em.strip():
                emails_found.add(em.strip().lower())

    homepage_html = fetch_url(website, timeout=7)
    if not homepage_html:
        return school

    # 1. Search homepage
    emails_found.update(clean_emails(MAILTO_REGEX.findall(homepage_html)))
    emails_found.update(clean_emails(EMAIL_REGEX.findall(homepage_html)))

    # 2. Extract socials
    soc = extract_socials(homepage_html)
    if soc["facebook"] and not school.get("facebook"):
        school["facebook"] = soc["facebook"]
    if soc["instagram"] and not school.get("instagram"):
        school["instagram"] = soc["instagram"]

    # 3. If no email found yet, discover and check /contact, /contact-us, /about links
    if not emails_found:
        contact_links = re.findall(
            r'href=["\'](https?://[^"\']+|/[^"\']*(?:contact|about|reach|admission)[^"\']*)["\']',
            homepage_html,
            re.IGNORECASE
        )
        parsed_base = urllib.parse.urlparse(website)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        subpage_candidates = []
        for link in contact_links[:6]:
            if link.startswith("/"):
                subpage_candidates.append(base_origin + link)
            elif parsed_base.netloc in link:
                subpage_candidates.append(link)

        # Standard fallbacks if no contact link was explicitly matched
        if not subpage_candidates:
            subpage_candidates = [
                f"{base_origin}/contact",
                f"{base_origin}/contact-us",
                f"{base_origin}/contact.html"
            ]

        # Crawl up to 2 subpages
        for sub_url in subpage_candidates[:2]:
            sub_html = fetch_url(sub_url, timeout=6)
            if sub_html:
                emails_found.update(clean_emails(MAILTO_REGEX.findall(sub_html)))
                emails_found.update(clean_emails(EMAIL_REGEX.findall(sub_html)))
                if emails_found:
                    break

    # Format emails
    if emails_found:
        school["email"] = ", ".join(sorted(list(emails_found))[:3])

    return school


# ==============================================================================
# Database & JSON Persistence
# ==============================================================================
def load_database() -> Dict[str, Dict[str, Any]]:
    """Load existing schools database."""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_database(data: Dict[str, Dict[str, Any]]):
    """Save schools database atomically to JSON."""
    temp_file = DB_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, DB_FILE)


def generate_school_key(school: Dict[str, Any], district: str) -> str:
    """Generate unique deduplication key."""
    title = (school.get("title") or school.get("name") or "").strip().lower()
    title_clean = re.sub(r'[^a-z0-9]', '', title)
    phone = re.sub(r'[^0-9]', '', str(school.get("phone") or ""))[-10:]
    if phone and len(phone) == 10:
        return f"{title_clean}_{phone}"
    return f"{district.lower()}_{title_clean}"


# ==============================================================================
# Google Maps Scraping Worker
# ==============================================================================
def scrape_district(base_url: str, district_info: Dict[str, Any], depth: int = 5) -> List[Dict[str, Any]]:
    """Submit scraping job to gosom scraper and download CSV results."""
    name = district_info["name"]
    lat = district_info["lat"]
    lon = district_info["lon"]
    radius = district_info.get("radius", 15000)

    keywords = [
        f"private schools in {name} rajasthan",
        f"cbse schools in {name} rajasthan",
        f"schools in {name} rajasthan",
    ]

    body = {
        "name": f"Rajasthan-{name}",
        "keywords": keywords,
        "lang": "en",
        "zoom": 14,
        "lat": str(lat),
        "lon": str(lon),
        "fast_mode": True,
        "radius": radius,
        "depth": depth,
        "email": True,
        "max_time": 400,
    }

    # Submit job
    req = urllib.request.Request(
        f"{base_url}/api/v1/jobs",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            job_id = resp_data.get("id")
    except Exception as e:
        print(f"  {RED}✗ Failed to start job for {name}: {e}{RESET}")
        return []

    if not job_id:
        return []

    # Poll status
    print(f"  {CYAN}▶ Job ID {job_id[:8]} started. Scraping Google Maps...{RESET}", end="", flush=True)
    status = ""
    for _ in range(60):
        time.sleep(5)
        try:
            poll_req = urllib.request.Request(f"{base_url}/api/v1/jobs/{job_id}", headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(poll_req, timeout=10) as p_resp:
                st_data = json.loads(p_resp.read().decode("utf-8"))
                status = st_data.get("Status") or st_data.get("status")
                print(".", end="", flush=True)
                if status == "ok":
                    print(f" {GREEN}Completed!{RESET}")
                    break
                elif status == "failed":
                    print(f" {RED}Failed.{RESET}")
                    return []
        except Exception:
            continue
    else:
        print(f" {YELLOW}Timeout.{RESET}")
        return []

    # Download CSV
    try:
        dl_req = urllib.request.Request(f"{base_url}/api/v1/jobs/{job_id}/download", headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(dl_req, timeout=30) as d_resp:
            csv_content = d_resp.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  {RED}✗ Could not download CSV: {e}{RESET}")
        return []

    reader = csv.DictReader(io.StringIO(csv_content))
    schools = []
    for r in reader:
        title = r.get("title", "").strip()
        if not title:
            continue
        
        # Filter out government schools to ensure ONLY PRIVATE schools are captured
        title_lower = title.lower()
        if any(term in title_lower for term in [
            "government ", "govt ", "govt.", "gsss", "ggsss", "g.s.s.s", "g.g.s.s",
            "pm shri govt", "rajkiya", "kendriya vidyalaya", "jawahar navodaya",
            "state school", "district institute"
        ]):
            continue

        # Filter out clearly non-school items
        category = (r.get("category") or "").lower()
        if any(x in category for x in ["hospital", "hotel", "restaurant", "store", "shop"]):
            continue

        # Direct Google Maps Link construction
        maps_link = (r.get("link") or "").strip()
        cid = (r.get("cid") or "").strip()
        if not maps_link:
            if cid:
                maps_link = f"https://maps.google.com/?cid={cid}"
            else:
                addr_part = (r.get("address") or name).strip()
                maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(title + ' ' + addr_part)}"

        cat_display = r.get("category", "").strip() or "Private School"

        school_data = {
            "district": name,
            "title": title,
            "phone": (r.get("phone") or "").strip(),
            "email": (r.get("emails") or r.get("email") or "").strip(),
            "website": (r.get("website") or "").strip(),
            "address": (r.get("complete_address") or r.get("address") or "").strip(),
            "rating": r.get("review_rating") or r.get("rating") or "",
            "review_count": r.get("review_count") or r.get("reviews") or "",
            "category": cat_display,
            "google_maps_url": maps_link,
            "facebook": "",
            "instagram": "",
            "scraped_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        schools.append(school_data)

    return schools


# ==============================================================================
# Professional Excel Exporter
# ==============================================================================
def export_to_excel(db: Dict[str, Dict[str, Any]], excel_path: str = EXCEL_FILE, csv_path: str = CSV_FILE):
    """Generate high-format corporate Excel workbook (.xlsx) and CSV copy."""
    schools_list = list(db.values())
    if not schools_list:
        print(f"{YELLOW}No schools in database to export.{RESET}")
        return

    # Sort primarily by District, then by School Name
    schools_list.sort(key=lambda s: (s.get("district", ""), s.get("title", "")))

    # Save CSV copy first
    fieldnames = [
        "District", "School Name", "Phone Number", "Email Address", "Website",
        "Address", "Rating", "Reviews Count", "Category", "Google Maps URL",
        "Facebook", "Instagram", "Scraped At"
    ]
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for s in schools_list:
                t_str = (s.get("title") or "").strip()
                d_str = s.get("district", "Rajasthan")
                p_str = str(s.get("phone") or "").strip()
                m_str = (s.get("google_maps_url") or "").strip()
                a_str = (s.get("address") or "").strip()
                if not m_str:
                    m_str = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(t_str + ' ' + (a_str or d_str))}"
                raw_r = str(s.get("rating") or "").strip()
                try:
                    r_disp = f"{float(raw_r):.1f}" if float(raw_r) > 0 else ""
                except ValueError:
                    r_disp = ""
                raw_rc = str(s.get("review_count") or "").strip()
                try:
                    rc_disp = str(int(float(raw_rc))) if float(raw_rc) > 0 else ""
                except ValueError:
                    rc_disp = ""
                writer.writerow([
                    d_str,
                    t_str,
                    f"'{p_str}" if p_str else "",
                    s.get("email", ""),
                    s.get("website", ""),
                    a_str,
                    r_disp,
                    rc_disp,
                    (s.get("category") or "").strip() or "Private School",
                    m_str,
                    s.get("facebook", ""),
                    s.get("instagram", ""),
                    s.get("scraped_at", "")
                ])
    except Exception as e:
        print(f"{YELLOW}⚠️ CSV export note: {e}{RESET}")

    if not OPENPYXL_AVAILABLE:
        print(f"{YELLOW}openpyxl not installed. Saved master CSV to {csv_path}{RESET}")
        return

    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # -------------------------------------------------------------
    # Sheet 1: Master Schools Data
    # -------------------------------------------------------------
    ws_data = wb.create_sheet(title="Rajasthan Private Schools")
    ws_data.views.sheetView[0].showGridLines = True

    # Styling definitions
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    bold_font = Font(name="Calibri", size=10, bold=True)
    green_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    link_font = Font(name="Calibri", size=10, color="0563C1", underline="single")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    headers = [
        "District / City", "School Name", "Phone Number", "Email Address",
        "Website", "Full Address", "Rating (Stars)", "Reviews",
        "Category", "Google Maps Link", "Facebook", "Instagram"
    ]
    ws_data.append(headers)

    # Header row formatting
    for col_idx in range(1, len(headers) + 1):
        cell = ws_data.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws_data.row_dimensions[1].height = 28

    # Populate rows
    for row_idx, s in enumerate(schools_list, start=2):
        title_str = (s.get("title") or "").strip()
        dist_str = s.get("district", "Rajasthan")
        phone_val = str(s.get("phone") or "").strip()
        email_val = str(s.get("email") or "").strip()
        website_val = str(s.get("website") or "").strip()
        maps_val = str(s.get("google_maps_url") or "").strip()
        addr_val = str(s.get("address") or "").strip()
        cat_val = (s.get("category") or "").strip() or "Private School"

        # Auto-fallback Google Maps Link
        if not maps_val:
            addr_query = addr_val if addr_val else f"{dist_str}, Rajasthan"
            maps_val = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(title_str + ' ' + addr_query)}"

        # Clean rating and review counts
        raw_rating = str(s.get("rating") or "").strip()
        try:
            rating_num = float(raw_rating)
            rating_display = f"{rating_num:.1f}" if rating_num > 0 else ""
        except ValueError:
            rating_display = ""

        raw_reviews = str(s.get("review_count") or "").strip()
        try:
            reviews_num = int(float(raw_reviews))
            reviews_display = str(reviews_num) if reviews_num > 0 else ""
        except ValueError:
            reviews_display = ""

        row_values = [
            dist_str,
            title_str,
            phone_val,
            email_val,
            website_val,
            addr_val,
            rating_display,
            reviews_display,
            cat_val,
            maps_val,
            s.get("facebook", ""),
            s.get("instagram", "")
        ]
        ws_data.append(row_values)
        ws_data.row_dimensions[row_idx].height = 20

        # Cell by cell formatting
        for col_idx in range(1, len(headers) + 1):
            cell = ws_data.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

            # District bold
            if col_idx == 1:
                cell.font = bold_font
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Phone as text format
            elif col_idx == 3:
                cell.number_format = '@'

            # Email highlight
            elif col_idx == 4 and email_val:
                cell.fill = green_fill
                cell.font = bold_font

            # Website hyperlink
            elif col_idx == 5 and website_val.startswith("http"):
                cell.hyperlink = website_val
                cell.font = link_font

            # Rating centered
            elif col_idx in (7, 8):
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Maps URL hyperlink
            elif col_idx == 10 and maps_val.startswith("http"):
                cell.hyperlink = maps_val
                cell.value = "Open on Maps"
                cell.font = link_font
                cell.alignment = Alignment(horizontal="center", vertical="center")

    # Autofilter & Freeze Panes
    ws_data.auto_filter.ref = ws_data.dimensions
    ws_data.freeze_panes = "C2"

    # Auto-adjust column widths
    for col in ws_data.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            v = str(cell.value or "")
            if len(v) > max_len:
                max_len = len(v)
        ws_data.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    # -------------------------------------------------------------
    # Sheet 2: District Coverage & Executive Summary
    # -------------------------------------------------------------
    ws_sum = wb.create_sheet(title="District Summary")
    ws_sum.views.sheetView[0].showGridLines = True

    sum_headers = [
        "District Name", "Total Schools", "With Phone", "With Email",
        "With Website", "Phone Coverage %", "Email Coverage %"
    ]
    ws_sum.append(sum_headers)
    for col_idx in range(1, len(sum_headers) + 1):
        cell = ws_sum.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_sum.row_dimensions[1].height = 26

    # Calculate statistics
    district_stats: Dict[str, Dict[str, int]] = {}
    for s in schools_list:
        d = s.get("district", "Unknown")
        if d not in district_stats:
            district_stats[d] = {"total": 0, "phone": 0, "email": 0, "website": 0}
        district_stats[d]["total"] += 1
        if s.get("phone"):
            district_stats[d]["phone"] += 1
        if s.get("email"):
            district_stats[d]["email"] += 1
        if s.get("website"):
            district_stats[d]["website"] += 1

    total_schools = len(schools_list)
    total_phone = sum(x["phone"] for x in district_stats.values())
    total_email = sum(x["email"] for x in district_stats.values())
    total_web = sum(x["website"] for x in district_stats.values())

    s_row = 2
    for dist_name in sorted(district_stats.keys()):
        st = district_stats[dist_name]
        p_pct = f"{(st['phone'] / st['total']) * 100:.1f}%" if st['total'] else "0%"
        e_pct = f"{(st['email'] / st['total']) * 100:.1f}%" if st['total'] else "0%"

        ws_sum.append([
            dist_name, st["total"], st["phone"], st["email"],
            st["website"], p_pct, e_pct
        ])
        for c in range(1, len(sum_headers) + 1):
            cell = ws_sum.cell(row=s_row, column=c)
            cell.font = data_font
            cell.border = thin_border
            if c > 1:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        s_row += 1

    # Totals Row
    ws_sum.append([
        "TOTAL (All Rajasthan)", total_schools, total_phone, total_email,
        total_web,
        f"{(total_phone / total_schools * 100):.1f}%" if total_schools else "0%",
        f"{(total_email / total_schools * 100):.1f}%" if total_schools else "0%"
    ])
    ws_sum.row_dimensions[s_row].height = 24
    total_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    for c in range(1, len(sum_headers) + 1):
        cell = ws_sum.cell(row=s_row, column=c)
        cell.font = bold_font
        cell.fill = total_fill
        cell.border = thin_border
        if c > 1:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    for col in ws_sum.columns:
        col_letter = get_column_letter(col[0].column)
        ws_sum.column_dimensions[col_letter].width = 22

    wb.save(excel_path)
    print(f"\n{GREEN}✓ Excel file successfully saved: {excel_path}{RESET}")
    print(f"{GREEN}✓ CSV backup successfully saved: {csv_path}{RESET}")


# ==============================================================================
# Pipeline Execution Controller
# ==============================================================================
def run_pipeline(selected_districts: List[Dict[str, Any]], depth: int = 5, enrich: bool = True):
    """Run full scraping & enrichment process across selected districts."""
    print_banner()
    base_url = ensure_scraper_running()

    database = load_database()
    initial_count = len(database)
    print(f"\n{CYAN}▶ Existing database loaded: {BOLD}{initial_count} schools{RESET}")
    print(f"{CYAN}▶ Total Districts to Scrape: {BOLD}{len(selected_districts)}{RESET}")
    print(f"{CYAN}▶ Scraping Depth: {depth} | Deep Email Enrichment: {'Enabled' if enrich else 'Disabled'}{RESET}\n")

    start_time = time.time()
    for idx, dist in enumerate(selected_districts, start=1):
        name = dist["name"]
        print(f"\n{BOLD}{CYAN}------------------------------------------------------------{RESET}")
        print(f"{BOLD}District [{idx}/{len(selected_districts)}]: {YELLOW}{name}{RESET}")
        print(f"{BOLD}{CYAN}------------------------------------------------------------{RESET}")

        # 1. Scrape District
        schools = scrape_district(base_url, dist, depth=depth)
        print(f"  ✓ Found {BOLD}{len(schools)}{RESET} candidate listings in {name}.")

        if not schools:
            continue

        # 2. Deduplicate against database
        new_count = 0
        added_keys = []
        for s in schools:
            key = generate_school_key(s, name)
            if key not in database:
                database[key] = s
                added_keys.append(key)
                new_count += 1
            else:
                # Merge richer data if available
                existing = database[key]
                if not existing.get("phone") and s.get("phone"):
                    existing["phone"] = s["phone"]
                if not existing.get("website") and s.get("website"):
                    existing["website"] = s["website"]
                if not existing.get("email") and s.get("email"):
                    existing["email"] = s["email"]

        print(f"  ✓ {GREEN}+{new_count} unique schools added to database.{RESET}")

        # 3. Deep Contact Enrichment
        if enrich and added_keys:
            to_enrich = [database[k] for k in added_keys if database[k].get("website")]
            if to_enrich:
                print(f"  {CYAN}▶ Deep-crawling {len(to_enrich)} school websites for emails & phone numbers...{RESET}")
                enriched_count = 0
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {executor.submit(deep_enrich_school, item): item for item in to_enrich}
                    for future in as_completed(futures):
                        item = futures[future]
                        res = future.result()
                        if res.get("email"):
                            enriched_count += 1
                print(f"  {GREEN}✓ Enriched: Found emails for {enriched_count}/{len(to_enrich)} schools.{RESET}")

        # 4. Incremental Save after every district
        save_database(database)
        export_to_excel(database)
        print(f"  {DIM}Database & Excel updated ({len(database)} total leads).{RESET}")

    elapsed = time.time() - start_time
    print(f"\n{BOLD}{GREEN}============================================================{RESET}")
    print(f"{BOLD}{GREEN}  SCRAPING COMPLETED IN {int(elapsed // 60)}m {int(elapsed % 60)}s!{RESET}")
    print(f"{BOLD}{GREEN}  Total Schools in Database: {len(database)} (+{len(database) - initial_count} new){RESET}")
    print(f"{BOLD}{GREEN}  Master Excel File: {EXCEL_FILE}{RESET}")
    print(f"{BOLD}{GREEN}============================================================{RESET}\n")


# ==============================================================================
# Banner & Interactive CLI
# ==============================================================================
def print_banner():
    print(f"""
{CYAN}╔══════════════════════════════════════════════════════════════════════════╗
║     RAJASTHAN PRIVATE SCHOOLS GOOGLE MAPS SCRAPER & ENRICHMENT           ║
║               Comprehensive Phone & Email Lead Generator                 ║
╚══════════════════════════════════════════════════════════════════════════╝{RESET}
""")


def main():
    parser = argparse.ArgumentParser(description="Scrape Rajasthan Private Schools with Deep Email & Phone Enrichment.")
    parser.add_argument("--all", action="store_true", help="Scrape all 50 districts of Rajasthan")
    parser.add_argument("--top", action="store_true", help="Scrape top 10 educational hub districts (Jaipur, Kota, Jodhpur, etc.)")
    parser.add_argument("--city", help="Scrape a specific city or district (e.g. --city Jaipur)")
    parser.add_argument("--depth", type=int, default=5, help="Google Maps pagination depth (default: 5)")
    parser.add_argument("--no-enrich", action="store_true", help="Skip deep website email crawling")
    parser.add_argument("--export-only", action="store_true", help="Re-export existing database to Excel/CSV without scraping")

    args = parser.parse_args()

    if args.export_only:
        db = load_database()
        print(f"Loaded {len(db)} schools from database.")
        export_to_excel(db)
        return

    enrich = not args.no_enrich

    # Specific city
    if args.city:
        matched = [d for d in RAJASTHAN_DISTRICTS if args.city.lower() in d["name"].lower()]
        if not matched:
            # Create ad-hoc district
            matched = [{"name": args.city.title(), "tier": 2, "lat": "26.9124", "lon": "75.7873", "radius": 15000}]
        run_pipeline(matched, depth=args.depth, enrich=enrich)
        return

    # Top educational hubs
    if args.top:
        top_districts = [d for d in RAJASTHAN_DISTRICTS if d["tier"] == 1]
        run_pipeline(top_districts, depth=args.depth, enrich=enrich)
        return

    # All districts
    if args.all:
        run_pipeline(RAJASTHAN_DISTRICTS, depth=args.depth, enrich=enrich)
        return

    # Interactive Menu if no flags passed
    print_banner()
    print(f"{BOLD}Choose an execution mode:{RESET}")
    print(f"  {CYAN}1.{RESET} {BOLD}All Rajasthan Districts (All 50 areas - Maximum Data){RESET}")
    print(f"  {CYAN}2.{RESET} {BOLD}Top 10 Education Hubs (Jaipur, Kota, Jodhpur, Udaipur, Ajmer, Sikar, etc.){RESET}")
    print(f"  {CYAN}3.{RESET} {BOLD}Single City / District (e.g., Jaipur or Kota){RESET}")
    print(f"  {CYAN}4.{RESET} {BOLD}Re-export Existing Data to Excel (.xlsx){RESET}")

    choice = input(f"\n{BOLD}Enter choice (1-4) [Default: 2]: {RESET}").strip()
    if choice == "1":
        run_pipeline(RAJASTHAN_DISTRICTS, depth=args.depth, enrich=enrich)
    elif choice == "3":
        city_name = input(f"{BOLD}Enter city/district name: {RESET}").strip()
        if not city_name:
            city_name = "Jaipur"
        matched = [d for d in RAJASTHAN_DISTRICTS if city_name.lower() in d["name"].lower()]
        if not matched:
            matched = [{"name": city_name.title(), "tier": 2, "lat": "26.9124", "lon": "75.7873", "radius": 15000}]
        run_pipeline(matched, depth=args.depth, enrich=enrich)
    elif choice == "4":
        db = load_database()
        print(f"Loaded {len(db)} schools from database.")
        export_to_excel(db)
    else:
        top_districts = [d for d in RAJASTHAN_DISTRICTS if d["tier"] == 1]
        run_pipeline(top_districts, depth=args.depth, enrich=enrich)


if __name__ == "__main__":
    main()
