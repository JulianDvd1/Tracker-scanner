import os
import sys
import time
import json
import sqlite3
import random
import argparse
import queue
import threading
from typing import List, Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()

DROPI_API_URL = "https://api.dropi.co/integrations/products/index"

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 5        # Para incluir productos con stock moderado
MIN_MARGIN = 10000   # Margen neto mínimo
PAGE_SIZE = 40       # Límite estricto del servidor de Dropi (40 productos por paquete)

USER_AGENTS = [
    "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "WordPress/6.4; Dropify",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
]

def get_tokens() -> List[str]:
    tokens = []
    for k in ["DROPI_TOKEN_1", "DROPI_TOKEN_2", "DROPI_TOKEN_3", "DROPI_TOKEN_4", "DROPI_TOKEN"]:
        val = (os.getenv(k) or "").strip().strip('"').strip("'")
        if val and val not in tokens:
            tokens.append(val)
    return tokens

def get_google_proxies() -> List[str]:
    raw = os.getenv("GOOGLE_PROXY_URLS", "")
    proxies = [p.strip().strip('"').strip("'") for p in raw.split(",") if p.strip()]
    return proxies

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

def create_http_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def fetch_page_gas(
    session: requests.Session,
    page: int,
    token: str,
    google_proxies: List[str],
    proxy_idx_holder: List[int],
    cooldown_event: threading.Event,
    trigger_cooldown_fn
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
        "integration": True,
        "userVerified": True
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "dropi-integration-key": token,
        "User-Agent": random.choice(USER_AGENTS)
    }

    paquete_puente = {
        "url": DROPI_API_URL,
        "method": "post",
        "headers": headers,
        "payload": payload
    }

    max_retries = 4
    for attempt in range(1, max_retries + 1):
        # Si hay cooldown global activo, esperar a que termine
        cooldown_event.wait()

        # Determinar endpoint: Google Apps Script o llamada directa
        if google_proxies:
            idx = proxy_idx_holder[0] % len(google_proxies)
            proxy_idx_holder[0] += 1
            url_target = google_proxies[idx]
            is_gas = True
        else:
            url_target = DROPI_API_URL
            is_gas = False

        try:
            if is_gas:
                r = session.post(url_target, json=paquete_puente, timeout=35, allow_redirects=True)
                if r.status_code == 200:
                    try:
                        res_google = r.json()
                    except Exception:
                        res_google = {}

                    status_dropi = res_google.get("status")
                    if status_dropi == 200:
                        body = res_google.get("body", "{}")
                        data_dropi = json.loads(body) if isinstance(body, str) else body
                        if data_dropi.get("isSuccess"):
                            return data_dropi.get("objects", [])
                        return []
                    elif status_dropi == 429:
                        # Dropi reportó 429 a través de Google Apps Script
                        time.sleep(random.uniform(3.0, 5.0))
                        continue
                    else:
                        time.sleep(1.5)
                        continue
                elif r.status_code == 429:
                    time.sleep(random.uniform(3.0, 5.0))
                    continue
                else:
                    time.sleep(2.0)
            else:
                # Modo directo (fallback cuando no se han configurado proxies GAS)
                time.sleep(2.5)
                r = session.post(url_target, json=payload, headers=headers, timeout=25)
                if r.status_code == 200:
                    data_dropi = r.json()
                    if data_dropi.get("isSuccess"):
                        return data_dropi.get("objects", [])
                    return []
                elif r.status_code == 429:
                    trigger_cooldown_fn()
                    continue
                else:
                    time.sleep(1.5)
        except Exception as e:
            if attempt == max_retries:
                # print(f" Error persistente en pág {page}: {e}", flush=True)
                pass
            time.sleep(2.0)

    return []

def run_worker_pool(total_pages: int = 1250, num_workers: int = 4):
    tokens = get_tokens()
    if not tokens:
        print(" ERROR: Ningún token configurado para Dropi.", flush=True)
        sys.exit(1)

    google_proxies = get_google_proxies()
    num_workers = min(num_workers, len(tokens)) if len(tokens) < num_workers else num_workers
    if not google_proxies:
        print(" [AVISO] GOOGLE_PROXY_URLS no configurado. Operando en modo directo seguro (1 worker).", flush=True)
        num_workers = 1

    db_filename = "catalog.db"
    init_db(db_filename)
    conn = sqlite3.connect(db_filename, check_same_thread=False)
    cursor = conn.cursor()

    db_lock = threading.Lock()
    cooldown_lock = threading.Lock()
    cooldown_event = threading.Event()
    cooldown_event.set()
    last_cooldown_time = [0.0]

    def trigger_cooldown():
        with cooldown_lock:
            now = time.time()
            if now - last_cooldown_time[0] > 35:
                last_cooldown_time[0] = now
                print(f"\n [COOLDOWN GLOBAL] 429 persistente detectado. Pausa unificada de 30s...", flush=True)
                cooldown_event.clear()
                time.sleep(30.0)
                cooldown_event.set()
                print(f" [COOLDOWN GLOBAL] Reanudando peticiones...\n", flush=True)

    page_queue = queue.Queue()
    for p in range(1, total_pages + 1):
        page_queue.put(p)

    total_prods_assigned = total_pages * PAGE_SIZE
    print(f"\n=======================================================", flush=True)
    print(f" ESCÁNER DROPI COLOMBIA CON GAS PROXY POOL", flush=True)
    print(f" - Destino BD: {db_filename}", flush=True)
    print(f" - Tokens asignados: {len(tokens)} (1 por hilo concurrente)", flush=True)
    print(f" - Puentes Google Apps Script configurados: {len(google_proxies)}", flush=True)
    print(f" - Hilos paralelos (max_workers): {num_workers}", flush=True)
    print(f" - Páginas a auditar: 1 a {total_pages} (~{total_prods_assigned:,} productos)", flush=True)
    print(f"=======================================================\n", flush=True)

    saved_count = [0]
    pages_done = [0]
    start_time = time.time()

    def worker_thread(worker_idx: int):
        token = tokens[worker_idx % len(tokens)]
        session = create_http_session()
        proxy_idx_holder = [worker_idx]

        while True:
            try:
                page = page_queue.get_nowait()
            except queue.Empty:
                break

            objects = fetch_page_gas(
                session=session,
                page=page,
                token=token,
                google_proxies=google_proxies,
                proxy_idx_holder=proxy_idx_holder,
                cooldown_event=cooldown_event,
                trigger_cooldown_fn=trigger_cooldown
            )

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
                        # PROVEEDOR BÁSICO O NO VERIFICADO -> DESCARTADO DIRECTAMENTE
                        continue

                    sale_price = float(item.get("sale_price") or 0)
                    sug_price = float(item.get("suggested_price") or sale_price)
                    margin = sug_price - sale_price

                    if margin < MIN_MARGIN:
                        continue

                    # Sanitizar errores tipográficos de proveedores en Dropi (ej. patillera de 35k con sugerido 80M)
                    if (sale_price < 200000 and sug_price > sale_price * 5) or (sug_price > sale_price * 10) or sug_price > 10000000:
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
                        1 if is_prem else 0, plan_name, tier
                    ))

                    for wh in warehouses:
                        wh_id = wh.get("warehouse_id", 0)
                        stock_val = int(wh.get("stock") or 0)
                        valid_stocks.append((pid, wh_id, stock_val, now_iso))

                with db_lock:
                    for vp in valid_prods:
                        cursor.execute("""
                            INSERT OR REPLACE INTO products (
                                id, name, category, supplier_id, supplier_name, sale_price,
                                suggested_price, margin, image_url, created_at, updated_at,
                                store_name, is_verified, is_premium, supplier_plan, supplier_tier
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, vp)
                    for vs in valid_stocks:
                        cursor.execute("""
                            INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                            VALUES (?, ?, ?, ?)
                        """, vs)
                    saved_count[0] += len(valid_prods)

            with db_lock:
                pages_done[0] += 1
                current_done = pages_done[0]
                if current_done % 10 == 0 or current_done == total_pages:
                    conn.commit()
                    elapsed = time.time() - start_time
                    speed = current_done / (elapsed / 60) if elapsed > 0 else 0
                    print(f" -> Progreso: {current_done}/{total_pages} págs | Ganadores guardados: {saved_count[0]:,} | {speed:.1f} págs/min | Tiempo: {elapsed:.1f}s", flush=True)

            page_queue.task_done()

    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=worker_thread, args=(i,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    conn.commit()
    conn.close()
    elapsed = time.time() - start_time
    print(f"\n=======================================================", flush=True)
    print(f" ESCANEO COMPLETADO EN {elapsed:.1f}s ({elapsed/60:.1f} min)!", flush=True)
    print(f" TOTAL GANADORES GUARDADOS: {saved_count[0]:,}", flush=True)
    print(f"=======================================================\n", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", "--total-pages", dest="total_pages", type=int, default=1250, help="Total páginas (1250 = ~50.000 productos)")
    parser.add_argument("--workers", type=int, default=4, help="Número de hilos concurrentes (default 4)")
    args = parser.parse_args()

    run_worker_pool(total_pages=args.total_pages, num_workers=args.workers)
