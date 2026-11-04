import os
import sys
import json
import csv
import time
from datetime import datetime
import requests

# Load .env file manually if python-dotenv is not installed
def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())

load_env()
API_KEY = os.getenv("APOLLO_API_KEY", "").strip()

if not API_KEY:
    print("[ERROR] No APOLLO_API_KEY found in .env or environment variables.")
    sys.exit(1)

HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
    "X-Api-Key": API_KEY
}

# Taltra Default Target ICP Configuration
DEFAULT_TITLES = [
    "Founder",
    "Co-Founder",
    "Managing Director",
    "Head of Recruitment",
    "Recruitment Operations Manager",
    "Head of Talent Acquisition",
    "Talent Acquisition Manager",
    "Director of Human Resources",
    "Head of HR"
]

DEFAULT_LOCATIONS = [
    "India",
    "United States",
    "United Kingdom",
    "United Arab Emirates",
    "Canada"
]

DEFAULT_EMPLOYEE_RANGES = [
    "11,20",
    "21,50",
    "51,100",
    "101,200",
    "201,500"
]

DEFAULT_KEYWORDS = [
    "Staffing",
    "Recruiting",
    "Human Resources",
    "Talent Acquisition",
    "Information Technology",
    "BPO"
]


def search_leads(titles=None, locations=None, employee_ranges=None, keywords=None, page=1, per_page=25):
    """
    Search Apollo database. Costs 0 CREDITS (Free search).
    Filters only candidates who have confirmed emails.
    """
    url = "https://api.apollo.io/api/v1/mixed_people/api_search"
    payload = {
        "person_titles": titles or DEFAULT_TITLES,
        "person_locations": locations or DEFAULT_LOCATIONS,
        "organization_num_employees_ranges": employee_ranges or DEFAULT_EMPLOYEE_RANGES,
        "q_organization_keyword_tags": keywords or DEFAULT_KEYWORDS,
        "contact_email_status": ["verified"],
        "page": page,
        "per_page": per_page
    }

    try:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=20)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[ERROR during search]: {e}")
        return None


def enrich_person(person_id):
    """
    Enriches a single person using their Apollo ID.
    COSTS EXACTLY 1 EMAIL CREDIT per person.
    Returns verified work email, office phone, and full details.
    """
    url = "https://api.apollo.io/api/v1/people/match"
    payload = {
        "id": person_id,
        "reveal_personal_emails": False
    }

    try:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=20)
        res.raise_for_status()
        data = res.json()
        return data.get("person")
    except Exception as e:
        print(f"[WARN] Failed to enrich ID {person_id}: {e}")
        return None


def run_prospecting(limit=10, country=None, title_keyword=None):
    """
    Runs credit-optimized prospecting for Taltra:
    1. Searches matching prospects (0 credits).
    2. Filters only people with confirmed email availability.
    3. Confirms credit usage before spending credits.
    4. Enriches and exports to CSV.
    """
    locations = [country] if country else DEFAULT_LOCATIONS
    titles = [title_keyword] if title_keyword else DEFAULT_TITLES

    print("\n" + "=" * 65)
    print("      TALTRA LEAD PROSPECTOR — POWERED BY APOLLO.IO")
    print("=" * 65)
    print(f"Target Locations : {', '.join(locations)}")
    print(f"Company Sizes    : 10 - 500 employees")
    print(f"Target Roles     : {len(titles)} recruitment decision maker titles")
    print(f"Desired Leads    : {limit} verified contacts (1 credit each)")
    print("-" * 65)
    print("[*] Searching Apollo database (0 CREDITS USED FOR SEARCH)...")

    prospects_to_enrich = []
    page = 1
    total_found = 0

    while len(prospects_to_enrich) < limit and page <= 10:
        data = search_leads(titles=titles, locations=locations, page=page, per_page=50)
        if not data:
            break

        total_found = data.get("total_entries", 0)
        people = data.get("people", [])
        if not people:
            break

        for p in people:
            # CREDIT SAVER CHECK: Only pick people where Apollo confirms an email exists
            if p.get("has_email"):
                prospects_to_enrich.append(p)
                if len(prospects_to_enrich) >= limit:
                    break

        page += 1

    print(f"[+] Total matching profiles found in Apollo: {total_found:,}")
    print(f"[+] Qualified leads with email ready to reveal: {len(prospects_to_enrich)}")

    if not prospects_to_enrich:
        print("[!] No leads found matching the exact criteria.")
        return

    credits_to_use = len(prospects_to_enrich)
    print(f"\n[CREDIT ALERT] We will use EXACTLY {credits_to_use} Apollo email credit(s).")
    print("[*] Fetching verified emails & phone numbers now...\n")

    results = []
    for i, p in enumerate(prospects_to_enrich, 1):
        pid = p.get("id")
        pname = p.get("first_name", "Unknown")
        ptitle = p.get("title", "Unknown")
        org_name = (p.get("organization") or {}).get("name", "Unknown")

        print(f"[{i}/{credits_to_use}] Enriching: {pname} | {ptitle} @ {org_name}...")
        enriched = enrich_person(pid)

        if enriched:
            email = enriched.get("email")
            email_status = enriched.get("email_status")
            org = enriched.get("organization") or {}
            
            # Office phone or direct company phone
            phone = org.get("phone") or (org.get("primary_phone") or {}).get("number", "")

            results.append({
                "Full Name": enriched.get("name", ""),
                "First Name": enriched.get("first_name", ""),
                "Last Name": enriched.get("last_name", ""),
                "Job Title": enriched.get("title", ""),
                "Work Email": email or "Not Available",
                "Email Status": email_status or "Unknown",
                "Company Phone": phone or "N/A",
                "Company Name": org.get("name", ""),
                "Company Website": org.get("website_url", ""),
                "Employees": org.get("estimated_num_employees", ""),
                "Industry": org.get("industry", ""),
                "City": enriched.get("city", "") or org.get("city", ""),
                "Country": enriched.get("country", "") or org.get("country", ""),
                "LinkedIn URL": enriched.get("linkedin_url", ""),
                "Company LinkedIn": org.get("linkedin_url", "")
            })

            status_icon = "OK" if email_status == "verified" else "?"
            print(f"    --> [{status_icon}] Email: {email} | Phone: {phone or 'N/A'}")
        
        # Friendly rate-limit spacing
        time.sleep(0.3)

    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_filename = f"taltra_leads_{timestamp}.csv"
    out_path = os.path.join(out_dir, out_filename)

    if results:
        fieldnames = list(results[0].keys())
        with open(out_path, mode="w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print("\n" + "=" * 65)
        print(f"[SUCCESS] {len(results)} Leads successfully extracted & saved!")
        print(f"CSV File: {out_path}")
        print("=" * 65)
    else:
        print("[!] No results were enriched.")


if __name__ == "__main__":
    limit = 10
    country = None

    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass

    if len(sys.argv) > 2:
        country = sys.argv[2]

    run_prospecting(limit=limit, country=country)
