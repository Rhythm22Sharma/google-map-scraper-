#!/usr/bin/env python3
"""Web application backend server for Google Maps Lead Scraper & MongoDB Pipeline.

Serves the modern HTML/CSS/JS frontend on port 5050 and exposes REST APIs for:
- System health (MongoDB Atlas connection, Scraper Engine API)
- Real-time scraping jobs with live progress streaming
- MongoDB Project & Lead management, search, and filtering
- CSV imports and exports
"""

import asyncio
import csv
import datetime
import http.server
import io
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set

try:
    import websockets
except ImportError:
    websockets = None

# Setup path imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(BASE_DIR, "googlemaps_scraper", "google-maps-scraper-kit")
SCRIPTS_DIR = os.path.join(KIT_DIR, "scripts")

for p in [KIT_DIR, SCRIPTS_DIR, BASE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts import mongo_pipeline, scrape, people_agent
except ImportError:
    try:
        import mongo_pipeline  # type: ignore
        import scrape  # type: ignore
        import people_agent  # type: ignore
    except ImportError:
        mongo_pipeline = None  # type: ignore
        scrape = None  # type: ignore
        people_agent = None  # type: ignore

PORT = 5050
WS_PORT = 5051
WEB_DIR = os.path.join(BASE_DIR, "web")

# In-memory tracking for active scraping jobs
ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}
ACTIVE_JOBS_LOCK = threading.Lock()

# WebSocket client tracking
WS_CLIENTS: Dict[str, Set[Any]] = {}
WS_GLOBAL_CLIENTS: Set[Any] = set()
WS_CLIENTS_LOCK = threading.Lock()
ws_event_loop: Optional[asyncio.AbstractEventLoop] = None


def ws_broadcast(job_id: Optional[str], message: dict):
    """Push a JSON message to WebSocket clients. If job_id is None, broadcast to all clients."""
    if not ws_event_loop or not ws_event_loop.is_running():
        return
    targets = set()
    with WS_CLIENTS_LOCK:
        if job_id and job_id in WS_CLIENTS:
            targets.update(WS_CLIENTS[job_id])
        targets.update(WS_GLOBAL_CLIENTS)
    if not targets:
        return
    payload = json.dumps(message, default=str)
    for ws in list(targets):
        try:
            asyncio.run_coroutine_threadsafe(ws.send(payload), ws_event_loop)
        except Exception:
            pass


def broadcast_job_progress(job_id: str):
    """Push latest job status and progress snapshot to WebSocket clients."""
    with ACTIVE_JOBS_LOCK:
        job = ACTIVE_JOBS.get(job_id)
        if not job:
            return
        msg = {
            "type": "progress",
            "job_id": job_id,
            "status": job.get("status", "running"),
            "step": job.get("step", ""),
            "progress": job.get("progress", 0),
            "current_query_label": job.get("current_query_label", ""),
            "current_query_index": job.get("current_query_index", 1),
            "total_queries": job.get("total_queries", 1),
            "cumulative_leads": job.get("cumulative_leads", 0),
            "completed_queries": job.get("completed_queries", []),
            "results_summary": job.get("results_summary"),
        }
    ws_broadcast(job_id, msg)


def log_job(job_id: str, message: str, level: str = "info"):
    """Append a log entry to a job's live feed and broadcast via WebSocket."""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    with ACTIVE_JOBS_LOCK:
        if job_id in ACTIVE_JOBS:
            ACTIVE_JOBS[job_id]["logs"].append({
                "time": timestamp,
                "msg": message,
                "level": level
            })
            ACTIVE_JOBS[job_id]["last_msg"] = message

    ws_broadcast(job_id, {
        "type": "log",
        "job_id": job_id,
        "time": timestamp,
        "msg": message,
        "level": level,
    })


async def ws_handler(websocket):
    """Handle incoming WebSocket connections from frontend for real-time streaming."""
    subscribed_job = None
    with WS_CLIENTS_LOCK:
        WS_GLOBAL_CLIENTS.add(websocket)
    try:
        await websocket.send(json.dumps({"type": "connected", "msg": "WebSocket server ready", "port": WS_PORT}))
        async for raw_msg in websocket:
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue
            action = data.get("action")
            if action == "subscribe":
                job_id = data.get("job_id")
                if job_id:
                    subscribed_job = job_id
                    with WS_CLIENTS_LOCK:
                        WS_CLIENTS.setdefault(job_id, set()).add(websocket)
                    # Push immediate snapshot
                    broadcast_job_progress(job_id)
            elif action == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            elif action == "skip_query":
                job_id = data.get("job_id") or subscribed_job
                if job_id:
                    with ACTIVE_JOBS_LOCK:
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]["skip_query_requested"] = True
                            log_job(job_id, "Skip query requested via WebSocket.", level="warn")
            elif action == "stop_scrape":
                job_id = data.get("job_id") or subscribed_job
                if job_id:
                    with ACTIVE_JOBS_LOCK:
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]["cancel_requested"] = True
                            log_job(job_id, "Cancellation requested via WebSocket.", level="warn")
    except Exception:
        pass
    finally:
        with WS_CLIENTS_LOCK:
            WS_GLOBAL_CLIENTS.discard(websocket)
            if subscribed_job and subscribed_job in WS_CLIENTS:
                WS_CLIENTS[subscribed_job].discard(websocket)
                if not WS_CLIENTS[subscribed_job]:
                    del WS_CLIENTS[subscribed_job]


def parse_items_list(val) -> List[str]:
    """Parse a multiline or comma-separated string or list into clean distinct items."""
    if not val:
        return []
    if isinstance(val, list):
        items = []
        for x in val:
            items.extend(parse_items_list(x))
        return items
    lines = str(val).splitlines()
    out = []
    for line in lines:
        parts = [p.strip() for p in line.split(",") if p.strip()]
        out.extend(parts)
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for item in out:
        if item.lower() not in seen:
            seen.add(item.lower())
            deduped.append(item)
    return deduped


def merge_lead_records(existing: Dict[str, Any], new_lead: Dict[str, Any]) -> Dict[str, Any]:
    """Intelligently merge an existing lead with newly scraped data across overlapping queries.
    
    Preserves existing enriched data (emails, socials) if the new record is blank,
    while unioning matched_keywords and matched_cities.
    """
    # Merge keywords
    ex_kws = existing.get("matched_keywords") or []
    if isinstance(ex_kws, str):
        ex_kws = [k.strip() for k in ex_kws.split(",") if k.strip()]
    elif isinstance(ex_kws, (list, tuple, set)):
        ex_kws = list(ex_kws)
    else:
        ex_kws = []

    new_kw = (new_lead.get("search_keyword") or "").strip()
    if new_kw and new_kw not in ex_kws:
        ex_kws.append(new_kw)
    existing["matched_keywords"] = ex_kws
    existing["search_keyword"] = ", ".join(ex_kws)

    # Merge cities
    ex_cities = existing.get("matched_cities") or []
    if isinstance(ex_cities, str):
        ex_cities = [c.strip() for c in ex_cities.split(",") if c.strip()]
    elif isinstance(ex_cities, (list, tuple, set)):
        ex_cities = list(ex_cities)
    else:
        ex_cities = []

    new_city = (new_lead.get("search_city") or "").strip()
    if new_city and new_city not in ex_cities:
        ex_cities.append(new_city)
    existing["matched_cities"] = ex_cities
    existing["search_city"] = ", ".join(ex_cities)

    # Merge all other attributes (update if new lead has non-empty values)
    for k, v in new_lead.items():
        if k in ("matched_keywords", "matched_cities", "search_keyword", "search_city"):
            continue
        if k == "decision_makers":
            ex_dms = existing.get("decision_makers") or []
            if not isinstance(ex_dms, list):
                ex_dms = []
            seen_urls = {dm.get("linkedin_url") for dm in ex_dms if dm.get("linkedin_url")}
            seen_names = {dm.get("name", "").lower() for dm in ex_dms if dm.get("name")}
            for ndm in (v if isinstance(v, list) else []):
                u = ndm.get("linkedin_url")
                nm = ndm.get("name", "").lower()
                if (u and u in seen_urls) or (nm and nm in seen_names):
                    continue
                ex_dms.append(ndm)
                if u:
                    seen_urls.add(u)
                if nm:
                    seen_names.add(nm)
            existing["decision_makers"] = ex_dms
            existing["decision_makers_count"] = len(ex_dms)
            continue
        if v not in (None, ""):
            existing[k] = v

    return existing


def run_scrape_worker(
    job_key: str,
    project_name: str,
    keywords: List[str],
    cities: List[str],
    depth: int,
    fast_mode: bool,
    extract_emails: bool,
    extract_socials: bool,
    extract_summary: bool,
    extract_people: bool,
    db_name: str,
    collection_name: str,
    save_csv: bool,
):
    """Worker thread that runs batch scraping across multiple keywords and locations."""
    clean_kws = [k for k in keywords if k]
    if not clean_kws:
        clean_kws = ["recruitment agency"]

    clean_cities = [c for c in cities if c]
    if not clean_cities:
        clean_cities = [""]  # empty string means search keyword globally

    # Generate all (keyword, city) query combinations
    tasks = [(kw, city) for kw in clean_kws for city in clean_cities]
    total_tasks = len(tasks)

    with ACTIVE_JOBS_LOCK:
        job = ACTIVE_JOBS[job_key]
        job["status"] = "running"
        job["step"] = f"Starting queue: {total_tasks} queries"
        job["progress"] = 5
        job["total_queries"] = total_tasks
        job["current_query_index"] = 0
        job["cumulative_leads"] = 0
        job["completed_queries"] = []

    broadcast_job_progress(job_key)

    env_cfg = mongo_pipeline.get_default_env() if mongo_pipeline else {}
    base_url = env_cfg.get("SCRAPER_BASE_URL", "http://localhost:8085")

    cumulative_dict: Dict[str, Dict[str, Any]] = {}
    total_inserted = 0
    total_updated = 0
    completed_queries = []
    clean_proj = re.sub(r"[^a-zA-Z0-9_]", "_", project_name.lower()).strip("_")
    master_csv_name = f"{clean_proj}_master_leads.csv"
    master_csv_path = os.path.join(KIT_DIR, master_csv_name)

    # Pre-populate cumulative_dict from existing project CSV if present
    if os.path.exists(master_csv_path):
        try:
            with open(master_csv_path, "r", encoding="utf-8-sig") as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    row_dict = dict(row)
                    fp = row_dict.get("lead_fingerprint")
                    if not fp and mongo_pipeline:
                        fp = mongo_pipeline.compute_lead_fingerprint(row_dict, project_name)
                    if not fp:
                        fp = f"csv_row:{len(cumulative_dict)}"
                    row_dict["lead_fingerprint"] = fp
                    cumulative_dict[fp] = row_dict
        except Exception:
            pass

    log_job(job_key, f"🚀 Initialized batch scrape for project '{project_name}'.")
    log_job(job_key, f"Queue contains {len(clean_kws)} keyword(s) × {len(clean_cities)} location(s) = {total_tasks} query job(s).")
    if fast_mode:
        log_job(job_key, "⚡ Fast Mode is ACTIVE: Scraper will automatically stop when page listings finish and move to the next query.")

    try:
        for idx, (kw, city) in enumerate(tasks):
            with ACTIVE_JOBS_LOCK:
                if job.get("cancel_requested"):
                    log_job(job_key, "User stopped the scraper pipeline.", level="warn")
                    break
                job["skip_query_requested"] = False
                job["current_query_index"] = idx + 1
                job["current_query_kw"] = kw
                job["current_query_city"] = city
                query_label = f"'{kw}' in '{city}'" if city else f"'{kw}'"
                job["current_query_label"] = query_label
                job["step"] = f"[{idx + 1}/{total_tasks}] Geocoding {city or kw}"
                base_pct = int((idx / total_tasks) * 100)
                job["progress"] = max(5, base_pct)

            broadcast_job_progress(job_key)
            log_job(job_key, f"")
            log_job(job_key, f"══════ [Query {idx + 1}/{total_tasks}] {query_label} ══════")

            # 1. Geocode
            query_baked = f"{kw} in {city}" if city and city.lower() not in kw.lower() else kw
            geocode_target = city or kw
            log_job(job_key, f"Resolving coordinates for '{geocode_target}'...")

            lat, lon = None, None
            try:
                q = urllib.parse.urlencode({"format": "json", "limit": 1, "q": geocode_target})
                url = f"https://nominatim.openstreetmap.org/search?{q}"
                req_geo = urllib.request.Request(url, headers={"User-Agent": "google-maps-scraper-kit/1.0"})
                with urllib.request.urlopen(req_geo, timeout=20) as resp:
                    hits = json.loads(resp.read())
                if hits:
                    lat, lon = str(hits[0]["lat"]), str(hits[0]["lon"])
            except Exception as e:
                log_job(job_key, f"Geocoding note: {e}", level="warn")

            if not (lat and lon):
                lat, lon = "40.7128", "-74.0060"
                log_job(job_key, f"Defaulted coordinates to {lat}, {lon}")
            else:
                log_job(job_key, f"Resolved coordinates: {lat}, {lon}")

            with ACTIVE_JOBS_LOCK:
                if job.get("cancel_requested"):
                    break
                if job.get("skip_query_requested"):
                    log_job(job_key, f"Skipped query {idx + 1}.", level="warn")
                    continue
                job["step"] = f"[{idx + 1}/{total_tasks}] Launching search on Google Maps"

            broadcast_job_progress(job_key)

            # 2. Submit to Scraper Engine
            headers = {"Content-Type": "application/json", "User-Agent": "google-maps-scraper-kit/1.0"}
            engine_payload = {
                "name": f"batch-{int(time.time())}-{idx + 1}",
                "keywords": [query_baked],
                "lang": "en",
                "zoom": 15,
                "lat": str(lat),
                "lon": str(lon),
                "fast_mode": fast_mode,
                "radius": 10000,
                "depth": depth,
                "email": False,  # Keep False on Docker engine to avoid 30s Playwright timeouts; Python enriches fast!
                "max_time": 180,  # Max 3 minutes per query
            }

            try:
                post_req = urllib.request.Request(f"{base_url}/api/v1/jobs", data=json.dumps(engine_payload).encode(), headers=headers, method="POST")
                with urllib.request.urlopen(post_req, timeout=30) as resp:
                    create_res = json.loads(resp.read().decode())
            except Exception as e:
                log_job(job_key, f"Could not submit to Scraper Engine ({e}). Skipping query...", level="warn")
                continue

            engine_job_id = create_res.get("id")
            if not engine_job_id:
                log_job(job_key, "Engine did not return job ID. Skipping query...", level="warn")
                continue

            with ACTIVE_JOBS_LOCK:
                job["engine_job_id"] = engine_job_id
                job["step"] = f"[{idx + 1}/{total_tasks}] Google Maps extraction in progress"

            broadcast_job_progress(job_key)

            # 3. Poll Scraper Engine
            engine_status = None
            max_polls = 60  # 60 * 3s = 180 seconds max
            query_skipped = False

            for poll_idx in range(max_polls):
                with ACTIVE_JOBS_LOCK:
                    if job.get("cancel_requested"):
                        log_job(job_key, "Cancellation requested during scrape.", level="warn")
                        break
                    if job.get("skip_query_requested"):
                        log_job(job_key, f"User skipped query '{query_label}'.", level="warn")
                        query_skipped = True
                        break

                try:
                    poll_req = urllib.request.Request(f"{base_url}/api/v1/jobs/{engine_job_id}", headers=headers)
                    with urllib.request.urlopen(poll_req, timeout=15) as resp:
                        status_res = json.loads(resp.read().decode())
                        engine_status = status_res.get("Status")
                except Exception as e:
                    engine_status = f"retry ({e})"

                task_progress = base_pct + int((poll_idx / max_polls) * (100 / total_tasks))
                with ACTIVE_JOBS_LOCK:
                    job["progress"] = min(98, task_progress)

                broadcast_job_progress(job_key)

                if engine_status == "ok":
                    log_job(job_key, f"Google Maps finished extraction for {query_label}.")
                    break
                elif engine_status == "failed":
                    log_job(job_key, f"Scraper job reported failure on engine for {query_label}.", level="warn")
                    break

                if poll_idx % 4 == 0:
                    log_job(job_key, f"Extracting Google Maps... status: '{engine_status}' (poll {poll_idx + 1})")
                time.sleep(3)
            else:
                log_job(job_key, f"Query {idx + 1} reached time limit (180s). Extracting collected leads...", level="warn")

            if query_skipped:
                continue

            with ACTIVE_JOBS_LOCK:
                if job.get("cancel_requested"):
                    break
                job["step"] = f"[{idx + 1}/{total_tasks}] Downloading leads"

            broadcast_job_progress(job_key)

            # 4. Download Scraped Data
            rows = []
            try:
                dl_req = urllib.request.Request(f"{base_url}/api/v1/jobs/{engine_job_id}/download", headers=headers)
                with urllib.request.urlopen(dl_req, timeout=40) as resp:
                    csv_raw = resp.read().decode("utf-8", "replace")
                rows = list(csv.DictReader(io.StringIO(csv_raw)))
            except Exception as e:
                log_job(job_key, f"Could not download leads: {e}", level="warn")
                rows = []

            log_job(job_key, f"Found {len(rows)} lead(s) on Google Maps for {query_label}.")

            # 5. Enrich & Preserve All Fields
            scraped_time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            query_leads = []
            for r in rows:
                lead = dict(r)
                lead["project_name"] = project_name.strip()
                lead["scraped_at"] = scraped_time_str
                lead["search_keyword"] = kw
                lead["search_city"] = city
                if not lead.get("title") and lead.get("name"):
                    lead["title"] = lead.get("name")
                if extract_summary:
                    g_desc = (r.get("descriptions") or "").strip()
                    g_about = (r.get("about") or "").strip()
                    if not lead.get("summary"):
                        lead["summary"] = g_desc or g_about
                query_leads.append(lead)

            # Concurrent Python enrichment for emails, summaries, and social media
            if query_leads and (extract_emails or extract_socials or extract_summary) and scrape:
                with ACTIVE_JOBS_LOCK:
                    job["step"] = f"[{idx + 1}/{total_tasks}] Enriching {len(query_leads)} website(s)"
                broadcast_job_progress(job_key)
                log_job(job_key, f"Enriching {len(query_leads)} business website(s) concurrently...")
                try:
                    scrape.enrich_websites(
                        query_leads,
                        extract_summary=extract_summary,
                        extract_socials=extract_socials,
                        extract_emails=extract_emails,
                        workers=10
                    )
                except Exception as e:
                    log_job(job_key, f"Enrichment note: {e}", level="warn")

            # Concurrent Decision-Maker Discovery (Founders, CEOs, HR Heads)
            if query_leads and extract_people and people_agent:
                with ACTIVE_JOBS_LOCK:
                    job["step"] = f"[{idx + 1}/{total_tasks}] Discovering Decision Makers for {len(query_leads)} company(ies)"
                broadcast_job_progress(job_key)
                log_job(job_key, f"🔎 Searching verified Founders, CEOs, and HR Directors for {len(query_leads)} company(ies)...")

                cache_db = None
                if mongo_pipeline and hasattr(mongo_pipeline, "get_mongo_db"):
                    try:
                        cache_db = mongo_pipeline.get_mongo_db(db_name=db_name)
                    except Exception:
                        pass

                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _enrich_person_task(lead_item):
                    c_name = lead_item.get("title") or lead_item.get("name") or ""
                    c_web = lead_item.get("website") or ""
                    c_city = lead_item.get("search_city") or city
                    if not c_name:
                        return
                    try:
                        dms = people_agent.discover_decision_makers(
                            company_name=c_name,
                            raw_website=c_web,
                            city=c_city,
                            max_per_company=3,
                            mongo_db=cache_db
                        )
                        if dms:
                            lead_item["decision_makers"] = dms
                            lead_item["decision_makers_count"] = len(dms)
                            for d_idx, dm in enumerate(dms[:3], 1):
                                lead_item[f"dm{d_idx}_name"] = dm.get("name", "")
                                lead_item[f"dm{d_idx}_role"] = dm.get("role", "")
                                lead_item[f"dm{d_idx}_tier"] = dm.get("tier", "")
                                lead_item[f"dm{d_idx}_linkedin"] = dm.get("linkedin_url", "")
                                lead_item[f"dm{d_idx}_email"] = dm.get("email", "")
                                lead_item[f"dm{d_idx}_email_status"] = dm.get("email_status", "")
                                lead_item[f"dm{d_idx}_confidence"] = f"{dm.get('confidence_score', '')}%"
                            dm_summary = ", ".join([f"{dm.get('name')} ({dm.get('role')})" for dm in dms])
                            log_job(job_key, f"🎯 Found leadership for {c_name}: {dm_summary}")
                    except Exception:
                        pass

                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(_enrich_person_task, l): l for l in query_leads}
                    for future in as_completed(futures):
                        try:
                            future.result(timeout=25.0)
                        except Exception:
                            pass

            # 6. Stream Leads in Micro-Batches of 5 to MongoDB Atlas & WebSocket
            BATCH_SIZE = 5
            query_new_count = 0
            query_merged_count = 0

            with ACTIVE_JOBS_LOCK:
                job["step"] = f"[{idx + 1}/{total_tasks}] Streaming leads (5/batch)"
            broadcast_job_progress(job_key)

            if not query_leads:
                log_job(job_key, f"No leads returned for {query_label}.")
            else:
                log_job(job_key, f"Streaming {len(query_leads)} leads in micro-batches of {BATCH_SIZE}...")

            for batch_start in range(0, len(query_leads), BATCH_SIZE):
                batch = query_leads[batch_start:batch_start + BATCH_SIZE]
                batch_new = []
                batch_merged = []

                # Deduplicate & multi-intent merge
                for lead in batch:
                    fp = mongo_pipeline.compute_lead_fingerprint(lead, project_name) if mongo_pipeline else (lead.get("title") or "")
                    lead["lead_fingerprint"] = fp
                    if fp in cumulative_dict:
                        cumulative_dict[fp] = merge_lead_records(cumulative_dict[fp], lead)
                        batch_merged.append(cumulative_dict[fp])
                        query_merged_count += 1
                    else:
                        lead["matched_keywords"] = [kw] if kw else []
                        lead["matched_cities"] = [city] if city else []
                        cumulative_dict[fp] = lead
                        batch_new.append(lead)
                        query_new_count += 1

                # Upsert micro-batch directly to MongoDB Atlas
                batch_inserted = 0
                batch_updated = 0
                if mongo_pipeline and batch:
                    try:
                        batch_fn = getattr(mongo_pipeline, "save_leads_batch_to_mongo", mongo_pipeline.save_leads_to_mongo)
                        save_stats = batch_fn(
                            leads=batch,
                            project_name=project_name,
                            db_name=db_name,
                            collection_name=collection_name,
                            query=query_baked,
                            city=city,
                            job_id=engine_job_id,
                        )
                        batch_inserted = save_stats.get("inserted", 0)
                        batch_updated = save_stats.get("updated", 0)
                        total_inserted += batch_inserted
                        total_updated += batch_updated
                    except Exception as e:
                        log_job(job_key, f"MongoDB batch sync warning: {e}", level="warn")

                with ACTIVE_JOBS_LOCK:
                    job["cumulative_leads"] = len(cumulative_dict)

                # Broadcast micro-batch to WebSocket subscribers immediately
                ws_broadcast(job_key, {
                    "type": "leads_batch",
                    "job_id": job_key,
                    "leads": batch,
                    "new_count": len(batch_new),
                    "merged_count": len(batch_merged),
                    "cumulative_unique": len(cumulative_dict),
                    "query_label": query_label,
                    "batch_range": f"{batch_start + 1}-{min(batch_start + len(batch), len(query_leads))}",
                    "total_in_query": len(query_leads),
                })

            cumulative_results = list(cumulative_dict.values())

            # Update MongoDB project metadata once per query
            if mongo_pipeline and hasattr(mongo_pipeline, "update_project_metadata") and query_leads:
                try:
                    mongo_pipeline.update_project_metadata(
                        project_name=project_name,
                        db_name=db_name,
                        collection_name=collection_name,
                        query=query_baked,
                        city=city,
                        job_id=engine_job_id,
                        total_scraped=len(query_leads),
                        new_inserted=query_new_count,
                        updated=query_merged_count,
                    )
                except Exception as e:
                    pass

            # 7. Write Deduplicated Leads to Master CSV
            if save_csv and cumulative_results:
                try:
                    fieldnames = ["project_name", "scraped_at", "lead_fingerprint", "search_keyword", "search_city", "matched_keywords", "matched_cities", "title", "phone", "emails", "website", "category", "address", "review_rating", "review_count", "instagram", "facebook", "linkedin", "summary"]
                    csv_rows = []
                    for item in cumulative_results:
                        row_copy = dict(item)
                        # Format lists into clean comma-delimited strings for CSV
                        if isinstance(row_copy.get("matched_keywords"), (list, set, tuple)):
                            row_copy["matched_keywords"] = ", ".join(row_copy["matched_keywords"])
                        if isinstance(row_copy.get("matched_cities"), (list, set, tuple)):
                            row_copy["matched_cities"] = ", ".join(row_copy["matched_cities"])
                        for k in row_copy.keys():
                            if k not in fieldnames:
                                fieldnames.append(k)
                        csv_rows.append(row_copy)

                    with open(master_csv_path, "w", newline="", encoding="utf-8-sig") as f:
                        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                        w.writeheader()
                        w.writerows(csv_rows)
                except Exception as e:
                    log_job(job_key, f"CSV backup note: {e}", level="warn")

            completed_queries.append({
                "keyword": kw,
                "city": city,
                "leads_count": len(query_leads),
                "new_unique": query_new_count,
                "merged": query_merged_count,
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
            })

            with ACTIVE_JOBS_LOCK:
                job["cumulative_leads"] = len(cumulative_results)
                job["completed_queries"] = completed_queries

            ws_broadcast(job_key, {
                "type": "query_complete",
                "job_id": job_key,
                "query_index": idx + 1,
                "total_queries": total_tasks,
                "query_info": completed_queries[-1],
                "cumulative_leads": len(cumulative_results),
            })

            log_job(job_key, f"✓ Query {idx + 1}/{total_tasks} finished! ({len(query_leads)} found: {query_new_count} new unique, {query_merged_count} merged duplicates | {len(cumulative_results)} total unique leads)", level="success")
            broadcast_job_progress(job_key)

        # Finished all queries or cancelled
        with ACTIVE_JOBS_LOCK:
            was_cancelled = job.get("cancel_requested", False)
            job["status"] = "cancelled" if was_cancelled else "completed"
            job["step"] = "Scraping complete" if not was_cancelled else "Stopped by user"
            job["progress"] = 100
            job["results_summary"] = {
                "total_scraped": len(cumulative_results),
                "inserted": total_inserted,
                "updated": total_updated,
                "total_in_project": len(cumulative_results),
                "completed_queries_count": len(completed_queries),
                "total_queries_planned": total_tasks,
                "csv_file": master_csv_name if save_csv and cumulative_results else None,
            }

        status_word = "Stopped" if was_cancelled else "Completed"
        log_job(job_key, f"🎉 Batch Pipeline {status_word}! Total: {len(cumulative_results)} leads collected across {len(completed_queries)}/{total_tasks} queries.", level="success")
        broadcast_job_progress(job_key)
        ws_broadcast(job_key, {
            "type": "job_complete",
            "job_id": job_key,
            "status": job["status"],
            "summary": job["results_summary"],
        })

    except Exception as e:
        with ACTIVE_JOBS_LOCK:
            job["status"] = "failed"
            job["step"] = f"Failed: {e}"
            job["error"] = str(e)
            job["progress"] = 100
        log_job(job_key, f"Pipeline Error: {e}", level="error")


class ScraperAppHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for serving frontend assets and REST APIs."""

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filepath: str, content_type: str):
        if not os.path.exists(filepath):
            self.send_error(404, "File Not Found")
            return
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Serve static assets
        if path == "/" or path == "/index.html":
            return self._serve_file(os.path.join(WEB_DIR, "index.html"), "text/html")
        elif path == "/style.css":
            return self._serve_file(os.path.join(WEB_DIR, "style.css"), "text/css")
        elif path == "/app.js":
            return self._serve_file(os.path.join(WEB_DIR, "app.js"), "application/javascript")

        # API: System status
        if path == "/api/status":
            mongo_ok = False
            mongo_msg = "Not checked"
            if mongo_pipeline:
                mongo_ok, mongo_msg = mongo_pipeline.check_mongo_connection()

            env_cfg = mongo_pipeline.get_default_env() if mongo_pipeline else {}
            base_url = env_cfg.get("SCRAPER_BASE_URL", "http://localhost:8085")
            scraper_ok = False
            try:
                req_chk = urllib.request.Request(f"{base_url}/api/v1/jobs", headers={"User-Agent": "google-maps-scraper-kit/1.0"})
                with urllib.request.urlopen(req_chk, timeout=2) as resp:
                    scraper_ok = resp.status in (200, 201)
            except Exception:
                scraper_ok = False

            return self._send_json({
                "mongo_connected": mongo_ok,
                "mongo_message": mongo_msg,
                "scraper_connected": scraper_ok,
                "scraper_url": base_url,
                "default_db": env_cfg.get("MONGO_DB", "scraper"),
            })

        # API: List all projects stored in MongoDB
        if path == "/api/projects":
            try:
                projects = mongo_pipeline.list_mongo_projects() if mongo_pipeline else []
                return self._send_json({"projects": projects})
            except Exception as e:
                return self._send_json({"error": str(e), "projects": []}, status=500)

        # API: Get leads for a project with search & filter
        if path == "/api/leads":
            project = query.get("project", [""])[0].strip()
            search = query.get("search", [""])[0].strip().lower()
            has_email = query.get("has_email", ["false"])[0].lower() == "true"
            has_socials = query.get("has_socials", ["false"])[0].lower() == "true"
            min_rating_str = query.get("min_rating", ["0"])[0]
            try:
                min_rating = float(min_rating_str)
            except ValueError:
                min_rating = 0.0

            limit = min(500, int(query.get("limit", [100])[0]))
            skip = max(0, int(query.get("skip", [0])[0]))

            if not mongo_pipeline:
                return self._send_json({"leads": [], "total": 0, "error": "mongo_pipeline unavailable"})

            try:
                db = mongo_pipeline.get_mongo_db()
                coll = db["leads"]

                filter_q: Dict[str, Any] = {}
                if project:
                    filter_q["project_name"] = project

                if has_email:
                    filter_q["emails"] = {"$exists": True, "$ne": "", "$nin": [None, ""]}

                if has_socials:
                    filter_q["$or"] = [
                        {"instagram": {"$exists": True, "$ne": "", "$nin": [None, ""]}},
                        {"facebook": {"$exists": True, "$ne": "", "$nin": [None, ""]}},
                        {"linkedin": {"$exists": True, "$ne": "", "$nin": [None, ""]}}
                    ]

                if min_rating > 0:
                    filter_q["review_rating"] = {"$gte": min_rating}

                if search:
                    rgx = re.compile(re.escape(search), re.I)
                    filter_q["$or"] = [
                        {"title": rgx},
                        {"name": rgx},
                        {"category": rgx},
                        {"address": rgx},
                        {"phone": rgx},
                        {"emails": rgx},
                        {"website": rgx},
                    ]

                total = coll.count_documents(filter_q)
                cursor = coll.find(filter_q).sort("created_at", -1).skip(skip).limit(limit)

                leads = []
                for doc in cursor:
                    doc["_id"] = str(doc["_id"])
                    leads.append(doc)

                return self._send_json({
                    "project": project,
                    "leads": leads,
                    "total": total,
                    "limit": limit,
                    "skip": skip
                })
            except Exception as e:
                return self._send_json({"error": str(e), "leads": [], "total": 0}, status=500)

        # API: Job status
        if path == "/api/scrape/status":
            job_id = query.get("job_id", [""])[0]
            with ACTIVE_JOBS_LOCK:
                if job_id not in ACTIVE_JOBS:
                    return self._send_json({"error": "Job not found"}, status=404)
                return self._send_json(ACTIVE_JOBS[job_id])

        # API: List local CSV files available for import
        if path == "/api/csv-files":
            csv_files = []
            for folder in [KIT_DIR, BASE_DIR]:
                if os.path.isdir(folder):
                    for fname in os.listdir(folder):
                        if fname.lower().endswith(".csv"):
                            fpath = os.path.join(folder, fname)
                            size_kb = round(os.path.getsize(fpath) / 1024, 1)
                            csv_files.append({"filename": fname, "size_kb": size_kb, "path": fpath})
            return self._send_json({"files": csv_files})

        # API: Export leads to CSV directly in browser
        if path == "/api/export-csv":
            project = query.get("project", [""])[0].strip()
            if not mongo_pipeline or not project:
                self.send_error(400, "Project name required")
                return

            try:
                db = mongo_pipeline.get_mongo_db()
                coll = db["leads"]
                cursor = coll.find({"project_name": project}).sort("created_at", -1)

                output = io.StringIO()
                writer = None
                fieldnames = ["project_name", "scraped_at", "title", "phone", "emails", "website", "category", "address", "review_rating", "review_count", "instagram", "facebook", "linkedin", "summary"]
                
                rows_written = 0
                for doc in cursor:
                    doc.pop("_id", None)
                    if writer is None:
                        # Add any extra keys discovered in the document
                        for k in doc.keys():
                            if k not in fieldnames:
                                fieldnames.append(k)
                        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
                        writer.writeheader()
                    writer.writerow(doc)
                    rows_written += 1

                csv_bytes = output.getvalue().encode("utf-8-sig")
                safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", project.lower()).strip("_")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename=\"{safe_name}_leads_{rows_written}.csv\"")
                self.send_header("Content-Length", str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)
                return
            except Exception as e:
                self.send_error(500, f"Export error: {e}")
                return

        self.send_error(404, "Endpoint Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        payload = {}
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                payload = {}

        # API: Start a scrape job
        if path == "/api/scrape/start":
            project_name = payload.get("project_name", "").strip()
            # Support both single 'keyword' / 'city' or arrays/multilines 'keywords' / 'cities'
            raw_keywords = payload.get("keywords") or payload.get("keyword") or ""
            raw_cities = payload.get("cities") or payload.get("city") or ""

            keywords_list = parse_items_list(raw_keywords)
            cities_list = parse_items_list(raw_cities)

            if not project_name:
                return self._send_json({"error": "Project Name is required!"}, status=400)
            if not keywords_list:
                return self._send_json({"error": "At least one Search Query / Keyword is required!"}, status=400)

            depth = int(payload.get("depth", 5))
            fast_mode = bool(payload.get("fast_mode", True))
            extract_emails = bool(payload.get("extract_emails", True))
            extract_socials = bool(payload.get("extract_socials", True))
            extract_summary = bool(payload.get("extract_summary", True))
            extract_people = bool(payload.get("extract_people", True))
            save_csv = bool(payload.get("save_csv", True))

            env_cfg = mongo_pipeline.get_default_env() if mongo_pipeline else {}
            db_name = payload.get("db_name", "").strip() or env_cfg.get("MONGO_DB", "scraper")
            collection_name = payload.get("collection_name", "").strip() or "leads"

            job_key = f"job-{int(time.time() * 1000)}"
            total_planned = len(keywords_list) * max(1, len(cities_list))

            with ACTIVE_JOBS_LOCK:
                ACTIVE_JOBS[job_key] = {
                    "id": job_key,
                    "project_name": project_name,
                    "keywords": keywords_list,
                    "cities": cities_list,
                    "total_queries": total_planned,
                    "current_query_index": 0,
                    "depth": depth,
                    "fast_mode": fast_mode,
                    "status": "queued",
                    "step": "Initializing batch queue",
                    "progress": 0,
                    "cumulative_leads": 0,
                    "logs": [],
                    "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "results_summary": None,
                }

            thread = threading.Thread(
                target=run_scrape_worker,
                kwargs={
                    "job_key": job_key,
                    "project_name": project_name,
                    "keywords": keywords_list,
                    "cities": cities_list,
                    "depth": depth,
                    "fast_mode": fast_mode,
                    "extract_emails": extract_emails,
                    "extract_socials": extract_socials,
                    "extract_summary": extract_summary,
                    "extract_people": extract_people,
                    "db_name": db_name,
                    "collection_name": collection_name,
                    "save_csv": save_csv,
                },
                daemon=True,
            )
            thread.start()

            return self._send_json({
                "message": "Scrape pipeline started",
                "job_id": job_key,
                "project_name": project_name,
                "total_queries": total_planned,
            })

        # API: Skip current query and advance to next
        if path == "/api/scrape/skip-query":
            job_id = payload.get("job_id", "")
            with ACTIVE_JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["skip_query_requested"] = True
                    log_job(job_id, "User requested to skip current query. Advancing to next...", level="warn")
                    return self._send_json({"message": "Skipping to next query..."})
            return self._send_json({"error": "Job not found"}, status=404)

        # API: Stop/Cancel a scrape job
        if path == "/api/scrape/stop":
            job_id = payload.get("job_id", "")
            with ACTIVE_JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["cancel_requested"] = True
                    log_job(job_id, "Cancellation requested. Preserving all scraped leads...", level="warn")
                    return self._send_json({"message": "Job cancellation requested"})
            return self._send_json({"error": "Job not found"}, status=404)

        # API: Import existing CSV into MongoDB under project_name
        if path == "/api/import-csv":
            project_name = payload.get("project_name", "").strip()
            filename = payload.get("filename", "").strip()

            if not project_name:
                return self._send_json({"error": "Project Name is required!"}, status=400)
            if not filename:
                return self._send_json({"error": "Filename is required!"}, status=400)

            # Find file
            target_path = None
            for folder in [KIT_DIR, BASE_DIR]:
                check = os.path.join(folder, filename)
                if os.path.exists(check):
                    target_path = check
                    break

            if not target_path:
                return self._send_json({"error": f"CSV file '{filename}' not found on server"}, status=404)

            try:
                stats = mongo_pipeline.import_csv_to_mongo(
                    csv_file=target_path,
                    project_name=project_name,
                )
                return self._send_json({
                    "message": "CSV imported successfully",
                    "stats": stats,
                    "project_name": project_name
                })
            except Exception as e:
                return self._send_json({"error": str(e)}, status=500)

        self.send_error(404, "Endpoint Not Found")


def run_websocket_server():
    """Run asyncio websockets server in a background thread on port WS_PORT."""
    global ws_event_loop
    if not websockets:
        print(f"  WebSocket Server: websockets package is not installed; running HTTP only.")
        return

    ws_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ws_event_loop)

    async def serve():
        async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
            print(f"  WebSocket Server: ws://localhost:{WS_PORT}")
            await asyncio.Future()

    try:
        ws_event_loop.run_until_complete(serve())
    except Exception as e:
        print(f"  WebSocket server error: {e}", file=sys.stderr)


def run_server():
    os.makedirs(WEB_DIR, exist_ok=True)

    # Start WebSocket Server in dedicated daemon thread
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True, name="WebSocketServer")
    ws_thread.start()
    time.sleep(0.3)

    server_address = ("0.0.0.0", PORT)
    httpd = socketserver.ThreadingTCPServer(server_address, ScraperAppHandler)
    httpd.allow_reuse_address = True
    print(f"\n========================================================")
    print(f"  MapLead Scraper Kaynetics - Web & Stream Servers")
    print(f"  HTTP URL:      http://localhost:{PORT}")
    print(f"  WebSocket URL: ws://localhost:{WS_PORT}")
    print(f"========================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()
