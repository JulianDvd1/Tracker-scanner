import os
import sys
import time
import json
import asyncio
import aiohttp
import sqlite3
import random
import argparse
from typing import List, Dict, Any

DROPI_API_URL = "https://api.dropi.co/integrations/products/index"

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 5        # Para incluir productos con stock moderado
MIN_MARGIN = 10000   # Para incluir relojes Curren, Casrray, calzado y accesorios
PAGE_SIZE = 40       # Límite estricto del servidor de Dropi (40 productos por paquete)

USER_AGENTS = [
    "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "WordPress/6.4; Dropify",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
]

def get_tokens(worker_id: int = 1) -> List[str]:
    tokens = []
    w_token = (os.getenv(f"DROPI_TOKEN_{worker_id}") or "").strip().strip('"').strip("'")
    if w_token:
        tokens.append(w_token)
    for k in ["DROPI_TOKEN_1", "DROPI_TOKEN_2", "DROPI_TOKEN_3", "DROPI_TOKEN_4", "DROPI_TOKEN"]:
        val = (os.getenv(k) or "").strip().strip('"').strip("'")
        if val and val not in tokens:
            tokens.append(val)
    return tokens

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
            supplier_tier TEXT
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

async def fetch_page(session: aiohttp.ClientSession, start_data: int, tokens: List[str], token_state: List[int]) -> List[Dict[str, Any]]:
    payload = {
        "startData": start_data,
        "pageSize": PAGE_SIZE,
        "order_type": "desc",
        "order_by": "id",
        "keywords": "",
        "active": True,
        "no_count": True,
        "integration": True,
        "userVerified": True
    }

    # Ritmo continuo entre peticiones (3.0s exactos)
    await asyncio.sleep(3.0)

    max_attempts = max(3, len(tokens) + 1)
    for attempt in range(1, max_attempts + 1):
        token = tokens[token_state[0] % len(tokens)]
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "dropi-integration-key": token,
            "User-Agent": random.choice(USER_AGENTS)
        }
        try:
            async with session.post(DROPI_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("isSuccess"):
                        return data.get("objects", [])
                    return []
                elif resp.status == 429:
                    # 1. Si tenemos múltiples tokens, rotamos primero
                    if len(tokens) > 1 and attempt < len(tokens):
                        token_state[0] = (token_state[0] + 1) % len(tokens)
                        print(f" [429] Rotando a Token #{token_state[0] + 1} de {len(tokens)} sin esperar...", flush=True)
                        await asyncio.sleep(1.0)
                        continue
                    
                    # 2. Pausa directa de 62.0s (la ventana exacta de reseteo de Dropi)
                    print(f" [429 Rate-Limit] Pausa directa de 62.0s (reseteo de ventana Dropi)...", flush=True)
                    await asyncio.sleep(62.0)
                else:
                    await asyncio.sleep(1.5)
        except Exception as e:
            if attempt == max_attempts:
                print(f" Error en offset {start_data}: {e}", flush=True)
            await asyncio.sleep(2)
    return []

async def run_worker(worker_id: int = 1, total_workers: int = 1, total_pages: int = 800):
    tokens = get_tokens(worker_id)
    if not tokens:
        print(f" ERROR: Ningún token configurado para Worker #{worker_id}.", flush=True)
        sys.exit(1)

    token_state = [0]
    pages_per_worker = total_pages // total_workers
    start_page = ((worker_id - 1) * pages_per_worker) + 1
    end_page = start_page + pages_per_worker - 1
    if worker_id == total_workers:
        end_page = total_pages

    db_filename = "catalog.db" if total_workers == 1 else f"worker_data_{worker_id}.db"
    init_db(db_filename)
    conn = sqlite3.connect(db_filename)
    cursor = conn.cursor()

    total_prods_assigned = (end_page - start_page + 1) * PAGE_SIZE
    print(f"\n=======================================================", flush=True)
    if total_workers == 1:
        print(f" ESCÁNER MAESTRO DROPI COLOMBIA INICIADO (1 WORKER CONTINUO)", flush=True)
    else:
        print(f" TURBO WORKER #{worker_id} / {total_workers} INICIADO", flush=True)
    print(f" - Destino BD: {db_filename}", flush=True)
    print(f" - Tokens disponibles para rotación: {len(tokens)}", flush=True)
    print(f" - Rango de páginas: {start_page} a {end_page} (~{total_prods_assigned:,} productos)", flush=True)
    print(f" - Ritmo calibrado: 1 petición cada 3.0s | Pausa directa 429: 62.0s exactos", flush=True)
    print(f"=======================================================\n", flush=True)

    saved_count = 0
    start_time = time.time()

    conn_tcp = aiohttp.TCPConnector(limit=3, ssl=False)
    async with aiohttp.ClientSession(connector=connector if 'connector' in locals() else conn_tcp) as session:
        for page in range(start_page, end_page + 1):
            start_data = (page - 1) * PAGE_SIZE
            objects = await fetch_page(session, start_data, tokens, token_state)

            if not objects:
                continue

            now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
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
                    # PROVEEDOR BÁSICO O NO VERIFICADO -> DESCARTADO DIRECTAMENTE
                    continue

                sale_price = float(item.get("sale_price") or 0)
                sug_price = float(item.get("suggested_price") or sale_price)
                margin = sug_price - sale_price

                if margin < MIN_MARGIN:
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

                cursor.execute("""
                    INSERT OR REPLACE INTO products (
                        id, name, category, supplier_id, supplier_name, sale_price,
                        suggested_price, margin, image_url, created_at, updated_at,
                        store_name, is_verified, is_premium, supplier_plan, supplier_tier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pid, pname, cat, supp_id, supp_name, sale_price, sug_price,
                    margin, img, item.get("created_at") or now_iso, now_iso,
                    store_name, 1 if is_veri else 0,
                    1 if is_prem else 0, plan_name, tier
                ))

                for wh in warehouses:
                    wh_id = wh.get("warehouse_id", 0)
                    stock_val = int(wh.get("stock") or 0)
                    cursor.execute("""
                        INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                        VALUES (?, ?, ?, ?)
                    """, (pid, wh_id, stock_val, now_iso))

                saved_count += 1

            if page % 10 == 0 or page == end_page:
                conn.commit()
                elapsed = time.time() - start_time
                print(f" -> Pág {page}/{end_page} auditada | Ganadores guardados: {saved_count:,} | Tiempo: {elapsed:.1f}s", flush=True)

    conn.commit()
    conn.close()
    elapsed = time.time() - start_time
    print(f"\n=======================================================", flush=True)
    print(f" ESCANEO COMPLETADO EN {elapsed:.1f}s ({elapsed/60:.1f} min)!", flush=True)
    print(f" TOTAL GANADORES GUARDADOS: {saved_count:,}", flush=True)
    print(f"=======================================================\n", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", type=int, default=1, help="ID del worker (default 1)")
    parser.add_argument("--total-workers", type=int, default=1, help="Total workers (default 1)")
    parser.add_argument("--pages", "--total-pages", dest="total_pages", type=int, default=800, help="Total páginas (800 = ~32.000 productos)")
    args = parser.parse_args()

    asyncio.run(run_worker(args.worker_id, args.total_workers, args.total_pages))
