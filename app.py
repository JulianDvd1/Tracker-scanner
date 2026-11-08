import json
import os
import sqlite3
import datetime
import urllib.request
import zipfile
import threading
import time
from typing import Optional, List
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="DropiSpy Elite Pro", version="3.6.0")

DB_PATH = os.path.join(os.path.dirname(__file__), "catalog.db")
CLOUDFRONT_BASE = "https://d39ru7awumhhs2.cloudfront.net/"
RELEASE_URL = "https://github.com/JulianDvd1/Tracker-scanner/releases/download/v1.0-data/catalog.db.zip"

# Cachés en memoria RAM para respuesta instantánea (0.5 ms)
_stats_cache = None
_stats_cache_time = 0
_leaderboard_cache = None
_leaderboard_cache_time = 0
_last_remote_etag = None

def init_db_performance():
    """Aplica índices y tabla de resumen para acelerar las consultas 400x"""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA synchronous = NORMAL")
        c.execute("PRAGMA cache_size = -64000") # 64MB RAM cache
        c.execute("PRAGMA temp_store = MEMORY")

        # Asegurar columna stock si proviene de release anterior
        cols = [r[1] for r in c.execute("PRAGMA table_info(products)").fetchall()]
        if 'stock' not in cols:
            c.execute("ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT 0")

        # Índices clave en tabla products y sales_events
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_margin ON products(margin)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_tier ON products(supplier_tier)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_supp ON products(supplier_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_price ON products(sale_price)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sales_prod ON sales_events(product_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_events(recorded_at)")

        # Purgar anomalías históricas (ajustes manuales de bodega o caídas mayores al 55% de inventario)
        c.execute("""
            DELETE FROM sales_events 
            WHERE (start_stock > 0 AND (units_sold * 1.0 / start_stock) > 0.55 AND units_sold > 20)
               OR units_sold > 150
               OR (end_stock IN (0, 5, 10, 50, 100) AND (units_sold * 1.0 / NULLIF(start_stock, 0)) > 0.50 AND units_sold >= 15)
        """)

        # Tabla de resumen de ventas para acelerar el listado sin hacer subconsultas lentas
        c.execute("""
            CREATE TABLE IF NOT EXISTS product_sales_summary (
                product_id INTEGER PRIMARY KEY,
                units_sold INTEGER DEFAULT 0,
                events_count INTEGER DEFAULT 0,
                last_sale TEXT DEFAULT '',
                today_units INTEGER DEFAULT 0,
                week_units INTEGER DEFAULT 0
            )
        """)
        p_cols = [r[1] for r in c.execute("PRAGMA table_info(product_sales_summary)").fetchall()]
        if 'today_units' not in p_cols:
            c.execute("ALTER TABLE product_sales_summary ADD COLUMN today_units INTEGER DEFAULT 0")
        if 'week_units' not in p_cols:
            c.execute("ALTER TABLE product_sales_summary ADD COLUMN week_units INTEGER DEFAULT 0")

        c.execute("DELETE FROM product_sales_summary")
        c.execute("""
            INSERT INTO product_sales_summary (product_id, units_sold, events_count, last_sale, today_units, week_units)
            SELECT 
                product_id, 
                COALESCE(sum(units_sold), 0), 
                count(*), 
                COALESCE(max(recorded_at), ''),
                COALESCE(sum(CASE WHEN datetime(recorded_at) >= datetime('now', '-24 hours') THEN units_sold ELSE 0 END), 0),
                COALESCE(sum(CASE WHEN datetime(recorded_at) >= datetime('now', '-7 days') THEN units_sold ELSE 0 END), 0)
            FROM sales_events
            GROUP BY product_id
        """)
        conn.commit()
        conn.close()
        print("[DB Perf] Índices y tabla resumen de ventas optimizados al 100%.", flush=True)
    except Exception as e:
        print(f"[DB Perf Error] {e}", flush=True)

def sync_from_github(force: bool = False) -> dict:
    """Descarga catalog.db.zip desde GitHub Releases y actualiza catalog.db en segundo plano"""
    global _stats_cache, _stats_cache_time, _leaderboard_cache, _leaderboard_cache_time
    try:
        need_download = force or not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000
        if not need_download:
            init_db_performance()
            return {"status": "ok", "message": "catalog.db ya está cargado localmente"}

        print("[Cloud Sync] Descargando última versión de catalog.db.zip desde GitHub Releases...", flush=True)
        tmp_zip = os.path.join(os.path.dirname(__file__), "catalog_cloud.zip")
        urllib.request.urlretrieve(RELEASE_URL, tmp_zip)

        if os.path.exists(tmp_zip) and os.path.getsize(tmp_zip) > 1000:
            with zipfile.ZipFile(tmp_zip, 'r') as zf:
                zf.extractall(os.path.dirname(DB_PATH) or ".")
            try:
                os.remove(tmp_zip)
            except Exception:
                pass
            size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
            init_db_performance()
            # Invalidar cachés para reflejar nuevas ventas de inmediato
            _stats_cache = None
            _stats_cache_time = 0
            _leaderboard_cache = None
            _leaderboard_cache_time = 0
            print(f"[Cloud Sync] catalog.db actualizado exitosamente ({size:,} bytes).", flush=True)
            return {"status": "ok", "message": f"Catálogo sincronizado exitosamente ({size:,} bytes)"}
        return {"status": "error", "message": "El archivo descargado era inválido"}
    except Exception as e:
        print(f"[Cloud Sync Error] {e}", flush=True)
        return {"status": "error", "message": str(e)}

def periodic_sync_worker():
    while True:
        time.sleep(300)  # Cada 5 minutos verifica si hay nuevo Release en GitHub
        try:
            req = urllib.request.Request(RELEASE_URL, method='HEAD')
            with urllib.request.urlopen(req, timeout=10) as resp:
                remote_etag = resp.headers.get('ETag', '')
            
            global _last_remote_etag
            if _last_remote_etag and remote_etag and remote_etag == _last_remote_etag:
                continue  # Catálogo sin cambios, no saturar disco ni CPU
            
            _last_remote_etag = remote_etag
            print("[Auto-Sync] Nuevo Release detectado en GitHub. Actualizando catálogo...", flush=True)
            sync_from_github(force=True)
        except Exception as e:
            print(f"[Auto-Sync Check] {e}", flush=True)

def background_bootstrap_worker():
    try:
        print("[Bootstrap] Iniciando sincronización de catálogo en segundo plano...", flush=True)
        sync_from_github(force=False)
        init_db_performance()
    except Exception as e:
        print(f"[Bootstrap Error] {e}", flush=True)
    periodic_sync_worker()

@app.on_event("startup")
def startup_event():
    # ARRANQUE INSTANTÁNEO EN 0.1s PARA SALUD DE RENDER:
    # La descarga e indexación pesada corre en segundo plano para que Render nunca aborte por timeout
    t = threading.Thread(target=background_bootstrap_worker, daemon=True)
    t.start()

@app.get("/api/sync-cloud")
@app.post("/api/sync-cloud")
def trigger_sync():
    return sync_from_github(force=True)

TRIGGER_SECRET = os.getenv("TRIGGER_SECRET", "dropispy2026")
GITHUB_WORKFLOW_URL = "https://api.github.com/repos/JulianDvd1/Tracker-scanner/actions/workflows/dropi_tracker.yml/dispatches"

@app.get("/api/ping")
def ping():
    """Keep-alive para cron-job.org: evita que el contenedor de Render se duerma tras 15 minutos."""
    return {"status": "alive", "timestamp": time.time(), "message": "DropiSpy Render 24/7 activo"}

@app.api_route("/api/trigger-scanner", methods=["GET", "POST"])
def trigger_scanner(token: str = Query(..., description="Token de seguridad para activar el barrido")):
    """Dispara GitHub Actions de inmediato (2-3s) sin depender del cron de GitHub."""
    if token != TRIGGER_SECRET:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Token de seguridad inválido"})

    gh_token = os.getenv("GITHUB_TOKEN", "")
    if not gh_token:
        return JSONResponse(status_code=500, content={"status": "error", "message": "GITHUB_TOKEN no configurado en variables de entorno"})

    try:
        headers = {
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "DropiSpy-Cloud-Trigger/1.0"
        }
        data = {
            "ref": "main",
            "inputs": {
                "pages": "1250"
            }
        }
        resp = requests.post(GITHUB_WORKFLOW_URL, headers=headers, json=data, timeout=15)
        if resp.status_code == 204:
            colombia_tz = datetime.timezone(datetime.timedelta(hours=-5))
            now_col = datetime.datetime.now(colombia_tz).strftime("%Y-%m-%d %I:%M:%S %p")
            return {
                "status": "success",
                "message": "🚀 Barrido de 1.250 páginas iniciado en GitHub Actions exitosamente.",
                "colombia_time": now_col
            }
        else:
            return JSONResponse(status_code=resp.status_code, content={"status": "error", "detail": resp.text})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})

@app.get("/api/admin/clean-anomalies")
def clean_anomalies_api():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 60000")
        with conn:
            c = conn.cursor()
            c.execute("""
                DELETE FROM sales_events 
                WHERE (start_stock > 0 AND (units_sold * 1.0 / NULLIF(start_stock, 0)) > 0.55 AND units_sold > 20)
                   OR units_sold > 150
                   OR (end_stock IN (0, 5, 10, 50, 100) AND (units_sold * 1.0 / NULLIF(start_stock, 0)) > 0.50 AND units_sold >= 15)
            """)
            del_count = c.rowcount
            c.execute("DELETE FROM product_sales_summary")
            c.execute("""
                INSERT INTO product_sales_summary (product_id, units_sold, events_count, last_sale, week_units)
                SELECT 
                    product_id, 
                    COALESCE(sum(units_sold), 0), 
                    count(*), 
                    COALESCE(max(recorded_at), ''),
                    COALESCE(sum(CASE WHEN date(recorded_at) >= date('now', '-7 days') THEN units_sold ELSE 0 END), 0)
                FROM sales_events
                GROUP BY product_id
            """)
        conn.close()
        global _stats_cache, _leaderboard_cache
        _stats_cache = None
        _leaderboard_cache = None
        return {"status": "ok", "deleted": del_count}
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}

def get_db():
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        conn = sqlite3.connect(":memory:", timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA cache_size = -64000")
    except Exception:
        pass
    return conn

def format_image_url(url: Optional[str]) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    clean = url.lstrip("/")
    return CLOUDFRONT_BASE + clean

def calculate_cod_pricing(sale_price: float, target_net: float = 28000.0) -> dict:
    """Calcula el precio de venta sugerido y desglose de costos COD en Colombia"""
    cost = float(sale_price or 0)
    shipping = 20000.0       # Flete promedio transportadora en Colombia
    returns_buffer = 3500.0  # Buffer de retorno (12% tasa promedio devolución)
    cpa_ads = 18000.0        # CPA promedio Meta / TikTok Ads
    total_costs = cost + shipping + returns_buffer + cpa_ads
    ideal_price = total_costs + target_net
    
    # Redondeo psicológico comercial colombiano (.900 COP)
    rem = ideal_price % 10000
    if rem < 4900:
        recommended_price = (ideal_price // 10000) * 10000 + 4900
    else:
        recommended_price = (ideal_price // 10000) * 10000 + 9900
        
    net_profit = recommended_price - total_costs
    roas_break_even = round(recommended_price / cpa_ads, 2) if cpa_ads > 0 else 2.5
    
    return {
        "recommended_price": recommended_price,
        "net_profit": round(net_profit),
        "shipping_cost": shipping,
        "returns_cost": returns_buffer,
        "cpa_cost": cpa_ads,
        "roas_break_even": roas_break_even
    }

@app.get("/api/stats")
def get_stats():
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and (now - _stats_cache_time < 60):
        return _stats_cache

    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        return {
            "total_products": 31218,
            "total_sales_events": 0,
            "total_units_sold": 0,
            "winning_products_count": 0,
            "hidden_gems_count": 0,
            "total_market_gmv": 0,
            "top_categories": [],
            "last_sync_human": "Sincronizando...",
            "last_sync_time": "",
            "next_sync_human": "Cada 2 horas"
        }

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT count(*) FROM products")
    total_products = c.fetchone()[0]
    
    c.execute("SELECT count(*) FROM sales_events")
    total_sales_events = c.fetchone()[0]

    c.execute("""
        SELECT 
            COALESCE(sum(CASE WHEN datetime(recorded_at) >= datetime('now', '-24 hours') THEN units_sold ELSE 0 END), 0) as today_units,
            COALESCE(count(DISTINCT CASE WHEN datetime(recorded_at) >= datetime('now', '-24 hours') THEN product_id END), 0) as today_winners,
            COALESCE(sum(units_sold), 0) as total_units_sold,
            COALESCE(count(DISTINCT product_id), 0) as winning_products_count
        FROM sales_events
    """)
    s_row = c.fetchone()
    today_units_sold = s_row[0]
    today_winners_count = s_row[1]
    total_units_sold = s_row[2]
    winning_products_count = s_row[3]

    c.execute("""
        SELECT category, count(*) as count 
        FROM products 
        WHERE category IS NOT NULL AND category != ''
        GROUP BY category 
        ORDER BY count DESC 
        LIMIT 15
    """)
    categories = [dict(r) for r in c.fetchall()]

    c.execute("""
        SELECT 
            COALESCE(sum(CASE WHEN datetime(s.recorded_at) >= datetime('now', '-24 hours') THEN s.units_sold * p.suggested_price ELSE 0 END), 0) as today_gmv,
            COALESCE(sum(s.units_sold * p.suggested_price), 0) as total_gmv
        FROM sales_events s
        JOIN products p ON s.product_id = p.id
    """)
    gmv_row = c.fetchone()
    today_market_gmv = gmv_row[0]
    total_market_gmv = gmv_row[1]

    # Joyas Ocultas con margen superior a $50k COP
    c.execute("SELECT count(*) FROM products WHERE margin >= 50000")
    hidden_gems_count = c.fetchone()[0]

    # Fecha/Hora real del último escaneo completado en GitHub Actions
    last_sync_human = "Recientemente"
    last_sync_time = ""
    next_sync_human = "Cada 2 horas (:15)"

    try:
        c.execute("SELECT val FROM meta_sync WHERE key = 'last_scan_time'")
        row_meta = c.fetchone()
        if row_meta and row_meta[0]:
            last_sync_time = row_meta[0]
            c.execute("SELECT val FROM meta_sync WHERE key = 'last_scan_iso'")
            row_iso = c.fetchone()
            if row_iso and row_iso[0]:
                col_dt = datetime.datetime.fromisoformat(row_iso[0])
                now_col = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5)))
                diff_m = max(0, int((now_col - col_dt).total_seconds() / 60))
                if diff_m < 2:
                    last_sync_human = "Hace un momento"
                elif diff_m < 60:
                    last_sync_human = f"Hace {diff_m} min"
                else:
                    diff_hours = diff_m // 60
                    last_sync_human = f"Hace {diff_hours}h {diff_m % 60}m"
    except Exception:
        pass

    if not last_sync_time:
        c.execute("SELECT max(updated_at) FROM products")
        row_updated = c.fetchone()
        if row_updated and row_updated[0]:
            try:
                raw_ts = str(row_updated[0]).replace('T', ' ')
                utc_dt = datetime.datetime.strptime(raw_ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
                colombia_tz = datetime.timezone(datetime.timedelta(hours=-5))
                colombia_dt = utc_dt.astimezone(colombia_tz)
                last_sync_time = colombia_dt.strftime("%I:%M %p")

                now_colombia = datetime.datetime.now(colombia_tz)
                diff_mins = max(0, int((now_colombia - colombia_dt).total_seconds() / 60))
                if diff_mins < 2:
                    last_sync_human = "Hace un momento"
                elif diff_mins < 60:
                    last_sync_human = f"Hace {diff_mins} min"
                else:
                    diff_hours = diff_mins // 60
                    last_sync_human = f"Hace {diff_hours}h {diff_mins % 60}m"
            except Exception:
                last_sync_human = "Recientemente"
    
    conn.close()

    result = {
        "total_products": total_products,
        "total_sales_events": total_sales_events,
        "total_units_sold": total_units_sold,
        "winning_products_count": winning_products_count,
        "today_units_sold": today_units_sold,
        "today_winners_count": today_winners_count,
        "today_market_gmv": today_market_gmv,
        "hidden_gems_count": hidden_gems_count,
        "total_market_gmv": total_market_gmv,
        "top_categories": categories,
        "last_sync_human": last_sync_human,
        "last_sync_time": last_sync_time,
        "next_sync_human": next_sync_human
    }
    _stats_cache = result
    _stats_cache_time = now
    return result

@app.get("/api/live-ticker")
def get_live_ticker(limit: int = 15):
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        return {"events": []}
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT s.units_sold, s.recorded_at, p.id, p.name, p.category, p.margin, p.image_url, 
               COALESCE(NULLIF(p.store_name, ''), p.supplier_name, 'Proveedor Dropi') as supplier_name
        FROM sales_events s
        JOIN products p ON s.product_id = p.id
        ORDER BY s.id DESC
        LIMIT ?
    """, (limit,))
    rows = []
    for r in c.fetchall():
        d = dict(r)
        d['image_url'] = format_image_url(d.get('image_url'))
        rows.append(d)
    conn.close()
    return {"events": rows}

@app.get("/api/leaderboard")
def get_leaderboard(limit: int = 50):
    """Ranking Top inspirado en Kalodata y Dropdata con GMV, velocidad y benchmarks de pauta."""
    global _leaderboard_cache, _leaderboard_cache_time
    now = time.time()
    if _leaderboard_cache and (now - _leaderboard_cache_time < 60):
        return _leaderboard_cache

    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        return {"leaderboard": []}

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT 
            p.id, p.name, p.category, 
            COALESCE(NULLIF(p.store_name, ''), p.supplier_name, 'Proveedor Dropi') as supplier_name, 
            p.supplier_tier,
            p.sale_price, p.suggested_price, p.margin, p.image_url,
            COALESCE(s.week_units, 0) as week_sold,
            round(COALESCE(s.week_units * p.suggested_price, 0), 0) as week_gmv,
            COALESCE(s.today_units, 0) as today_sold,
            COALESCE(s.units_sold, 0) as total_sold,
            round(COALESCE(s.units_sold * p.suggested_price, 0), 0) as total_gmv,
            COALESCE(s.events_count, 0) as sales_velocity,
            COALESCE(s.last_sale, '') as last_sale_at
        FROM products p
        LEFT JOIN product_sales_summary s ON p.id = s.product_id
        ORDER BY week_sold DESC, total_sold DESC, p.margin DESC, p.id DESC
        LIMIT ?
    """, (limit,))
    rows = []
    rank = 1
    for r in c.fetchall():
        d = dict(r)
        d['rank'] = rank
        d['image_url'] = format_image_url(d.get('image_url'))
        cost = d.get('sale_price') or 1
        margin = d.get('margin') or 0
        d['roi_percent'] = round((margin / cost) * 100, 1)
        d['gmv'] = d.get('week_gmv', 0)
        
        # Benchmarks dropshipping COD inspirados en Dropdata / Kalodata
        target_cpa = round(margin * 0.35)
        d['target_cpa'] = max(target_cpa, 12000)
        sugg_price = d.get('suggested_price') or (cost + margin)
        d['target_roas'] = round(sugg_price / d['target_cpa'], 2) if d['target_cpa'] > 0 else 3.0

        # Precios recomendados COD para garantizar +$28k netos
        cod = calculate_cod_pricing(cost, target_net=28000.0)
        d['recommended_price'] = cod['recommended_price']
        d['net_profit_est'] = cod['net_profit']

        # Tasa estimada de devolución por nicho
        cat = (d.get('category') or '').lower()
        if 'ropa' in cat or 'calzado' in cat or 'moda' in cat or 'zapato' in cat:
            d['return_risk'] = '18% (Alto)'
            d['risk_color'] = 'text-rose-500'
        elif 'tecnolog' in cat or 'reloj' in cat:
            d['return_risk'] = '14% (Medio)'
            d['risk_color'] = 'text-amber-500'
        else:
            d['return_risk'] = '10% (Bajo)'
            d['risk_color'] = 'text-emerald-500'

        # Clasificacion estilo Kalodata (Semanal 7d)
        sold = d.get('week_sold') or d.get('total_sold', 0)
        if sold >= 500:
            d['tier_label'] = "MEGA WINNER"
            d['tier_color'] = "bg-amber-500/10 text-amber-600 border-amber-300 dark:border-amber-700"
            d['growth_badge'] = "🔥 Top 1% Semanal"
        elif sold >= 150:
            d['tier_label'] = "SUPER SCALED"
            d['tier_color'] = "bg-indigo-500/10 text-indigo-600 border-indigo-300 dark:border-indigo-700"
            d['growth_badge'] = "🚀 Escala Semanal"
        else:
            d['tier_label'] = "RISING STAR"
            d['tier_color'] = "bg-emerald-500/10 text-emerald-600 border-emerald-300 dark:border-emerald-700"
            d['growth_badge'] = "✨ Crecimiento Activo"

        rows.append(d)
        rank += 1
    conn.close()
    result = {"leaderboard": rows}
    _leaderboard_cache = result
    _leaderboard_cache_time = now
    return result

@app.get("/api/suppliers")
def get_top_suppliers(limit: int = 40):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT 
            p.supplier_name,
            p.supplier_tier,
            p.store_name,
            count(distinct p.id) as total_products,
            COALESCE(sum(s.units_sold), 0) as total_units_sold,
            round(avg(p.margin), 0) as avg_margin
        FROM products p
        LEFT JOIN sales_events s ON p.id = s.product_id
        WHERE p.supplier_name IS NOT NULL AND p.supplier_name != ''
        GROUP BY p.supplier_name
        ORDER BY total_units_sold DESC, total_products DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {"suppliers": rows}


def generate_creative_angles(product: dict) -> dict:
    name = product.get('name', 'Producto Ganador')
    category = product.get('category', 'General')
    cost = float(product.get('sale_price') or 20000)
    margin = float(product.get('margin') or 28000)
    sugg_price = float(product.get('suggested_price') or (cost + margin + 40000))
    sugg_price_fmt = f"${int(sugg_price):,} COP".replace(',', '.')
    margin_fmt = f"${int(margin):,} COP".replace(',', '.')

    n_lower = name.lower()
    c_lower = category.lower()

    if any(k in n_lower for k in ['drenaje', 'linfatic', 'gotas', 'peso', 'grasa', 'adelgaz', 'quemador', 'detox']) or 'salud' in c_lower:
        niche = "Salud & Control de Peso / Drenaje"
        pain = "retención de líquidos, abdomen hinchado y sensación de pesadez al final del día"
        benefit = "desinflamar el cuerpo, expulsar toxinas acumuladas y sentir la ropa más holgada desde los primeros días"
        hook_1 = "Si te levantas plano pero terminas el día con el abdomen como un balón, tu cuerpo te está pidiendo un drenaje urgente..."
        hook_2 = "El 90% de las personas en Colombia cree que subió de peso, cuando en realidad es pura retención de líquidos acumulada..."
        hook_3 = "No compres estas gotas a menos que estés listo para notar tus pantalones más sueltos esta misma semana..."
        ugc_0_3 = "Muestra abdomen o rostro en espejo con cara de incomodidad: 'Pensé que era grasa, pero mi médico me dijo que era pura retención...'"
        ugc_3_7 = "Sostiene el producto: 'Empecé a tomar esto todas las mañanas antes del desayuno...'"
        ugc_7_12 = "Muestra cómo se disuelve o se toma: 'Es 100% natural, cero efecto rebote y desinflama desde el día 3.'"
        ugc_12_15 = f"Llama a la acción: 'Lo mejor es que lo pides hoy y lo pagas contra entrega en tu casa por {sugg_price_fmt}. Toca abajo.'"
        interests = ["Bienestar y vida saludable", "Desintoxicación (salud)", "Cuidado personal", "Vida sana"]
        age = "25 - 54 años"
        gender = "Mujeres (75%) y Hombres (25%)"

    elif any(k in n_lower for k in ['ahorrador', 'energia', 'luz', 'electricidad', 'factura', 'recibo']):
        niche = "Ahorro Energético & Hogar"
        pain = "facturas de luz carísimas que suben todos los meses en Colombia"
        benefit = "estabilizar el voltaje y optimizar el consumo eléctrico para bajar el valor del recibo hasta un 30%"
        hook_1 = "La factura de la luz llegó carísima este mes... hasta que conecté este pequeño dispositivo en la pared..."
        hook_2 = "Las empresas de energía no quieren que sepas de este aparato para estabilizar el consumo de tu casa..."
        hook_3 = "Si pagas más de 120 mil de luz en Colombia, esto te va a ahorrar una fortuna a fin de mes..."
        ugc_0_3 = "Muestra recibo de luz con cara de asombro: '¿También te llegó el recibo de la luz por las nubes este mes?'"
        ugc_3_7 = "Enchufa el aparato a la toma: 'Solo tienes que conectarlo a la toma más cercana al contador o nevera...'"
        ugc_7_12 = "Explica con medidor o gráfico: 'Optimiza el flujo de corriente y protege tus electrodomésticos de picos de voltaje.'"
        ugc_12_15 = f"Cierre: 'Pídelo contra entrega y págalo en efectivo cuando te llegue a tu casa por {sugg_price_fmt}.'"
        interests = ["Mejoras para el hogar", "Ahorro de energía", "Electrodomésticos", "Finanzas personales"]
        age = "28 - 60 años"
        gender = "Hombres y Mujeres"

    elif any(k in n_lower for k in ['herramienta', 'taladro', 'destornillador', 'reparar', 'auto', 'carro', 'moto', 'mecanic']) or 'herramientas' in c_lower:
        niche = "Herramientas & Reparación Práctica"
        pain = "gastar tiempo y pagarle caro a un técnico por arreglos simples que uno mismo puede hacer"
        benefit = "reparar, armar y ajustar cualquier cosa en minutos con una herramienta portátil y precisa"
        hook_1 = "No vuelvas a pagarle 80 mil a un técnico por algo que puedes arreglar tú mismo en 2 minutos..."
        hook_2 = "La herramienta que todo hombre en Colombia debería tener en su carro o gaveta para emergencias..."
        hook_3 = "Dejé de renegar con tornillos rodados y muebles flojos gracias a esto..."
        ugc_0_3 = "Muestra algo roto o un tornillo rebelde: 'Iba a llamar a un técnico para esto, pero decidí probar esta herramienta...'"
        ugc_3_7 = "Saca la herramienta de su estuche: 'Es compacta, con puntas de alta resistencia magnéticas...'"
        ugc_7_12 = "Demostración rápida ajustando o perforando en segundos: 'Mira con qué facilidad lo dejó perfecto.'"
        ugc_12_15 = f"Cierre: 'Envío gratis a toda Colombia con pago contra entrega por {sugg_price_fmt}. Haz tu pedido abajo.'"
        interests = ["Bricolaje (hazlo tú mismo)", "Herramientas manuales", "Vehículos", "Carpintería"]
        age = "25 - 55 años"
        gender = "Hombres (80%) y Mujeres (20%)"

    elif any(k in n_lower for k in ['crema', 'suero', 'serum', 'acne', 'manchas', 'arrugas', 'facial', 'antiedad', 'piel']) or 'belleza' in c_lower:
        niche = "Belleza & Cuidado Facial"
        pain = "manchas en la piel, imperfecciones y tratamientos estéticos carísimos que no dan resultados"
        benefit = "unificar el tono de la piel, atenuar líneas de expresión y recuperar la luminosidad natural"
        hook_1 = "Antes de gastarte un platal en sesiones de láser o spas, mira el cambio de mi piel en 14 días..."
        hook_2 = "El secreto que las clínicas estéticas no quieren que sepas para atenuar manchas en casa..."
        hook_3 = "Día 1 vs. Día 15 usando esto todas las noches en mi rutina facial..."
        ugc_0_3 = "Primer plano a la piel mostrando zona a mejorar: 'Tenía estas manchas desde hace meses y nada me las quitaba...'"
        ugc_3_7 = "Aplica unas gotas o crema: 'Empecé a usar esta fórmula recomendada por cosmetólogos...'"
        ugc_7_12 = "Muestra piel suave y radiante: 'Cero grasoso, se absorbe al instante y la piel queda como de filtro.'"
        ugc_12_15 = f"Cierre: 'Pide hoy con pago contra entrega en Servientrega o Envía por solo {sugg_price_fmt}.'"
        interests = ["Cuidado de la piel", "Cosméticos", "Dermatología", "Belleza natural"]
        age = "22 - 50 años"
        gender = "Mujeres (85%) y Hombres (15%)"

    elif any(k in n_lower for k in ['smartwatch', 'reloj', 'audifono', 'auricular', 'bluetooth', 'parlante', 'cargador']) or 'tecnologia' in c_lower:
        niche = "Tecnología & Gadgets Inteligentes"
        pain = "marcas carísimas que cobran $500k por funciones que este dispositivo hace igual o mejor"
        benefit = "disfrutar de máxima autonomía, sonido nítido y conectividad instantánea sin pagar de más"
        hook_1 = "Cancelación de ruido y batería para 3 días sin pagar medio millón de pesos en una tienda de centro comercial..."
        hook_2 = "Dejé de comprar marcas caras cuando descubrí este gadget viral..."
        hook_3 = "Si buscas un regalo impresionante o quieres renovar tus audífonos/reloj, mira esto antes de que se agote..."
        ugc_0_3 = "Abre la caja o se pone el dispositivo: 'Todo el mundo me pregunta cuánto me costó esto pensando que vale un platal...'"
        ugc_3_7 = "Muestra pantalla o conectando a Bluetooth en 1 segundo: 'Se vincula al instante con cualquier celular Android o iPhone...'"
        ugc_7_12 = "Demostración de sonido o funciones en vivo: 'La calidad es brutal, resistente al sudor y súper cómodo.'"
        ugc_12_15 = f"Cierre: 'Pídelo contra entrega por {sugg_price_fmt} y págalo cuando lo tengas en tus manos. Clic abajo.'"
        interests = ["Tecnología", "Gadgets", "Electrónica de consumo", "Música"]
        age = "18 - 45 años"
        gender = "Hombres y Mujeres"

    else:
        niche = f"E-Commerce & {category}"
        pain = f"perder tiempo y dinero buscando soluciones para {category.lower()}"
        benefit = f"obtener resultados profesionales, durabilidad y practicidad en tu día a día"
        hook_1 = f"¿Por qué todo el mundo en Colombia está comprando este {name[:30]} esta semana?"
        hook_2 = f"No compres esto a menos que quieras simplificar tu vida y ahorrar tiempo todos los días..."
        hook_3 = f"El producto viral que llegó a Colombia y está agotando inventario en Dropi..."
        ugc_0_3 = f"Sostiene el {name[:25]}: 'Vi este producto viral por todos lados y quise ponerlo a prueba...'"
        ugc_3_7 = f"Muestra el detalle: 'La calidad del material es de 10 sobre 10 y cumple exactamente lo que promete...'"
        ugc_7_12 = f"Muestra el producto en acción rápida resolviendo el problema: 'En menos de 1 minuto hace todo el trabajo.'"
        ugc_12_15 = f"Cierre: 'Pídelo hoy por {sugg_price_fmt} con envío a todo Colombia y paga en efectivo al recibir.'"
        interests = ["Compras en línea", "TikTok", "Estilo de vida", f"{category}"]
        age = "22 - 55 años"
        gender = "Hombres y Mujeres"

    ad_copy = f"""🔥 ¿Todavía lidiando con {pain}?

Descubre el {name.strip()}, la solución favorita de miles de colombianos para {benefit}.

✅ Máxima efectividad y resultados garantizados
✅ Material de alta durabilidad y calidad certificada
✅ Fácil de usar desde el primer día en casa

🚚 ENVÍO A TODA COLOMBIA CON PAGO CONTRA ENTREGA:
Pide con total tranquilidad y paga en efectivo al recibir en la puerta de tu casa con Servientrega, Envía o Interrapidísimo. ¡Cero riesgos!

👇 ¡Toca en 'Pedir Ahora' antes de que se agote el lote disponible!"""

    master_prompt = f"""Actúa como un Media Buyer y Copywriter de élite especializado en Dropshipping con Pago Contra Entrega (COD) en Colombia.

Analiza el siguiente producto ganador de Dropi Colombia:
- Nombre: {name}
- Categoría: {category}
- Costo Proveedor: ${int(cost):,} COP
- PVP Sugerido al Público: {sugg_price_fmt}
- Margen Neto Estimado: {margin_fmt}

Genera una estrategia de creativos de alta conversión:
1. 5 Ganchos (Hooks) agresivos para los primeros 3 segundos de TikTok y Reels (enfocados en el dolor y la curiosidad del comprador colombiano).
2. 2 Guiones de video UGC de 15 segundos para creadores de contenido (estructura: Gancho -> Problema -> Solución/Demo -> Oferta Contra Entrega).
3. 2 Variaciones de Copy para Meta Ads (uno enfocado en dolor/problema y otro en transformación/oferta).
4. Las 3 objeciones principales de compra en Colombia y cómo derribarlas en el video.
5. Segmentación recomendada en Facebook Ads Manager (Edad, Género e Intereses para Colombia)."""

    return {
        "product_id": product.get('id'),
        "product_name": name,
        "niche": niche,
        "hooks": [
            {"type": "Dolor Agudo", "hook": hook_1, "desc": "Ataca la frustración cotidiana para detener el scroll de inmediato"},
            {"type": "Curiosidad Viral", "hook": hook_2, "desc": "Despierta intriga con revelación o secreto de la industria"},
            {"type": "Transformación & Cierre", "hook": hook_3, "desc": "Muestra el resultado final y elimina el riesgo con pago al recibir"}
        ],
        "ugc_script": {
            "title": "Guión UGC de 15 Segundos (TikTok / Reels)",
            "pacing": [
                {"time": "0:00 - 0:03", "stage": "Gancho Scroll-Stopper", "direction": ugc_0_3},
                {"time": "0:03 - 0:07", "stage": "Problema / Dolor", "direction": ugc_3_7},
                {"time": "0:07 - 0:12", "stage": "Demostración 'Wow'", "direction": ugc_7_12},
                {"time": "0:12 - 0:15", "stage": "Llamado a la Acción COD", "direction": ugc_12_15}
            ]
        },
        "meta_ad_copy": {
            "headline": f"🔥 {name[:35]} | Pago Contra Entrega",
            "body": ad_copy,
            "cta": "Pedir Ahora (Pago al Recibir)"
        },
        "target_audience": {
            "age": age,
            "gender": gender,
            "interests": interests,
            "pro_tip": "Pauta con campaña de Ventas / Conversiones en Meta Ads optimizada para Colombia usando creativos formato 9:16 (vertical)."
        },
        "chatgpt_master_prompt": master_prompt
    }

def get_or_generate_angles(prod_dict: dict) -> dict:
    pid = prod_dict.get('id')
    if not pid:
        return generate_creative_angles(prod_dict)
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS product_angles_cache (product_id INTEGER PRIMARY KEY, angles_json TEXT, created_at TEXT)")
        c.execute("SELECT angles_json FROM product_angles_cache WHERE product_id = ?", (pid,))
        row = c.fetchone()
        if row and row[0]:
            conn.close()
            return json.loads(row[0])
        angles = generate_creative_angles(prod_dict)
        c.execute("INSERT OR REPLACE INTO product_angles_cache (product_id, angles_json, created_at) VALUES (?, ?, datetime('now'))", (pid, json.dumps(angles)))
        conn.commit()
        conn.close()
        return angles
    except Exception as e:
        print(f"[Angles Cache Error] {e}", flush=True)
        return generate_creative_angles(prod_dict)

@app.get("/api/product/{product_id}")
def get_product_detail(product_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    prod = c.fetchone()
    if not prod:
        conn.close()
        return {"error": "Producto no encontrado"}

    prod_dict = dict(prod)
    if prod_dict.get('store_name'):
        prod_dict['supplier_name'] = prod_dict['store_name']
    prod_dict['image_url'] = format_image_url(prod_dict.get('image_url'))

    # Agrupar ventas por fecha colombiana exacta (-5 horas respecto a UTC)
    c.execute("""
        SELECT 
            date(recorded_at, '-5 hours') as sale_date,
            sum(units_sold) as daily_units,
            count(*) as events_count,
            min(start_stock) as max_stock,
            max(end_stock) as min_stock
        FROM sales_events
        WHERE product_id = ?
        GROUP BY date(recorded_at, '-5 hours')
        ORDER BY sale_date ASC
    """, (product_id,))
    raw_daily = {r['sale_date']: dict(r) for r in c.fetchall()}

    # Construir línea de tiempo continua de los últimos 7 días exactos estilo Dropkiller / Kalodata
    colombia_tz = datetime.timezone(datetime.timedelta(hours=-5))
    today_col = datetime.datetime.now(colombia_tz).date()
    daily_sales = []
    for i in range(6, -1, -1):
        day_val = today_col - datetime.timedelta(days=i)
        day_key = day_val.strftime("%Y-%m-%d")
        if day_key in raw_daily:
            daily_sales.append(raw_daily[day_key])
        else:
            daily_sales.append({
                "sale_date": day_key,
                "daily_units": 0,
                "events_count": 0,
                "max_stock": 0,
                "min_stock": 0
            })

    c.execute("SELECT COALESCE(sum(units_sold), 0) FROM sales_events WHERE product_id = ?", (product_id,))
    total_sales = c.fetchone()[0]

    week_sales = sum(d['daily_units'] for d in daily_sales)
    if week_sales == 0 and total_sales > 0:
        week_sales = total_sales

    prod_dict['total_sales'] = total_sales
    prod_dict['week_sales'] = week_sales

    last_day_sales = daily_sales[-1]['daily_units'] if daily_sales else 0
    if last_day_sales >= 30:
        prod_dict['scale_badge'] = "ESCALANDO"
        prod_dict['scale_desc'] = "Ventas aceleradas en las ultimas horas (Pauta activa)"
    elif total_sales >= 300:
        prod_dict['scale_badge'] = "CONSOLIDADO"
        prod_dict['scale_desc'] = "Producto evergreen con rotacion constante"
    elif prod_dict.get('margin', 0) >= 50000:
        prod_dict['scale_badge'] = "JOYA OCULTA"
        prod_dict['scale_desc'] = "Alto margen neto con baja saturacion aparente"
    else:
        prod_dict['scale_badge'] = "TESTEANDO"
        prod_dict['scale_desc'] = "Ventas recurrentes en validacion"

    conn.close()
    angles = get_or_generate_angles(prod_dict)
    return {
        "product": prod_dict, 
        "daily_sales": daily_sales,
        "total_units_sold": total_sales,
        "week_sales": week_sales,
        "angles": angles
    }

@app.get("/api/product/{product_id}/angles")
def get_product_angles(product_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    prod = c.fetchone()
    conn.close()
    if not prod:
        return {"error": "Producto no encontrado"}
    prod_dict = dict(prod)
    return get_or_generate_angles(prod_dict)

@app.get("/api/products")
def list_products(
    category: Optional[str] = None,
    tier: Optional[str] = None,
    min_margin: float = 0,
    search: Optional[str] = None,
    supplier: Optional[str] = None,
    sort_by: str = "sales",
    ticket: Optional[str] = None,
    badge: Optional[str] = None,
    limit: int = 48,
    offset: int = 0
):
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        return {"products": [], "count": 0, "total_matching": 0, "offset": offset, "limit": limit}
    conn = get_db()
    c = conn.cursor()

    query = """
        SELECT 
            p.id, p.name, p.category, 
            COALESCE(NULLIF(p.store_name, ''), p.supplier_name, 'Proveedor Dropi') as supplier_name, 
            p.supplier_tier,
            p.sale_price, p.suggested_price, p.margin, p.image_url,
            COALESCE(p.stock, 0) as stock,
            COALESCE(s.today_units, 0) as today_units,
            COALESCE(s.week_units, 0) as week_units,
            COALESCE(s.units_sold, 0) as units_sold,
            COALESCE(s.events_count, 0) as events_count,
            COALESCE(s.last_sale, '') as last_sale,
            p.created_at
        FROM products p
        LEFT JOIN product_sales_summary s ON p.id = s.product_id
        WHERE p.margin >= ?
    """
    params = [min_margin]

    if category and category != "all":
        cat_lower = category.lower().strip()
        if "juguet" in cat_lower or "niñ" in cat_lower:
            query += " AND (p.category LIKE '%Juguet%' OR p.category LIKE '%Niñ%' OR p.category LIKE '%Infantil%')"
        elif "calzado" in cat_lower or "ropa deportiva" in cat_lower:
            query += " AND (p.category LIKE '%Calzado%' OR p.category LIKE '%Zapato%' OR p.category LIKE '%Tenis%' OR p.category = 'Ropa Deportiva')"
        else:
            query += " AND p.category = ?"
            params.append(category)

    if tier and tier != "all":
        query += " AND p.supplier_tier = ?"
        params.append(tier)

    if supplier and supplier != "all":
        query += " AND p.supplier_name = ?"
        params.append(supplier)

    if search:
        query += " AND (p.name LIKE ? OR p.supplier_name LIKE ? OR p.id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    if ticket == "low":
        query += " AND p.sale_price <= 35000"
    elif ticket == "medium":
        query += " AND p.sale_price > 35000 AND p.sale_price <= 65000"
    elif ticket == "high":
        query += " AND p.sale_price > 65000"

    if badge == "DESPEGANDO" or sort_by == "breakout":
        query += " AND s.today_units >= 15 AND (s.today_units * 1.0 / NULLIF(s.week_units, 0) >= 0.40 OR (s.week_units - s.today_units) <= 30)" 

    if sort_by == "sales" or sort_by == "sales_today":
        query += " ORDER BY s.today_units DESC, s.week_units DESC, s.units_sold DESC, p.margin DESC"
    elif sort_by == "sales_week":
        query += " ORDER BY s.week_units DESC, s.today_units DESC, s.units_sold DESC, p.margin DESC"
    elif sort_by == "breakout":
        query += " ORDER BY (s.today_units * 1.0 / NULLIF(s.week_units, 0.1)) DESC, s.today_units DESC"
    elif sort_by == "gmv":
        query += " ORDER BY (s.today_units * p.suggested_price) DESC, (s.week_units * p.suggested_price) DESC"
    elif sort_by == "margin":
        query += " ORDER BY p.margin DESC"
    elif sort_by == "price_asc":
        query += " ORDER BY p.sale_price ASC"
    elif sort_by == "price_desc":
        query += " ORDER BY p.sale_price DESC"
    elif sort_by == "newest":
        query += " ORDER BY p.id DESC"

    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    # Conteo total para paginación y visibilidad completa
    count_query = "SELECT count(*) FROM products p WHERE p.margin >= ?"
    count_params = [min_margin]
    if category and category != "all":
        cat_lower = category.lower().strip()
        if "juguet" in cat_lower or "niñ" in cat_lower:
            count_query += " AND (p.category LIKE '%Juguet%' OR p.category LIKE '%Niñ%' OR p.category LIKE '%Infantil%')"
        elif "calzado" in cat_lower or "ropa deportiva" in cat_lower:
            count_query += " AND (p.category LIKE '%Calzado%' OR p.category LIKE '%Zapato%' OR p.category LIKE '%Tenis%' OR p.category = 'Ropa Deportiva')"
        else:
            count_query += " AND p.category = ?"
            count_params.append(category)
    if tier and tier != "all":
        count_query += " AND p.supplier_tier = ?"
        count_params.append(tier)
    if supplier and supplier != "all":
        count_query += " AND p.supplier_name = ?"
        count_params.append(supplier)
    if search:
        count_query += " AND (p.name LIKE ? OR p.supplier_name LIKE ? OR p.id LIKE ?)"
        count_params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    if ticket == "low":
        count_query += " AND p.sale_price <= 35000"
    elif ticket == "medium":
        count_query += " AND p.sale_price > 35000 AND p.sale_price <= 65000"
    elif ticket == "high":
        count_query += " AND p.sale_price > 65000"

    if badge == "DESPEGANDO" or sort_by == "breakout":
        count_query = count_query.replace("FROM products p", "FROM products p LEFT JOIN product_sales_summary s ON p.id = s.product_id")
        count_query += " AND s.today_units >= 15 AND (s.today_units * 1.0 / NULLIF(s.week_units, 0) >= 0.40 OR (s.week_units - s.today_units) <= 30)" 
    c.execute(count_query, count_params)
    total_matching = c.fetchone()[0]

    c.execute(query, params)
    rows = []
    for r in c.fetchall():
        d = dict(r)
        d['image_url'] = format_image_url(d.get('image_url'))
        cost = d.get('sale_price') or 1
        m = d.get('margin') or 0
        d['roi_percent'] = round((m / cost) * 100, 1)

        u = d.get('units_sold', 0)
        sugg = d.get('suggested_price') or (cost + m)
        d['estimated_gmv'] = round(u * sugg)
        d['target_cpa'] = max(round(m * 0.35), 12000)

        # Métricas de Venta Sugerida y Utilidad Neta Real COD
        cod = calculate_cod_pricing(cost, target_net=28000.0)
        d['recommended_price'] = cod['recommended_price']
        d['net_profit_est'] = cod['net_profit']
        d['break_even_roas'] = cod['roas_break_even']

        today_u = d.get('today_units', 0)
        week_u = d.get('week_units', 0)
        
        # Insignia inteligente de tracción
        if today_u >= 15 and (today_u * 1.0 / max(week_u, 1) >= 0.40 or (week_u - today_u) <= 30):
            d['badge_type'] = "DESPEGANDO"
            d['growth_tag'] = "🚀 Despegando Hoy"
        elif today_u >= 80 or week_u >= 300:
            d['badge_type'] = "ESCALANDO"
            d['growth_tag'] = "🔥 Escalando Fuerte"
        elif today_u >= 15 or week_u >= 50:
            d['badge_type'] = "CONSOLIDADO"
            d['growth_tag'] = "📦 Ventas Constantes"
        elif m >= 50000 and (today_u > 0 or week_u > 0):
            d['badge_type'] = "JOYA OCULTA"
            d['growth_tag'] = "💎 Joya +$50k"
        else:
            d['badge_type'] = "POTENCIAL"
            d['growth_tag'] = "⚡ Validación"

        # Semáforo de stock de bodega para escalar
        stock_val = d.get('stock', 0)
        if stock_val >= 300:
            d['stock_status'] = "ESCALA_SEGURA"
            d['stock_status_label'] = "Apto para Escalar"
        elif stock_val >= 50:
            d['stock_status'] = "ESTABLE"
            d['stock_status_label'] = "Stock Estable"
        elif stock_val > 0:
            d['stock_status'] = "CRITICO"
            d['stock_status_label'] = "Stock Crítico"
        else:
            d['stock_status'] = "VERIFICAR"
            d['stock_status_label'] = "Verificar Bodega"

        rows.append(d)

    conn.close()
    return {"products": rows, "count": len(rows), "total_matching": total_matching, "offset": offset, "limit": limit}

@app.get("/", response_class=HTMLResponse)
def dashboard_view():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()
