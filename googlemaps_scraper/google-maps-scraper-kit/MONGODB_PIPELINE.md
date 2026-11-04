# MongoDB Lead Pipeline Guide

This pipeline integrates your Google Maps Scraper with **MongoDB** so you can organize your leads by **Project Name** (e.g., `scrape for taltra`) with automatic deduplication, email and social media enrichment, and multi-project querying.

---

## 🚀 How to Run the Pipeline

### Method 1: Web Application Frontend (Easiest & Visual)

Launch the modern Web UI in your browser:
```bash
python server.py
```
*(Or simply double-click `run_frontend.bat` on Windows)*

Then open **[http://localhost:5050](http://localhost:5050)** in your browser:
- **Interactive Scrape Form**: Fill in Project Name, Search Keyword, Target City, Depth, and toggles (Emails, Socials, AI Summary).
- **Live Visual Monitor**: Watch geocoding, scraping, and MongoDB synchronization in real-time with step-by-step progress and terminal logs.
- **MongoDB Leads Explorer**: Search, filter ("Has Email", "Has Socials", "4+ Stars"), view ratings, phone numbers, social links, and export leads directly to CSV.
- **CSV Importer**: 1-click import from local CSV files into any project in MongoDB Atlas.

---

### Method 2: Interactive CLI Wizard

Simply run:
```bash
python pipeline.py
```
*(Or double-click `run_pipeline.bat` on Windows)*

The interactive wizard will prompt you:
1. **Project Name:** (e.g. `scrape for taltra`)
2. **Search Title / Keyword:** (e.g. `recruitment agencies` or `luxury car rentals`)
3. **Target City / Location:** (e.g. `Dubai, UAE`)
4. **Scrape Depth:** (e.g. `5` ~ 100 potential listings)
5. **Extract Business Emails:** `[Y/n]`
6. **Enrich Social Media (Instagram, Facebook, LinkedIn):** `[Y/n]`
7. **MongoDB Destination:** Database name & Collection (`leads`)
8. **Save CSV Backup:** `[Y/n]`

The pipeline runs the job, tracks progress, enriches leads, and inserts them directly into MongoDB!

---

### Method 2: Direct Command-Line Pipeline

```bash
python pipeline.py --project "scrape for taltra" --keyword "recruitment agencies" --city "Dubai, UAE" --depth 5
```

Options:
- `--project <name>`: Assign a project name (e.g. `"scrape for taltra"`)
- `--keyword <query>`: Search keyword
- `--city <location>`: City or place name (auto-geocoded)
- `--depth <n>`: Scroll depth (default: 5)
- `--no-email`: Skip email extraction for a faster run
- `--no-socials`: Skip Instagram/Facebook/LinkedIn extraction
- `--no-csv`: Skip creating offline CSV file

---

### Method 3: Import Existing CSVs into MongoDB

If you already have existing lead CSVs (e.g. `taltra_dubai_leads.csv`), you can import them into MongoDB with one command:

```bash
python pipeline.py --import-csv taltra_dubai_leads.csv --project "scrape for taltra"
```

---

### Method 4: List Projects & Lead Statistics

View all stored projects, lead counts, and enrichment metrics in MongoDB:

```bash
python pipeline.py --list-projects
```

Example Output:
```
Project Name                   Leads    With Email   With Socials   Last Updated
--------------------------------------------------------------------------------
scrape for taltra              54       25           37             2026-10-15 05:02:55
```

---

## 🗄️ MongoDB Document Structure

Each document saved in `scraper.leads` contains **`project_name`** (taken from the user prompt) plus **all fields from the CSV download**:

```json
{
  "_id": ObjectId("6ad060ab349c56c7b6dafef8"),
  "project_name": "scrape for taltra",
  "title": "HR International UAE",
  "phone": "+971 4 351 0009",
  "emails": "employer@hrinternational.in, coordinator12@hrinternational.in",
  "website": "http://hrinternational.ae/",
  "category": "Employment consultant",
  "address": "HR International UAE - 309, 3rd floor - Sheikh Khalifa Bin Zayed St - Karama - Dubai",
  "summary": "Premier overseas recruitment agency...",
  "review_rating": 3.8,
  "review_count": 54,
  "instagram": "",
  "facebook": "https://www.facebook.com/yamadadenkiweb.jp",
  "linkedin": "",
  "created_at": ISODate("2026-10-15T05:12:10Z")
}
```

---

## ⚙️ Configuration (.env)

Configured in [.env](file:///c:/Users/rhythm/Desktop/google-maps-scraper-kit/googlemaps_scraper/google-maps-scraper-kit/.env):
```ini
# Scraper Configuration
SCRAPER_PORT=8080
SCRAPER_API_KEY=

# MongoDB Configuration (Set your connection string here)
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.example.mongodb.net/scraper
MONGO_DB=scraper
```
