#!/usr/bin/env python3
"""Google Maps Lead Scraper - MongoDB Pipeline

Interactive end-to-end pipeline:
1. Prompts for Project Name (e.g. 'scrape for taltra')
2. Prompts for Search Title / Query & Location details
3. Runs the scraping engine with email & social media enrichment
4. Automatically saves, deduplicates, and indexes leads in MongoDB
5. Optionally exports CSV copy and logs project run metrics
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from typing import Optional, Tuple
import urllib.request
import urllib.parse
import urllib.error

# Add scripts directory to module path
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from scripts import mongo_pipeline
except ImportError:
    import mongo_pipeline  # type: ignore

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

# Color helpers for terminal output
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

NOMINATIM_UA = "google-maps-scraper-kit/1.0 (https://github.com/Mahanaicoach/google-maps-scraper-kit)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
LEAD_FIELDS = ["title", "phone", "emails", "website", "category", "address", "summary", "review_rating", "review_count"]


def print_banner():
    print(f"""
{CYAN}========================================================================{RESET}
{BOLD}{CYAN}      GOOGLE MAPS SCRAPER - MONGO DB LEAD PIPELINE{RESET}
{CYAN}========================================================================{RESET}
""")


def prompt_input(prompt_text: str, default: str = "") -> str:
    """Prompt user with optional default value."""
    if default:
        p = f"{BOLD}{prompt_text}{RESET} [{CYAN}{default}{RESET}]: "
    else:
        p = f"{BOLD}{prompt_text}{RESET}: "
    val = input(p).strip()
    return val if val else default


def prompt_bool(prompt_text: str, default: bool = True) -> bool:
    """Prompt user for yes/no choice."""
    choice_str = "Y/n" if default else "y/N"
    p = f"{BOLD}{prompt_text}{RESET} [{CYAN}{choice_str}{RESET}]: "
    val = input(p).strip().lower()
    if not val:
        return default
    return val.startswith("y")


def check_scraper_api(base_url: str) -> bool:
    """Check if the local scraper API is responding."""
    try:
        req = urllib.request.Request(f"{base_url}/api/v1/jobs", headers={"User-Agent": NOMINATIM_UA})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except Exception:
        return False


def geocode_place(place: str) -> Optional[tuple]:
    """Geocode place name to lat/lon via Nominatim."""
    q = urllib.parse.urlencode({"format": "json", "limit": 1, "q": place})
    url = f"https://nominatim.openstreetmap.org/search?{q}"
    r = urllib.request.Request(url, headers={"User-Agent": NOMINATIM_UA})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            hits = json.loads(resp.read())
        time.sleep(1)  # respect Nominatim's 1 req/sec policy
        if hits:
            return str(hits[0]["lat"]), str(hits[0]["lon"])
    except Exception as e:
        print(f"  {YELLOW}(geocoding notice: {e}){RESET}", file=sys.stderr)
    return None


def run_pipeline_interactive():
    print_banner()

    # 1. Environment & Mongo Check
    env_cfg = mongo_pipeline.get_default_env()
    mongo_uri = env_cfg["MONGO_URI"]
    default_db = env_cfg["MONGO_DB"]
    base_url = env_cfg["SCRAPER_BASE_URL"]

    print(f"[*] Checking system connections...")
    mongo_ok, mongo_msg = mongo_pipeline.check_mongo_connection(mongo_uri)
    if mongo_ok:
        print(f"  {GREEN}[✓] MongoDB:{RESET} {mongo_msg}")
    else:
        print(f"  {RED}[✗] MongoDB connection failed:{RESET} {mongo_msg}")
        print(f"      Make sure MongoDB is running. Try: Start-Service MongoDB")
        cont = prompt_bool("Do you want to proceed anyway?", default=False)
        if not cont:
            sys.exit(1)

    scraper_ok = check_scraper_api(base_url)
    if scraper_ok:
        print(f"  {GREEN}[✓] Scraper Engine:{RESET} Active at {base_url}")
    else:
        print(f"  {YELLOW}[!] Scraper Engine at {base_url} is not responding.{RESET}")
        print(f"      To start the scraper container, run:")
        print(f"      {CYAN}docker compose up -d{RESET} (inside google-maps-scraper-kit)")
        retry = prompt_bool("Is Docker running now? Retry connection?", default=True)
        if retry:
            if check_scraper_api(base_url):
                print(f"  {GREEN}[✓] Scraper Engine is now active!{RESET}")
            else:
                print(f"  {RED}[✗] Scraper is still not reachable.{RESET}")
                print(f"      Please start Docker and the scraper before running a live scrape.")
                print(f"      (Note: You can still use '{CYAN}python pipeline.py --import-csv <file.csv>{RESET}' to import CSVs into MongoDB)")
                sys.exit(1)
        else:
            sys.exit(1)

    print(f"\n{CYAN}--- Step 1: Project & Search Details ---{RESET}")

    # Prompt: Project Name
    while True:
        project_name = prompt_input("Enter Project Name (e.g. 'scrape for taltra')", default="scrape for taltra")
        if project_name.strip():
            break
        print(f"  {RED}Project name cannot be empty.{RESET}")

    # Prompt: Title / Search Query
    while True:
        search_query = prompt_input("Enter Search Title / Keyword (e.g. 'recruitment agencies' or 'coffee shops')")
        if search_query.strip():
            break
        print(f"  {RED}Search keyword cannot be empty.{RESET}")

    # Prompt: City / Location
    city = prompt_input("Enter Target City / Location (e.g. 'Dubai, UAE' or 'Austin, TX')")

    print(f"\n{CYAN}--- Step 2: Scraping Options ---{RESET}")
    depth_str = prompt_input("Scraping Depth (scroll pages, roughly 20 leads/page)", default="5")
    try:
        depth = int(depth_str)
    except ValueError:
        depth = 5

    extract_emails = prompt_bool("Extract Business Emails from websites? (recommended)", default=True)
    extract_socials = prompt_bool("Enrich Social Media (Instagram, Facebook, LinkedIn)?", default=True)
    extract_summary = prompt_bool("Extract Website AI/Meta Summaries?", default=True)

    print(f"\n{CYAN}--- Step 3: MongoDB Destination ---{RESET}")
    db_name = prompt_input("Target MongoDB Database", default=default_db)
    coll_choice = prompt_input("Store in: [1] Unified 'leads' collection with project tag (Recommended), [2] Project-specific collection", default="1")
    if coll_choice.strip() == "2":
        clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", project_name.lower()).strip("_")
        collection_name = f"{clean_slug}_leads"
    else:
        collection_name = "leads"

    save_csv = prompt_bool("Also save an offline CSV backup?", default=True)

    # Confirmation
    print(f"\n{CYAN}========================================================================{RESET}")
    print(f"{BOLD}Pipeline Ready to Launch:{RESET}")
    print(f"  • Project:      {GREEN}{project_name}{RESET}")
    print(f"  • Search Query: {GREEN}{search_query}{RESET}")
    print(f"  • Location:     {GREEN}{city or '(baked into query)'}{RESET}")
    print(f"  • Depth:        {GREEN}{depth}{RESET} (~{depth * 20} potential listings)")
    print(f"  • Emails:       {GREEN}{'Enabled' if extract_emails else 'Disabled'}{RESET}")
    print(f"  • Socials:      {GREEN}{'Enabled' if extract_socials else 'Disabled'}{RESET}")
    print(f"  • Database:     {GREEN}{db_name}.{collection_name}{RESET}")
    print(f"  • CSV Backup:   {GREEN}{'Yes' if save_csv else 'No'}{RESET}")
    print(f"{CYAN}========================================================================{RESET}")

    confirm = prompt_bool("Start scraping pipeline now?", default=True)
    if not confirm:
        print("Cancelled.")
        return

    # Execute scrape
    execute_pipeline(
        project_name=project_name,
        search_query=search_query,
        city=city,
        depth=depth,
        extract_emails=extract_emails,
        extract_socials=extract_socials,
        extract_summary=extract_summary,
        db_name=db_name,
        collection_name=collection_name,
        save_csv=save_csv,
        base_url=base_url,
    )


def execute_pipeline(
    project_name: str,
    search_query: str,
    city: str = "",
    depth: int = 5,
    extract_emails: bool = True,
    extract_socials: bool = True,
    extract_summary: bool = True,
    db_name: str = "google_maps_leads",
    collection_name: str = "leads",
    save_csv: bool = True,
    base_url: str = "http://localhost:8080",
    max_time: int = 600,
):
    """Executes the scraper and writes directly to MongoDB."""
    # 1. Geocode location
    query_baked = f"{search_query} in {city}" if city and city.lower() not in search_query.lower() else search_query
    geocode_target = city or search_query
    print(f"\n{CYAN}▶ Geocoding \"{geocode_target}\"...{RESET}")
    coords = geocode_place(geocode_target)
    if not coords:
        sys.exit(f"{RED}✗ Could not resolve coordinates for '{geocode_target}'. Please specify a clearer city.{RESET}")
    lat, lon = coords
    print(f"  {GREEN}→ Coordinates:{RESET} {lat}, {lon}")

    # 2. Submit job to scraper engine
    headers = {"Content-Type": "application/json", "User-Agent": NOMINATIM_UA}
    body = {
        "name": f"mongo-pipeline-{int(time.time())}",
        "keywords": [query_baked],
        "lang": "en",
        "zoom": 15,
        "lat": str(lat),
        "lon": str(lon),
        "fast_mode": False,
        "radius": 10000,
        "depth": depth,
        "email": extract_emails,
        "max_time": max_time,
    }

    print(f"\n{CYAN}▶ Submitting job to Google Maps Scraper...{RESET}")
    print(f"    • Keyword: {query_baked}")
    print(f"    • Depth: {depth} | Emails: {extract_emails}")

    try:
        req = urllib.request.Request(f"{base_url}/api/v1/jobs", data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            create_res = json.loads(resp.read().decode())
    except Exception as e:
        sys.exit(f"{RED}✗ Failed to create scraper job: {e}{RESET}")

    job_id = create_res.get("id")
    if not job_id:
        sys.exit(f"{RED}✗ Scraper API did not return a job ID.{RESET}")
    print(f"  {GREEN}[✓] Job created:{RESET} {job_id}")

    # 3. Poll for completion
    print(f"\n{CYAN}▶ Scraping in progress (polling engine)...{RESET}")
    status = None
    for attempt in range(150):
        try:
            req = urllib.request.Request(f"{base_url}/api/v1/jobs/{job_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                status_res = json.loads(resp.read().decode())
                status = status_res.get("Status")
        except Exception as e:
            status = f"retrying ({e})"

        print(f"\r  Status: {BOLD}{str(status):<12}{RESET} (attempt {attempt + 1})", end="", flush=True)
        if status == "ok":
            print(f"\n  {GREEN}[✓] Scraping job completed successfully!{RESET}")
            break
        if status == "failed":
            sys.exit(f"\n{RED}✗ Scraping job failed. You may be temporarily rate-limited.{RESET}")
        time.sleep(6)
    else:
        sys.exit(f"\n{RED}✗ Scraper job timed out.{RESET}")

    # 4. Download scraped data
    print(f"\n{CYAN}▶ Downloading scraped results...{RESET}")
    try:
        req = urllib.request.Request(f"{base_url}/api/v1/jobs/{job_id}/download", headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            csv_raw = resp.read().decode("utf-8", "replace")
    except Exception as e:
        sys.exit(f"{RED}✗ Failed to download results: {e}{RESET}")

    import csv, io
    rows = list(csv.DictReader(io.StringIO(csv_raw)))
    print(f"  {GREEN}[✓] Retrieved {len(rows)} raw listings from Google Maps.{RESET}")

    # 5. Prepare & enrich leads (Preserving all scraped fields)
    scraped_time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    results = []
    for r in rows:
        # Keep the exact same data from the scrape without dropping any columns
        lead = dict(r)
        # Ensure project_name and scraped_at are explicitly attached to each lead
        lead["project_name"] = project_name.strip()
        lead["scraped_at"] = scraped_time_str

        # Guarantee title is populated
        if not lead.get("title") and lead.get("name"):
            lead["title"] = lead.get("name")

        if extract_summary:
            g_desc = (r.get("descriptions") or "").strip()
            g_about = (r.get("about") or "").strip()
            if not lead.get("summary"):
                lead["summary"] = g_desc or g_about
        results.append(lead)

    # Enrich from website (meta summaries and social media)
    if (extract_summary or extract_socials) and results:
        print(f"\n{CYAN}▶ Enriching leads (summaries & social media) from websites...{RESET}")
        try:
            from scripts import scrape
            scrape.enrich_websites(results, extract_summary=extract_summary, extract_socials=extract_socials)
        except ImportError:
            try:
                import scrape  # type: ignore
                scrape.enrich_websites(results, extract_summary=extract_summary, extract_socials=extract_socials)
            except Exception:
                pass
        except Exception:
            # Fallback enrichment
            pass

    # 6. Save to MongoDB
    print(f"\n{CYAN}▶ Inserting leads into MongoDB database '{db_name}'...{RESET}")
    save_stats = mongo_pipeline.save_leads_to_mongo(
        leads=results,
        project_name=project_name,
        db_name=db_name,
        collection_name=collection_name,
        query=query_baked,
        city=city,
        job_id=job_id,
    )

    print(f"  {GREEN}========================================================================{RESET}")
    print(f"  {BOLD}{GREEN}✓ MONGODB PIPELINE COMPLETED SUCCESSFULLY!{RESET}")
    print(f"  {GREEN}========================================================================{RESET}")
    print(f"  • Database:        {CYAN}{save_stats['db']}{RESET}")
    print(f"  • Collection:      {CYAN}{save_stats['collection']}{RESET}")
    print(f"  • Project Name:    {BOLD}{project_name}{RESET}")
    print(f"  • Scraped Time:    {CYAN}{scraped_time_str}{RESET}")
    print(f"  • Total Scraped:   {len(results)}")
    print(f"  • New Leads Added: {GREEN}{save_stats['inserted']}{RESET}")
    print(f"  • Duplicates/Updated: {YELLOW}{save_stats['updated']}{RESET}")
    print(f"  • Total in Project:{BOLD} {save_stats['total_in_project']} leads{RESET}")

    # 7. Optional CSV Backup (All columns preserved + project_name + scraped_at)
    if save_csv:
        clean_proj = re.sub(r"[^a-zA-Z0-9_]", "_", project_name.lower()).strip("_")
        out_csv = f"{clean_proj}_leads_{job_id[:8]}.csv"
        try:
            # Build column headers with project_name and scraped_at first, followed by all scraped fields
            all_fieldnames = ["project_name", "scraped_at"]
            for r in results:
                for k in r.keys():
                    if k not in all_fieldnames:
                        all_fieldnames.append(k)

            with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=all_fieldnames, extrasaction="ignore")
                w.writeheader()
                w.writerows(results)
            print(f"  • Offline CSV Backup: {CYAN}{out_csv}{RESET}")
        except Exception as e:
            print(f"  {YELLOW}(CSV backup skipped: {e}){RESET}")

    # 8. Sample preview
    print(f"\n{CYAN}Preview of scraped leads in MongoDB:{RESET}")
    for idx, r in enumerate(results[:5], 1):
        soc_str = []
        if r.get("instagram"): soc_str.append(f"IG: {r['instagram']}")
        if r.get("linkedin"): soc_str.append(f"IN: {r['linkedin']}")
        soc_text = f" | {' '.join(soc_str)}" if soc_str else ""
        lead_title = r.get('title') or r.get('name') or 'N/A'
        print(f"  {idx}. [{BOLD}{project_name}{RESET}] {BOLD}{lead_title}{RESET} | Phone: {r.get('phone') or 'N/A'} | Email: {r.get('emails') or 'N/A'}{soc_text}")

    print(f"\n{CYAN}Query tips for MongoDB Compass or mongosh:{RESET}")
    print(f"  {BOLD}mongosh{RESET}")
    print(f"  use {db_name}")
    print(f'  db.{collection_name}.find({{ "project_name": "{project_name}" }})')
    print(f'  db.{collection_name}.find({{ "project_name": "{project_name}", "emails.0": {{ "$exists": true }} }})')


def main():
    ap = argparse.ArgumentParser(description="Google Maps Scraper - MongoDB Pipeline")
    ap.add_argument("--project", "-p", help="Project name (e.g. 'scrape for taltra')")
    ap.add_argument("--keyword", "-k", help="Search keyword (e.g. 'recruitment agencies')")
    ap.add_argument("--city", "-c", help="Target city / location")
    ap.add_argument("--depth", "-d", type=int, default=5, help="Scraping depth (default: 5)")
    ap.add_argument("--no-email", action="store_true", help="Disable email extraction")
    ap.add_argument("--no-socials", action="store_true", help="Disable social media extraction")
    ap.add_argument("--no-csv", action="store_true", help="Do not save CSV backup")
    ap.add_argument("--db", default=None, help="Target MongoDB database name")
    ap.add_argument("--collection", default="leads", help="Target MongoDB collection name (default: leads)")
    ap.add_argument("--import-csv", help="Import an existing CSV file into MongoDB under --project")
    ap.add_argument("--list-projects", action="store_true", help="List all projects and stats in MongoDB")

    args = ap.parse_args()

    # 1. List projects
    if args.list_projects:
        print_banner()
        print(f"[*] Fetching projects from MongoDB...")
        try:
            projects = mongo_pipeline.list_mongo_projects(db_name=args.db)
            if not projects:
                print("No projects found in MongoDB yet.")
                return
            print(f"\n{'Project Name':<30} {'Leads':<8} {'With Email':<12} {'With Socials':<14} {'Last Updated'}")
            print("-" * 80)
            for p in projects:
                up_str = str(p['last_updated'])[:19] if p['last_updated'] else "N/A"
                print(f"{p['project_name']:<30} {p['lead_count']:<8} {p['has_emails']:<12} {p['has_socials']:<14} {up_str}")
        except Exception as e:
            print(f"{RED}Error fetching projects: {e}{RESET}")
        return

    # 2. Import CSV
    if args.import_csv:
        print_banner()
        if not args.project:
            args.project = prompt_input("Enter Project Name for this CSV import", default="scrape for taltra")
        print(f"[*] Importing '{args.import_csv}' into MongoDB under project '{args.project}'...")
        try:
            stats = mongo_pipeline.import_csv_to_mongo(
                csv_file=args.import_csv,
                project_name=args.project,
                db_name=args.db,
                collection_name=args.collection
            )
            print(f"{GREEN}[✓] CSV Import Complete!{RESET}")
            print(f"  • Database:        {stats['db']}")
            print(f"  • Collection:      {stats['collection']}")
            print(f"  • Project:         {args.project}")
            print(f"  • Leads Imported:  {stats['total_scraped']}")
            print(f"  • New Added:       {stats['inserted']}")
            print(f"  • Updated:         {stats['updated']}")
            print(f"  • Total in Project:{stats['total_in_project']}")
        except Exception as e:
            print(f"{RED}Error during CSV import: {e}{RESET}")
        return

    # 3. If keyword or project given via CLI, run non-interactively
    if args.project and args.keyword:
        env_cfg = mongo_pipeline.get_default_env()
        execute_pipeline(
            project_name=args.project,
            search_query=args.keyword,
            city=args.city or "",
            depth=args.depth,
            extract_emails=not args.no_email,
            extract_socials=not args.no_socials,
            extract_summary=True,
            db_name=args.db or env_cfg["MONGO_DB"],
            collection_name=args.collection,
            save_csv=not args.no_csv,
            base_url=env_cfg["SCRAPER_BASE_URL"],
        )
        return

    # 4. Otherwise, run full interactive wizard
    run_pipeline_interactive()


if __name__ == "__main__":
    main()
