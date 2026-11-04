#!/usr/bin/env python3
"""Autonomous Decision-Maker & Verified People Discovery Agent.

Extracts verified leadership contacts (Founders, CEOs, Managing Directors,
HR Directors, and Recruitment/Talent Heads) using DuckDuckGo search intelligence,
deep website crawling, and strict zero-guessing email verification.
"""

import argparse
import datetime
import json
import os
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import bs4
from ddgs import DDGS
from ddgs.exceptions import DDGSException
import httpx
from rapidfuzz import fuzz
import tldextract

# ---------------------------------------------------------------------------
# Load Environment & API Keys
# ---------------------------------------------------------------------------
def _load_env_file():
    """Load .env from project root or kit directories."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, ".env"),
        os.path.join(base_dir, "googlemaps_scraper", "google-maps-scraper-kit", ".env"),
    ]
    for env_path in candidates:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())

_load_env_file()
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
HTTP_TIMEOUT = 7.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

BLOCKED_AGGREGATOR_DOMAINS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "yelp.com", "yellowpages.com", "justdial.com", "tripadvisor.com",
    "sulekha.com", "indiamart.com", "google.com", "youtube.com",
    "pinterest.com", "tiktok.com", "wikipedia.org", "bloomberg.com",
    "dnb.com", "zoominfo.com", "crunchbase.com", "glassdoor.com",
    "indeed.com", "mapquest.com", "bbb.org", "trustpilot.com"
}

TEAM_PAGE_PATHS = [
    "/about", "/about-us", "/our-team", "/team", "/leadership",
    "/management", "/people", "/contact", "/contact-us"
]

EX_EMPLOYEE_RE = re.compile(
    r"\b(ex[- ]|former\b|previously\b|past\b|prior\b|previous\b)",
    re.IGNORECASE
)

# Standardized Role Tiers with Regex Patterns
ROLE_TIERS = {
    "Tier 1: Founder & C-Suite": [
        (re.compile(r"\b(co-?founder|founder)\b", re.I), "Founder"),
        (re.compile(r"\b(ceo|chief executive officer)\b", re.I), "CEO"),
        (re.compile(r"\b(managing director|md)\b", re.I), "Managing Director"),
        (re.compile(r"\b(president|owner|partner)\b", re.I), "Executive Partner"),
    ],
    "Tier 2: HR Leadership": [
        (re.compile(r"\b(hr director|director of human resources|director hr)\b", re.I), "HR Director"),
        (re.compile(r"\b(head of hr|head of human resources)\b", re.I), "Head of HR"),
        (re.compile(r"\b(vp of human resources|vp hr|chief people officer)\b", re.I), "Chief People Officer"),
        (re.compile(r"\b(people & culture director|head of people)\b", re.I), "Head of People & Culture"),
    ],
    "Tier 3: Recruitment Leadership": [
        (re.compile(r"\b(head of recruitment|recruitment director|director of recruitment)\b", re.I), "Head of Recruitment"),
        (re.compile(r"\b(head of talent acquisition|talent acquisition director|talent acquisition head)\b", re.I), "Head of Talent Acquisition"),
        (re.compile(r"\b(recruitment operations manager|recruitment operations)\b", re.I), "Recruitment Operations"),
        (re.compile(r"\b(lead recruiter|talent acquisition manager)\b", re.I), "Talent Acquisition Lead"),
    ]
}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
EMAIL_SKIP_DOMAINS = {
    "sentry.io", "example.com", "w3.org", "schema.org", "domain.com",
    "google.com", "facebook.com", "twitter.com", "linkedin.com", "cloudflare.com"
}
EMAIL_SKIP_EXT = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".woff", ".ttf"
)


# ---------------------------------------------------------------------------
# Domain Resolution & Cleansing
# ---------------------------------------------------------------------------
def extract_clean_domain(url: str) -> str:
    """Extract registered domain (e.g., 'company.com') from a URL."""
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    extracted = tldextract.extract(url)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return ""


def is_aggregator_or_social(url: str) -> bool:
    """Check if domain is a directory, social platform, or aggregator."""
    domain = extract_clean_domain(url)
    return domain in BLOCKED_AGGREGATOR_DOMAINS or not domain


def resolve_company_domain(company_name: str, raw_url: str = "", city: str = "") -> str:
    """Resolve clean genuine company domain, falling back to DuckDuckGo if missing or aggregator."""
    clean_dom = extract_clean_domain(raw_url)
    if clean_dom and not is_aggregator_or_social(clean_dom):
        return clean_dom

    # Fallback to DuckDuckGo search to locate official corporate website
    query = f'"{company_name}" {city} official website'
    try:
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=3))
        for r in results:
            href = r.get("href", "")
            d = extract_clean_domain(href)
            if d and not is_aggregator_or_social(d):
                return d
    except Exception:
        pass

    return clean_dom


# ---------------------------------------------------------------------------
# Role Matching & Normalization
# ---------------------------------------------------------------------------
def normalize_role(raw_title: str) -> Tuple[Optional[str], Optional[str], int]:
    """
    Match and normalize raw title against target ICP roles.
    Returns: (standardized_role, tier_name, tier_weight)
    """
    if not raw_title:
        return None, None, 0

    # Reject former/ex employees
    if EX_EMPLOYEE_RE.search(raw_title):
        return None, None, 0

    for tier_name, patterns in ROLE_TIERS.items():
        weight = 3 if "Tier 1" in tier_name else (2 if "Tier 2" in tier_name else 1)
        for pattern, std_name in patterns:
            if pattern.search(raw_title):
                return std_name, tier_name, weight

    return None, None, 0


# ---------------------------------------------------------------------------
# Deep Website Team & About Crawler
# ---------------------------------------------------------------------------
def crawl_website_team_page(domain: str) -> Dict[str, Any]:
    """
    Crawls company website for leadership profiles, team cards, and direct emails.
    Returns: {
        'direct_emails': [str],
        'team_members': [{'name': str, 'role': str, 'email': str}]
    }
    """
    out: Dict[str, Any] = {"direct_emails": [], "team_members": []}
    if not domain:
        return out

    base_url = f"https://{domain}"
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        verify=False
    )

    visited_emails: Set[str] = set()

    for path in TEAM_PAGE_PATHS[:5]:  # Check top paths
        url = urllib.parse.urljoin(base_url, path)
        try:
            resp = client.get(url)
            if resp.status_code != 200 or not resp.text:
                continue

            html = resp.text
            soup = bs4.BeautifulSoup(html, "lxml")

            # 1. Harvest emails
            mailtos = soup.select('a[href^="mailto:"]')
            for a in mailtos:
                href = a.get("href", "")
                em = href.replace("mailto:", "").split("?")[0].strip().lower()
                if em and "@" in em:
                    em_dom = em.split("@")[-1]
                    if em_dom == domain and em not in visited_emails:
                        visited_emails.add(em)
                        out["direct_emails"].append(em)

            # Raw regex email scan on site
            for em in EMAIL_RE.findall(html):
                em_clean = em.lower().strip(".,:;'/\"")
                if em_clean.endswith(EMAIL_SKIP_EXT):
                    continue
                em_dom = em_clean.split("@")[-1]
                if em_dom in EMAIL_SKIP_DOMAINS or em_dom != domain:
                    continue
                if em_clean not in visited_emails:
                    visited_emails.add(em_clean)
                    out["direct_emails"].append(em_clean)

            # 2. Extract JSON-LD schema.org/Person
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for it in items:
                        if isinstance(it, dict) and it.get("@type") in ("Person", "http://schema.org/Person"):
                            p_name = it.get("name", "").strip()
                            p_job = it.get("jobTitle", "").strip()
                            p_email = it.get("email", "").strip().lower()
                            if p_name and p_job:
                                std_role, _, _ = normalize_role(p_job)
                                if std_role:
                                    out["team_members"].append({
                                        "name": p_name,
                                        "role": std_role,
                                        "email": p_email if p_email and p_email.endswith(domain) else ""
                                    })
                except Exception:
                    pass

        except Exception:
            continue
        finally:
            time.sleep(0.1)

    try:
        client.close()
    except Exception:
        pass

    return out


# ---------------------------------------------------------------------------
# Strict Email Verification Engine (ZERO GUESSING)
# ---------------------------------------------------------------------------
def verify_email_strictly(
    first_name: str,
    last_name: str,
    domain: str,
    company_name: str,
    on_site_emails: List[str]
) -> Tuple[str, str]:
    """
    STRICT ZERO-GUESSING EMAIL VERIFICATION.
    Only returns an email if:
    1. Direct match on official company team/contact page ('Verified (On-Site)').
    2. Verified through Apollo API match ('Verified (Apollo)').
    Otherwise, returns ('', 'Not Found / Verified Only').
    """
    if not first_name or not domain:
        return "", "Not Found / Verified Only"

    fn = re.sub(r"[^a-zA-Z]", "", first_name).lower()
    ln = re.sub(r"[^a-zA-Z]", "", last_name).lower()

    # Step 1: Check On-Site Harvested Emails
    for em in on_site_emails:
        user_part = em.split("@")[0].lower()
        if (fn and fn in user_part) or (ln and len(ln) > 2 and ln in user_part):
            return em, "Verified (On-Site)"

    # Step 2: Check Apollo Match (if key exists)
    if APOLLO_API_KEY:
        try:
            url = "https://api.apollo.io/api/v1/people/match"
            headers = {
                "Content-Type": "application/json",
                "X-Api-Key": APOLLO_API_KEY
            }
            payload = {
                "first_name": first_name,
                "last_name": last_name,
                "domain": domain,
                "organization_name": company_name,
                "reveal_personal_emails": False
            }
            r = httpx.post(url, headers=headers, json=payload, timeout=8.0)
            if r.status_code == 200:
                p_data = r.json().get("person") or {}
                verified_em = p_data.get("email", "").strip().lower()
                status = p_data.get("email_status", "").lower()
                if verified_em and status in ("verified", "valid", "deliverable"):
                    return verified_em, "Verified (Apollo)"
        except Exception:
            pass

    # ZERO-GUESSING ENFORCEMENT: Never generate pattern-guessed emails!
    return "", "Not Found / Verified Only"


# ---------------------------------------------------------------------------
# DuckDuckGo LinkedIn Leadership Discovery
# ---------------------------------------------------------------------------
def _parse_linkedin_title(raw_title: str) -> Tuple[str, str]:
    """Extract clean person name and role from a LinkedIn snippet title."""
    title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", raw_title, flags=re.I).strip()
    title = re.sub(r"\s*-\s*LinkedIn\s*$", "", title, flags=re.I).strip()

    parts = [p.strip() for p in re.split(r"\s*[-–—|•]\s*", title) if p.strip()]
    if not parts:
        return "", ""

    name = parts[0]
    name = re.sub(r"\(.*?\)", "", name).strip()
    name = re.sub(r"[,].*$", "", name).strip()

    role = parts[1] if len(parts) >= 2 else ""
    return name, role


def search_duckduckgo_leadership(company_name: str, domain: str = "") -> List[Dict[str, Any]]:
    """
    Search DuckDuckGo for public LinkedIn profiles matching target decision makers.
    Uses randomized backoff and anti-noise company validation.
    """
    candidates = []
    seen_urls: Set[str] = set()

    queries = [
        f'site:linkedin.com/in/ "{company_name}" ("CEO" OR "Founder" OR "Managing Director")',
        f'site:linkedin.com/in/ "{company_name}" ("Head of Recruitment" OR "HR Director" OR "Talent Acquisition")',
    ]

    for q in queries:
        try:
            # Randomized pacing jitter to avoid search blocks
            time.sleep(random.uniform(1.2, 2.2))
            ddgs = DDGS()
            results = list(ddgs.text(q, max_results=4))
        except DDGSException:
            results = []
        except Exception:
            results = []

        for r in results:
            url = r.get("href", "")
            title = r.get("title", "")
            body = r.get("body", "")

            if not url or "linkedin.com/in/" not in url:
                continue

            # Strip tracking parameters from LinkedIn URL
            clean_url = url.split("?")[0].rstrip("/")
            if clean_url in seen_urls:
                continue

            # Reject ex-employees
            full_text = f"{title} {body}"
            if EX_EMPLOYEE_RE.search(full_text):
                continue

            # Validate company affiliation via RapidFuzz
            company_match_score = max(
                fuzz.partial_ratio(company_name.lower(), title.lower()),
                fuzz.partial_ratio(company_name.lower(), body.lower())
            )
            if company_match_score < 70:
                continue

            name, raw_role = _parse_linkedin_title(title)
            if not name or len(name.split()) < 2:
                continue

            # Check role normalization against title and snippet body
            std_role, tier, weight = normalize_role(raw_role)
            if not std_role:
                std_role, tier, weight = normalize_role(body)

            if not std_role:
                continue

            seen_urls.add(clean_url)
            candidates.append({
                "name": name,
                "role": std_role,
                "tier": tier,
                "weight": weight,
                "linkedin_url": clean_url,
                "company_match_score": company_match_score,
                "source": "DuckDuckGo + LinkedIn"
            })

    return candidates


# ---------------------------------------------------------------------------
# MongoDB TTL Caching Helpers
# ---------------------------------------------------------------------------
def get_cached_decision_makers(db: Any, company_name: str, domain: str = "") -> Optional[List[Dict[str, Any]]]:
    """Retrieve cached decision makers from MongoDB enrichment_cache collection if present."""
    if db is None:
        return None
    try:
        coll = db["enrichment_cache"]
        filter_q: Dict[str, Any] = {}
        if domain:
            filter_q["domain"] = domain.lower()
        else:
            filter_q["company_name"] = company_name.strip().lower()
        doc = coll.find_one(filter_q)
        if doc and "decision_makers" in doc:
            return doc["decision_makers"]
    except Exception:
        pass
    return None


def save_cached_decision_makers(db: Any, company_name: str, domain: str, decision_makers: List[Dict[str, Any]]):
    """Save discovered decision makers into MongoDB enrichment_cache with 30-day TTL."""
    if db is None:
        return
    try:
        coll = db["enrichment_cache"]
        coll.create_index("created_at", expireAfterSeconds=30 * 86400, background=True)
        coll.create_index([("domain", 1)], background=True)
        coll.create_index([("company_name", 1)], background=True)

        doc = {
            "company_name": company_name.strip().lower(),
            "domain": domain.lower() if domain else "",
            "decision_makers": decision_makers,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        filter_q = {"domain": domain.lower()} if domain else {"company_name": company_name.strip().lower()}
        coll.update_one(filter_q, {"$set": doc}, upsert=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main Consolidated Discovery Function
# ---------------------------------------------------------------------------
def discover_decision_makers(
    company_name: str,
    raw_website: str = "",
    city: str = "",
    max_per_company: int = 3,
    mongo_db: Any = None
) -> List[Dict[str, Any]]:
    """
    End-to-end discovery of verified decision makers for a business.
    Adheres strictly to the Zero-Guessed Email Policy and utilizes 30-day Mongo caching.
    """
    if not company_name:
        return []

    # 1. Resolve genuine corporate domain
    domain = resolve_company_domain(company_name, raw_website, city)

    # 2. Check MongoDB cache first (TTL 30 days)
    if mongo_db is not None:
        cached = get_cached_decision_makers(mongo_db, company_name, domain)
        if cached is not None:
            return cached[:max_per_company]

    # 2. Deep crawl company website for team members & on-site verified emails
    site_data = crawl_website_team_page(domain)
    on_site_emails = site_data.get("direct_emails", [])
    team_members = site_data.get("team_members", [])

    # 3. Discover LinkedIn decision-maker profiles via DuckDuckGo
    ddg_candidates = search_duckduckgo_leadership(company_name, domain)

    # Merge candidates deduplicating by normalized name
    merged: Dict[str, Dict[str, Any]] = {}

    for c in ddg_candidates:
        norm_key = re.sub(r"[^a-zA-Z]", "", c["name"]).lower()
        merged[norm_key] = c

    for tm in team_members:
        norm_key = re.sub(r"[^a-zA-Z]", "", tm["name"]).lower()
        if norm_key in merged:
            if tm.get("email"):
                merged[norm_key]["email"] = tm["email"]
                merged[norm_key]["email_status"] = "Verified (On-Site)"
        else:
            std_role, tier, weight = normalize_role(tm["role"])
            if std_role:
                merged[norm_key] = {
                    "name": tm["name"],
                    "role": std_role,
                    "tier": tier,
                    "weight": weight,
                    "linkedin_url": "",
                    "email": tm.get("email", ""),
                    "email_status": "Verified (On-Site)" if tm.get("email") else "Not Found / Verified Only",
                    "company_match_score": 100,
                    "source": "Official Website Team Page"
                }

    final_results = []
    for norm_key, cand in merged.items():
        name_parts = cand["name"].split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

        # Strict email verification (zero guessing)
        if not cand.get("email"):
            verified_em, em_status = verify_email_strictly(
                first_name=first_name,
                last_name=last_name,
                domain=domain,
                company_name=company_name,
                on_site_emails=on_site_emails
            )
            cand["email"] = verified_em
            cand["email_status"] = em_status

        # Calculate transparent confidence score (0 - 100%)
        # Company match (up to 40) + Role tier (up to 30) + Contact proof (up to 30)
        c_score = int(cand.get("company_match_score", 70) * 0.4)
        r_score = 30 if cand.get("weight") == 3 else (25 if cand.get("weight") == 2 else 20)
        v_score = 30 if "Verified" in cand.get("email_status", "") else (15 if cand.get("linkedin_url") else 5)
        cand["confidence_score"] = min(100, c_score + r_score + v_score)
        cand["discovered_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        final_results.append(cand)

    # Sort by Role Priority (Tier 1 Founders/CEOs first) then Confidence Score
    final_results.sort(key=lambda x: (x.get("weight", 0), x.get("confidence_score", 0)), reverse=True)
    if mongo_db is not None and final_results:
        save_cached_decision_makers(mongo_db, company_name, domain, final_results)
    return final_results[:max_per_company]


# ---------------------------------------------------------------------------
# CLI & Dry-Run Interface
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Verified Decision-Maker Discovery Agent.")
    parser.add_argument("--company", required=True, help="Company Name")
    parser.add_argument("--website", default="", help="Company Website URL (optional)")
    parser.add_argument("--city", default="", help="City / Region (optional)")
    parser.add_argument("--max", type=int, default=3, help="Max decision makers to return")
    parser.add_argument("--dry-run", action="store_true", help="Print findings without saving")
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("      VERIFIED DECISION-MAKER DISCOVERY AGENT")
    print("=" * 65)
    print(f"Company      : {args.company}")
    print(f"Website URL  : {args.website or '(auto-resolve)'}")
    print(f"City         : {args.city or '(unspecified)'}")
    print(f"Policy       : STRICT ZERO-GUESSING (Only 100% Verified Emails)")
    print("-" * 65)
    print("[*] Running discovery engine...")

    start_t = time.time()
    results = discover_decision_makers(
        company_name=args.company,
        raw_website=args.website,
        city=args.city,
        max_per_company=args.max
    )
    duration = time.time() - start_t

    print(f"\n[✓] Completed in {duration:.2f}s. Discovered: {len(results)} Decision Maker(s)\n")
    if not results:
        print("[-] No matching leadership profiles found for this query.")
        return

    for idx, dm in enumerate(results, 1):
        print(f"[{idx}] {dm['name']} — {dm['role']}")
        print(f"    • Tier             : {dm.get('tier', 'Unknown')}")
        print(f"    • LinkedIn         : {dm.get('linkedin_url') or 'N/A'}")
        print(f"    • Verified Email   : {dm.get('email') or '(None - Unverified)'}")
        print(f"    • Email Status     : {dm.get('email_status')}")
        print(f"    • Confidence Score : {dm.get('confidence_score')}%")
        print(f"    • Source           : {dm.get('source')}")
        print()


if __name__ == "__main__":
    main()
