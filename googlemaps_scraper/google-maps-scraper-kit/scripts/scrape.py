#!/usr/bin/env python3
"""One-shot Google Maps scrape using only the Python standard library (no pip installs).

Single keyword:
    python3 scripts/scrape.py "gyms in Miami FL" 25.7617 -80.1918 --depth 5

Auto-geocode (no coordinates needed):
    python3 scripts/scrape.py "cafes in Austin TX" --city "Austin, TX" --depth 5

Batch (one job, many keywords) from a file (one keyword per line):
    python3 scripts/scrape.py --keywords-file examples/queries.example.txt --city "Denver, CO"

Notes:
- Required by the API: keywords, lat/lon (strings), max_time (SECONDS). This script fills them in.
- Geocoding uses OpenStreetMap Nominatim (free, no key). Please be gentle: it allows ~1 request/sec
  and requires a descriptive User-Agent (set below). Don't loop it aggressively.
"""
import argparse, csv, html, io, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor

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

ENV_KEYS = ("SCRAPER_BASE_URL", "SCRAPER_PORT", "SCRAPER_API_KEY")


def load_env_file():
    """Read SCRAPER_* from the kit's .env, the same file docker compose reads, so a remapped
    port needs one edit. Variables already set in the environment win over the file."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".env")
    try:
        with open(path) as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep and k in ENV_KEYS and k not in os.environ:
                    os.environ[k] = v.strip().strip("\"'")
    except OSError:
        pass


load_env_file()
BASE = os.environ.get("SCRAPER_BASE_URL") or f"http://localhost:{os.environ.get('SCRAPER_PORT') or '8080'}"
KEY = os.environ.get("SCRAPER_API_KEY", "")
# Money-useful LEAD fields only — what you actually use to contact/qualify a lead.
# Everything else (geo coordinates, IDs, hours, images, reviews blobs…) is dropped by default.
LEAD = ["title", "phone", "emails", "website", "category", "address", "summary", "review_rating", "review_count"]
NOMINATIM_UA = "google-maps-scraper-kit/1.0 (https://github.com/Mahanaicoach/google-maps-scraper-kit)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
UA = NOMINATIM_UA


def req(method, path, body=None):
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if KEY:
        headers["X-API-Key"] = KEY
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=60) as resp:
        return resp.status, resp.read()


def geocode(place):
    """City/place name -> ('lat','lon') strings via Nominatim, or None."""
    q = urllib.parse.urlencode({"format": "json", "limit": 1, "q": place})
    url = f"https://nominatim.openstreetmap.org/search?{q}"
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            hits = json.loads(resp.read())
        time.sleep(1)  # respect Nominatim's ~1 req/sec policy
        if hits:
            return str(hits[0]["lat"]), str(hits[0]["lon"])
    except Exception as e:
        print(f"  (geocoding failed: {e})", file=sys.stderr)
    return None


def collect_keywords(a):
    kws = []
    if a.keyword:
        kws.append(a.keyword)
    kws.extend(a.also or [])
    if a.keywords_file:
        with open(a.keywords_file, encoding="utf-8", errors="ignore") as f:
            kws.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
    # de-dupe, keep order
    seen, out = set(), []
    for k in kws:
        if k not in seen:
            seen.add(k); out.append(k)
    return out


# ── Website enrichment (Summaries & Socials) ──────────────────────────────
# Pure code (HTTP + regex) → ZERO LLM tokens. Visits each business website once.
META_DESC_RE = [
    re.compile(r'<meta\s+[^>]*?name=["\'](?:description|twitter:description)["\'][^>]*?content=["\'](.*?)["\']', re.I | re.S),
    re.compile(r'<meta\s+[^>]*?content=["\'](.*?)["\'][^>]*?name=["\'](?:description|twitter:description)["\']', re.I | re.S),
    re.compile(r'<meta\s+[^>]*?property=["\']og:description["\'][^>]*?content=["\'](.*?)["\']', re.I | re.S),
    re.compile(r'<meta\s+[^>]*?content=["\'](.*?)["\'][^>]*?property=["\']og:description["\']', re.I | re.S),
]

def _find_summary(html_text):
    if not html_text:
        return ""
    for rx in META_DESC_RE:
        m = rx.search(html_text)
        if m:
            desc = html.unescape(m.group(1).strip())
            desc = re.sub(r'\s+', ' ', desc).strip()
            if len(desc) > 10:
                return desc[:350].rstrip()
    return ""

SOCIAL_RE = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)", re.I),
    "facebook":  re.compile(r"https?://(?:www\.|m\.|web\.)?facebook\.com/([A-Za-z0-9_.\-]+)", re.I),
    "linkedin":  re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/([A-Za-z0-9_.\-%]+)", re.I),
}
_SKIP_HANDLE = {"", "home", "pages", "people", "help", "about", "policies", "policy",
                "legal", "tos", "privacy", "settings", "sharer", "tr", "profile.php",
                "plugins", "dialog", "intent", "login", "share.php", "permalink.php",
                "p", "reel", "reels", "explore", "stories", "tv", "watch", "events",
                "groups", "marketplace", "gaming", "photo", "hashtag", "search"}

def _fetch_html(url, timeout=10):
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        r = urllib.request.Request(url, headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.read(400_000).decode("utf-8", "replace")
    except Exception:
        return ""

def _find_socials(html_content):
    out = {"instagram": "", "facebook": "", "linkedin": ""}
    for plat, rx in SOCIAL_RE.items():
        for m in rx.finditer(html_content or ""):
            h = m.group(1).lower()
            if h in _SKIP_HANDLE:
                continue
            if plat == "facebook" and (h.isdigit() or len(h) < 3):  # skip junk like /2008
                continue
            out[plat] = m.group(0).rstrip('"\'/').replace("\\", "")
            break
    return out

EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
_EMAIL_SKIP_SUFFIX = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.woff', '.ttf')
_EMAIL_SKIP_DOMAINS = {'sentry.io', 'example.com', 'w3.org', 'schema.org', 'domain.com', 'google.com', 'facebook.com', 'twitter.com'}

def _find_emails(html_content):
    if not html_content:
        return []
    mailto_matches = re.findall(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', html_content, re.I)
    raw_matches = EMAIL_RE.findall(html_content)
    found = []
    seen = set()
    for em in mailto_matches + raw_matches:
        em_lower = em.lower().strip(".,:;'/\"")
        if em_lower in seen:
            continue
        if any(em_lower.endswith(sfx) for sfx in _EMAIL_SKIP_SUFFIX):
            continue
        domain = em_lower.split('@')[-1]
        if domain in _EMAIL_SKIP_DOMAINS:
            continue
        seen.add(em_lower)
        found.append(em_lower)
        if len(found) >= 3:
            break
    return found

def enrich_websites(results, extract_summary=True, extract_socials=False, extract_emails=False, workers=10):
    """Enrich leads by checking company websites concurrently for emails, meta descriptions and social links."""
    if extract_socials:
        for r in results:
            r.setdefault("instagram", ""); r.setdefault("facebook", ""); r.setdefault("linkedin", "")
    if extract_emails:
        for r in results:
            r.setdefault("emails", "")
    todo = [r for r in results if r.get("website")]
    done = 0
    def work(r):
        html_content = _fetch_html(r["website"], timeout=8)
        if extract_summary and not r.get("summary"):
            site_summary = _find_summary(html_content)
            if site_summary:
                r["summary"] = site_summary
        if extract_socials:
            r.update(_find_socials(html_content))
        if extract_emails and not r.get("emails"):
            emails = _find_emails(html_content)
            if emails:
                r["emails"] = ", ".join(emails)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(work, todo):
            done += 1
            print(f"\r  enriching websites: {done}/{len(todo)} checked", end="", flush=True)
    if todo:
        print()

def enrich_socials(results, workers=8):
    enrich_websites(results, extract_summary=False, extract_socials=True, workers=workers)


def main():
    ap = argparse.ArgumentParser(description="Scrape Google Maps business listings.")
    ap.add_argument("keyword", nargs="?", help='e.g. "coffee shops in Austin TX"')
    ap.add_argument("lat", nargs="?", help="latitude (optional if --city given)")
    ap.add_argument("lon", nargs="?", help="longitude (optional if --city given)")
    ap.add_argument("--keyword", dest="also", action="append", help="extra keyword (repeatable)")
    ap.add_argument("--keywords-file", help="file with one keyword per line (batch)")
    ap.add_argument("--city", help="city/place to auto-geocode for lat/lon")
    ap.add_argument("--depth", type=int, default=5)
    # Emails are ON by default (they're the most valuable lead field). Visits each business
    # website to find an address — a bit slower. Use --no-email to skip for a fast run.
    ap.add_argument("--email", dest="email", action="store_true", default=True, help=argparse.SUPPRESS)
    ap.add_argument("--no-email", dest="email", action="store_false",
                    help="skip email extraction for a faster run (emails are on by default)")
    ap.add_argument("--max-time", type=int, default=600, help="job time limit in SECONDS")
    ap.add_argument("--out", default=None, help="output file path (default: results-<id>.csv). "
                    "The extension picks the format: .csv (default) or .json")
    ap.add_argument("--json", action="store_true", help="write JSON instead of the default CSV")
    ap.add_argument("--full", action="store_true", help="keep ALL raw columns (default: lean lead fields)")
    ap.add_argument("--fields", help="comma-separated columns to keep (overrides the default lead set)")
    ap.add_argument("--summary", dest="summary", action="store_true", default=True, help=argparse.SUPPRESS)
    ap.add_argument("--no-summary", dest="summary", action="store_false",
                    help="skip summary extraction (summaries are on by default)")
    ap.add_argument("--socials", action="store_true",
                    help="also find Instagram/Facebook/LinkedIn from each website (0 LLM tokens; slower)")
    ap.add_argument("--append", action="store_true",
                    help="append leads into existing output file (with automatic duplicate checking) instead of overwriting")
    ap.add_argument("--project", default=None, help="Project name (e.g. 'scrape for taltra') for MongoDB storage")
    ap.add_argument("--mongo", action="store_true", help="Store scraped leads into MongoDB")
    ap.add_argument("--mongo-uri", default=None, help="MongoDB connection URI (default: mongodb://localhost:27017/)")
    ap.add_argument("--mongo-db", default=None, help="MongoDB database name (default: google_maps_leads)")
    ap.add_argument("--collection", default="leads", help="MongoDB collection name (default: leads)")
    ap.add_argument("--interactive", "-i", action="store_true", help="Launch interactive prompt wizard")
    a = ap.parse_args()

    keywords = collect_keywords(a)
    if not keywords or a.interactive:
        if a.interactive or len(sys.argv) == 1:
            try:
                import pipeline
                pipeline.run_pipeline_interactive()
                return
            except ImportError:
                pass
        sys.exit("✗ No keywords. Pass a keyword, --keyword, --keywords-file, or run with --interactive.")

    # Resolve coordinates: explicit lat/lon, else geocode --city, else geocode first keyword.
    lat, lon = a.lat, a.lon
    if not (lat and lon):
        place = a.city or keywords[0]
        print(f"▶ Geocoding \"{place}\"…")
        coords = geocode(place)
        if not coords:
            sys.exit("✗ Could not resolve coordinates. Pass lat/lon or a clearer --city.")
        lat, lon = coords
        print(f"  → {lat}, {lon}")

    if a.email:
        print("ℹ Email extraction is ON (visits each business website; a bit slower). "
              "Use --no-email for a fast run.")

    # --- WARN, don't block: flag high-volume jobs (proceed anyway) ---
    if a.depth >= 15 or len(keywords) >= 10:
        print("⚠️  Heads-up: this is a large job (high depth or many keywords).")
        print("    Running it back-to-back without proxies can get your IP temporarily rate-limited by")
        print("    Google (clears in minutes–hours; returns empty/failed jobs meanwhile). For big or")
        print("    repeated runs, add proxies. Proceeding…\n")

    # Health check
    try:
        req("GET", "/api/v1/jobs")
    except Exception as e:
        sys.exit(f"✗ Scraper not reachable at {BASE} — run 'docker compose up -d' first.\n  ({e})")

    body = {"name": "scrape-py", "keywords": keywords, "lang": "en", "zoom": 15,
            "lat": str(lat), "lon": str(lon), "fast_mode": False, "radius": 10000,
            "depth": a.depth, "email": a.email, "max_time": a.max_time}
    print(f"▶ Creating job: {len(keywords)} keyword(s) @ {lat},{lon} depth={a.depth} email={a.email}")
    for k in keywords:
        print(f"    • {k}")
    try:
        _, raw = req("POST", "/api/v1/jobs", body)
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ Create failed: HTTP {e.code} — {e.read().decode()[:200]}")
    job_id = json.loads(raw).get("id")
    if not job_id:
        sys.exit("✗ No job id returned.")
    print(f"  job id: {job_id}")

    print("▶ Polling…")
    status = None
    for i in range(120):
        _, raw = req("GET", f"/api/v1/jobs/{job_id}")
        status = json.loads(raw).get("Status")
        print(f"\r  status: {str(status):<10} (attempt {i + 1})", end="", flush=True)
        if status == "ok":
            print(); break
        if status == "failed":
            sys.exit("\n✗ Job failed. If this keeps happening you may be rate-limited — wait or add proxies.")
        time.sleep(8)
    else:
        sys.exit("\n✗ Timed out.")

    _, raw = req("GET", f"/api/v1/jobs/{job_id}/download")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))
    if a.full:
        fields = list(rows[0].keys()) if rows else LEAD
    elif a.fields:
        fields = [c.strip() for c in a.fields.split(",") if c.strip()]
    else:
        fields = [f for f in LEAD if f != "summary" or a.summary]

    results = []
    for r in rows:
        lead = {k: r.get(k, "") for k in fields}
        if "summary" in fields:
            # Option 1: initial fallback from Google Maps editorial description or about
            g_desc = (r.get("descriptions") or "").strip()
            g_about = (r.get("about") or "").strip()
            lead["summary"] = g_desc or g_about
        results.append(lead)
    print(f"✓ Done — {len(results)} businesses (fields: {', '.join(fields)}).")

    if a.summary or a.socials:
        action_parts = []
        if a.summary: action_parts.append("summaries")
        if a.socials: action_parts.append("socials")
        print(f"▶ Enriching leads ({' + '.join(action_parts)}) from company websites…")
        enrich_websites(results, extract_summary=a.summary, extract_socials=a.socials)
        if a.socials:
            for s in ["instagram", "facebook", "linkedin"]:
                if s not in fields:
                    fields.append(s)
            found_soc = sum(1 for r in results if r.get("instagram") or r.get("facebook") or r.get("linkedin"))
            print(f"  socials found for {found_soc}/{len(results)} businesses")
        if a.summary:
            # Option 2 fallback: if website meta and Google descriptions were blank, provide clean category context
            for r in results:
                if not r.get("summary"):
                    cat = r.get("category") or "Business"
                    addr = r.get("address") or ""
                    r["summary"] = f"{cat} in {addr}" if addr else cat
            found_sum = sum(1 for r in results if r.get("summary"))
            print(f"  summaries populated for {found_sum}/{len(results)} businesses")

    # Default output is a CSV file (opens in Excel / Google Sheets). Use --json (or a .json --out path) for JSON.
    as_json = a.json or (a.out and a.out.lower().endswith(".json"))
    out = a.out or f"results-{job_id[:8]}.{'json' if as_json else 'csv'}"
    if as_json:
        if a.append and os.path.exists(out):
            existing = []
            try:
                with open(out, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
            seen = {(r.get("title", "").strip().lower(), r.get("phone", "").strip(), r.get("website", "").strip().lower()) for r in existing}
            new_leads = [r for r in results if (r.get("title", "").strip().lower(), r.get("phone", "").strip(), r.get("website", "").strip().lower()) not in seen]
            combined = existing + new_leads
            with open(out, "w", encoding="utf-8") as f:
                json.dump(combined, f, indent=2, ensure_ascii=False)
            print(f"  appended {len(new_leads)} new leads ({len(results) - len(new_leads)} duplicates skipped, total: {len(combined)}) → {out}")
        else:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"  saved → {out}")
    else:
        if a.append and os.path.exists(out):
            existing_rows = []
            existing_fields = []
            try:
                with open(out, "r", encoding="utf-8-sig") as f:
                    rdr = csv.DictReader(f)
                    existing_fields = list(rdr.fieldnames or [])
                    existing_rows = list(rdr)
            except Exception:
                existing_rows, existing_fields = [], []
            for fld in fields:
                if fld not in existing_fields:
                    existing_fields.append(fld)
            seen = {(r.get("title", "").strip().lower(), r.get("phone", "").strip(), r.get("website", "").strip().lower()) for r in existing_rows}
            new_leads = [r for r in results if (r.get("title", "").strip().lower(), r.get("phone", "").strip(), r.get("website", "").strip().lower()) not in seen]
            combined = existing_rows + new_leads
            with open(out, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=existing_fields or fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(combined)
            print(f"  appended {len(new_leads)} new leads ({len(results) - len(new_leads)} duplicates skipped, total: {len(combined)}) → {out}")
        else:
            with open(out, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(results)
            print(f"  saved → {out}")

    # Save to MongoDB if requested
    if a.mongo or a.project:
        project_name = a.project
        if not project_name:
            if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                try:
                    p_in = input("Enter Project Name for MongoDB storage [General Scrapes]: ").strip()
                    project_name = p_in if p_in else "General Scrapes"
                except Exception:
                    project_name = "General Scrapes"
            else:
                project_name = "General Scrapes"

        print(f"▶ Saving leads to MongoDB under project '{project_name}'…")
        try:
            import mongo_pipeline
            # Preserve all raw scraped fields and combine with enriched fields
            scraped_time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            mongo_leads = []
            for idx, r in enumerate(rows):
                m_lead = dict(r)
                m_lead["project_name"] = project_name
                m_lead["scraped_at"] = scraped_time_str
                if not m_lead.get("title") and m_lead.get("name"):
                    m_lead["title"] = m_lead.get("name")
                if idx < len(results):
                    for k in ("instagram", "facebook", "linkedin", "summary"):
                        if results[idx].get(k):
                            m_lead[k] = results[idx][k]
                mongo_leads.append(m_lead)

            stats = mongo_pipeline.save_leads_to_mongo(
                leads=mongo_leads,
                project_name=project_name,
                db_name=a.mongo_db,
                collection_name=a.collection,
                query=", ".join(keywords),
                city=a.city or "",
                job_id=job_id,
                uri=a.mongo_uri
            )
            print(f"  ✓ MongoDB: {stats['inserted']} new leads inserted, {stats['updated']} updated ({stats['total_in_project']} total in {stats['db']}.{stats['collection']})")
        except Exception as e:
            print(f"  ✗ MongoDB error: {e}", file=sys.stderr)

    for r in results[:5]:
        tail = f" | IG:{r.get('instagram','') or '—'}" if a.socials else f" | {r.get('website','')}"
        sum_preview = f"\n    ↳ Summary: {r.get('summary')[:90]}..." if r.get("summary") else ""
        print(f"  • {r.get('title','')} | {r.get('phone','')} | {r.get('emails','')}{tail}{sum_preview}")


if __name__ == "__main__":
    main()
