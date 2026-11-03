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
# Limpiamos rigurosamente cualquier espacio, comilla o salto de línea invisible
DROPI_TOKEN = os.getenv("DROPI_TOKEN", "").strip().strip('"').strip("'")

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 15
MIN_MARGIN = 18000
PAGE_SIZE = 40

USER_AGENT = "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)"

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

async def fetch_page(session: aiohttp.ClientSession, page: int, log_diagnostic: bool = False) -> List[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "dropi-integration-key": DROPI_TOKEN,
        "User-Agent": USER_AGENT
    }
    
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

    await asyncio.sleep(0.75 + random.uniform(0.05, 0.15))

    for attempt in range(1, 4):
        try:
            async with session.post(DROPI_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                text = await resp.text()

                if log_diagnostic:
                    print(f" [DIAGNÓSTICO INICIAL] HTTP Status: {resp.status} | Respuesta: {text[:140]}", flush=True)

                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        if data.get("isSuccess"):
                            return data.get("objects", [])
                    except Exception:
                        pass
                    return []
                elif resp.status == 429:
                    wait_time = attempt * 12
                    print(f" [429 Rate-Limit] Pausa de {wait_time}s...", flush=True)
                    await asyncio.sleep(wait_time)
                elif resp.status == 401:
                    print(f" [401 Error pág {page}] Detalle: {text[:100]}", flush=True)
                    await asyncio.sleep(8)
                else:
                    await asyncio.sleep(2)
        except Exception as e:
            if attempt == 3:
                print(f" Error en pág {page}: {e}", flush=True)
            await asyncio.sleep(2)
    return []

async def run_worker(worker_id: int, total_workers: int = 4, total_pages: int = 800):
    if not DROPI_TOKEN:
        print(" ERROR: DROPI_TOKEN no configurado en GitHub Secrets.", flush=True)
        sys.exit(1)

    print(f" Longitud del token detectado: {len(DROPI_TOKEN)} caracteres (Comienza con: {DROPI_TOKEN[:10]}...)", flush=True)

    pages_per_worker = total_pages // total_workers
    start_page = ((worker_id - 1) * pages_per_worker) + 1
    end_page = start_page + pages_per_worker - 1
    if worker_id == total_workers:
        end_page = total_pages

    db_filename = f"worker_data_{worker_id}.db"
    init_worker_db(db_filename)
    conn = sqlite3.connect(db_filename)
    cursor = conn.cursor()

    print(f"\n=== WORKER #{worker_id} / {total_workers} INICIADO ===", flush=True)
    print(f" - Rango: Páginas {start_page} a {end_page} (~{(end_page - start_page + 1) * PAGE_SIZE:,} productos)", flush=True)
    print(f" - Ritmo seguro: 1 petición/segundo", flush=True)

    saved_count = 0
    start_time = time.time()

    conn_tcp = aiohttp.TCPConnector(limit=3, ssl=False)
    async with aiohttp.ClientSession(connector=conn_tcp) as session:
        for idx, page in enumerate(range(start_page, end_page + 1)):
            # En la primera petición de cada worker imprimimos el diagnóstico exacto
            is_first = (idx == 0)
            objects = await fetch_page(session, page, log_diagnostic=is_first)
            now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')

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

            if page % 15 == 0 or page == end_page:
                conn.commit()
                elapsed = time.time() - start_time
                print(f" -> Progreso: Página {page}/{end_page} auditada | Guardados: {saved_count:,} | Tiempo: {elapsed:.1f}s", flush=True)

    conn.commit()
    conn.close()
    print(f"\n WORKER #{worker_id} FINALIZADO EN {time.time() - start_time:.1f}s! Total guardados: {saved_count:,}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", type=int, required=True, help="ID de este worker (1 a 4)")
    parser.add_argument("--total-workers", type=int, default=4, help="Total de workers paralelos")
    parser.add_argument("--total-pages", type=int, default=800, help="Total de páginas del catálogo")
    args = parser.parse_args()

    asyncio.run(run_worker(args.worker_id, args.total_workers, args.total_pages))
