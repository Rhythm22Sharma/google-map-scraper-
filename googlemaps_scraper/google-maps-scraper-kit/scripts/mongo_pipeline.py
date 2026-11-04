#!/usr/bin/env python3
"""MongoDB storage and pipeline module for Google Maps Scraper leads."""

import csv
import datetime
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

try:
    import pymongo
    from pymongo import UpdateOne
    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False


def get_default_env() -> Dict[str, str]:
    """Load config strictly from .env file or environment variables."""
    config = {
        "MONGO_URI": os.environ.get("MONGO_URI", ""),
        "MONGO_DB": os.environ.get("MONGO_DB", "scraper"),
        "SCRAPER_PORT": os.environ.get("SCRAPER_PORT", "8085"),
        "SCRAPER_BASE_URL": os.environ.get("SCRAPER_BASE_URL", ""),
    }
    env_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("\"'")
                            if k in config and k not in os.environ:
                                config[k] = v
            except Exception:
                pass
            break
    if not config.get("SCRAPER_BASE_URL"):
        port = config.get("SCRAPER_PORT", "8085")
        config["SCRAPER_BASE_URL"] = f"http://localhost:{port}"
    return config


def check_mongo_connection(uri: Optional[str] = None) -> Tuple[bool, str]:
    """Test connection to MongoDB server."""
    if not HAS_PYMONGO:
        return False, "pymongo package is not installed. Run: pip install pymongo"
    mongo_uri = uri or get_default_env()["MONGO_URI"]
    if not mongo_uri:
        return False, "MONGO_URI is not configured. Please set MONGO_URI in your .env file."
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, tlsAllowInvalidCertificates=True)
        info = client.server_info()
        version = info.get("version", "Atlas")
        client.close()
        return True, f"Connected to MongoDB Atlas v{version}"
    except Exception as e:
        return False, f"Could not connect to MongoDB: {e}"


def get_mongo_db(uri: Optional[str] = None, db_name: Optional[str] = None):
    """Get MongoDB database instance."""
    if not HAS_PYMONGO:
        raise RuntimeError("pymongo is required. Install with: pip install pymongo")
    cfg = get_default_env()
    mongo_uri = uri or cfg["MONGO_URI"]
    if not mongo_uri:
        raise ValueError("MONGO_URI is not configured. Please set MONGO_URI in your .env file.")
    target_db = db_name or cfg["MONGO_DB"]
    client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=10000, tlsAllowInvalidCertificates=True)
    return client[target_db]


def normalize_phone_digits(phone: str) -> str:
    """Normalize phone number by stripping formatting and keeping relevant digits."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    # If 11 digits starting with 1 (US country code), strip leading 1
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalize_domain(url: str) -> str:
    """Extract and normalize website domain (stripping protocol, www, paths)."""
    if not url:
        return ""
    clean = str(url).strip().lower()
    if not clean.startswith(("http://", "https://")):
        clean = "http://" + clean
    try:
        parsed = urllib.parse.urlparse(clean)
        domain = parsed.netloc or parsed.path
        domain = re.sub(r"^www\.", "", domain)
        domain = domain.split(":")[0].strip()
        # Exclude common social / generic sites from domain-based fingerprinting
        generic_domains = {
            "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
            "x.com", "youtube.com", "google.com", "maps.google.com", "yelp.com"
        }
        if domain in generic_domains:
            return ""
        return domain
    except Exception:
        return ""


def normalize_title(title: str) -> str:
    """Normalize business title for fuzzy comparison (strip punctuation, common legal entity suffixes)."""
    if not title:
        return ""
    t = str(title).lower().strip()
    # Strip common legal suffixes
    t = re.sub(r"\b(llc|inc|corp|ltd|co|limited|incorporated|company|pvt)\b", "", t)
    # Strip punctuation and multiple spaces
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def compute_lead_fingerprint(lead: Dict[str, Any], project_name: str = "") -> str:
    """Compute a deterministic, multi-tiered fingerprint for a lead to guarantee deduplication.
    
    Tiers:
    1. Immutable Google Place Identifier (data_id, cid, place_id, or google_id)
    2. Normalized Title + Normalized Phone (last 10 digits)
    3. Normalized Title + Normalized Domain
    4. Normalized Title + Normalized Address/City
    5. Clean Normalized Title
    """
    # Tier 1: Google Place Unique ID (100% collision-free)
    for key in ("data_id", "cid", "place_id", "google_id"):
        val = str(lead.get(key, "")).strip()
        if val:
            return f"gmap:{val}"

    norm_title = normalize_title(lead.get("title") or lead.get("name") or "")

    # Tier 2: Phone number + Title
    raw_phone = lead.get("phone") or ""
    phone_digits = normalize_phone_digits(raw_phone)
    if len(phone_digits) >= 7 and norm_title:
        # Use last 10 digits to match across local vs international format variations
        match_digits = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
        return f"phone:{norm_title}:{match_digits}"

    # Tier 3: Website domain + Title
    raw_web = lead.get("website") or lead.get("site") or lead.get("link") or ""
    domain = normalize_domain(raw_web)
    if domain and norm_title:
        return f"web:{norm_title}:{domain}"

    # Tier 4: Location / Address + Title
    loc = lead.get("address") or lead.get("search_city") or lead.get("city") or ""
    loc_clean = re.sub(r"[^\w\s]", " ", str(loc).lower()).strip()
    loc_clean = re.sub(r"\s+", " ", loc_clean)
    if norm_title and loc_clean:
        return f"loc:{norm_title}:{loc_clean[:30]}"

    # Tier 5: Title only fallback
    if norm_title:
        return f"title:{norm_title}"

    # Last resort fallback: raw string hash
    raw_str = f"{lead.get('title', '')}-{lead.get('phone', '')}-{lead.get('website', '')}"
    return f"raw:{hash(raw_str)}"


def normalize_lead_document(
    raw: Dict[str, Any],
    project_name: str,
    query: str = "",
    city: str = "",
) -> Dict[str, Any]:
    """Turn a raw scraped lead or CSV row into a clean MongoDB lead document.
    
    Contains:
    - project_name (from user input)
    - lead_fingerprint (deterministic deduplication key)
    - matched_keywords / matched_cities (tracking multiple search intents)
    - All fields from the scrape / CSV download
    """
    clean_project = str(project_name).strip() if project_name else "General Scrapes"
    doc: Dict[str, Any] = {
        "project_name": clean_project,
    }

    # Copy all fields from the scrape / CSV download
    for k, v in raw.items():
        if k in ("_id", "project_name"):
            continue
        if v is None:
            doc[k] = ""
        elif isinstance(v, (int, float, bool, list, dict)):
            doc[k] = v
        else:
            val_str = str(v).strip()
            # If review_rating or review_count or numeric fields can be parsed, do so
            if k in ("review_rating", "rating", "latitude", "longitude"):
                try:
                    doc[k] = float(val_str) if val_str else ""
                except ValueError:
                    doc[k] = val_str
            elif k in ("review_count", "reviews", "photos_count"):
                try:
                    doc[k] = int(val_str) if val_str else ""
                except ValueError:
                    doc[k] = val_str
            else:
                doc[k] = val_str

    # Guarantee project_name is always set to the user-specified project_name
    doc["project_name"] = clean_project

    # Scraped timestamp (record exact time when data is scraped)
    if not doc.get("scraped_at"):
        doc["scraped_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Guarantee title and name fields are synchronized
    title = (doc.get("title") or doc.get("name") or "").strip()
    if title:
        doc["title"] = title
        if not doc.get("name"):
            doc["name"] = title

    # Compute deterministic deduplication fingerprint
    fp = compute_lead_fingerprint(doc, clean_project)
    doc["lead_fingerprint"] = fp

    # Intent tracking
    kw = query or doc.get("search_keyword", "")
    ct = city or doc.get("search_city", "")
    if kw:
        doc["matched_keywords"] = [kw.strip()]
    if ct:
        doc["matched_cities"] = [ct.strip()]

    return doc


def save_leads_to_mongo(
    leads: List[Dict[str, Any]],
    project_name: str,
    db_name: Optional[str] = None,
    collection_name: str = "leads",
    query: str = "",
    city: str = "",
    job_id: str = "",
    uri: Optional[str] = None,
    update_project_meta: bool = True,
) -> Dict[str, Any]:
    """Upsert leads into MongoDB with exact CSV fields + project_name and guaranteed deduplication."""
    if not HAS_PYMONGO:
        raise RuntimeError("pymongo is not installed.")

    clean_project = str(project_name).strip() if project_name else "General Scrapes"
    db = get_mongo_db(uri, db_name)
    coll = db[collection_name]

    # Compound index on project_name and lead_fingerprint ensuring zero duplicate leads per project
    try:
        coll.create_index([("project_name", 1), ("lead_fingerprint", 1)], unique=True, background=True)
        coll.create_index([("project_name", 1), ("title", 1)], background=True)
        coll.create_index([("project_name", 1)], background=True)
    except Exception:
        pass

    now = datetime.datetime.now(datetime.timezone.utc)
    ops = []
    saved_docs = []

    for item in leads:
        doc = normalize_lead_document(item, clean_project, query=query, city=city)
        title = doc.get("title", "").strip() or doc.get("name", "").strip()
        if not title:
            continue
        saved_docs.append(doc)
        fp = doc["lead_fingerprint"]

        # Filter strictly by project_name + lead_fingerprint
        filter_q: Dict[str, Any] = {
            "project_name": clean_project,
            "lead_fingerprint": fp,
        }

        # Build $set update: only overwrite if new value is non-empty, preserving existing enriched data
        set_fields: Dict[str, Any] = {
            "last_updated_at": now,
            "project_name": clean_project,
            "lead_fingerprint": fp,
        }
        for k, v in doc.items():
            if k in ("_id", "created_at", "matched_keywords", "matched_cities"):
                continue
            # If value is non-empty, update it
            if v not in (None, ""):
                set_fields[k] = v

        update_doc: Dict[str, Any] = {
            "$set": set_fields,
            "$setOnInsert": {"created_at": now},
        }

        # Multi-intent tracking: merge matching keywords and cities into array set without duplicates
        add_to_set: Dict[str, Any] = {}
        if query:
            add_to_set["matched_keywords"] = query.strip()
        if city:
            add_to_set["matched_cities"] = city.strip()
        if add_to_set:
            update_doc["$addToSet"] = add_to_set

        ops.append(UpdateOne(filter_q, update_doc, upsert=True))

    inserted_count = 0
    updated_count = 0

    if ops:
        result = coll.bulk_write(ops, ordered=False)
        inserted_count = result.upserted_count
        updated_count = result.modified_count

    # Update project tracking collection if enabled
    total_for_project = 0
    if update_project_meta:
        try:
            projects_coll = db["projects"]
            projects_coll.create_index([("project_name", 1)], unique=True, background=True)
            total_for_project = coll.count_documents({"project_name": project_name.strip()})
            run_record = {
                "job_id": job_id,
                "query": query,
                "city": city,
                "total_scraped": len(saved_docs),
                "new_inserted": inserted_count,
                "updated": updated_count,
                "timestamp": now,
            }
            projects_coll.update_one(
                {"project_name": project_name.strip()},
                {
                    "$set": {
                        "last_scraped_at": now,
                        "total_leads": total_for_project,
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "created_at": now,
                    },
                    "$push": {
                        "runs": {
                            "$each": [run_record],
                            "$slice": -50  # keep last 50 runs
                        }
                    }
                },
                upsert=True
            )
        except Exception as e:
            print(f"  (Notice: project tracking update skipped: {e})", file=sys.stderr)

    return {
        "db": db.name,
        "collection": collection_name,
        "total_scraped": len(saved_docs),
        "inserted": inserted_count,
        "updated": updated_count,
        "total_in_project": total_for_project or len(saved_docs),
    }


def save_leads_batch_to_mongo(
    leads: List[Dict[str, Any]],
    project_name: str,
    db_name: Optional[str] = None,
    collection_name: str = "leads",
    query: str = "",
    city: str = "",
    job_id: str = "",
    uri: Optional[str] = None,
) -> Dict[str, Any]:
    """Lightweight micro-batch upsert for real-time streaming without full project recounting on every batch."""
    return save_leads_to_mongo(
        leads=leads,
        project_name=project_name,
        db_name=db_name,
        collection_name=collection_name,
        query=query,
        city=city,
        job_id=job_id,
        uri=uri,
        update_project_meta=False,
    )


def update_project_metadata(
    project_name: str,
    db_name: Optional[str] = None,
    collection_name: str = "leads",
    query: str = "",
    city: str = "",
    job_id: str = "",
    total_scraped: int = 0,
    new_inserted: int = 0,
    updated: int = 0,
    uri: Optional[str] = None,
) -> int:
    """Update project document metadata and run record once per query/job completion."""
    if not HAS_PYMONGO:
        return 0
    clean_project = str(project_name).strip() if project_name else "General Scrapes"
    try:
        db = get_mongo_db(uri, db_name)
        coll = db[collection_name]
        projects_coll = db["projects"]
        projects_coll.create_index([("project_name", 1)], unique=True, background=True)
        total_for_project = coll.count_documents({"project_name": clean_project})
        now = datetime.datetime.now(datetime.timezone.utc)
        run_record = {
            "job_id": job_id,
            "query": query,
            "city": city,
            "total_scraped": total_scraped,
            "new_inserted": new_inserted,
            "updated": updated,
            "timestamp": now,
        }
        projects_coll.update_one(
            {"project_name": clean_project},
            {
                "$set": {
                    "last_scraped_at": now,
                    "total_leads": total_for_project,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
                "$push": {
                    "runs": {
                        "$each": [run_record],
                        "$slice": -50
                    }
                }
            },
            upsert=True
        )
        return total_for_project
    except Exception as e:
        print(f"  (Notice: update_project_metadata failed: {e})", file=sys.stderr)
        return 0


def import_csv_to_mongo(
    csv_file: str,
    project_name: str,
    db_name: Optional[str] = None,
    collection_name: str = "leads",
    uri: Optional[str] = None
) -> Dict[str, Any]:
    """Import an existing CSV file into MongoDB under the given project name."""
    if not os.path.exists(csv_file):
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    rows = []
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    query_hint = os.path.splitext(os.path.basename(csv_file))[0].replace("_", " ")
    return save_leads_to_mongo(
        leads=rows,
        project_name=project_name,
        db_name=db_name,
        collection_name=collection_name,
        query=query_hint,
        city="",
        job_id=f"csv-import-{os.path.basename(csv_file)}",
        uri=uri
    )


def list_mongo_projects(db_name: Optional[str] = None, uri: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all projects currently stored in MongoDB."""
    db = get_mongo_db(uri, db_name)
    coll = db["leads"]
    pipeline = [
        {"$group": {
            "_id": "$project_name",
            "lead_count": {"$sum": 1},
            "last_updated": {"$max": "$created_at"},
            "categories": {"$addToSet": "$category"},
            "has_emails": {"$sum": {"$cond": [
                {"$and": [{"$ne": ["$emails", ""]}, {"$ne": ["$emails", None]}]}, 1, 0
            ]}},
            "has_phone": {"$sum": {"$cond": [
                {"$and": [{"$ne": ["$phone", ""]}, {"$ne": ["$phone", None]}]}, 1, 0
            ]}},
            "has_socials": {"$sum": {"$cond": [
                {"$or": [
                    {"$and": [{"$ne": ["$instagram", ""]}, {"$ne": ["$instagram", None]}]},
                    {"$and": [{"$ne": ["$facebook", ""]}, {"$ne": ["$facebook", None]}]},
                    {"$and": [{"$ne": ["$linkedin", ""]}, {"$ne": ["$linkedin", None]}]}
                ]}, 1, 0
            ]}},
        }},
        {"$sort": {"last_updated": -1}}
    ]
    results = list(coll.aggregate(pipeline))
    out = []
    for r in results:
        cats = [c for c in r.get("categories", []) if c]
        out.append({
            "project_name": r["_id"],
            "lead_count": r["lead_count"],
            "last_updated": r.get("last_updated"),
            "categories": cats[:5],
            "has_emails": r.get("has_emails", 0),
            "has_phone": r.get("has_phone", 0),
            "has_socials": r.get("has_socials", 0),
        })
    return out
