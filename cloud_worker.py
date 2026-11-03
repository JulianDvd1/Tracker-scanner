import os
import sys
import time
import json
import asyncio
import aiohttp
import sqlite3
import random
import argparse
from typing import List, Dict, Any, Optional

DROPI_API_URL = "https://api.dropi.co/integrations/products/index"
DROPI_TOKEN = os.getenv("DROPI_TOKEN")

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 15
MIN_MARGIN = 18000
PAGE_SIZE = 40  # Tamaño nativo por página en Dropi

USER_AGENTS = [
    "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

def classify_tier(p: dict) -> str:
    plan = str(p.get("supplier_plan") or "").upper()
    is_prem = bool(p.get("is_premium"))
    is_veri = bool(p.get("is_verified"))
    if "EXCLUSIVO" in plan or (is_prem and "EXCLUSIV" in str(p.get("supplier_name", "")).upper()):
        return "PREMIUM EXCLUSIVO"
    if is_prem or "PREMIUM" in plan:
        return "PREMIUM"
    if is_veri:
        return "VERIFICADO"
    return "ESTANDAR"

def init_worker_db(db_path: str):
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
        CREATE TABLE IF NOT EXISTS stock_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            warehouse_id INTEGER,
            stock INTEGER,
            recorded_at TEXT
        )
    """)
    conn.commit()
    conn.close()

async def fetch_page(session: aiohttp.ClientSession, page: int, semaphore: asyncio.Semaphore) -> List[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "dropi-integration-key": DROPI_TOKEN,
        "User-Agent": random.choice(USER_AGENTS)
    }
    payload = {"pageSize": PAGE_SIZE, "page": page}

    async with semaphore:
        for attempt in range(1, 4):
            try:
                # Latencia corta segura entre llamadas
                await asyncio.sleep(random.uniform(0.15, 0.35))
                async with session.post(DROPI_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=18)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("objects", [])
                    elif resp.status == 429:
                        print(f" [Rate-Limit 429] Worker esperando {attempt * 8}s...")
                        await asyncio.sleep(attempt * 8)
                    else:
                        await asyncio.sleep(1)
            except Exception as e:
                if attempt == 3:
                    print(f" Error en página {page}: {e}")
                await asyncio.sleep(1.5)
    return []

async def run_worker(worker_id: int, total_workers: int = 4, total_pages: int = 1500):
    if not DROPI_TOKEN:
        print(" ERROR FATAL: DROPI_TOKEN no configurado en variables de entorno.")
        sys.exit(1)

    pages_per_worker = total_pages // total_workers
    start_page = ((worker_id - 1) * pages_per_worker) + 1
    end_page = start_page + pages_per_worker - 1
    if worker_id == total_workers:
        end_page = total_pages

    db_filename = f"worker_data_{worker_id}.db"
    init_worker_db(db_filename)
    conn = sqlite3.connect(db_filename)
    cursor = conn.cursor()

    print(f"=== WORKER #{worker_id} / {total_workers} INICIADO ===")
    print(f" - Rango asignado: Páginas {start_page} a {end_page} (~{(end_page - start_page + 1) * PAGE_SIZE:,} productos)")
    print(f" - Modo: Paralelo asíncrono (4 canales simultáneos)\n")

    saved_count = 0
    start_time = time.time()
    semaphore = asyncio.Semaphore(4)

    conn_tcp = aiohttp.TCPConnector(limit=6, ssl=False)
    async with aiohttp.ClientSession(connector=conn_tcp) as session:
        # Descarga en bloques de 25 páginas en paralelo
        batch_size = 25
        for batch_start in range(start_page, end_page + 1, batch_size):
            batch_end = min(batch_start + batch_size, end_page + 1)
            tasks = [fetch_page(session, p, semaphore) for p in range(batch_start, batch_end)]
            results = await asyncio.gather(*tasks)

            now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
            for objects in results:
                for item in objects:
                    tier = classify_tier(item)
                    if tier not in ALLOWED_SUPPLIER_TIERS:
                        continue

                    sale_price = float(item.get("sale_price") or 0)
                    sug_price = float(item.get("suggested_price") or sale_price)
                    margin = sug_price - sale_price

                    if margin < MIN_MARGIN:
                        continue

                    warehouses = item.get("product_warehouses", [])
                    total_stock = sum(int(w.get("stock") or 0) for w in warehouses)
                    if total_stock < MIN_STOCK:
                        continue

                    pid = item.get("id")
                    pname = (item.get("name") or "Sin nombre").strip()
                    cat = item.get("category") or "General"
                    supp_id = item.get("user_id")
                    supp_name = item.get("supplier_name") or "Proveedor"
                    img = item.get("gallery", [""])[0] if item.get("gallery") else ""

                    cursor.execute("""
                        INSERT OR REPLACE INTO products (
                            id, name, category, supplier_id, supplier_name, sale_price,
                            suggested_price, margin, image_url, created_at, updated_at,
                            store_name, is_verified, is_premium, supplier_plan, supplier_tier
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pid, pname, cat, supp_id, supp_name, sale_price, sug_price,
                        margin, img, item.get("created_at") or now_iso, now_iso,
                        item.get("store_name"), 1 if item.get("is_verified") else 0,
                        1 if item.get("is_premium") else 0, item.get("supplier_plan"), tier
                    ))

                    for wh in warehouses:
                        wh_id = wh.get("warehouse_id", 0)
                        stock_val = int(wh.get("stock") or 0)
                        cursor.execute("""
                            INSERT INTO stock_snapshots (product_id, warehouse_id, stock, recorded_at)
                            VALUES (?, ?, ?, ?)
                        """, (pid, wh_id, stock_val, now_iso))

                    saved_count += 1

            conn.commit()
            print(f" Worker #{worker_id}: Páginas hasta {batch_end-1}/{end_page} listas | Guardados: {saved_count:,} | Tiempo: {time.time() - start_time:.1f}s")

    conn.commit()
    conn.close()
    print(f"\n WORKER #{worker_id} FINALIZADO EN {time.time() - start_time:.1f}s. Total guardados: {saved_count:,}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", type=int, required=True, help="ID de este worker (1 a 4)")
    parser.add_argument("--total-workers", type=int, default=4, help="Total de workers paralelos")
    parser.add_argument("--total-pages", type=int, default=1500, help="Total de páginas del catálogo")
    args = parser.parse_args()

    asyncio.run(run_worker(args.worker_id, args.total_workers, args.total_pages))
