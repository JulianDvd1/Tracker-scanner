import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from db import get_connection

# Cargar configuración desde .env
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
CONFIG = {}
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                CONFIG[k.strip()] = v.strip()

API_TOKEN = CONFIG.get("DROPI_TOKEN", "")
API_URL = CONFIG.get("DROPI_API_URL", "https://api.dropi.co/integrations/products/index")

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "dropi-integration-key": API_TOKEN,
    "User-Agent": "WordPress/6.4; Dropify"
}

def fetch_products_page(start_data=0, page_size=40, only_verified=True, min_stock=15, max_retries=6):
    payload = {
        "startData": start_data,
        "pageSize": page_size,
        "order_type": "desc",
        "order_by": "id",
        "keywords": "",
        "active": True,
        "no_count": True,
        "integration": True
    }
    if only_verified:
        payload["userVerified"] = True
    if min_stock:
        payload["stockmayor"] = min_stock
    
    data_bytes = json.dumps(payload).encode("utf-8")
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                API_URL,
                data=data_bytes,
                headers=HEADERS,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("isSuccess"):
                    return data.get("objects", [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = 5.0 * (attempt + 1)
                print(f"Límite de velocidad detectado (HTTP 429). Pausando {wait_time}s antes de reintentar offset {start_data} (intento {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            elif attempt < max_retries - 1:
                time.sleep(2.0 * (attempt + 1))
            else:
                print(f"Error fetching page at offset {start_data} after {max_retries} attempts: {e}")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2.0 * (attempt + 1))
            else:
                print(f"Error fetching page at offset {start_data} after {max_retries} attempts: {e}")
    return []

ALLOWED_SUPPLIER_TIERS = {
    "PREMIUM EXCLUSIVO",
    "PREMIUM",
    "VERIFICADO"
}

def record_snapshot(max_products=10000, page_size=40, min_margin=18000.0, min_stock=15):
    """
    Descarga y audita hasta `max_products` productos aplicando el embudo de purga anti-basura.
    Nota técnica: Dropi limita la entrega a un máximo estricto de 40 productos por petición HTTP.
    Por lo tanto, para llegar a 10.000 se recorren 250 páginas de 40 productos.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    now_iso = datetime.utcnow().isoformat()
    total_scanned = 0
    total_saved = 0
    total_filtered_out = 0
    
    pages = (max_products + page_size - 1) // page_size
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Iniciando barrido masivo de hasta {max_products} productos ({pages} páginas a {page_size} items)...")
    print(f"Filtros: Stock >= {min_stock} | Margen >= ${min_margin:,.0f} COP | Proveedores: {', '.join(ALLOWED_SUPPLIER_TIERS)}")

    for page in range(pages):
        start_data = page * page_size
        products = fetch_products_page(start_data, page_size, only_verified=True, min_stock=min_stock)
        
        if not products:
            print(f"Catálogo completado en offset {start_data} (sin más productos).")
            break
            
        for p in products:
            total_scanned += 1
            user_data = p.get("user") or {}
            cat_user = user_data.get("category_user") or {}
            tier_name = (cat_user.get("name") or "").strip().upper()
            
            # 1. Filtro estricto de nivel de proveedor
            if tier_name not in ALLOWED_SUPPLIER_TIERS:
                total_filtered_out += 1
                continue

            # 2. Precios y margen
            try:
                sale_price = float(p.get("sale_price") or 0)
                suggested_price = float(p.get("suggested_price") or 0)
            except (ValueError, TypeError):
                sale_price = 0.0
                suggested_price = 0.0
                
            margin = suggested_price - sale_price
            
            # Filtro de margen comercial mínimo para pauta
            if margin < min_margin:
                total_filtered_out += 1
                continue

            # 3. Filtro de imagen válida
            gallery = p.get("gallery", [])
            img_url = ""
            if gallery:
                img_url = gallery[0].get("urlS3") or gallery[0].get("url") or ""
            if not img_url:
                total_filtered_out += 1
                continue

            # 4. Validar stock real en bodegas
            warehouses = p.get("warehouse_product", [])
            total_prod_stock = sum(w.get("stock") or 0 for w in warehouses)
            if total_prod_stock < min_stock:
                total_filtered_out += 1
                continue

            # Si pasa todos los filtros, se registra como producto de calidad
            prod_id = p.get("id")
            name = p.get("name", "").strip()
            categories = p.get("categories", [])
            category_name = categories[0].get("name") if categories else "General"
            
            supplier_id = user_data.get("id")
            supplier_name = user_data.get("name", "")
            store_name = user_data.get("store_name") or supplier_name
            plan_name = (user_data.get("plan") or {}).get("name", "")

            cursor.execute("""
            INSERT INTO products (
                id, name, category, supplier_id, supplier_name, store_name, 
                is_verified, is_premium, supplier_plan, supplier_tier, sale_price, 
                suggested_price, margin, image_url, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                category=excluded.category,
                supplier_name=excluded.supplier_name,
                store_name=excluded.store_name,
                is_verified=excluded.is_verified,
                is_premium=excluded.is_premium,
                supplier_plan=excluded.supplier_plan,
                supplier_tier=excluded.supplier_tier,
                sale_price=excluded.sale_price,
                suggested_price=excluded.suggested_price,
                margin=excluded.margin,
                image_url=excluded.image_url,
                updated_at=excluded.updated_at
            """, (
                prod_id, name, category_name, supplier_id, supplier_name, store_name,
                1, 1 if "PREMIUM" in tier_name else 0, plan_name, tier_name,
                sale_price, suggested_price, margin, img_url, now_iso
            ))

            # Guardar snapshots de stock por bodega y calcular deltas
            for w in warehouses:
                w_id = w.get("warehouse_id")
                w_info = w.get("warehouse") or {}
                w_name = w_info.get("name", "Principal")
                current_stock = w.get("stock")
                if current_stock is None:
                    continue

                cursor.execute("""
                SELECT stock, recorded_at FROM stock_history
                WHERE product_id = ? AND warehouse_id = ?
                ORDER BY id DESC LIMIT 1
                """, (prod_id, w_id))
                last_record = cursor.fetchone()

                cursor.execute("""
                INSERT INTO stock_history (product_id, warehouse_id, warehouse_name, stock, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """, (prod_id, w_id, w_name, current_stock, now_iso))

                if last_record:
                    prev_stock = last_record["stock"]
                    prev_time_str = last_record["recorded_at"]
                    try:
                        prev_dt = datetime.fromisoformat(prev_time_str)
                        curr_dt = datetime.fromisoformat(now_iso)
                        hours_diff = (curr_dt - prev_dt).total_seconds() / 3600.0
                    except Exception:
                        hours_diff = 1.0

                    if prev_stock > current_stock:
                        units_sold = prev_stock - current_stock
                        cursor.execute("""
                        INSERT INTO sales_events (product_id, warehouse_id, units_sold, start_stock, end_stock, interval_hours, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (prod_id, w_id, units_sold, prev_stock, current_stock, hours_diff, now_iso))

            total_saved += 1

        conn.commit()
        if (page + 1) % 25 == 0:
            print(f"Progreso: {total_scanned}/{max_products} examinados | {total_saved} de alto valor guardados...")
        time.sleep(0.35)

    conn.close()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Barrido finalizado con éxito.")
    print(f"Total examinados: {total_scanned} | Descartados por filtros: {total_filtered_out} | Guardados en base de datos: {total_saved}")

if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    record_snapshot(max_products=count, page_size=40, min_margin=18000.0, min_stock=15)
