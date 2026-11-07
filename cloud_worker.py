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
    # --- TOP 300 PROVEEDORES ÉLITE DE DROPI COLOMBIA ---
    73285,  # LA RELOJERIA (PREMIUM - 150 prods)
    109054,  # UniversalesCol (VERIFICADO - 264 prods)
    67745,  # AZ COMMERCE (PREMIUM - 387 prods)
    160694,  # EliteDrop (VERIFICADO - 170 prods)
    632008,  # PRO TIME INVERSIONES (PREMIUM - 664 prods)
    622983,  # Aureo Perfumeria (PREMIUM - 320 prods)
    917,  # Denuevoo (VERIFICADO - 376 prods)
    144205,  # Oh Homie (PREMIUM EXCLUSIVO - 1547 prods)
    13615,  # Emdel Colombia Mayorista (PREMIUM EXCLUSIVO - 616 prods)
    13704,  # TIENDA OSHOP (PREMIUM EXCLUSIVO - 307 prods)
    78900,  # One tech (PREMIUM EXCLUSIVO - 293 prods)
    98,  # PUNTO BARATO CALI (PREMIUM EXCLUSIVO - 56 prods)
    5935,  # GGP (PREMIUM EXCLUSIVO - 905 prods)
    17053,  # BGZ ONLINE (PREMIUM - 1332 prods)
    43728,  # impor house (PREMIUM - 1598 prods)
    13657,  # Tus Machetes Online (VERIFICADO - 1504 prods)
    42478,  # TV MARKET ONLINE (VERIFICADO - 1002 prods)
    2384,  # WAREHOUSE PLUS (VERIFICADO - 236 prods)
    22343,  # El Melao Online (PREMIUM - 303 prods)
    74080,  # GIZMO COMPANY (PREMIUM - 336 prods)
    195017,  # Proveedor VIP (VIP - 0 prods)
    454816,  # VITALUXE (PREMIUM EXCLUSIVO - 67 prods)
    498287,  # Vitalzen (PREMIUM - 208 prods)
    197958,  # Zamia Naturaleza Latina (VERIFICADO - 1509 prods)
    475263,  # LIVANA COLOMBIA SAS (VERIFICADO - 189 prods)
    23739,  # CEREZA (VERIFICADO - 132 prods)
    1012262,  # Duopiel (PREMIUM - 180 prods)
    13691,  # SOPHIA SHOES (PREMIUM - 91 prods)
    6605,  # ALIANZA CONTRA ENTREGA (PREMIUM - 66 prods)
    32016,  # TECNONNEK NICOL (PREMIUM - 840 prods)
    29151,  # KROMBI (PREMIUM - 387 prods)
    205895,  # GOLDBOX (PREMIUM - 239 prods)
    86395,  # TU BODEGA LED (PREMIUM - 40 prods)
    786,  # FAKA STORE  SAS (PREMIUM - 193 prods)
    62086,  # XPACEFY (PREMIUM - 107 prods)
    6606,  # Quality Tienda (PREMIUM - 372 prods)
    7689,  # Distri Shop RML (PREMIUM - 184 prods)
    36223,  # TIENDA DE CLICKS (PREMIUM - 780 prods)
    11029,  # Proveedor VIP (VIP - 0 prods)
    54112,  # Proveedor VIP (VIP - 0 prods)
    84219,  # Proveedor VIP (VIP - 0 prods)
    92104,  # Proveedor VIP (VIP - 0 prods)
    22786,  # ADMA (VERIFICADO - 230 prods)
    125258,  # Shop Colombia (PREMIUM - 119 prods)
    250051,  # Todo Novedad Centro (PREMIUM - 93 prods)
    819781,  # LLEVAME ON LINE COLOMBIA (PREMIUM - 74 prods)
    394908,  # Proveedor VIP (VIP - 0 prods)
    43296,  # Proveedor VIP (VIP - 0 prods)
    6385,  # DITRIBUIDORA ALEDAN (VERIFICADO - 179 prods)
    279182,  # ROGO SHOP (PREMIUM - 9 prods)
    325736,  # Proveedor VIP (VIP - 0 prods)
    599130,  # CLOCK COLOMBIA SAS (PREMIUM - 3 prods)
    579129,  # Proveedor VIP (VIP - 0 prods)
    264653,  # GLOBAL TIME LATAM (PREMIUM - 2 prods)
    5592,  # Place Shop (PREMIUM - 75 prods)
    7494,  # Directo a casa (VERIFICADO - 3 prods)
    15048,  # DIGYTAL COLOMBIA (VERIFICADO - 307 prods)
    93931,  # Tecnotodo Fv (VERIFICADO - 232 prods)
    112108,  # Proveedor VIP (VIP - 0 prods)
    39108,  # Proveedor VIP (VIP - 0 prods)
    183128,  # KATZ SUPPLY 🐈‍⬛ (PREMIUM - 91 prods)
    257033,  # Proveedor VIP (VIP - 0 prods)
    308743,  # VIRTUAL TENDENCE (PREMIUM - 1 prods)
    322352,  # CALZADO JHOMELISS (PREMIUM - 9 prods)
    402211,  # Proveedor VIP (VIP - 0 prods)
    633914,  # Royal Traders (PREMIUM - 51 prods)
    819782,  # Proveedor VIP (VIP - 0 prods)
    121020,  # Proveedor VIP (VIP - 0 prods)
    20055,  # TUSHOP (VERIFICADO - 149 prods)
    121858,  # Nikomar (VERIFICADO - 439 prods)
    106656,  # IMPONOVEDADES (VERIFICADO - 1085 prods)
    65298,  # Proveedor VIP (VIP - 0 prods)
    317436,  # Proveedor VIP (VIP - 0 prods)
    183129,  # Proveedor VIP (VIP - 0 prods)
    221666,  # Proveedor VIP (VIP - 0 prods)
    213601,  # Proveedor VIP (VIP - 0 prods)
    177748,  # Proveedor VIP (VIP - 0 prods)
    250052,  # Proveedor VIP (VIP - 0 prods)
    394909,  # Proveedor VIP (VIP - 0 prods)
    9928,  # CURREN LATAM (PREMIUM EXCLUSIVO - 61 prods)
    9671,  # TUDEO 2.0 BODEGA ONLINE (PREMIUM - 10 prods)
    27426,  # DLUJO ORO LAMINADO (PREMIUM - 154 prods)
    205896,  # Proveedor VIP (VIP - 0 prods)
    40107,  # C_store99 (VERIFICADO - 296 prods)
    102652,  # BAGY SHOP (VERIFICADO - 336 prods)
    187387,  # Proveedor VIP (VIP - 0 prods)
    215443,  # Proveedor VIP (VIP - 0 prods)
    93766,  # AlphaTechnology (VERIFICADO - 63 prods)
    325737,  # Proveedor VIP (VIP - 0 prods)
    189520,  # Proveedor VIP (VIP - 0 prods)
    209741,  # Proveedor VIP (VIP - 0 prods)
    232362,  # Proveedor VIP (VIP - 0 prods)
    147524,  # Proveedor VIP (VIP - 0 prods)
    13658,  # Proveedor VIP (VIP - 0 prods)
    2385,  # Proveedor VIP (VIP - 0 prods)
    23306,  # KINO COMPANY SAS (VERIFICADO - 185 prods)
    322353,  # Proveedor VIP (VIP - 0 prods)
    13692,  # Proveedor VIP (VIP - 0 prods)
    40108,  # Proveedor VIP (VIP - 0 prods)
    6607,  # Proveedor VIP (VIP - 0 prods)
    204846,  # Proveedor VIP (VIP - 0 prods)
    43297,  # Proveedor VIP (VIP - 0 prods)
    65299,  # Proveedor VIP (VIP - 0 prods)
    125259,  # Proveedor VIP (VIP - 0 prods)
    394910,  # Proveedor VIP (VIP - 0 prods)
    106657,  # Proveedor VIP (VIP - 0 prods)
    232889,  # Proveedor VIP (VIP - 0 prods)
    231869,  # Proveedor VIP (VIP - 0 prods)
    1222,  # Proveedor VIP (VIP - 0 prods)
    2008,  # Proveedor VIP (VIP - 0 prods)
    365543,  # Variedades L&G (VERIFICADO - 2260 prods)
    192984,  # ADRIANA (PREMIUM - 1670 prods)
    833898,  # NS NATURALES (PREMIUM - 1506 prods)
    45331,  # DEROCHA STORE SAS (PREMIUM EXCLUSIVO - 1267 prods)
    35040,  # DTS IMPORTADORES (PREMIUM EXCLUSIVO - 1169 prods)
    308761,  # CLICKSTORE (PREMIUM - 817 prods)
    179249,  # ADYSFAST (PREMIUM - 814 prods)
    10046,  # Brothers Shoes (VERIFICADO - 752 prods)
    832655,  # Perfumissimo Colombia (PREMIUM - 734 prods)
    118707,  # PERFUMERIA GLOW FRAGANCE (VERIFICADO - 652 prods)
    539491,  # CORMEGA S.A.S (PREMIUM - 646 prods)
    27764,  # SEVEN Y ELEVEN (VERIFICADO - 636 prods)
    407399,  # Vidix (PREMIUM - 585 prods)
    49923,  # TOONS MAYORISTA (VERIFICADO - 562 prods)
    825649,  # Vaxaris JM (PREMIUM - 551 prods)
    21996,  # Worldsport.co (VERIFICADO - 540 prods)
    464853,  # Juguetería Taiwán (PREMIUM - 481 prods)
    825412,  # GM (PREMIUM - 460 prods)
    47,  # ADMA (PREMIUM - 443 prods)
    70316,  # sr virtual shop (PREMIUM - 421 prods)
    551808,  # Manifiesto de atracción perfumeria (PREMIUM - 419 prods)
    846870,  # Compra Facil Colombia (PREMIUM - 416 prods)
    94839,  # AROMA DE PRIMERA (VERIFICADO - 405 prods)
    215864,  # Multinicho Store (VERIFICADO - 400 prods)
    73779,  # A Tu Mano Bodega (PREMIUM - 396 prods)
    520562,  # PRO CLICK (VERIFICADO - 391 prods)
    32318,  # Diversidades mf (VERIFICADO - 391 prods)
    58998,  # ONIX  TECH (VERIFICADO - 366 prods)
    243946,  # Labodega de accesorios (VERIFICADO - 321 prods)
    409447,  # IMPERIUM (PREMIUM - 314 prods)
    10826,  # GD Colombia (PREMIUM - 312 prods)
    96165,  # Unimarket (VERIFICADO - 311 prods)
    6338,  # tecnologia mundial el paisa (PREMIUM - 302 prods)
    75231,  # KIOH OFICIAL (PREMIUM - 294 prods)
    472806,  # etherflowstore43 (PREMIUM - 290 prods)
    358931,  # Dalclick Store (PREMIUM - 287 prods)
    3897,  # www.ventasbogota.com (PREMIUM - 279 prods)
    177132,  # BOGOCLOCK (VERIFICADO - 270 prods)
    844431,  # Botania (VERIFICADO - 268 prods)
    4454,  # BCOMPANY (VERIFICADO - 262 prods)
    14644,  # POWERFUL (PREMIUM - 261 prods)
    3195,  # tlovend (VERIFICADO - 254 prods)
    178340,  # Distribuciones Román (VERIFICADO - 252 prods)
    937033,  # Androy Sport (PREMIUM - 247 prods)
    64606,  # TMAX TECNOLOGIA SAS (VERIFICADO - 242 prods)
    651177,  # VitalEcoms Prov (PREMIUM - 237 prods)
    105021,  # FABIAN PATIÑO (PREMIUM - 235 prods)
    354795,  # Eladio (PREMIUM - 227 prods)
    64834,  # Stockeado + Andrey Business (PREMIUM EXCLUSIVO - 227 prods)
    100837,  # TELE VARIEDADES  JV (PREMIUM - 226 prods)
    777541,  # Parfum store (PREMIUM - 219 prods)
    147195,  # Wopi Bodega (PREMIUM - 216 prods)
    73211,  # Ventas colombia (VERIFICADO - 215 prods)
    7151,  # cubimart (VERIFICADO - 215 prods)
    7165,  # MVMarcas.com (VERIFICADO - 211 prods)
    432393,  # Jm tecnologia (VERIFICADO - 208 prods)
    72363,  # 2024Store (PREMIUM - 208 prods)
    147584,  # Mds Store (PREMIUM - 206 prods)
    5076,  # GRAVIFLY (VERIFICADO - 191 prods)
    52856,  # IMPOWINNER (PREMIUM EXCLUSIVO - 188 prods)
    72962,  # Tu San Victorino (VERIFICADO - 185 prods)
    553114,  # Heidy (PREMIUM - 184 prods)
    43339,  # MUNDO TENDENCIAS/ SERUM 10 (PREMIUM - 182 prods)
    66141,  # TULASTORE (PREMIUM - 181 prods)
    637846,  # DIAMOND TECHNOLOGY  DISTRIBUTIONS S.A.S (VERIFICADO - 179 prods)
    115342,  # LA BODEGUITA CHINA (PREMIUM EXCLUSIVO - 179 prods)
    537179,  # Igniz Technology (PREMIUM - 178 prods)
    34202,  # BARATON VENTAS (PREMIUM - 178 prods)
    1027949,  # SOL NATURE (PREMIUM - 176 prods)
    680217,  # La luz de Maria (PREMIUM - 176 prods)
    32580,  # powermin32 (PREMIUM - 175 prods)
    85343,  # Geeka Market (VERIFICADO - 171 prods)
    42879,  # Exploradoras Led Tubodega (VERIFICADO - 171 prods)
    817140,  # Davidcommerce (PREMIUM - 169 prods)
    762866,  # PERFUM SHOP (PREMIUM - 169 prods)
    982666,  # REYES Y LOGISTICA S.A.S (PREMIUM - 167 prods)
    216010,  # Hornet Shop (PREMIUM - 159 prods)
    965595,  # comercializadora el Hueco (PREMIUM - 157 prods)
    52350,  # Bodega NEW TECNOLOGY FC (VERIFICADO - 157 prods)
    224165,  # BODEGA VHERMELA (PREMIUM - 154 prods)
    967954,  # Todo Esencial (PREMIUM - 153 prods)
    893051,  # gabrielle perfumeria (PREMIUM - 151 prods)
    53267,  # LUTHIER (VERIFICADO - 150 prods)
    166172,  # TecnoGar (VERIFICADO - 147 prods)
    36442,  # MACAEL (PREMIUM - 143 prods)
    286651,  # A UN SOLO CLICK (VERIFICADO - 142 prods)
    122530,  # Joesma Prov. (PREMIUM - 141 prods)
    39222,  # COMERCIALIZADORA SUKI S.A.S (VERIFICADO - 141 prods)
    39858,  # Beta Store Online (PREMIUM - 140 prods)
    441247,  # CONTAINER IMPORTACIONES S.A.S (PREMIUM - 139 prods)
    679300,  # Alfusa (PREMIUM - 138 prods)
    8086,  # Dimportados (PREMIUM - 136 prods)
    21472,  # Primo's CyberMarket (PREMIUM EXCLUSIVO - 134 prods)
    980300,  # MAGENTA SEX SHOP (PREMIUM - 133 prods)
    17792,  # ImperioMedellin (VERIFICADO - 132 prods)
    16698,  # Tienda Yosep (PREMIUM - 132 prods)
    11004,  # Gold Stone (PREMIUM EXCLUSIVO - 132 prods)
    376574,  # Locura De Ofertas (PREMIUM - 131 prods)
    87204,  # Distriecom (VERIFICADO - 125 prods)
    55394,  # FYA (VERIFICADO - 125 prods)
    31053,  # COLOMBIA DE COMPRAS TV (PREMIUM - 125 prods)
    39095,  # PerduOutlet (PREMIUM - 124 prods)
    250912,  # Decoplantas Online (VERIFICADO - 123 prods)
    148403,  # Velandia (PREMIUM - 122 prods)
    933658,  # Easytools (PREMIUM - 118 prods)
    4173,  # Triada (PREMIUM - 116 prods)
    78620,  # Colombia Hogar (VERIFICADO - 115 prods)
    894235,  # infinity shop (PREMIUM - 114 prods)
    218726,  # MOTO STEEL SAS (PREMIUM - 114 prods)
    651557,  # SKYTEC (VERIFICADO - 113 prods)
    771002,  # BIOBELL COMPANY SAS (PREMIUM - 112 prods)
    22984,  # UNMERCO (VERIFICADO - 112 prods)
    1005293,  # Agriequipos (PREMIUM - 111 prods)
    945805,  # Variedades JP (PREMIUM - 111 prods)
    834096,  # hamilton (PREMIUM - 111 prods)
    322772,  # bigtoy (PREMIUM - 110 prods)
    199820,  # null (PREMIUM - 109 prods)
    39512,  # De Compras (VERIFICADO - 109 prods)
    958276,  # Special Moments (PREMIUM - 108 prods)
    859966,  # DeseOculto (PREMIUM - 107 prods)
    932443,  # Danne variedades (PREMIUM - 106 prods)
    156110,  # Rcimportaciones (VERIFICADO - 105 prods)
    36082,  # Zococio tienda (VERIFICADO - 105 prods)
    20227,  # Twimo (VERIFICADO - 105 prods)
    8705,  # Soluciones Shop (VERIFICADO - 105 prods)
    632711,  # PERFUMERIA ROYAL AROMA (PREMIUM - 104 prods)
    797942,  # Neo Variedades (PREMIUM - 102 prods)
    661724,  # Kavada Bodega Mayorista (PREMIUM - 102 prods)
    302619,  # Alimentos Nutricionales Natural Health SAS (PREMIUM - 101 prods)
    12510,  # Tienda AMMS (VERIFICADO - 101 prods)
    596817,  # FLY (PREMIUM - 100 prods)
    207761,  # GRAVIFLY (PREMIUM - 99 prods)
    671741,  # Tiendafy (PREMIUM - 98 prods)
    73761,  # Consigueloo (VERIFICADO - 97 prods)
    1000939,  # Magic Confort (PREMIUM - 96 prods)
    7297,  # AG COSMETICS - BURBAY BEAUTY (VERIFICADO - 96 prods)
    973796,  # perfumery fhanthon (PREMIUM - 95 prods)
    40749,  # Fenix store (PREMIUM - 95 prods)
    45561,  # G.W.T. (VERIFICADO - 94 prods)
    13352,  # TUCOLTIENDA (VERIFICADO - 92 prods)
    72889,  # Tendex.co (VERIFICADO - 91 prods)
    136436,  # Elcontainer.shop (VERIFICADO - 90 prods)
    804229,  # TECNOVARIEDADES (PREMIUM - 89 prods)
    775799,  # Nexion tech (VERIFICADO - 89 prods)
    302862,  # Thunder Store ⚡ (PREMIUM - 89 prods)
    290771,  # Cero Tabú Sexshop (PREMIUM - 89 prods)
    918064,  # DISTRI JJ (PREMIUM - 88 prods)
    71362,  # BEST PRICE COLOMBIA (VERIFICADO - 88 prods)
    367018,  # SyJ Global (VERIFICADO - 87 prods)
    350805,  # Alma Verde Naturals (VERIFICADO - 87 prods)
    204867,  # SHOPLIC MARKET (VERIFICADO - 87 prods)
    469966,  # KETAL BUSINESS (PREMIUM - 86 prods)
    796386,  # D&T.STORE COLOMBIA- (PREMIUM - 85 prods)
    625426,  # IMPERIO7 (PREMIUM - 84 prods)
    100463,  # Importadora MAKA SAS (VERIFICADO - 84 prods)
    69935,  # G-MASS SAS (PREMIUM - 83 prods)
    20019,  # BALI (VERIFICADO - 83 prods)
    3242,  # AMERCAR (PREMIUM EXCLUSIVO - 83 prods)
    447674,  # Resveratrol Colombia (PREMIUM - 82 prods)
    217564,  # TIENDA GOLD ONLINE (PREMIUM - 82 prods)
    13544,  # Tienda Qcarachitos (VERIFICADO - 82 prods)
    640540,  # apulso virtual shop (PREMIUM - 81 prods)
    167740,  # GRAVIFLY (PREMIUM - 81 prods)
    879303,  # viviana (PREMIUM - 80 prods)
    668029,  # innovatech colombia (PREMIUM - 79 prods)
    595191,  # Ecommerce Elite (PREMIUM - 78 prods)
    437394,  # Link Game (PREMIUM - 77 prods)
    54262,  # Stockeado Andrey Business (PREMIUM EXCLUSIVO - 77 prods)
    602246,  # Liamu Tech (PREMIUM - 76 prods)
    210347,  # APOLO SAS (VERIFICADO - 75 prods)
    10349,  # Klixmant (VERIFICADO - 75 prods)
    911649,  # M&M MARKET (PREMIUM - 74 prods)
    525509,  # Ylo Shoes (PREMIUM - 74 prods)
    940506,  # VARIEDADES F&F (PREMIUM - 73 prods)
    795046,  # Miadex Global (PREMIUM - 73 prods)
    317816,  # TeamG6 (PREMIUM - 73 prods)
    232067,  # Dropmarket Colombia (VERIFICADO - 73 prods)
    48926,  # ANT (PREMIUM - 73 prods)
    778365,  # Sayii Cosmeticos (PREMIUM - 72 prods)
    600636,  # ariastore (PREMIUM - 72 prods)
    289273,  # Distribuidora Suple UP (VERIFICADO - 72 prods)
    971292,  # Bogo Accesorios (PREMIUM - 71 prods)
    480941,  # BLACK SWAN (PREMIUM - 71 prods)
    323272,  # GDL store (VERIFICADO - 71 prods)
    923772,  # bodega m/j (PREMIUM - 70 prods)
    863049,  # Ardicarrselectro (PREMIUM - 70 prods)
    556357,  # FOCUS (PREMIUM - 70 prods)
    145270,  # null (PREMIUM - 70 prods)
    124607,  # dream (VERIFICADO - 70 prods)
    92800,  # Julian (PREMIUM - 70 prods)
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

    try:
        public_ip = session.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        public_ip = "No detectada"

    print(f"\n=======================================================", flush=True)
    print(f" ESCÁNER DROPI DIRECTO - SHARD {shard_id + 1}/{total_shards}", flush=True)
    print(f" - Destino BD: {db_name}", flush=True)
    print(f" - IP Pública Saliente: {public_ip}", flush=True)
    print(f" - Token asignado: {masked_token}", flush=True)
    print(f" - Rango de páginas: {start_page} a {end_page} ({total_pages} páginas | ~{total_pages * PAGE_SIZE:,} productos)", flush=True)
    print(f" - Marcapasos: Fijo a 5.5s de enfriamiento | Pausa 429: 60s", flush=True)
    print(f"=======================================================\n", flush=True)

    # FASE 1: Proveedores VIP asignados equitativamente a este Shard
    my_vip = [s for i, s in enumerate(VIP_SUPPLIERS) if i % total_shards == shard_id]
    print(f" [SHARD {shard_id + 1}] Auditando {len(my_vip)} Proveedores VIP prioritarios (máx 2 pág/bodega)...", flush=True)
    vip_count = 0
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
    for i_sid, sid in enumerate(my_vip, 1):
        p = 1
        while p <= 2:  # Optimizado a 2 páginas (80 productos más recientes/más vendidos) por ciclo
            objs = fetch_supplier_direct(session=session, supplier_id=sid, page=p, token=token)
            if not objs:
                break
            added = save_items_batch(objs, cursor, now_iso, is_vip=True)
            vip_count += added
            conn.commit()
            if len(objs) < PAGE_SIZE:
                break
            p += 1
        if i_sid % 10 == 0 or i_sid == len(my_vip):
            print(f" [SHARD {shard_id + 1}] VIP Progreso: {i_sid}/{len(my_vip)} bodegas auditadas ({vip_count} productos)", flush=True)
    print(f" [SHARD {shard_id + 1}] VIP Fase 1 Completada: {vip_count} productos guardados.\n", flush=True)

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
