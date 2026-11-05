import os
import sqlite3
import datetime
import urllib.request
import zipfile
import threading
import time
from typing import Optional, List
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="DropiSpy Elite Pro", version="3.5.0")

DB_PATH = os.path.join(os.path.dirname(__file__), "catalog.db")
CLOUDFRONT_BASE = "https://d39ru7awumhhs2.cloudfront.net/"
RELEASE_URL = "https://github.com/JulianDvd1/Tracker-scanner/releases/download/v1.0-data/catalog.db.zip"

def sync_from_github(force: bool = False) -> dict:
    """Descarga catalog.db.zip desde GitHub Releases y actualiza catalog.db en segundo plano"""
    try:
        need_download = force or not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000
        if not need_download:
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
            print(f"[Cloud Sync] catalog.db actualizado exitosamente ({size:,} bytes).", flush=True)
            return {"status": "ok", "message": f"Catálogo sincronizado exitosamente ({size:,} bytes)"}
        return {"status": "error", "message": "El archivo descargado era inválido"}
    except Exception as e:
        print(f"[Cloud Sync Error] {e}", flush=True)
        return {"status": "error", "message": str(e)}

def periodic_sync_worker():
    while True:
        time.sleep(120)  # Cada 2 minutos busca y actualiza si hay nuevo Release en GitHub
        print("[Auto-Sync] Sincronizando catálogo con GitHub Releases...", flush=True)
        sync_from_github(force=True)

@app.on_event("startup")
def startup_event():
    # Asegurar descarga del catálogo más fresco al arrancar en Render
    sync_from_github(force=True)
    # Hilo en segundo plano para auto-actualización cada 2 minutos
    t = threading.Thread(target=periodic_sync_worker, daemon=True)
    t.start()

@app.get("/api/sync-cloud")
@app.post("/api/sync-cloud")
def trigger_sync():
    return sync_from_github(force=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT count(*) FROM products")
    total_products = c.fetchone()[0]
    
    c.execute("SELECT count(*) FROM sales_events")
    total_sales_events = c.fetchone()[0]

    c.execute("SELECT COALESCE(sum(units_sold), 0) FROM sales_events")
    total_units_sold = c.fetchone()[0]

    c.execute("SELECT count(DISTINCT product_id) FROM sales_events")
    winning_products_count = c.fetchone()[0]

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
        SELECT COALESCE(sum(s.units_sold * p.suggested_price), 0)
        FROM sales_events s
        JOIN products p ON s.product_id = p.id
    """)
    total_market_gmv = c.fetchone()[0]

    # Joyas Ocultas con margen superior a $50k COP
    c.execute("SELECT count(*) FROM products WHERE margin >= 50000")
    hidden_gems_count = c.fetchone()[0]

    # Fecha/Hora real del último escaneo completado en GitHub Actions (de la base de datos)
    c.execute("SELECT max(updated_at) FROM products")
    row_updated = c.fetchone()
    
    conn.close()

    last_sync_human = "Recientemente"
    last_sync_time = ""
    next_sync_human = "Cada 2 horas (:15)"

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

    return {
        "total_products": total_products,
        "total_sales_events": total_sales_events,
        "total_units_sold": total_units_sold,
        "winning_products_count": winning_products_count,
        "hidden_gems_count": hidden_gems_count,
        "total_market_gmv": total_market_gmv,
        "top_categories": categories,
        "last_sync_human": last_sync_human,
        "last_sync_time": last_sync_time,
        "next_sync_human": next_sync_human
    }

@app.get("/api/live-ticker")
def get_live_ticker(limit: int = 15):
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
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT 
            p.id, p.name, p.category, 
            COALESCE(NULLIF(p.store_name, ''), p.supplier_name, 'Proveedor Dropi') as supplier_name, 
            p.supplier_tier,
            p.sale_price, p.suggested_price, p.margin, p.image_url,
            COALESCE(sum(s.units_sold), 0) as total_sold,
            round(COALESCE(sum(s.units_sold * p.suggested_price), 0), 0) as gmv,
            count(s.id) as sales_velocity,
            max(s.recorded_at) as last_sale_at
        FROM products p
        LEFT JOIN sales_events s ON p.id = s.product_id
        GROUP BY p.id
        ORDER BY total_sold DESC, p.margin DESC, p.id DESC
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

        # Clasificacion estilo Kalodata
        sold = d['total_sold']
        if sold >= 800:
            d['tier_label'] = "MEGA WINNER"
            d['tier_color'] = "bg-amber-500/10 text-amber-600 border-amber-300 dark:border-amber-700"
            d['growth_badge'] = "🔥 Top 1% Velocidad"
        elif sold >= 250:
            d['tier_label'] = "SUPER SCALED"
            d['tier_color'] = "bg-indigo-500/10 text-indigo-600 border-indigo-300 dark:border-indigo-700"
            d['growth_badge'] = "🚀 En Escala Fuerte"
        else:
            d['tier_label'] = "RISING STAR"
            d['tier_color'] = "bg-emerald-500/10 text-emerald-600 border-emerald-300 dark:border-emerald-700"
            d['growth_badge'] = "✨ Creciendo Rápido"

        rows.append(d)
        rank += 1
    conn.close()
    return {"leaderboard": rows}

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

    c.execute("""
        SELECT 
            date(recorded_at) as sale_date,
            sum(units_sold) as daily_units,
            count(*) as events_count,
            min(start_stock) as max_stock,
            max(end_stock) as min_stock
        FROM sales_events
        WHERE product_id = ?
        GROUP BY date(recorded_at)
        ORDER BY sale_date ASC
    """, (product_id,))
    daily_sales = [dict(r) for r in c.fetchall()]

    c.execute("SELECT COALESCE(sum(units_sold), 0) FROM sales_events WHERE product_id = ?", (product_id,))
    total_sales = c.fetchone()[0]

    c.execute("""
        SELECT COALESCE(sum(units_sold), 0) 
        FROM sales_events 
        WHERE product_id = ? AND date(recorded_at) >= date('now', '-7 days')
    """, (product_id,))
    week_sales = c.fetchone()[0]
    if week_sales == 0 and total_sales > 0:
        week_sales = sum(d['daily_units'] for d in daily_sales[-7:])

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
    return {
        "product": prod_dict, 
        "daily_sales": daily_sales,
        "total_units_sold": total_sales,
        "week_sales": week_sales
    }

@app.get("/api/products")
def list_products(
    category: Optional[str] = None,
    tier: Optional[str] = None,
    min_margin: float = 0,
    search: Optional[str] = None,
    supplier: Optional[str] = None,
    sort_by: str = "sales",
    limit: int = 48,
    offset: int = 0
):
    conn = get_db()
    c = conn.cursor()

    query = """
        SELECT 
            p.id, p.name, p.category, 
            COALESCE(NULLIF(p.store_name, ''), p.supplier_name, 'Proveedor Dropi') as supplier_name, 
            p.supplier_tier,
            p.sale_price, p.suggested_price, p.margin, p.image_url,
            COALESCE(s.units_sold, 0) as units_sold,
            COALESCE(s.events_count, 0) as events_count,
            COALESCE(s.last_sale, '') as last_sale,
            COALESCE(s.week_units, 0) as week_units,
            p.created_at
        FROM products p
        LEFT JOIN (
            SELECT 
                product_id, 
                sum(units_sold) as units_sold, 
                count(*) as events_count, 
                max(recorded_at) as last_sale,
                sum(CASE WHEN date(recorded_at) >= date('now', '-7 days') THEN units_sold ELSE 0 END) as week_units
            FROM sales_events
            GROUP BY product_id
        ) s ON p.id = s.product_id
        WHERE p.margin >= ?
    """
    params = [min_margin]

    if category and category != "all":
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

    if sort_by == "sales":
        query += " ORDER BY units_sold DESC, p.margin DESC"
    elif sort_by == "gmv":
        query += " ORDER BY (units_sold * p.suggested_price) DESC"
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

        if u >= 300:
            d['badge_type'] = "CONSOLIDADO"
            d['growth_tag'] = "🔥 Top 1% Volumen"
        elif u >= 40:
            d['badge_type'] = "ESCALANDO"
            d['growth_tag'] = "🚀 Escalando Fuerte"
        elif m >= 50000:
            d['badge_type'] = "JOYA OCULTA"
            d['growth_tag'] = "💎 Joya +$50k"
        else:
            d['badge_type'] = "POTENCIAL"
            d['growth_tag'] = "⚡ Validación"

        rows.append(d)

    conn.close()
    return {"products": rows, "count": len(rows), "total_matching": total_matching, "offset": offset, "limit": limit}

@app.get("/", response_class=HTMLResponse)
def dashboard_view():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()
