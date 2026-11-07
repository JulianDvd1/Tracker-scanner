import os
import glob
import sqlite3
import zipfile
import time
import datetime
import requests

MASTER_DB = "catalog.db"

def init_master_db():
    conn = sqlite3.connect(MASTER_DB)
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
    # Asegurar que la columna stock existe si el catálogo proviene de un release anterior
    cols = [r[1] for r in c.execute("PRAGMA table_info(products)").fetchall()]
    if 'stock' not in cols:
        c.execute("ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT 0")

    c.execute("""
        CREATE TABLE IF NOT EXISTS meta_sync (
            key TEXT PRIMARY KEY,
            val TEXT
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

def fetch_node2_shards():
    url = "https://github.com/JulianDvd1/Tracker-scanner-worker2/releases/download/v1.0-worker2/worker2-shards.zip"
    try:
        print(" -> Intentando descargar Shards del Nodo 2 (Shards 4-7) desde " + url + "...")
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            os.makedirs("downloaded_shards/node2", exist_ok=True)
            with open("worker2-shards.zip", "wb") as f:
                f.write(r.content)
            with zipfile.ZipFile("worker2-shards.zip", "r") as z:
                z.extractall("downloaded_shards/node2")
            print(" -> Shards del Nodo 2 descargados y extraídos con éxito.")
            if os.path.exists("worker2-shards.zip"):
                os.remove("worker2-shards.zip")
        else:
            print(f" -> Nodo 2 no disponible o aún no publicado (HTTP {r.status_code}). Se continuará con los shards locales.")
    except Exception as e:
        print(f" -> Aviso: no se pudieron descargar shards del Nodo 2: {e}")

def restore_previous_catalog():
    if os.path.exists(MASTER_DB):
        return
    url = "https://github.com/JulianDvd1/Tracker-scanner/releases/download/v1.0-data/catalog.db.zip"
    try:
        print(f" -> Intentando descargar catálogo previo desde Release para trazabilidad de ventas...")
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            with open("prev_catalog.zip", "wb") as f:
                f.write(r.content)
            with zipfile.ZipFile("prev_catalog.zip", "r") as z:
                z.extractall(".")
            print(" -> Catálogo previo restaurado con éxito.")
            if os.path.exists("prev_catalog.zip"):
                os.remove("prev_catalog.zip")
    except Exception as e:
        print(f" -> No se pudo restaurar catálogo previo (se creará uno nuevo): {e}")

def merge_all_shards():
    fetch_node2_shards()
    restore_previous_catalog()
    init_master_db()

    conn_master = sqlite3.connect(MASTER_DB)
    c_master = conn_master.cursor()

    patterns = [
        "downloaded_shards/**/*.db",
        "downloaded_shards/*.db",
        "catalog_shard_*.db",
        "worker_data_*.db",
        "downloaded_artifacts/**/*.db"
    ]
    shard_files = []
    for pat in patterns:
        shard_files.extend(glob.glob(pat, recursive=True))

    shard_files = [f for f in list(dict.fromkeys(shard_files)) if os.path.basename(f) != MASTER_DB]
    shard_files.sort()

    print(f"\n=======================================================")
    print(f" FUSIÓN DE SHARDS DE DROPI")
    print(f" - Shards encontrados ({len(shard_files)}): {shard_files}")
    print(f" - Base de datos destino: {MASTER_DB}")
    print(f"=======================================================\n")

    if not shard_files:
        print(" [AVISO] No se encontraron archivos de shards para fusionar.")

    total_prods_merged = 0
    total_sales_detected = 0
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')

    for s_file in shard_files:
        print(f" -> Procesando {s_file}...")
        try:
            s_conn = sqlite3.connect(s_file)
            s_conn.row_factory = sqlite3.Row
            s_cursor = s_conn.cursor()

            # 1. Insertar / Actualizar productos ganadores
            s_cursor.execute("SELECT * FROM products")
            prods = s_cursor.fetchall()
            valid_prods = []
            for p in prods:
                d = dict(p)
                valid_prods.append((
                    d["id"], d["name"], d.get("category"), d.get("supplier_id"), d.get("supplier_name"),
                    d.get("sale_price"), d.get("suggested_price"), d.get("margin"), d.get("image_url"),
                    d.get("created_at"), now_iso, d.get("store_name"), d.get("is_verified", 0),
                    d.get("is_premium", 0), d.get("supplier_plan"), d.get("supplier_tier"),
                    d.get("stock", 0)
                ))

            if valid_prods:
                c_master.executemany("""
                    INSERT OR REPLACE INTO products (
                        id, name, category, supplier_id, supplier_name, sale_price,
                        suggested_price, margin, image_url, created_at, updated_at,
                        store_name, is_verified, is_premium, supplier_plan, supplier_tier, stock
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, valid_prods)
                total_prods_merged += len(valid_prods)

            # 2. Copiar stock_history y calcular ventas
            try:
                s_cursor.execute("SELECT product_id, warehouse_id, stock, recorded_at FROM stock_history")
                stocks = s_cursor.fetchall()
                for st in stocks:
                    pid = st["product_id"]
                    wid = st["warehouse_id"]
                    current_stock = st["stock"]
                    rec_at = st["recorded_at"] or now_iso

                    # Comparar con el último stock conocido en master
                    c_master.execute("""
                        SELECT stock FROM stock_history
                        WHERE product_id = ? AND warehouse_id = ?
                        ORDER BY id DESC LIMIT 1
                    """, (pid, wid))
                    last = c_master.fetchone()

                    if last:
                        last_stock = last[0]
                        diff = last_stock - current_stock
                        drop_ratio = (diff / last_stock) if last_stock > 0 else 0

                        # Filtros Anti-Anomalías y Ajustes Manuales de Bodega:
                        # 1. Caída violenta del inventario (>55% del stock cuando son más de 20 unidades)
                        is_abrupt_drop = (drop_ratio > 0.55 and diff > 20)
                        # 2. Exceso atípico de volumen para un solo intervalo de 2 horas (>150 unidades)
                        is_excess_volume = (diff > 150)
                        # 3. Ajuste a números redondos de inventario de bodega (0, 5, 10, 50, 100) con más del 50% de caída y >= 15 unds
                        is_round_adjustment = (current_stock in (0, 5, 10, 50, 100) and drop_ratio > 0.50 and diff >= 15)

                        is_anomaly = is_abrupt_drop or is_excess_volume or is_round_adjustment

                        # Si el stock disminuyó legítimamente sin ser anomalía de inventario
                        if 0 < diff and not is_anomaly:
                            c_master.execute("""
                                INSERT INTO sales_events (product_id, warehouse_id, units_sold, start_stock, end_stock, interval_hours, recorded_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (pid, wid, diff, last_stock, current_stock, 1.0, rec_at))
                            total_sales_detected += diff

                    c_master.execute("""
                        INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                        VALUES (?, ?, ?, ?)
                    """, (pid, wid, current_stock, rec_at))

            except sqlite3.OperationalError:
                pass

            s_conn.close()

        except Exception as e:
            print(f" [ERROR] Error leyendo shard {s_file}: {e}")

    # Optimización de alto rendimiento: Índices y Tabla Resumen
    print(" -> Generando índices y tabla resumen de alta velocidad para la web...")
    c_master.execute("""
        CREATE TABLE IF NOT EXISTS product_sales_summary (
            product_id INTEGER PRIMARY KEY,
            units_sold INTEGER DEFAULT 0,
            events_count INTEGER DEFAULT 0,
            last_sale TEXT DEFAULT '',
            week_units INTEGER DEFAULT 0
        )
    """)
    # Purgar anomalías históricas (ajustes manuales o caídas mayores al 55% de inventario)
    c_master.execute("""
        DELETE FROM sales_events 
        WHERE (start_stock > 0 AND (units_sold * 1.0 / start_stock) > 0.55 AND units_sold > 20)
           OR units_sold > 150
           OR (end_stock IN (0, 5, 10, 50, 100) AND (units_sold * 1.0 / NULLIF(start_stock, 0)) > 0.50 AND units_sold >= 15)
    """)

    c_master.execute("DELETE FROM product_sales_summary")
    c_master.execute("""
        INSERT INTO product_sales_summary (product_id, units_sold, events_count, last_sale, week_units)
        SELECT 
            product_id, 
            COALESCE(sum(units_sold), 0), 
            count(*), 
            COALESCE(max(recorded_at), ''),
            COALESCE(sum(CASE WHEN date(recorded_at) >= date('now', '-7 days') THEN units_sold ELSE 0 END), 0)
        FROM sales_events
        GROUP BY product_id
    """)

    c_master.execute("CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category)")
    c_master.execute("CREATE INDEX IF NOT EXISTS idx_products_margin ON products(margin)")
    c_master.execute("CREATE INDEX IF NOT EXISTS idx_products_tier ON products(supplier_tier)")
    c_master.execute("CREATE INDEX IF NOT EXISTS idx_products_supp ON products(supplier_name)")
    c_master.execute("CREATE INDEX IF NOT EXISTS idx_products_price ON products(sale_price)")
    c_master.execute("CREATE INDEX IF NOT EXISTS idx_sales_prod ON sales_events(product_id)")
    c_master.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_events(recorded_at)")
    
    # Grabar hora exacta colombiana de la consolidación en la base de datos
    colombia_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5)))
    c_master.execute("INSERT OR REPLACE INTO meta_sync (key, val) VALUES ('last_scan_time', ?)", (colombia_dt.strftime("%I:%M %p"),))
    c_master.execute("INSERT OR REPLACE INTO meta_sync (key, val) VALUES ('last_scan_iso', ?)", (colombia_dt.isoformat(),))
    conn_master.commit()

    # Contar total consolidado único
    c_master.execute("SELECT COUNT(*) FROM products")
    unique_prods = c_master.fetchone()[0]

    c_master.execute("SELECT COUNT(*) FROM stock_history")
    total_stocks = c_master.fetchone()[0]

    conn_master.close()

    print(f"\n=======================================================")
    print(f" CONSOLIDACIÓN EXITOSA:")
    print(f" - Productos únicos en catálogo: {unique_prods:,}")
    print(f" - Inserciones totales procesadas: {total_prods_merged:,}")
    print(f" - Registros de stock: {total_stocks:,}")
    print(f" - Ventas nuevas detectadas: {total_sales_detected:,}")

    # Comprimir a catalog.db.zip
    zip_path = "catalog.db.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(MASTER_DB, arcname="catalog.db")

    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f" - Archivo comprimido generado: {zip_path} ({zip_size_mb:.2f} MB)")
    print(f"=======================================================\n")

    # Generar nota detallada con hora colombiana para GitHub Releases
    colombia_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5)))
    hora_colombia_str = colombia_dt.strftime("%Y-%m-%d %I:%M:%S %p")
    release_note = f"""## 🚀 Catálogo Dropi Colombia Consolidado (50k)
- 📅 **Último Escaneo:** {hora_colombia_str} (Hora Colombia)
- 📦 **Productos en Catálogo:** {unique_prods:,}
- 📈 **Nuevas Ventas Detectadas:** {total_sales_detected:,}
- 💾 **Archivo Base de Datos:** `catalog.db` ({zip_size_mb:.2f} MB)

*Generado automáticamente por el clúster multi-OS de GitHub Actions.*
"""
    with open("release_body.md", "w", encoding="utf-8") as f:
        f.write(release_note)

if __name__ == "__main__":
    merge_all_shards()
