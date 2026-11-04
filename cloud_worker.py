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
DROPI_TOKEN = os.getenv("DROPI_TOKEN", "").strip().strip('"').strip("'")

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 15
MIN_MARGIN = 18000
PAGE_SIZE = 40

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

async def fetch_page(session: aiohttp.ClientSession, start_data: int) -> List[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "dropi-integration-key": DROPI_TOKEN,
        "User-Agent": "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)"
    }
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

    # Delay constante de 1.2s para respetar el límite de 1 req/s del Token de Dropi
    await asyncio.sleep(1.2)

    for attempt in range(1, 4):
        try:
            async with session.post(DROPI_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("isSuccess"):
                        return data.get("objects", [])
                    return []
                elif resp.status == 429:
                    wait_time = attempt * 8
                    print(f" [Dropi 429] Esperando {wait_time}s para vaciar cuota de token...", flush=True)
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(2)
        except Exception as e:
            if attempt == 3:
                print(f" Error conexión en offset {start_data}: {e}", flush=True)
            await asyncio.sleep(2)
    return []

async def run_scanner(max_pages: int = 250):
    """
    Rastreador maestro de catálogo activo:
    - 250 páginas = 10.000 productos con rotación reciente
    - 1 solo proceso limpio sin choques de 429
    - Claves exactas de Dropi: warehouse_product y user.category_user
    """
    if not DROPI_TOKEN:
        print(" ERROR: DROPI_TOKEN no configurado en GitHub Secrets.", flush=True)
        sys.exit(1)

    db_filename = "worker_data_1.db"
    init_worker_db(db_filename)
    conn = sqlite3.connect(db_filename)
    cursor = conn.cursor()

    print(f"\n=======================================================", flush=True)
    print(f" DROPI CLOUD SCANNER MAESTRO INICIADO", flush=True)
    print(f" - Páginas objetivo: {max_pages} (~{max_pages * PAGE_SIZE:,} productos)", flush=True)
    print(f" - Ritmo: 1 petición cada 1.2s (Cero choques 429)", flush=True)
    print(f"=======================================================\n", flush=True)

    saved_count = 0
    start_time = time.time()

    conn_tcp = aiohttp.TCPConnector(limit=2, ssl=False)
    async with aiohttp.ClientSession(connector=conn_tcp) as session:
        for page in range(1, max_pages + 1):
            start_data = (page - 1) * PAGE_SIZE
            objects = await fetch_page(session, start_data)

            if not objects:
                # Si Dropi no devuelve objetos tras varias páginas, llegamos al final del catálogo activo
                if page > 10:
                    print(f" Final del catálogo activo alcanzado en página {page}.", flush=True)
                    break
                continue

            now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
            for item in objects:
                # 1. Tier de proveedor (Detección robusta de verificación)
                user_data = item.get("user") or {}
                cat_user = user_data.get("category_user") or {}
                is_veri = bool(item.get("is_verified") or user_data.get("is_verified") or item.get("userVerified"))
                is_prem = bool(item.get("is_premium") or user_data.get("is_premium") or "PREMIUM" in str(item.get("supplier_name", "")).upper())
                plan = str(cat_user.get("name") or user_data.get("plan") or item.get("supplier_plan") or "").upper()

                if "EXCLUSIVO" in plan:
                    tier = "PREMIUM EXCLUSIVO"
                elif is_prem or "PREMIUM" in plan:
                    tier = "PREMIUM"
                else:
                    tier = "VERIFICADO"

                # 2. Precios y margen
                sale_price = float(item.get("sale_price") or 0)
                sug_price = float(item.get("suggested_price") or sale_price)
                margin = sug_price - sale_price

                if margin < MIN_MARGIN:
                    continue

                # 3. Stock real en bodegas (Compatibilidad total con warehouse_product y stock directo)
                warehouses = item.get("warehouse_product") or item.get("product_warehouses") or []
                total_stock = sum(int(w.get("stock") or 0) for w in warehouses) if warehouses else int(item.get("stock") or 0)
                if warehouses and total_stock < MIN_STOCK:
                    continue

                # 4. Imagen válida
                gallery = item.get("gallery") or []
                img = ""
                if gallery:
                    img = gallery[0].get("urlS3") or gallery[0].get("url") or (gallery[0] if isinstance(gallery[0], str) else "")

                pid = item.get("id")
                pname = (item.get("name") or "Sin nombre").strip()
                categories = item.get("categories") or []
                cat = categories[0].get("name") if categories else (item.get("category") or "General")

                supp_id = user_data.get("id") or item.get("user_id")
                supp_name = user_data.get("name") or item.get("supplier_name") or "Proveedor"
                store_name = user_data.get("store_name") or supp_name
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
                    store_name, 1 if item.get("is_verified") else 0,
                    1 if item.get("is_premium") else 0, plan_name, tier
                ))

                for wh in warehouses:
                    wh_id = wh.get("warehouse_id", 0)
                    stock_val = int(wh.get("stock") or 0)
                    cursor.execute("""
                        INSERT INTO stock_snapshots (product_id, warehouse_id, stock, recorded_at)
                        VALUES (?, ?, ?, ?)
                    """, (pid, wh_id, stock_val, now_iso))

                saved_count += 1

            if page % 10 == 0 or page == max_pages:
                conn.commit()
                elapsed = time.time() - start_time
                print(f" -> Página {page}/{max_pages} auditada | Ganadores guardados: {saved_count:,} | Tiempo: {elapsed:.1f}s", flush=True)

    conn.commit()
    conn.close()
    total_elapsed = time.time() - start_time
    print(f"\n BARRIDO FINALIZADO EN {total_elapsed:.1f}s! Total ganadores guardados: {saved_count:,}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=250, help="Páginas a auditar")
    args, _ = parser.parse_known_args()

    asyncio.run(run_scanner(max_pages=args.pages))
