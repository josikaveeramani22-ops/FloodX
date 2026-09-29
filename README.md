# 🌊 FloodX 2.0 — Urban Flood Nowcasting System

A live, low-cost flood nowcasting dashboard for Chennai's streets: **FastAPI backend + real-time dashboards (admin + citizen view) + ESP32 sensor integration**. Streets ingest one reading at a time — the dashboard screens on a single reading at boot, then updates live as ESP32 sensors push data.

---

## ✨ Features

- **Admin dashboard** (`/`, `/v2`, `/v3`) — Leaflet map of 8 Chennai zones, risk assessment, current & simulated flood probability, drainage health, route planner, CCTV (webcam / ESP32-CAM), live feed, dataset CSV replay.
- **Citizen SafeZone** (`/user`, `/userv2`, `/userv3`) — resident single-zone view, flood warning banner, neighborhood safety chips, and a **safer-route planner** (Dijkstra over a flood-weighted street graph) with alternate routes + road closures.
- **Budget one-pager** (`/budget`) — ₹35,300 absolute-minimum per-street sensor deployment.
- **Real-time pipeline** — readings POST to `/ingest`, broadcast over **SSE** (`/stream`) and **WebSocket** (`/ws`), persisted to SQLite.
- **Low-cost sensors + local actuators** — ESP32 + HC-SR04 (water level, GPIO 26/27) + YF-S201 (flow, GPIO 13) + rain sensor (GPIO 34), with 3 status LEDs (GPIO 18/19/21), a buzzer (GPIO 23) and 2x two-channel relay modules (GPIO 22/25/16/17) driving pump, flood lamp, barrier and siren. Sketch in `esp32_floodx.ino`; the flood logic runs on the node itself, so pump/lamps/siren keep working with no cloud.

---

## 📁 Project structure

| File | Purpose |
|---|---|
| `fastapi_server.py` | FastAPI back-end: static pages, ingest, SSE/WS, SQLite, demo replay |
| `floodx_dashboard.html` / `floodx_dashboard_v2.html` | Admin dashboards (v2 = defensive-map rebuild) |
| `floodx_user.html` / `floodx_user_v2.html` | Citizen dashboards |
| `floodx_budget.html` | Budget one-pager |
| `esp32_floodx.ino` | ESP32 street node: reads the 3 sensors, drives LEDs/buzzer/relays, POSTs readings to `/ingest` |
| `requirements.txt` | Python dependencies |
| `render.yaml` | Render.com rendering blueprint |
| `Dockerfile` | Container for Railway / Fly.io |
| `app.py` | Optional Streamlit dashboard (reads `/latest`) |
| `data/floodx.db` | SQLite readings database (auto-created) |

---

## 🚀 Run locally

```bat
Start Dashboard.bat
```

or manually:

```bat
pip install -r requirements.txt
python fastapi_server.py --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/v2`. Add `--demo` to replay the synthetic dataset (`data/synthetic.csv`, bundled in this repo).

> ⚠️ Always open through `http://…`, never by double-clicking the `.html` files — the live stream and webcam require HTTP.

---

## 🌐 Publish as a public website

### Option A — Render.com (free, GitHub required)

1. Create a **GitHub** repository and push **at least**:
   `fastapi_server.py`, `floodx_dashboard_v2.html`, `floodx_user_v2.html`, `floodx_dashboard.html`, `floodx_user.html`, `floodx_budget.html`, `esp32_floodx.ino`, `requirements.txt`, `render.yaml`.
2. In [render.com](https://render.com) → **New → Blueprint** → select the repo.
3. Render auto-builds from `render.yaml` (≈ 2–3 min). You get:
   `https://<app>.onrender.com`
   - Dashboard: `https://<app>.onrender.com/v3`
   - Citizen: `https://<app>.onrender.com/userv3`
   - Use **v3** when deployed (auto-HTTPS/wss); v2 works too and self-adapts.
   - API docs: `https://<app>.onrender.com/docs`

### Option B — Railway (free tier, no GitHub needed)

```bash
npm install -g @railway/cli
railway login
railway up          # run inside this folder — auto-uses Dockerfile
```

### Option C — Fly.io

```bash
fly launch --dockerfile Dockerfile
fly deploy
```

---

## 📡 Sensor data protocol

**CSV line (dashboard CSV format):**

```
timestamp,zone,rainfall_intensity_mm_hr,water_level_cm,flow_rate_lps,drain_capacity_lps,blockage_pct,drain_saturation_pct,flood_next_30min
```

**JSON (preferred for ESP32):**

```json
{
  "timestamp": "2026-01-01 00:00:00",
  "zone": "Zone_3",
  "rainfall_intensity_mm_hr": 74,
  "water_level_cm": 38.2,
  "flow_rate_lps": 126,
  "drain_capacity_lps": 150,
  "blockage_pct": 38,
  "drain_saturation_pct": 84,
  "flood_next_30min": 1
}
```

Actually send it with:

```bash
curl -X POST https://<app-url>/ingest \
  -H "Content-Type: application/json" \
  -d '{"zone":"Zone_3","water_level_cm":38.2,"flow_rate_lps":126,"drain_capacity_lps":150,"flood_next_30min":1}'
```

The dashboard maps `zone` → street automatically (`Zone_N` → Nth street).

---

## 🔌 ESP32 integration

1. Open `esp32_floodx.ino` in Arduino IDE.
2. Set your Wi-Fi credentials and `SERVER` = `https://<app-url>/ingest`.
3. Pick your zone (`ZONE = "Zone_1" … "Zone_8"`), capacity, blockage.
4. Upload — one JSON reading is POSTed every 5 s; the dashboard updates live.

---

## 🔗 API reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` · `/v2` · `/v3` · `/user` · `/userv2` · `/userv3` · `/budget` | Pages |
| GET | `/health` | Health check |
| GET | `/latest` | Most recent reading |
| GET | `/history?limit=500` | Recent readings (SQLite) |
| POST | `/ingest` | Accept one reading (JSON or CSV line) |
| GET | `/stream` | SSE live feed |
| WS | `/ws` | WebSocket live feed |
| POST | `/demo/start` / `/demo/stop` | Replay the demo dataset |
| GET | `/docs` | Swagger UI |

---

## ⚠️ Production notes

- Free hosts use an **ephemeral disk** — `data/floodx.db` resets on redeploy. To keep history, mount a **persistent disk** at `/app/data` (see the commented block in `render.yaml`).
- The 2000-row demo dataset is **bundled** at `data/synthetic.csv`, so `--demo` and `POST /demo/start` work on the cloud out of the box.
- Render **sleeps** after ~15 min idle (first load after sleep ≈ 30 s wake time).
- Justify the payload in front of a jury: each street drain serves a **~1 ha urban sub-catchment**; flows of 30–130 L/s with drains sized 45–140 L/s are realistic for 0.3–0.5 m feeder drains.