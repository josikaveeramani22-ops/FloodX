#!/usr/bin/env python3
"""Build floodx_combined.html = admin dashboard (v3) + citizen view (v3) in one file."""
from pathlib import Path

ROOT = Path(r"C:\Users\josik\OneDrive\Documents\Default Project")
ADMIN = (ROOT / "floodx_dashboard_v3.html").read_text(encoding="utf-8")
USER = (ROOT / "floodx_user_v3.html").read_text(encoding="utf-8")

# ---------------- extract pieces ----------------
def slice_block(html, start_tag, end_tag):
    i = html.index(start_tag)
    j = html.index(end_tag, i) + len(end_tag)
    return html[i:j]

def css_between(html):
    i = html.index("<style>") + len("<style>")
    j = html.rindex("</style>")
    return html[i:j].strip()

admin_style = css_between(ADMIN)
user_style = css_between(USER)

# body content precedes the main <script> (last one in each file)
def body_and_script(html):
    body_i = html.index("<body>") + len("<body>")
    scr_i = html.rindex("<script>")
    scr_j = html.rindex("</script>") + len("</script>")
    return html[body_i:scr_i].strip(), html[scr_i:scr_j]

admin_body, admin_script = body_and_script(ADMIN)
user_body, user_script = body_and_script(USER)

# ---------------- CSS ----------------
user_style = user_style.replace("#map{", "#mapCitizen{")

SCOPED_CSS = """
#adminRoot{display:flex;flex-direction:column;height:100vh;overflow:hidden}
#citizenRoot{display:none;height:100vh;overflow:hidden}
#mapCitizen{flex:1;border-radius:12px;border:1px solid var(--border);min-height:320px;z-index:1}
#adminRoot .panel{border-radius:10px;padding:12px}
#citizenRoot .panel{border-radius:12px;padding:14px;margin-bottom:14px}
#adminRoot .metrics{grid-template-columns:1fr 1fr 1fr 1fr;gap:6px}
#adminRoot .metric{border-radius:8px;padding:8px}
#adminRoot .m-value{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums}
#adminRoot .m-unit{font-size:9px;color:var(--muted);font-weight:400;margin-left:2px}
#citizenRoot .metrics{grid-template-columns:1fr 1fr;gap:8px}
#citizenRoot .metric{border-radius:9px;padding:10px}
#citizenRoot .m-value{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
#citizenRoot .m-unit{font-size:10px;color:var(--muted);font-weight:500;margin-left:3px}
#adminRoot .chip{font-size:9px;font-weight:800;padding:1px 8px;border-radius:8px;display:inline-block;background:none;border:none}
#citizenRoot .chips{display:grid;grid-template-columns:1fr 1fr;gap:6px}
#citizenRoot .chip{background:var(--card2);border:1px solid var(--border);border-radius:8px;padding:7px 9px;font-size:11px;display:flex;align-items:center;gap:7px}
#adminRoot .risk-badge{font-size:10px;font-weight:800;padding:2px 9px;border-radius:11px}
#citizenRoot .risk-badge{font-size:11px;font-weight:800;padding:3px 10px;border-radius:12px;letter-spacing:.04em}
/* compact admin tab bar — docked back to the TOP as a slim dock (wider tabs) */
#adminRoot .tabbar{order:0;height:34px;padding:0 10px;justify-content:flex-start;gap:6px}
#adminRoot .content{order:1}
#adminRoot .tab{font-size:12px;padding:5px 18px;border-radius:8px}
#adminRoot .tpill{font-size:9px;padding:1px 6px;margin-left:5px}
/* admin map view: FULL-LENGTH zones column | MAP filling the middle | wider drainage column */
#adminRoot .map-layout{grid-template-columns:250px minmax(0,1fr) 340px;grid-template-rows:1fr auto}
#adminRoot .side-left{grid-column:1;grid-row:1/3}
#adminRoot .side-right{grid-column:3;grid-row:1/3}
#adminRoot .map-main{grid-column:2;grid-row:1;min-width:0}
/* alerts + safer route sit BELOW the map, side by side (horizontal) */
#adminRoot .bottom-bar{grid-column:2;grid-row:2;padding:8px 10px;gap:10px}
#adminRoot .bottom-bar .bb-alerts,#adminRoot .bottom-bar .bb-routes{min-width:0;max-height:260px}
/* "Select a street" panel lives in the right column next to Drainage health */
#adminRoot .side-right .bb-street{flex:none;min-width:0;max-width:none;max-height:none;overflow:visible}
/* FloodX brand / tagline line (admin dock + resident top strip) */
.brandline{display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;min-width:0;flex:0 1 auto;color:var(--muted);font-size:11px;font-weight:500}
.brandline b{flex:none;font-size:13px;font-weight:800;color:var(--text);letter-spacing:.02em}
.brandline span{overflow:hidden;text-overflow:ellipsis}
#adminRoot .brandline{flex:0 1 auto;min-width:80px;padding-right:10px;margin-right:4px;border-right:1px solid var(--border);height:20px}
#citizenRoot .brandline{display:flex;height:28px;padding:0 14px;background:var(--bg2);border-bottom:1px solid var(--border)}
@media (max-width:1280px){.brandline span{display:none}}
/* remove top bars (navbar + citizen topbar) and file banners */
#adminRoot .navbar{display:none}
#citizenRoot .topbar{display:none}
#citizenRoot .layout{height:calc(100vh - 58px)}
#fileBanner,#fileBannerCitizen{display:none}
/* citizen full-screen MAP page + bottom dock */
#citizenRoot{position:relative}
#citMapWrap{position:relative;flex:1;min-height:0}
#mapPage{position:absolute;left:0;right:0;top:28px;bottom:30px;background:var(--bg);z-index:60;display:none}
#mapPage #citMapWrap{position:absolute;inset:0;display:flex;flex-direction:column;flex:none}
#mapPage #mapCitizen{flex:1;height:auto;min-height:0}
#citizenRoot .cit-dock{position:absolute;left:0;right:0;bottom:0;height:30px;z-index:70;display:flex;align-items:center;justify-content:center;gap:6px;background:var(--bg2);border-top:1px solid var(--border)}
#citizenRoot .ctab{background:transparent;border:none;color:var(--muted);font-size:11px;padding:3px 14px;border-radius:7px;cursor:pointer}
#citizenRoot .ctab:hover{color:var(--text)}
#citizenRoot .ctab.active{background:var(--card);color:var(--accent);font-weight:700}
/* resident: my zone | routes stacked in ONE column | fixed SQUARE map in the next column */
#citizenRoot .layout{grid-template-columns:340px 320px minmax(0,1fr)}
#citizenRoot .col-map{overflow-y:auto;padding:10px}
#citizenRoot .col-map > div{display:flex !important;flex-direction:column;gap:12px}
#citizenRoot .col-map .panel{margin:0}
#citColMapSq{grid-column:3;padding:12px;display:flex;align-items:center;justify-content:center;overflow:hidden;min-width:0;min-height:0}
#citColMapSq #citMapWrap{position:relative;flex:0 0 auto;display:flex;flex-direction:column;width:min(100%,calc(100vh - 90px));aspect-ratio:1/1;max-height:100%;border-radius:12px;overflow:hidden}
#citColMapSq #mapCitizen{flex:1;min-height:0;height:auto}
/* floating mode switch */
.modefab{position:fixed;right:14px;bottom:42px;z-index:9999;background:var(--accent, #2dd4bf);color:#fff;border:none;border-radius:20px;padding:9px 15px;font-size:12px;font-weight:700;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.35)}
.modefab:hover{filter:brightness(1.1)}
body{display:block}
"""

# ---------------- admin HTML transforms ----------------
admin_body = admin_body.replace(
    '<a class="toplink" href="/user">👤 Resident view →</a>',
    '<a class="toplink" href="javascript:void(0)" onclick="goMode(\'citizen\')">👤 Resident view →</a>',
)

# balanced-div extractor (used by the citizen transform below)
import re as _re
def _extract_div(html, start):
    """Return (block, end_index) for the balanced <div> starting at `start`."""
    depth, i = 0, start
    pat = _re.compile(r"<div\b|</div>")
    while True:
        m = pat.search(html, i)
        assert m, "unbalanced div"
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                return html[start:m.end()], m.end()
        else:
            depth += 1
        i = m.end()

# FloodX name + tagline — shown in the admin tab dock and atop the resident view
TAGLINE = '<b>FloodX</b><span>– A dashboard for real-time urban flood monitoring, risk assessment, and early warning.</span>'
admin_body = admin_body.replace(
    '<div class="tabbar">',
    '<div class="tabbar"><div class="brandline">' + TAGLINE + '</div>',
    1,
)
assert 'class="brandline"' in admin_body, "admin tagline insert failed"
assert '<div class="bottom-bar">' in admin_body, "admin bottom row must stay at the bottom"

# move the "Select a street" (CCTV street) panel out of the bottom strip and into
# the right-hand column, together with Drainage health
_st_i = admin_body.index('<div class="panel bb-street">')
_st_block, _st_end = _extract_div(admin_body, _st_i)
admin_body = admin_body[:_st_i] + admin_body[_st_end:]
_sr_i = admin_body.index('<div class="side-right">')
_sr_block, _sr_end = _extract_div(admin_body, _sr_i)
_ins = _sr_end - len('</div>')
admin_body = admin_body[:_ins] + _st_block + '\n      ' + admin_body[_ins:]
assert admin_body.count('class="panel bb-street"') == 1, "street panel move failed"
assert admin_body.count('class="panel bb-alerts"') == 1 and admin_body.count('class="panel bb-routes"') == 1, "alerts/routes must stay below the map"

# ---------------- user HTML transforms ----------------
user_body = '<div class="brandline">' + TAGLINE + '</div>\n' + user_body
assert user_body.startswith('<div class="brandline">'), "resident tagline insert failed"
user_body = user_body.replace(
    '<a class="toplink" href="/">⚙️ Admin dashboard →</a>',
    '<a class="toplink" href="javascript:void(0)" onclick="goMode(\'admin\')">⚙️ Admin dashboard →</a>',
)
for old, new in [
    ('id="fileBanner"', 'id="fileBannerCitizen"'),
    ('id="map"', 'id="mapCitizen"'),
    ('id="mapErr"', 'id="mapErrCitizen"'),
    ('id="clock"', 'id="clockCitizen"'),
]:
    assert old in user_body, "missing " + old
    user_body = user_body.replace(old, new)

# ---------------- citizen: move the map into its own full-screen page ----------------
WRAP_START = '<div style="position:relative;flex:1;min-height:0">'
ws = user_body.index(WRAP_START)
inner = ws + len(WRAP_START)
gb = user_body.index('<button class="gotobox"', ws)
ge = user_body.index('</button>', gb) + len('</button>')
close_i = user_body.index('</div>', ge)
wrap = '<div id="citMapWrap">' + user_body[inner:close_i] + '</div>'
user_body = user_body[:ws] + user_body[close_i + len('</div>'):]
user_body = user_body.replace('<div class="col-map">', '<div class="col-map" id="citColMap">', 1)
# ... and give the square map its own dedicated third column, right after the route column
_cm_i = user_body.index('<div class="col-map" id="citColMap">')
_cm_block, _cm_end = _extract_div(user_body, _cm_i)
user_body = user_body[:_cm_end] + '\n  <div id="citColMapSq"></div>' + user_body[_cm_end:]
assert 'id="citColMapSq"' in user_body, "square-map column insert failed"
CIT_DOCK = (
    '\n<div class="cit-dock">'
    '<button class="ctab active" data-cpage="overview" onclick="citizenPage(\'overview\')">🏠 Overview</button>'
    '<button class="ctab" data-cpage="map" onclick="citizenPage(\'map\')">🗺️ Full map</button>'
    '</div>'
)
user_body += '\n<div id="mapPage">' + wrap + '</div>' + CIT_DOCK
assert 'id="mapPage"' in user_body and 'citMapWrap' in user_body and 'cit-dock' in user_body

# ---------------- admin script transforms ----------------
admin_script = admin_script.replace(
    "const okMap = initMap();",
    "const okMap = initMap(); window.__adminMap = map;",
)
assert "window.__adminMap" in admin_script, "admin initMap patch failed"
admin_script = admin_script.replace(
    "'http://localhost:8000/v3'", "'http://localhost:8000/combined'"
).replace("location.origin+'/v3'", "location.origin+'/combined'")

# ---------------- user script transforms ----------------
assert "id=\"map\"" not in user_body
for old, new in [
    ("L.map('map', ", "L.map('mapCitizen', "),
    ("getElementById('map')", "getElementById('mapCitizen')"),
    ("getElementById('mapErr')", "getElementById('mapErrCitizen')"),
    ("getElementById('clock')", "getElementById('clockCitizen')"),
    ("getElementById('fileBanner')", "getElementById('fileBannerCitizen')"),
]:
    assert old in user_script, "missing user JS token: " + old
    user_script = user_script.replace(old, new)

boot_live_old = (
    "if(location.protocol!=='file:') setTimeout(connectFeed, 400);\n"
    "else setTimeout(()=>{ try{ testFeed(); }catch(e){} }, 900);"
)
boot_live_new = (
    "window.__citizenStartLive = function(){\n"
    "  if (window.__citizenLiveDone) return; window.__citizenLiveDone = true;\n"
    "  if (location.protocol === 'file:'){ try{ testFeed(); }catch(e){} }\n"
    "  else { try{ connectFeed(); }catch(e){} }\n"
    "};"
)
assert boot_live_old in user_script, "citizen boot-live patch failed"
user_script = user_script.replace(boot_live_old, boot_live_new)

user_script = user_script.replace(
    "'http://localhost:8000/userv3'", "'http://localhost:8000/combined'"
).replace("location.origin+'/userv3'", "location.origin+'/combined'")

# ---------------- tiles ----------------
# OSM blocks file:// apps (403 "Access blocked") and CARTO now needs an API key,
# so use Esri's open tile services: primary = World Street Map, fallback = World Topo.
_ESRI_ATTR = "attribution:'\u00a9 Esri, TomTom, Garmin, FAO, NOAA, USGS, OpenStreetMap contributors'"
for name in ("admin_script", "user_script"):
    _s = globals()[name]
    _s = _s.replace(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    ).replace(
        "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    ).replace(
        "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    ).replace(
        "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    ).replace(
        "attribution:'\u00a9 OpenStreetMap \u00a9 CARTO'", _ESRI_ATTR,
    ).replace(
        "attribution:'\u00a9 OpenStreetMap'", _ESRI_ATTR,
    )
    globals()[name] = _s
assert "tile.openstreetmap.org" not in admin_script + user_script, "OSM tiles must be gone"
assert "basemaps.cartocdn.com" not in admin_script + user_script, "CARTO tiles must be gone"
assert "arcgisonline.com" in admin_script and "arcgisonline.com" in user_script, "Esri tiles missing"

EXPOSURES = """
/* expose for inline handlers + combined-mode control */
window.connectFeed = connectFeed;
window.testFeed = testFeed;
window.recomputeRoutes = recomputeRoutes;
window.focusRoute = focusRoute;
window.bootMap = bootMap;
function fitZones(){
  if(!map || !window.L) return;
  try{
    map.invalidateSize();
    map.fitBounds(L.latLngBounds(ZONES.map(function(z){ return [z.lat, z.lng]; })),
      { padding:[55,55], maxZoom:16, animate:false });
  }catch(e){}
}
function citizenPage(p){
  var mp = document.getElementById('mapPage');
  var wrap = document.getElementById('citMapWrap');
  var col = document.getElementById('citColMapSq');
  var tabs = document.querySelectorAll('#citizenRoot .ctab');
  for (var i=0;i<tabs.length;i++){
    tabs[i].classList.toggle('active', tabs[i].getAttribute('data-cpage') === p);
  }
  if (p === 'map'){
    if (wrap.parentNode !== mp){ mp.appendChild(wrap); }
    mp.style.display = 'block';
    setTimeout(function(){
      try{
        if (!map){ bootAttempts = 0; bootMap(); }
        if (map){ fitZones(); renderMap(); drawRoutes(); }
      }catch(e){}
    }, 160);
  } else {
    mp.style.display = 'none';
    if (wrap.parentNode !== col){ col.appendChild(wrap); }
    setTimeout(function(){ try{ if (map) map.invalidateSize(); }catch(e){} }, 160);
  }
}
window.citizenPage = citizenPage;
window.__citizenShow = function(first){
  if (first){ bootAttempts = 0; }
  bootMap();
  setTimeout(function(){ try{
    if (mapLoaded && map){ updateMyZone(); fitZones(); }
    else { bootMap(); }
  }catch(e){} }, 600);
};
"""
user_script = user_script.rstrip()
assert user_script.endswith("</script>")
user_script = user_script[:-len("</script>")] + EXPOSURES + "</script>"
# wrap in an IIFE so the two apps' globals never collide
user_script = user_script.replace("<script>", "<script>\n(function(){\n", 1)
user_script = user_script.replace("</script>", "})();\n</script>", 1)

# ---------------- head + final control script ----------------
HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FloodX 2.0 — Urban Flood Nowcasting (Admin + Citizen)</title>
<script>window.__L = false;</script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script>
window.__L = window.L || null;
(function () {
  function loadScript(src, cb) {
    var s = document.createElement('script');
    s.src = src;
    s.onload = function () { cb(true); };
    s.onerror = function () { cb(false); };
    document.head.appendChild(s);
  }
  window.__loadLeaflet = function (cb) {
    if (window.L && L.map) { if (cb) cb(true); return; }
    loadScript('https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js', function (ok) {
      if (window.L && L.map) { if (cb) cb(true); return; }
      loadScript('https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js', function (ok2) {
        if (window.L && L.map) { if (cb) cb(true); }
        else if (cb) cb(false);
      });
    });
  };
  setTimeout(function () {
    if (!(window.L && L.map)) { try { window.__loadLeaflet(); } catch (e) {} }
  }, 2500);
})();
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" onerror="try{window.__loadLeaflet&&window.__loadLeaflet()}catch(e){}"></script>
<style>
"""

CONTROL = """
<script>
/* ── combined mode switcher: ADMIN <-> CITIZEN ── */
var __jointMode = 'admin';
function goMode(m){
  __jointMode = m;
  document.getElementById('adminRoot').style.display   = (m === 'admin')   ? 'flex'  : 'none';
  document.getElementById('citizenRoot').style.display = (m === 'citizen') ? 'block' : 'none';
  if (m === 'admin'){
    if (window.__adminMap) setTimeout(function(){ try{ window.__adminMap.invalidateSize(); }catch(e){} }, 180);
  } else {
    if (window.citizenPage)        citizenPage('overview');
    if (window.__citizenShow)    window.__citizenShow(true);
    if (window.__citizenStartLive) window.__citizenStartLive();
  }
  if (window.__fabLabel) window.__fabLabel();
}
if (location.hash === '#citizen'){ setTimeout(function(){ goMode('citizen'); }, 30); }
/* floating switch fab */
var __fab = document.createElement('button');
__fab.className = 'modefab';
window.__fabLabel = function(){
  __fab.textContent = (__jointMode === 'admin') ? '👤 Resident view' : '⚙️ Admin dashboard';
};
__fab.onclick = function(){ goMode(__jointMode === 'admin' ? 'citizen' : 'admin'); };
__fabLabel();
document.body.appendChild(__fab);
</script>
</body>
</html>
"""

out = (
    HEAD +
    admin_style + "\n/* ═══ citizen styles ═══ */\n" + user_style +
    SCOPED_CSS + "\n</style>\n</head>\n<body>\n"
    '<div id="adminRoot">\n' + admin_body + "\n</div>\n"
    '<div id="citizenRoot">\n' + user_body + "\n</div>\n"
    + "\n<!-- ═══════════ ADMIN SCRIPT ═══════════ -->\n" + admin_script + "\n"
    + "\n<!-- ═══════════ CITIZEN SCRIPT (scoped) ═══════════ -->\n" + user_script + "\n"
    + CONTROL
)

target = ROOT / "floodx_combined_v2.html"
target.write_text(out, encoding="utf-8")
print("wrote", target, len(out), "bytes")
print("admin map ids:", out.count('id="map"'), "| citizen map ids:", out.count('id="mapCitizen"'))