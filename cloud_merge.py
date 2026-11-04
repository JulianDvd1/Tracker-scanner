import os
import glob
import sqlite3
import zipfile
import time

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

def merge_all_workers():
    init_master_db()
    conn_master = sqlite3.connect(MASTER_DB)
    c_master = conn_master.cursor()

    worker_files = sorted(glob.glob("downloaded_artifacts/**/worker_data_*.db", recursive=True) + glob.glob("worker_data_*.db"))
    worker_files = list(dict.fromkeys(worker_files))
    print(f"\n Fusionando {len(worker_files)} bases de datos parciales encontradas: {worker_files}...")

    total_prods_merged = 0
    total_sales_detected = 0
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')

    for w_file in worker_files:
        print(f" -> Procesando {w_file}...")
        w_conn = sqlite3.connect(w_file)
        w_conn.row_factory = sqlite3.Row
        w_cursor = w_conn.cursor()

        # 1. Insertar o actualizar productos
        w_cursor.execute("SELECT * FROM products")
        prods = w_cursor.fetchall()
        for p in prods:
            d = dict(p)
            c_master.execute("""
                INSERT OR REPLACE INTO products (
                    id, name, category, supplier_id, supplier_name, sale_price,
                    suggested_price, margin, image_url, created_at, updated_at,
                    store_name, is_verified, is_premium, supplier_plan, supplier_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d["id"], d["name"], d["category"], d["supplier_id"], d["supplier_name"],
                d["sale_price"], d["suggested_price"], d["margin"], d["image_url"],
                d["created_at"], now_iso, d["store_name"], d["is_verified"],
                d["is_premium"], d["supplier_plan"], d["supplier_tier"]
            ))
            total_prods_merged += 1

        # 2. Procesar snapshots de stock y detectar ventas
        w_cursor.execute("SELECT * FROM stock_snapshots")
        snaps = w_cursor.fetchall()
        for s in snaps:
            pid = s["product_id"]
            wid = s["warehouse_id"]
            current_stock = s["stock"]

            # Comprobar ultimo stock registrado en el master
            c_master.execute("""
                SELECT stock FROM stock_history
                WHERE product_id = ? AND warehouse_id = ?
                ORDER BY id DESC LIMIT 1
            """, (pid, wid))
            last = c_master.fetchone()

            if last:
                last_stock = last[0]
                diff = last_stock - current_stock
                if 0 < diff <= 250:
                    c_master.execute("""
                        INSERT INTO sales_events (product_id, warehouse_id, units_sold, start_stock, end_stock, interval_hours, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (pid, wid, diff, last_stock, current_stock, 1.0, now_iso))
                    total_sales_detected += diff

            c_master.execute("""
                INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (pid, wid, current_stock, now_iso))

        w_conn.close()

    conn_master.commit()
    conn_master.close()

    print(f"\n CONSOLIDACIÓN EXITOSA:")
    print(f" - Productos consolidados: {total_prods_merged:,}")
    print(f" - Ventas nuevas detectadas: {total_sales_detected:,}")

    # Comprimir en zip para descarga ultrarrápida
    zip_path = "catalog.db.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(MASTER_DB, arcname="catalog.db")
    
    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f" - Archivo comprimido generado: {zip_path} ({zip_size_mb:.2f} MB)")

if __name__ == "__main__":
    merge_all_workers()
