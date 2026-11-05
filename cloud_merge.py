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
                        # Si el stock disminuyó entre 1 y 250 unidades, es una venta confirmada
                        if 0 < diff <= 250:
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
