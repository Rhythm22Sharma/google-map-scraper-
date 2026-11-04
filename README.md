# MapLead Scraper Kaynetics 🚀

An end-to-end Google Maps lead generation and MongoDB Atlas pipeline with real-time web dashboard, visual tag-based batch queuing, fast early-stop scraping, and automated lead enrichment (emails, social media, summaries).

---

## ✨ Features

- **Interactive Visual Tag / Chip Manager**: Easily input multiple search keywords (e.g. `recruitment agency`, `staffing agency`, `executive search`) and multiple target cities (e.g. `Udaipur`, `Jaipur`, `Dubai, UAE`, `New York`).
- **Dynamic Batch Queue Matrix**: Cross-multiplies keywords × locations into sequential scrape tasks.
- **Fast Mode & Early Auto-Stop**: When Google Maps runs out of results (e.g. 40 listings found instead of 100), the scraper terminates immediately without waiting, advancing instantly to the next query.
- **Zero-Loss Data Preservation**: Keeps all raw Google Maps attributes intact (title, address, phone, website, category, reviews, rating, coordinates) stamped with `project_name` and `scraped_at`.
- **Parallel Enrichment**: Fast multi-threaded website crawler extracts business emails, Instagram/Facebook/LinkedIn handles, and meta descriptions in seconds.
- **MongoDB Atlas Sync**: Upserts and deduplicates leads under user-defined project names.
- **Offline CSV Master Backup**: Creates master project CSV files automatically.
- **Live Pipeline Monitor**: Real-time progress bar, live execution logs, "Skip Query", and "Stop & Save" controls.

---

## 🛠️ Architecture & Tech Stack

- **Frontend**: Vanilla HTML5, CSS3 (Rich Dark Mode & Glassmorphism), Modern ES6+ JavaScript.
- **Backend**: Python 3.12 HTTP server with multi-threaded background workers and REST API.
- **Database**: MongoDB Atlas (`pymongo` with TLS).
- **Engine**: Dockerized headless Chromium scraper container (`gosom/google-maps-scraper:v1.18.1`).

---

## 🚀 Quick Start

### 1. Start Scraper Engine (Docker)
Ensure Docker Desktop is running, then start the scraper container:
```bash
start_scraper_engine.bat
# Or manually:
docker compose -f googlemaps_scraper/google-maps-scraper-kit/docker-compose.yml up -d
```
The scraper engine API will run on `http://localhost:8085`.

### 2. Configure Environment (`.env`)
Create or edit `googlemaps_scraper/google-maps-scraper-kit/.env`:
```env
SCRAPER_PORT=8085
SCRAPER_BASE_URL=http://localhost:8085
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGO_DB=scraper
```

### 3. Launch Web Application
Double-click `run_frontend.bat` or run:
```bash
python server.py
```
Open **[http://localhost:5050](http://localhost:5050)** in your browser.

---

## 📂 Project Structure

```text
├── web/
│   ├── index.html          # Web dashboard UI
│   ├── style.css           # Premium dark-mode glassmorphic styling
│   └── app.js              # Tag management & real-time monitoring
├── server.py               # Backend web server & batch queue worker
├── pipeline.py             # CLI pipeline launcher
├── scripts/
│   ├── mongo_pipeline.py   # MongoDB Atlas connector & deduplication
│   └── scrape.py           # Enrichment worker (emails, socials, summaries)
├── googlemaps_scraper/
│   └── google-maps-scraper-kit/
│       ├── docker-compose.yml
│       └── .env.example
├── run_frontend.bat        # Windows one-click frontend launcher
└── start_scraper_engine.bat# Windows one-click Docker starter
```

---

## 📜 License
MIT