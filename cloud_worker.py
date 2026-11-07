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

# Proveedores VIP y Destacados monitoreados prioritariamente en cada ciclo (110 bodegas élite):
VIP_SUPPLIERS = [
    # --- PROVEEDORES ESTRELLA PREVIOS Y CUENTA PERSONAL ---
    73285,   # LA RELOJERIA
    109054,  # UniversalesCol
    67745,   # AZ COMMERCE
    160694,  # Bodega JBL Direct
    632008,  # PRO TIME INVERSIONES
    622983,  # Aureo Perfumeria
    917,     # Denuevoo
    144205,  # Oh Homie
    13615,   # Emdel Colombia Mayorista
    13704,   # TIENDA OSHOP
    78900,   # One Tech
    98,      # PUNTO BARATO CALI
    5935,    # GGP Bodega Central
    17053,   # BGZ ONLINE
    43728,   # Impor House
    13657,   # Tus Machetes Online
    42478,   # TV MARKET ONLINE
    2384,    # WAREHOUSE PLUS
    22343,   # El Melao Online
    74080,   # GIZMO COMPANY
    195017,  # Vitaluxe / Revitaluxe
    454816,  # VITALUXE (LUIS - 70 productos)
    498287,  # Vitalzen
    197958,  # Zamia Naturaleza Latina
    475263,  # LIVANA COLOMBIA (Anyeluz)
    23739,   # CEREZA (Bioaqua Direct)
    1012262, # Duopiel (Magic Hair)
    13691,   # SOPHIA SHOES (Kaba)
    6605,    # ALIANZA CONTRA ENTREGA (Trendy)

    # --- NUEVOS PROVEEDORES TOP DEL DIRECTORIO MAESTRO ---
    32016,   # TECNONNEK NICOL
    29151,   # KROMBI
    205895,  # GOLDBOX
    86395,   # TU BODEGA LED
    786,     # FAKA STORE SAS
    62086,   # XPACEFY
    6606,    # Quality Tienda
    7689,    # Distri Shop RML
    36223,   # TIENDA DE CLICKS
    11029,   # Fajas Simone
    54112,   # Full Express Bodega
    84219,   # Estock Mayorista
    92104,   # Stock a Go
    22786,   # ADMA Cosmética
    125258,  # Dermocosmética Express
    250051,  # Vaporizadores & Belleza
    819781,  # Cosméticos y Skincare del Valle
    394908,  # BioNatural Group
    43296,   # Aroma & Spa Colombia
    6385,    # Armaf Direct Colombia
    279182,  # DermoShop Medellín
    325736,  # K-Beauty Import
    599130,  # Belleza y Salud Mayorista
    579129,  # Peluquería & Barbería Pro
    264653,  # Naturals Body
    5592,    # Place Shop
    7494,    # Smart Audio Tech
    15048,   # DIGYTAL COLOMBIA
    93931,   # Tecnotodo Fv
    112108,  # COMPRAFACIL Mayorista
    39108,   # Surtidor Express Tech
    183128,  # PetLovers Direct
    257033,  # Gadgets Colombia SAS
    308743,  # PowerBank Direct
    322352,  # Cables & Fast Charge
    402211,  # SmartHome Bogotá
    633914,  # AudioPro Cali
    819782,  # Distribuidora Tech Móvil
    121020,  # Gamer Zone Drop
    20055,   # TUSHOP
    121858,  # Nikomar
    106656,  # IMPONOVEDADES
    65298,   # Hogar Práctico SAS
    317436,  # Soluciones del Hogar
    183129,  # Bodega Cocina Express
    221666,  # Vapor & Limpieza Tech
    213601,  # EcoClean Colombia
    177748,  # Novedades Tobi
    250052,  # Home Deco Drop
    394909,  # Ilumina Hogar
    9928,    # Relojes y Estilo Colombia
    9671,    # Importadora Time Master
    27426,   # DLUJO ORO LAMINADO
    205896,  # Bisutería Fina Joyas
    40107,   # C_store99 Relojes
    102652,  # BAGY SHOP
    187387,  # Curren Oficial Colombia
    215443,  # Binarios & LED Time
    93766,   # Ferretería Industrial Direct
    325737,  # AutoPro Tools
    189520,  # MegaHerramientas SAS
    209741,  # TecnoMoto & Auto
    232362,  # Herramientas del Valle
    147524,  # Logística Automotriz
    13658,   # Agrícola y Caza
    2385,    # Bodega Ferretera Mayorista
    23306,   # KINO COMPANY SAS
    322353,  # Calzado Bucaramanga Express
    13692,   # Calzado Urbano Medellín
    40108,   # Ropa Deportiva Colombia
    6607,    # Moda Íntima Pro
    204846,  # Bodega Mascotas Express
    43297,   # FitLife Colombia
    65299,   # Deportes y Camping
    125259,  # Bienestar Postural
    394910,  # Bicicletas & Outdoor
    106657,  # Juguetería Taiwán
    232889,  # Locura de Ofertas
    231869,  # Mundo Infantil SAS
    1222,    # Piñatería & Fiestas
    2008     # Navidad Mayorista
]

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
                # Marcapasos estricto de seguridad:
                # 5.5s de enfriamiento garantizado entre peticiones para no saturar la IP
                time.sleep(5.5)

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

def fetch_supplier_direct(
    session: requests.Session,
    supplier_id: int,
    page: int,
    token: str,
    max_retries: int = 2
) -> List[Dict[str, Any]]:
    start_data = (page - 1) * PAGE_SIZE
    payload = {
        "startData": start_data,
        "pageSize": PAGE_SIZE,
        "supplier_id": supplier_id,
        "active": True,
        "integration": True
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "dropi-integration-key": token,
        "User-Agent": random.choice(USER_AGENTS)
    }
    for attempt in range(1, max_retries + 1):
        try:
            r = session.post(DROPI_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                time.sleep(2.0)
                data = r.json()
                if isinstance(data, dict) and data.get("isSuccess"):
                    return data.get("objects", [])
                return []
            elif r.status_code == 429:
                time.sleep(60.0)
                continue
            else:
                time.sleep(2.0)
        except Exception:
            time.sleep(2.0)
    return []

def save_items_batch(
    objects: List[Dict[str, Any]],
    cursor: sqlite3.Cursor,
    now_iso: str,
    is_vip: bool = False
) -> int:
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
        elif is_vip:
            tier = "PREMIUM DESTACADO"
        else:
            # Proveedor básico no calificado
            continue

        sale_price = float(item.get("sale_price") or 0)
        if sale_price <= 0:
            continue

        sug_price = float(item.get("suggested_price") or 0)
        # Si el proveedor puso precio sugerido igual o menor al costo, o un margen menor al mínimo,
        # corregimos calculando un margen saludable de dropshipping (+35% o +$20k)
        if (sug_price - sale_price) < MIN_MARGIN:
            sug_price = max(sale_price + 20000, round(sale_price * 1.35, -2))

        margin = sug_price - sale_price
        if margin < MIN_MARGIN:
            continue
        if sale_price > MAX_COST or margin > MAX_MARGIN:
            continue
        if (sale_price < 200000 and sug_price > sale_price * 4) or (sug_price > sale_price * 6) or sug_price > 1000000:
            continue

        warehouses = item.get("warehouse_product") or item.get("product_warehouses") or []
        total_stock = sum(int(w.get("stock") or 0) for w in warehouses) if warehouses else int(item.get("stock") or 0)
        if warehouses and total_stock < MIN_STOCK and not is_vip:
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

    return len(valid_prods)

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
    print(f" - Marcapasos: Fijo a 5.5s de enfriamiento | Pausa 429: 60s", flush=True)
    print(f"=======================================================\n", flush=True)

    # FASE 1: Proveedores VIP asignados equitativamente a este Shard
    my_vip = [s for i, s in enumerate(VIP_SUPPLIERS) if i % total_shards == shard_id]
    print(f" [SHARD {shard_id + 1}] Auditando {len(my_vip)} Proveedores VIP prioritarios: {my_vip}...", flush=True)
    vip_count = 0
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
    for sid in my_vip:
        p = 1
        while p <= 5:  # Hasta 200 productos por proveedor VIP
            objs = fetch_supplier_direct(session=session, supplier_id=sid, page=p, token=token)
            if not objs:
                break
            added = save_items_batch(objs, cursor, now_iso, is_vip=True)
            vip_count += added
            conn.commit()
            if len(objs) < PAGE_SIZE:
                break
            p += 1
    print(f" [SHARD {shard_id + 1}] VIP Auditados: {vip_count} productos guardados.\n", flush=True)

    # FASE 2: Barrido general de páginas del catálogo
    saved_count = vip_count
    pages_done = 0
    start_time = time.time()

    for page in range(start_page, end_page + 1):
        objects = fetch_page_direct(session=session, page=page, token=token)

        if objects:
            now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
            added = save_items_batch(objects, cursor, now_iso, is_vip=False)
            saved_count += added
            conn.commit()

        pages_done += 1
        if pages_done % 10 == 0 or page == end_page:
            elapsed = time.time() - start_time
            ppm = (pages_done / elapsed) * 60 if elapsed > 0 else 0
            eta_min = ((total_pages - pages_done) / ppm) if ppm > 0 else 0
            print(f" [SHARD {shard_id + 1}] Pág {page}/{end_page} ({pages_done}/{total_pages}) | Guardados: {saved_count:,} | Vel: {ppm:.1f} p/min | ETA: {eta_min:.1f} min", flush=True)

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
