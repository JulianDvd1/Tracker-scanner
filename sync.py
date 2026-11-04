import os
import urllib.request
import zipfile
import sqlite3
import time

DEFAULT_RELEASE_URL = "https://github.com/JulianDvd1/Tracker-scanner/releases/download/v1.0-data/catalog.db.zip"
DB_PATH = os.path.join(os.path.dirname(__file__), "catalog.db")
ZIP_PATH = os.path.join(os.path.dirname(__file__), "catalog.db.zip")
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp_sync")

def init_local_db():
    conn = sqlite3.connect(DB_PATH)
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

def sync_catalog(release_url: str = DEFAULT_RELEASE_URL):
    print(f" Descargando catálogo actualizado desde GitHub Actions...")
    init_local_db()

    try:
        urllib.request.urlretrieve(release_url, ZIP_PATH)
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
            zip_ref.extractall(TEMP_DIR)
        os.remove(ZIP_PATH)

        cloud_db = os.path.join(TEMP_DIR, "catalog.db")
        if not os.path.exists(cloud_db):
            print(" Error: No se encontró catalog.db dentro del ZIP descargado.")
            return

        print(" Fusionando datos de la nube con la base de datos local...")
        conn_local = sqlite3.connect(DB_PATH)
        conn_cloud = sqlite3.connect(cloud_db)
        conn_cloud.row_factory = sqlite3.Row

        c_local = conn_local.cursor()
        c_cloud = conn_cloud.cursor()

        # 1. Fusionar productos
        c_cloud.execute("SELECT * FROM products")
        cloud_prods = c_cloud.fetchall()
        for p in cloud_prods:
            d = dict(p)
            c_local.execute("""
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
                d["id"], d["name"], d["category"], d["supplier_id"], d["supplier_name"],
                d["sale_price"], d["suggested_price"], d["margin"], d["image_url"],
                d["created_at"], d.get("updated_at") or time.strftime('%Y-%m-%dT%H:%M:%S'),
                d["store_name"], d["is_verified"], d["is_premium"], d["supplier_plan"], d["supplier_tier"]
            ))

        # 2. Fusionar stock y calcular ventas nuevas si hay disminución
        now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
        new_sales = 0
        c_cloud.execute("SELECT * FROM stock_history")
        for s in c_cloud.fetchall():
            pid = s["product_id"]
            wid = s["warehouse_id"]
            cur_stock = s["stock"]

            c_local.execute("""
                SELECT stock FROM stock_history
                WHERE product_id = ? AND warehouse_id = ?
                ORDER BY id DESC LIMIT 1
            """, (pid, wid))
            last = c_local.fetchone()

            if last:
                diff = last[0] - cur_stock
                if 0 < diff <= 250:
                    c_local.execute("""
                        INSERT INTO sales_events (product_id, warehouse_id, units_sold, start_stock, end_stock, interval_hours, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (pid, wid, diff, last[0], cur_stock, 2.0, now_iso))
                    new_sales += diff

            c_local.execute("""
                INSERT INTO stock_history (product_id, warehouse_id, stock, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (pid, wid, cur_stock, now_iso))

        conn_local.commit()
        conn_cloud.close()
        conn_local.close()

        # Limpiar temporal
        try:
            import shutil
            shutil.rmtree(TEMP_DIR)
        except Exception:
            pass

        print(f" ¡Fusión completada exitosamente! Productos sincronizados: {len(cloud_prods)} | Nuevas ventas detectadas: {new_sales}")

    except Exception as e:
        print(f" Error al sincronizar: {e}")

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RELEASE_URL
    sync_catalog(url)
