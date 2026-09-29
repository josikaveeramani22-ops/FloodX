"""
FloodX 2.0 — FastAPI live back-end
==================================
Serves the dashboard, ingests real-time sensor data, persists readings to
SQLite, and broadcasts them over SSE + WebSocket so the dashboard updates live.

Endpoints
---------
  GET  /                     → serves floodx_dashboard.html (same-page dashboard)
  GET  /user , /user.html    → serves floodx_user.html (resident / citizen view)
  GET  /budget               → serves floodx_budget.html (low-cost budget one-pager)
  GET  /v2                   → serves floodx_dashboard_v2.html (rebuilt admin dashboard)
  GET  /userv2               → serves floodx_user_v2.html (rebuilt resident view)
  GET  /v3        (/v3.html) → serves floodx_dashboard_v3.html (HTTPS/Render-safe admin)
  GET  /userv3    (/userv3.html) → serves floodx_user_v3.html (HTTPS/Render-safe citizen)
  GET  /combined  (/combined.html) → serves floodx_combined.html (admin + citizen in one file)
  GET  /combined2 (/combined2.html) → serves floodx_combined_v2.html (clean-top rebuild)
  GET  /latest               → latest reading as JSON (used by app.py / Streamlit)
  GET  /history?limit=500    → recent readings from SQLite (for charts / app.py)
  POST /ingest               → accept a sensor reading (JSON object or CSV line)
  GET  /stream               → Server-Sent Events feed (dashboard "LIVE FEED" SSE)
  WS   /ws                   → WebSocket feed (dashboard "LIVE FEED" WS mode)
  POST /demo/start           → start replaying the synthetic CSV as a live stream
  POST /demo/stop            → stop the demo replay
  GET  /health               → health check

Run
---
  python fastapi_server.py                # listen on 127.0.0.1:8000
  python fastapi_server.py --host 0.0.0.0 # expose on LAN (for ESP32 / sensors)
  python fastapi_server.py --demo         # auto-start replay of the synthetic dataset

Security note: this is a prototype. Add auth/TLS/rate-limiting before production.
"""
import argparse
import asyncio
import csv
import json
import os
import queue
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# ------------------------------------------------------------------
# Paths / config
# ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / 'data'
DB = DB_DIR / 'floodx.db'
DASHBOARD = ROOT / 'floodx_dashboard.html'
USER_PAGE = ROOT / 'floodx_user.html'
BUDGET_PAGE = ROOT / 'floodx_budget.html'
V2_DASHBOARD = ROOT / 'floodx_dashboard_v2.html'
V2_USER_PAGE = ROOT / 'floodx_user_v2.html'
V3_DASHBOARD = ROOT / 'floodx_dashboard_v3.html'
V3_USER_PAGE = ROOT / 'floodx_user_v3.html'
COMBINED_PAGE = ROOT / 'floodx_combined.html'
COMBINED_V2_PAGE = ROOT / 'floodx_combined_v2.html'
# Prefer a repo-bundled dataset (works on GitHub/Render), fall back to the
# author's local Downloads copy for offline runs.
_BUNDLED_DATASET = ROOT / 'data' / 'synthetic.csv'
_LOCAL_DATASET = Path.home() / 'Downloads' / 'synthetic_urban_flood_dataset_2000.csv'
DEFAULT_DATASET = _BUNDLED_DATASET if _BUNDLED_DATASET.exists() else _LOCAL_DATASET

ZONE_STREETS = {
    'Zone_1': '1st Street', 'Zone_2': '2nd Street', 'Zone_3': '3rd Street',
    'Zone_4': '4th Street', 'Zone_5': '5th Street', 'Zone_6': '6th Street',
    'Zone_7': '7th Street', 'Zone_8': '8th Street',
}


class SensorReading(BaseModel):
    """A single sensor reading (dashboard CSV-line / JSON protocol)."""
    timestamp: Optional[str] = None
    zone: Optional[str] = None                    # CSV label: Zone_1..Zone_8
    rainfall_intensity_mm_hr: Optional[float] = None
    water_level_cm: Optional[float] = None
    flow_rate_lps: Optional[float] = None
    drain_capacity_lps: Optional[float] = None
    blockage_pct: Optional[float] = None
    drain_saturation_pct: Optional[float] = None
    flood_next_30min: Optional[int] = 0
    # Streamlit / app.py style fields (also accepted)
    zone_id: Optional[str] = None
    risk_level: Optional[str] = None
    flood_probability: Optional[float] = None

    def zone_key(self) -> str:
        return (self.zone or self.zone_id or '').strip()

    def street(self) -> str:
        return ZONE_STREETS.get(self.zone_key(), f'{self.zone_key()} (unmapped)')


# ------------------------------------------------------------------
# Broadcast plumbing (SSE queues + WebSocket clients)
# ------------------------------------------------------------------
_sse_clients: Set[queue.Queue] = set()
_ws_clients: Set[WebSocket] = set()
_broadcast_lock = threading.Lock()
_app_loop: Optional[asyncio.AbstractEventLoop] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _app_loop
    _app_loop = asyncio.get_running_loop()
    _connect()  # ensure DB / table exist
    yield
    with _broadcast_lock:
        _sse_clients.clear()
        _ws_clients.clear()


app = FastAPI(
    title='FloodX 2.0 — Urban Flood Nowcasting API',
    version='2.0.0',
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],   # prototype: allow dashboard from file:// or LAN
    allow_methods=['*'],
    allow_headers=['*'],
)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# SQLite helpers
# ------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            zone_id TEXT,
            water_level_cm REAL,
            flow_rate_lps REAL,
            flood_probability REAL,
            risk_level TEXT,
            street_name TEXT
        )
        """
    )
    conn.commit()
    return conn


def _derive_risk(water_cm: float, flood: int, sat: float) -> str:
    if flood >= 1 or water_cm >= 40:
        return 'CRITICAL'
    if water_cm >= 30 or sat >= 95:
        return 'HIGH'
    if water_cm >= 20 or sat >= 75:
        return 'MODERATE'
    return 'LOW'


def _derive_probability(flood: int, sat: float) -> float:
    if flood >= 1:
        return min(0.99, max(0.92, sat / 100.0))
    return min(0.95, max(0.02, (sat / 100.0) * 0.55))


def _save_reading(r: SensorReading, risk: str, prob: float) -> dict:
    row = {
        'timestamp': r.timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'zone_id': r.zone_key(),
        'water_level_cm': r.water_level_cm,
        'flow_rate_lps': r.flow_rate_lps,
        'flood_probability': prob,
        'risk_level': risk,
        'street_name': r.street(),
    }
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO readings (timestamp, zone_id, water_level_cm,
                                  flow_rate_lps, flood_probability, risk_level,
                                  street_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (row['timestamp'], row['zone_id'], row['water_level_cm'],
             row['flow_rate_lps'], row['flood_probability'], row['risk_level'],
             row['street_name']),
        )
        conn.commit()
        row['id'] = cur.lastrowid
    finally:
        conn.close()
    return row


def _to_csv_line(r: SensorReading, risk: str, prob: float) -> str:
    """Serialize to the dashboard's 9-column CSV line protocol."""
    now = r.timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return ','.join(str(v) for v in (
        now,
        r.zone_key(),
        r.rainfall_intensity_mm_hr if r.rainfall_intensity_mm_hr is not None else '',
        r.water_level_cm if r.water_level_cm is not None else '',
        r.flow_rate_lps if r.flow_rate_lps is not None else '',
        r.drain_capacity_lps if r.drain_capacity_lps is not None else '',
        r.blockage_pct if r.blockage_pct is not None else '',
        r.drain_saturation_pct if r.drain_saturation_pct is not None else '',
        int(r.flood_next_30min or 0),
    ))


def _line_to_dict(line: str) -> dict:
    p = line.split(',')
    zone = p[1] if len(p) > 1 else ''
    return {
        'timestamp': p[0] if p else None,
        'zone': zone,
        'rainfall_intensity_mm_hr': _f(p[2] if len(p) > 2 else None),
        'water_level_cm': _f(p[3] if len(p) > 3 else None),
        'flow_rate_lps': _f(p[4] if len(p) > 4 else None),
        'drain_capacity_lps': _f(p[5] if len(p) > 5 else None),
        'blockage_pct': _f(p[6] if len(p) > 6 else None),
        'drain_saturation_pct': _f(p[7] if len(p) > 7 else None),
        'flood_next_30min': int(p[8]) if len(p) > 8 and p[8] else 0,
        'street': ZONE_STREETS.get(zone, ''),
    }


async def broadcast(line: str) -> None:
    """Push a line to every SSE queue and WebSocket client."""
    with _broadcast_lock:
        for q in list(_sse_clients):
            try:
                q.put_nowait('data: ' + line + '\n\n')
            except queue.Full:
                pass
        for ws in list(_ws_clients):
            try:
                await ws.send_text(json.dumps(_line_to_dict(line)))
            except Exception:
                _ws_clients.discard(ws)


def broadcast_from_thread(line: str) -> None:
    """Schedule a broadcast from a background (demo) thread on the app loop."""
    if _app_loop is None:
        return
    fut = asyncio.run_coroutine_threadsafe(broadcast(line), _app_loop)
    try:
        fut.result(timeout=2)
    except Exception:
        pass


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@app.get('/')
async def index():
    if not DASHBOARD.exists():
        raise HTTPException(404, 'floodx_dashboard.html not found next to the server')
    return FileResponse(DASHBOARD)


@app.get('/user')
@app.get('/user.html')
async def user_page():
    if not USER_PAGE.exists():
        raise HTTPException(404, 'floodx_user.html not found next to the server')
    return FileResponse(USER_PAGE)


@app.get('/budget')
async def budget_page():
    if not BUDGET_PAGE.exists():
        raise HTTPException(404, 'floodx_budget.html not found next to the server')
    return FileResponse(BUDGET_PAGE)


@app.get('/v2')
@app.get('/v2.html')
async def v2_dashboard():
    if not V2_DASHBOARD.exists():
        raise HTTPException(404, 'floodx_dashboard_v2.html not found next to the server')
    return FileResponse(V2_DASHBOARD)


@app.get('/userv2')
@app.get('/userv2.html')
async def v2_user_page():
    if not V2_USER_PAGE.exists():
        raise HTTPException(404, 'floodx_user_v2.html not found next to the server')
    return FileResponse(V2_USER_PAGE)


@app.get('/v3')
@app.get('/v3.html')
async def v3_dashboard():
    if not V3_DASHBOARD.exists():
        raise HTTPException(404, 'floodx_dashboard_v3.html not found next to the server')
    return FileResponse(V3_DASHBOARD)


@app.get('/userv3')
@app.get('/userv3.html')
async def v3_user_page():
    if not V3_USER_PAGE.exists():
        raise HTTPException(404, 'floodx_user_v3.html not found next to the server')
    return FileResponse(V3_USER_PAGE)


@app.get('/combined')
@app.get('/combined.html')
async def combined_page():
    if not COMBINED_PAGE.exists():
        raise HTTPException(404, 'floodx_combined.html not found next to the server')
    return FileResponse(COMBINED_PAGE)


@app.get('/combined2')
@app.get('/combined2.html')
async def combined_v2_page():
    if not COMBINED_V2_PAGE.exists():
        raise HTTPException(404, 'floodx_combined_v2.html not found next to the server')
    return FileResponse(COMBINED_V2_PAGE)


@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'FloodX API',
            'clients': len(_sse_clients) + len(_ws_clients)}


@app.get('/latest')
async def latest():
    """Latest reading, Streamlit-friendly shape."""
    conn = _connect()
    try:
        r = conn.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    finally:
        conn.close()
    if not r:
        return {'zone_id': None, 'water_level_cm': None, 'risk_level': 'UNKNOWN'}
    return dict(r)


@app.get('/history')
async def history(limit: int = 500):
    conn = _connect()
    try:
        rows = conn.execute(
            'SELECT id, timestamp, zone_id, water_level_cm, flood_probability, '
            'risk_level, flow_rate_lps FROM readings ORDER BY id DESC LIMIT ?',
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]


@app.post('/ingest')
async def ingest(request: Request):
    """Accept a sensor reading as JSON or as a dashboard CSV line."""
    raw = (await request.body()).decode('utf-8', 'replace').strip()
    if not raw:
        raise HTTPException(400, 'Empty body')

    if raw.startswith('{') or raw.startswith('['):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(400, 'Invalid JSON')
        if isinstance(payload, list):
            results = [_ingest_one(SensorReading(**item)) for item in payload]
            return JSONResponse({'ingested': len(results), 'items': results})
        reading = SensorReading(**payload)
    else:
        parts = raw.split(',')
        if len(parts) < 2:
            raise HTTPException(400, 'CSV line needs at least timestamp,zone')
        reading = SensorReading(
            timestamp=parts[0].strip(),
            zone=parts[1].strip(),
            rainfall_intensity_mm_hr=_f(parts[2]) if len(parts) > 2 else None,
            water_level_cm=_f(parts[3]) if len(parts) > 3 else None,
            flow_rate_lps=_f(parts[4]) if len(parts) > 4 else None,
            drain_capacity_lps=_f(parts[5]) if len(parts) > 5 else None,
            blockage_pct=_f(parts[6]) if len(parts) > 6 else None,
            drain_saturation_pct=_f(parts[7]) if len(parts) > 7 else None,
            flood_next_30min=int(_f(parts[8])) if len(parts) > 8 and parts[8] else 0,
        )

    result = _ingest_one(reading)
    return JSONResponse(result)


def _ingest_one(reading: SensorReading) -> dict:
    if not reading.zone_key():
        raise HTTPException(400, 'Missing "zone" / "zone_id"')
    risk = reading.risk_level or _derive_risk(
        reading.water_level_cm or 0,
        int(reading.flood_next_30min or 0),
        reading.drain_saturation_pct or 0,
    )
    prob = reading.flood_probability or _derive_probability(
        int(reading.flood_next_30min or 0),
        reading.drain_saturation_pct or 0,
    )
    row = _save_reading(reading, risk, prob)
    line = _to_csv_line(reading, risk, prob)
    if _app_loop is not None and _app_loop.is_running():
        asyncio.create_task(broadcast(line))
    return {'ok': True, 'id': row['id'], 'risk_level': risk, 'broadcast': True}


@app.get('/stream')
async def stream():
    """SSE feed — the dashboard's LIVE FEED (EventSource) subscribes here."""
    q: queue.Queue = queue.Queue(maxsize=200)
    with _broadcast_lock:
        _sse_clients.add(q)

    async def gen():
        keepalive = 0
        try:
            while True:
                try:
                    yield q.get_nowait()
                except queue.Empty:
                    if keepalive >= 15:
                        yield ': keepalive\n\n'
                        keepalive = 0
                    else:
                        yield ''
                    await asyncio.sleep(1)
                    keepalive += 1
        finally:
            with _broadcast_lock:
                _sse_clients.discard(q)

    return StreamingResponse(
        gen(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache',
                 'Connection': 'keep-alive',
                 'X-Accel-Buffering': 'no'},
    )


@app.websocket('/ws')
async def ws_endpoint(websocket: WebSocket):
    """WebSocket live feed."""
    await websocket.accept()
    with _broadcast_lock:
        _ws_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                if data.startswith('{') or data.startswith('['):
                    obj = json.loads(data)
                    reading = SensorReading(**obj if isinstance(obj, dict) else obj[0])
                else:
                    parts = data.split(',')
                    if len(parts) < 2:
                        continue
                    reading = SensorReading(
                        timestamp=parts[0].strip(),
                        zone=parts[1].strip(),
                        rainfall_intensity_mm_hr=_f(parts[2]) if len(parts) > 2 else None,
                        water_level_cm=_f(parts[3]) if len(parts) > 3 else None,
                        flow_rate_lps=_f(parts[4]) if len(parts) > 4 else None,
                        drain_capacity_lps=_f(parts[5]) if len(parts) > 5 else None,
                        blockage_pct=_f(parts[6]) if len(parts) > 6 else None,
                        drain_saturation_pct=_f(parts[7]) if len(parts) > 7 else None,
                        flood_next_30min=int(_f(parts[8])) if len(parts) > 8 and parts[8] else 0,
                    )
                if reading.zone_key():
                    _ingest_one(reading)
            except Exception:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        with _broadcast_lock:
            _ws_clients.discard(websocket)


# ------------------------------------------------------------------
# Demo replay (replays the synthetic dataset as a live feed)
# ------------------------------------------------------------------
_demo_stop = threading.Event()


@app.post('/demo/start')
async def demo_start(path: Optional[str] = None, interval_s: float = 0.8):
    dataset = path or str(DEFAULT_DATASET)
    if not Path(dataset).exists():
        raise HTTPException(404, f'Dataset not found: {dataset}')
    _demo_stop.clear()
    threading.Thread(target=_replay_loop, args=(dataset, interval_s), daemon=True).start()
    return {'status': 'started', 'path': dataset, 'interval_s': interval_s}


@app.post('/demo/stop')
async def demo_stop():
    _demo_stop.set()
    return {'status': 'stopped'}


def _replay_loop(path: str, interval_s: float) -> None:
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if _demo_stop.is_set():
                break
            zone = (row.get('zone') or '').strip()
            if zone not in ZONE_STREETS:
                continue
            g = lambda key: _f(row[key]) if row.get(key) else None
            f_key = lambda key: int(_f(row[key])) if row.get(key) else 0
            reading = SensorReading(
                timestamp=(row.get('timestamp') or '').strip(),
                zone=zone,
                rainfall_intensity_mm_hr=g('rainfall_intensity_mm_hr'),
                water_level_cm=g('water_level_cm'),
                flow_rate_lps=g('flow_rate_lps'),
                drain_capacity_lps=g('drain_capacity_lps'),
                blockage_pct=g('blockage_pct'),
                drain_saturation_pct=g('drain_saturation_pct'),
                flood_next_30min=f_key('flood_next_30min'),
            )
            risk = _derive_risk(reading.water_level_cm or 0,
                                reading.flood_next_30min or 0,
                                reading.drain_saturation_pct or 0)
            prob = _derive_probability(reading.flood_next_30min or 0,
                                       reading.drain_saturation_pct or 0)
            _save_reading(reading, risk, prob)
            broadcast_from_thread(_to_csv_line(reading, risk, prob))
            time.sleep(interval_s)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FloodX 2.0 FastAPI back-end')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8000')))
    parser.add_argument('--demo', action='store_true',
                        help='start replaying the synthetic dataset on boot')
    parser.add_argument('--dataset', default=None,
                        help='path to CSV to replay for the demo')
    parser.add_argument('--interval', type=float, default=0.8,
                        help='seconds between demo rows')
    args = parser.parse_args()

    print('FloodX 2.0 API')
    print(f'  Dashboard : http://{args.host}:{args.port}/')
    print(f'  Latest    : http://{args.host}:{args.port}/latest')
    print(f'  History   : http://{args.host}:{args.port}/history')
    print(f'  Ingest    : POST http://{args.host}:{args.port}/ingest')
    print(f'  SSE feed  : http://{args.host}:{args.port}/stream')
    print(f'  WebSocket : ws://{args.host}:{args.port}/ws')
    print(f'  Docs      : http://{args.host}:{args.port}/docs')

    if args.demo:
        threading.Thread(
            target=_replay_loop,
            args=(args.dataset or str(DEFAULT_DATASET), args.interval),
            daemon=True,
        ).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')