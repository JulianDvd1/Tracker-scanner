import os
import sys
import time
import json
import sqlite3
import random
import argparse
from typing import List, Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()

DROPI_API_URL = "https://api.dropi.co/integrations/products/index"

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 5        # Para incluir productos con stock moderado
MIN_MARGIN = 10000   # Margen neto mínimo ($10.000 COP)
MAX_COST = 350000    # Costo máximo ($350.000 COP) para dropshipping COD
MAX_MARGIN = 180000  # Margen máximo ($180.000 COP) para filtrar maquinaria industrial
PAGE_SIZE = 40       # Límite estricto de Dropi (40 productos por paquete)

# Headers oficiales de la integración de WooCommerce / WordPress con Dropi.
# La API /integrations/ de Dropi EXIGE un User-Agent de WordPress/WooCommerce;
# cualquier User-Agent de navegador tradicional (Mozilla/Chrome) es rechazado con 401 Access denied.
USER_AGENTS = [
    "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)",
    "DropiIntegration/2.5.0 (WordPress/6.5.0; WooCommerce/8.6.0)",
    "DropiIntegration/2.4.1 (WordPress/6.4.4; WooCommerce/8.5.3)",
    "WordPress/6.4.3; WooCommerce/8.5.2; Dropify"
]

def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            supplier_id INTEGER,
            supplier_name TEXT,
            sale_price REAL,
            suggested_price REAL,
            margin REAL,
            image_url TEXT,
            created_at TEXT,
            updated_at TEXT,
            store_name TEXT,
            is_verified INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0,
            supplier_plan TEXT,
            supplier_tier TEXT,
            stock INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stock_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            warehouse_id INTEGER,
            stock INTEGER,
            recorded_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            warehouse_id INTEGER,
            units_sold INTEGER,
            start_stock INTEGER,
            end_stock INTEGER,
            interval_hours REAL,
            recorded_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def create_http_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def fetch_page_direct(
    session: requests.Session,
    page: int,
    token: str,
    max_retries: int = 3
) -> List[Dict[str, Any]]:
    start_data = (page - 1) * PAGE_SIZE
    payload = {
        "startData": start_data,
        "pageSize": PAGE_SIZE,
        "order_type": "desc",
        "order_by": "id",
        "keywords": "",
        "active": True,
        "no_count": True,
        "integration": True
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "dropi-integration-key": token,
        "User-Agent": random.choice(USER_AGENTS)
    }

    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        try:
            r = session.post(DROPI_API_URL, json=payload, headers=headers, timeout=30)
            elapsed = time.time() - t0

            if r.status_code == 200:
                # Marcapasos adaptativo (reloj delta):
                # Si el request tardó 3.2s, solo dormimos 5.5 - 3.2 = 2.3s
                espera = max(0.5, 5.5 - elapsed)
                time.sleep(espera)

                try:
                    data = r.json()
                except Exception as je:
                    print(f" [ERROR JSON Pág {page}] {je}", flush=True)
                    return []

                if isinstance(data, dict) and data.get("isSuccess"):
                    objs = data.get("objects", [])
                    return objs
                else:
                    msg = data.get("message") if isinstance(data, dict) else "Formato inesperado"
                    print(f" [DROPI RESPUESTA NO EXITOSA Pág {page}] {msg}", flush=True)
                    return []

            elif r.status_code == 429:
                print(f" [429 Rate-Limit Pág {page}] Pausando 60.0s para enfriar ventana...", flush=True)
                time.sleep(60.0)
                continue

            elif r.status_code == 401:
                print(f" [401 No Autorizado Pág {page}] Token inválido o rechazo de cabecera: {r.text[:200]}", flush=True)
                time.sleep(5.0)
                return []

            else:
                print(f" [HTTP {r.status_code} Pág {page}] Intento {attempt}: {r.text[:150]}", flush=True)
                time.sleep(2.0)

        except requests.exceptions.RequestException as e:
            elapsed = time.time() - t0
            print(f" [TIMEOUT/RED Pág {page}] Intento {attempt} ({elapsed:.1f}s): {e}", flush=True)
            time.sleep(2.0)

    return []

def run_shard(
    shard_id: int,
    total_shards: int,
    start_page: int,
    end_page: int,
    token: str,
    db_name: str
):
    init_db(db_name)
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    session = create_http_session()

    total_pages = end_page - start_page + 1
    masked_token = token[:6] + "..." + token[-4:] if len(token) > 10 else "***"

    print(f"\n=======================================================", flush=True)
    print(f" ESCÁNER DROPI DIRECTO - SHARD {shard_id + 1}/{total_shards}", flush=True)
    print(f" - Destino BD: {db_name}", flush=True)
    print(f" - Token asignado: {masked_token}", flush=True)
    print(f" - Rango de páginas: {start_page} a {end_page} ({total_pages} páginas | ~{total_pages * PAGE_SIZE:,} productos)", flush=True)
    print(f" - Marcapasos: Adaptativo a 5.5s (Delta Timing) | Pausa 429: 60s única", flush=True)
    print(f"=======================================================\n", flush=True)

    saved_count = 0
    pages_done = 0
    start_time = time.time()

    for page in range(start_page, end_page + 1):
        objects = fetch_page_direct(session=session, page=page, token=token)

        if objects:
            now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
            valid_prods = []
            valid_stocks = []

            for item in objects:
                user_data = item.get("user") or {}
                cat_user = user_data.get("category_user") or {}
                plan_val = user_data.get("plan")
                plan_str = plan_val.get("name", "") if isinstance(plan_val, dict) else str(plan_val or "")
                cat_name = cat_user.get("name", "") if isinstance(cat_user, dict) else str(cat_user or "")
                supp_plan = item.get("supplier_plan") or ""
                if isinstance(supp_plan, dict):
                    supp_plan = supp_plan.get("name", "")

                tier_raw = str(cat_name or plan_str or supp_plan or "").strip().upper()
                is_veri = bool(item.get("is_verified") or user_data.get("is_verified") or item.get("userVerified"))
                is_prem = bool(item.get("is_premium") or user_data.get("is_premium"))

                if "EXCLUSIVO" in tier_raw:
                    tier = "PREMIUM EXCLUSIVO"
                elif is_prem or "PREMIUM" in tier_raw:
                    tier = "PREMIUM"
                elif is_veri or "VERIFICADO" in tier_raw:
                    tier = "VERIFICADO"
                else:
                    tier = "PROVEEDOR DROPI"

                sale_price = float(item.get("sale_price") or 0)
                if sale_price <= 0:
                    continue

                sug_price = float(item.get("suggested_price") or 0)
                if sug_price <= sale_price:
                    # Si el proveedor no fijó un precio sugerido, estimamos un precio razonable de mercado para dropshipping (+35% o +$20k)
                    sug_price = max(sale_price + 20000, round(sale_price * 1.35, -2))

                margin = sug_price - sale_price

                # Filtro de margen mínimo
                if margin < MIN_MARGIN:
                    continue

                # FILTRO DE DROPSHIPPING REAL:
                # Solo productos testeables para dropshipping COD (Costo <= $350k y Margen <= $180k)
                if sale_price > MAX_COST or margin > MAX_MARGIN:
                    continue

                # Sanitizar errores tipográficos de proveedores en Dropi
                if (sale_price < 200000 and sug_price > sale_price * 4) or (sug_price > sale_price * 6) or sug_price > 1000000:
                    continue

                warehouses = item.get("warehouse_product") or item.get("product_warehouses") or []
                total_stock = sum(int(w.get("stock") or 0) for w in warehouses) if warehouses else int(item.get("stock") or 0)
                if warehouses and total_stock < MIN_STOCK:
                    continue

                gallery = item.get("gallery") or []
                img = ""
                if gallery:
                    img = gallery[0].get("urlS3") or gallery[0].get("url") or (gallery[0] if isinstance(gallery[0], str) else "")

                pid = item.get("id")
                pname = (item.get("name") or "Sin nombre").strip()
                categories = item.get("categories") or []
                cat = categories[0].get("name", "General") if categories and isinstance(categories[0], dict) else "General"
                supp_id = item.get("user_id") or user_data.get("id") or 0
                store_name = (user_data.get("brand_name") or user_data.get("store_name") or "").strip()
                supp_name = store_name if store_name else (item.get("supplier_name") or user_data.get("name") or "Proveedor Dropi").strip()
                plan_name = tier

                valid_prods.append((
                    pid, pname, cat, supp_id, supp_name, sale_price, sug_price,
                    margin, img, item.get("created_at") or now_iso, now_iso,
                    store_name, 1 if is_veri else 0,
                    1 if is_prem else 0, plan_name, tier, total_stock
                ))

                for wh in warehouses:
                    wh_id = wh.get("warehouse_id", 0)
                    stock_val = int(wh.get("stock") or 0)
                    valid_stocks.append((pid, wh_id, stock_val, now_iso))

            if valid_prods:
                cursor.executemany("""
                    INSERT OR REPLACE INTO products (
                        id, name, category, supplier_id, supplier_name, sale_price,
                        suggested_price, margin, image_url, created_at, updated_at,
                        store_name, is_verified, is_premium, supplier_plan, supplier_tier, stock
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, valid_prods)

            if valid_stocks:
                cursor.executemany("""
                    INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                    VALUES (?, ?, ?, ?)
                """, valid_stocks)

            conn.commit()
            saved_count += len(valid_prods)

        pages_done += 1
        if pages_done % 10 == 0 or page == end_page:
            elapsed = time.time() - start_time
            speed = pages_done / (elapsed / 60) if elapsed > 0 else 0
            pct = (pages_done / total_pages) * 100
            print(f" -> [Shard {shard_id}] Progreso: {pages_done}/{total_pages} ({pct:.1f}%) | Ganadores: {saved_count:,} | {speed:.1f} págs/min | Tiempo: {elapsed:.1f}s", flush=True)

    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    print(f"\n=======================================================", flush=True)
    print(f" [SHARD {shard_id}] COMPLETADO EN {elapsed:.1f}s ({elapsed/60:.1f} min)!", flush=True)
    print(f" [SHARD {shard_id}] GANADORES GUARDADOS: {saved_count:,} EN {db_name}", flush=True)
    print(f"=======================================================\n", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Escáner Dropi Sharded en Modo Directo")
    parser.add_argument("--shard-id", type=int, default=0, help="ID del Shard (0 a total_shards-1)")
    parser.add_argument("--total-shards", type=int, default=1, help="Total de Shards paralelos (default 1)")
    parser.add_argument("--start-page", type=int, default=None, help="Página inicial manual")
    parser.add_argument("--end-page", type=int, default=None, help="Página final manual")
    parser.add_argument("--pages", "--total-pages", dest="total_pages", type=int, default=1730, help="Total de páginas global (default 1730)")
    parser.add_argument("--token-index", type=int, default=1, help="Número de token a usar (1 a 6)")
    parser.add_argument("--token", type=str, default="", help="Token explícito")
    parser.add_argument("--db-name", type=str, default="", help="Nombre del archivo SQLite")

    args = parser.parse_args()

    # Determinar rango de páginas
    if args.start_page is not None and args.end_page is not None:
        start_p = args.start_page
        end_p = args.end_page
    else:
        tot = args.total_pages
        shards = max(1, args.total_shards)
        shard_size = (tot + shards - 1) // shards
        start_p = args.shard_id * shard_size + 1
        end_p = min(tot, (args.shard_id + 1) * shard_size)

    # Si el shard queda fuera del rango solicitado (ej. prueba corta de pocas páginas)
    if start_p > end_p:
        print(f" [SHARD {args.shard_id}] Rango vacío ({start_p} > {end_p}). Nada que procesar.")
        db_file = args.db_name if args.db_name else f"catalog_shard_{args.shard_id}.db"
        init_db(db_file)
        sys.exit(0)

    # Determinar base de datos de salida
    db_file = args.db_name if args.db_name else (f"catalog_shard_{args.shard_id}.db" if args.total_shards > 1 else "catalog.db")

    # Determinar token a usar
    chosen_token = ""
    if args.token:
        chosen_token = args.token.strip()
    else:
        var_name = f"DROPI_TOKEN_{args.token_index}"
        chosen_token = (os.getenv(var_name) or "").strip()
        if not chosen_token:
            chosen_token = (os.getenv("DROPI_TOKEN_1") or os.getenv("DROPI_TOKEN") or "").strip()

    if not chosen_token:
        print(f" ERROR: No se encontró ningún token configurado para el Shard {args.shard_id}.", flush=True)
        sys.exit(1)

    run_shard(
        shard_id=args.shard_id,
        total_shards=args.total_shards,
        start_page=start_p,
        end_page=end_p,
        token=chosen_token,
        db_name=db_file
    )
