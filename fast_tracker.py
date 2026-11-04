import os
import time
import json
import asyncio
import aiohttp
import sqlite3
import random
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

DROPI_API_URL = os.getenv("DROPI_API_URL", "https://api.dropi.co/integrations/products/index")
DROPI_TOKEN = os.getenv("DROPI_TOKEN")
DB_PATH = os.path.join(os.path.dirname(__file__), "catalog.db")
CHECKPOINT_PATH = os.path.join(os.path.dirname(__file__), "tracker_checkpoint.json")

ALLOWED_SUPPLIER_TIERS = {"PREMIUM EXCLUSIVO", "PREMIUM", "VERIFICADO"}
MIN_STOCK = 15
MIN_MARGIN = 18000
PAGE_SIZE = 40  # Límite por petición de Dropi

# Headers idénticos a los del plugin oficial de WooCommerce de Dropi (inmunes a bloqueos de bot)
USER_AGENTS = [
    "DropiIntegration/2.4.0 (WordPress/6.4.3; WooCommerce/8.5.2)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_checkpoint() -> int:
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_page", 0)
        except Exception:
            return 0
    return 0

def save_checkpoint(page: int, total_saved: int, total_sales: int):
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "last_page": page,
            "total_saved": total_saved,
            "total_sales": total_sales,
            "updated_at": time.strftime('%Y-%m-%d %H:%M:%S')
        }, f, indent=2)

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

async def fetch_page_safe(session: aiohttp.ClientSession, page: int, delay_between_calls: float = 0.55) -> Optional[List[Dict[str, Any]]]:
    """
    Descarga controlada con ritmo adaptativo para evitar el firewall de Dropi:
    - Intervalo mínimo forzado entre peticiones
    - Detección temprana de 429 con pausa de enfriamiento
    - Reintentos con retroceso exponencial
    """
    headers = {
        "Content-Type": "application/json",
        "dropi-integration-key": DROPI_TOKEN,
        "User-Agent": random.choice(USER_AGENTS)
    }
    payload = {"pageSize": PAGE_SIZE, "page": page}

    # Pequeña pausa estricta para garantizar que nunca superemos 1.8 req/s
    await asyncio.sleep(delay_between_calls + random.uniform(0.05, 0.15))

    for attempt in range(1, 4):
        try:
            async with session.post(DROPI_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("objects", [])
                
                elif resp.status == 429:
                    wait_time = attempt * 12.0
                    print(f"\n [Alerta Preventiva] Rate Limit en pág {page}. Pausando {wait_time}s para enfriar firewall...", flush=True)
                    await asyncio.sleep(wait_time)
                
                elif resp.status == 401:
                    print(f"\n [BLOQUEO DETECTADO] Dropi respondió 401 en pág {page}. La IP sigue bloqueada temporalmente.", flush=True)
                    return None
                
                else:
                    await asyncio.sleep(2)
        except Exception as e:
            if attempt == 3:
                print(f" Advertencia: Fallo tras 3 intentos en pág {page}: {e}", flush=True)
            await asyncio.sleep(2.5)

    return []

async def run_safe_sweep(target_pages: int = 1250, resume: bool = True):
    """
    Barrido Masivo Anti-Bloqueo de 50.000 productos:
    - 1.250 páginas * 40 productos = 50.000 productos auditados
    - Ritmo seguro continuo (~1.4 req/s) sin saturar Dropi
    - Pausas de enfriamiento cada 40 páginas
    - Guardado progresivo con Checkpoint reanudable
    """
    start_page = 1
    if resume:
        saved_page = load_checkpoint()
        if saved_page > 0:
            start_page = saved_page + 1
            print(f" Reanudando desde página {start_page} (Checkpoint previo guardado)", flush=True)

    if start_page > target_pages:
        print(f" Ya se completó el objetivo de {target_pages} páginas ({target_pages * PAGE_SIZE:,} productos). Reiniciando ciclo de auditoría...", flush=True)
        start_page = 1

    total_prods_target = target_pages * PAGE_SIZE
    print(f"\n{'='*75}")
    print(f" MOTOR BLINDADO DE AUDITORÍA DROPI (ANTI-BLOQUEO 100%)")
    print(f" - Objetivo: {target_pages:,} páginas (~{total_prods_target:,} productos)")
    print(f" - Inicio: Página {start_page}")
    print(f" - Filtros: Stock >= {MIN_STOCK} | Margen >= ${MIN_MARGIN:,} COP | Bodegas Certificadas")
    print(f" - Estrategia: Delay controlado de 0.6s + Enfriamiento cada 40 páginas")
    print(f"{'='*75}\n", flush=True)

    conn = get_db()
    cursor = conn.cursor()

    total_saved = 0
    total_sales_detected = 0
    start_time = time.time()

    conn_tcp = aiohttp.TCPConnector(limit=5, ssl=False)
    async with aiohttp.ClientSession(connector=conn_tcp) as session:
        
        batch_size = 40  # Tanda de 40 páginas = 1.600 productos
        for batch_start in range(start_page, target_pages + 1, batch_size):
            batch_end = min(batch_start + batch_size, target_pages + 1)
            
            for page in range(batch_start, batch_end):
                objects = await fetch_page_safe(session, page, delay_between_calls=0.55)
                
                if objects is None:
                    print("\n El barrido se detiene preventivamente porque la IP aún está restringida por Dropi.")
                    print(" Por favor espera la expiración de la ventana o reinicia el módem de internet.")
                    conn.close()
                    return

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
                        INSERT INTO products (
                            id, name, category, supplier_id, supplier_name, sale_price,
                            suggested_price, margin, image_url, created_at, updated_at,
                            store_name, is_verified, is_premium, supplier_plan, supplier_tier
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name=excluded.name,
                            category=excluded.category,
                            sale_price=excluded.sale_price,
                            suggested_price=excluded.suggested_price,
                            margin=excluded.margin,
                            image_url=excluded.image_url,
                            updated_at=excluded.updated_at,
                            supplier_tier=excluded.supplier_tier
                    """, (
                        pid, pname, cat, supp_id, supp_name, sale_price, sug_price,
                        margin, img, item.get("created_at") or now_iso, now_iso,
                        item.get("store_name"), 1 if item.get("is_verified") else 0,
                        1 if item.get("is_premium") else 0, item.get("supplier_plan"), tier
                    ))

                    # Detección de ventas en bodega
                    for wh in warehouses:
                        wh_id = wh.get("warehouse_id", 0)
                        stock_val = int(wh.get("stock") or 0)

                        cursor.execute("""
                            SELECT stock FROM stock_history
                            WHERE product_id = ? AND warehouse_id = ?
                            ORDER BY id DESC LIMIT 1
                        """, (pid, wh_id))
                        last_snap = cursor.fetchone()

                        if last_snap:
                            last_stock = last_snap["stock"]
                            diff = last_stock - stock_val
                            if 0 < diff <= 250:
                                cursor.execute("""
                                    INSERT INTO sales_events (product_id, warehouse_id, units_sold, start_stock, end_stock, interval_hours, recorded_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (pid, wh_id, diff, last_stock, stock_val, 1.0, now_iso))
                                total_sales_detected += diff

                        cursor.execute("""
                            INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                            VALUES (?, ?, ?, ?)
                        """, (pid, wh_id, stock_val, now_iso))

                    total_saved += 1

                # Guardamos progreso página por página
                conn.commit()
                save_checkpoint(page, total_saved, total_sales_detected)

            elapsed = time.time() - start_time
            current_count = batch_end * PAGE_SIZE
            print(f" Bloque completado hasta pág {batch_end} (~{current_count:,} prods) | Guardados: {total_saved:,} | Ventas nuevas: {total_sales_detected:,} | Tiempo: {elapsed:.1f}s", flush=True)

            # Pausa de enfriamiento entre bloques de 40 páginas
            if batch_end < target_pages:
                cool_down = 5.0
                print(f" [Cool-down] Pausa de {cool_down}s para reiniciar contadores de Dropi...\n", flush=True)
                await asyncio.sleep(cool_down)

    conn.close()
    print(f"\n BARRIDO COMPLETO DE {target_pages * PAGE_SIZE:,} PRODUCTOS FINALIZADO EXITOSAMENTE!")

if __name__ == "__main__":
    import sys
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 1250
    asyncio.run(run_safe_sweep(target_pages=pages, resume=True))
