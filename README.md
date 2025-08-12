# Traffic Density Analyzer

AI-powered traffic analysis (images/videos) with YOLOv8, unique vehicle counting, density timeline, upload progress, and an upgraded, modern UI.

## Demo

<video src="Traffic%20Density%20Analyzer.mp4" controls muted loop width="800" style="max-width:100%"></video>

If the embedded player doesn’t load, [download/view the demo video](Traffic%20Density%20Analyzer.mp4).

## Features

- Upload images/videos with real upload progress (percentage)
- YOLOv8 detection with unique counting and per-class stats (car, truck, bus, motorcycle)
- Density over time chart synced to the video timeline (click chart to scrub)
- Badges: "No Motorcycles" and "Low Confidence"
- Adjustable thresholds preset (confidence, IOU) with re-run UI (applied on next upload)
- Results export: CSV and JSON; snapshot JPG with KPI overlay
- History page: search, filter (images/videos), sort (date/density), clear all
- Theme presets (Slate/Neon/Forest) + light/dark toggle, accessible focus states

## Requirements

- Python 3.10–3.12
- FFmpeg (recommended, for best video compatibility)
- Windows/Linux/macOS

## Quick Start

```bash
# 1) Create venv and install dependencies
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 2) Configure environment
copy .env.example .env   # then edit values if needed

# 3) Run the app
python main.py
# or
# set FLASK_APP=main.py && flask run
```

App runs at `http://127.0.0.1:5000/`.

## Configuration (.env)

```
FLASK_APP=main.py
FLASK_ENV=development
SECRET_KEY=change-this
DATABASE_URL=sqlite:///traffic_density.db
UPLOAD_FOLDER=static/uploads
RESULT_FOLDER=static/results
SAMPLE_DATA_FOLDER=static/sample_data
```

Notes:
- Large generated media and model weights are git-ignored (`.gitignore`).
- `yolov8n.pt` is not required in repo; Ultralytics auto-downloads models when needed. If you place one, it will be ignored.

## Usage

1) Open Home page → drag-and-drop or select file
2) Watch the percentage upload bar; when it reaches 100% it switches to "Processing…"
3) Results page shows:
   - KPIs (total, density, per-class counts)
   - Density timeline synced to video (click the chart to scrub the video)
   - Badges: "No Motorcycles" and/or "Low Confidence" when applicable
   - Quick actions: Download CSV, JSON, Snapshot JPG
4) Optional: Open "Re-run" panel (top-right slider icon) to save a threshold preset. This preset is automatically applied to future uploads.

### Threshold Preset
- Sliders for global confidence, motorcycle confidence, and IOU
- Saved to `localStorage`; automatically sent with the next upload

## API Endpoints

- `POST /process_file` → process uploaded file (applies optional form fields: `conf_global`, `motorcycle_conf`, `iou_thresh`)
- `GET  /report/<filename>` → CSV download
- `GET  /report/json/<analysis_id>` → JSON payload
- `GET  /snapshot/<analysis_id>` → KPI snapshot JPG
- `GET  /history` → history page
- `POST /history/clear` → delete all history and associated files

## Project Structure

```
.
├─ main.py                 # Flask app, routes, logging, processing flow
├─ app/
│  ├─ __init__.py
│  ├─ models.py           # SQLAlchemy model(s)
│  └─ utils.py            # Video/image processing (YOLOv8)
├─ templates/              # Jinja templates (index, result, history, base)
├─ static/
│  ├─ css/                 # Styles (theme variables, glassmorphism, etc.)
│  ├─ js/                  # Frontend logic (upload progress, drag-n-drop)
│  ├─ img/                 # Logos/icons
│  ├─ uploads/             # Ignored; user uploads (kept empty via .gitkeep)
│  └─ results/             # Ignored; processed media/exports (.gitkeep)
├─ instance/               # SQLite DB (ignored)
├─ .env.example            # Sample environment
├─ .gitignore              # Excludes venv, media, logs, weights, etc.
├─ requirements.txt        # Python dependencies
└─ pyproject.toml          # Project metadata
```

## Development

- Frontend
  - Real upload progress via XHR; drag-and-drop and inline validation
  - Density chart with Chart.js; datalabels plugin enabled
  - Theme presets with accessible focus rings; light/dark toggle persisted
- Backend
  - `app.utils.process_video(input, output, *, conf_global, motorcycle_conf, iou_thresh)` returns:
    - `total_vehicles`, `vehicle_counts{car,truck,bus,motorcycle}`
    - `density` (overall), `density_series` (timeline), `avg_confidence`, `low_confidence`

## Roadmap (next)

- Background jobs (RQ) + SSE progress
- ByteTrack/DeepSORT tracking for more accurate unique counts
- FFmpeg normalization & thumbnails + resumable uploads (tus)
- Object storage (S3/minio) for media, signed URLs
- Dockerfile & Compose + GitHub Actions CI

## Troubleshooting

- Upload fails immediately → check file type/size and `.env` limits
- Video doesn’t play → install FFmpeg and try a standard H.264/AAC MP4
- White/light UI too bright → use theme toggle in navbar
- Reset stale caching → hard refresh (Ctrl+F5)

## License

MIT 