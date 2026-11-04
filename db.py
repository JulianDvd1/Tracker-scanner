import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "catalog.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Tabla maestra de productos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT,
        supplier_id INTEGER,
        supplier_name TEXT,
        store_name TEXT,
        is_verified BOOLEAN DEFAULT 0,
        is_premium BOOLEAN DEFAULT 0,
        supplier_plan TEXT,
        sale_price REAL,
        suggested_price REAL,
        margin REAL,
        image_url TEXT,
        last_stock_activity TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Tabla de variaciones de stock (snapshots en el tiempo)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        warehouse_id INTEGER,
        warehouse_name TEXT,
        stock INTEGER NOT NULL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)

    # Tabla de cálculo de ventas por producto (ventas estimadas periódicas)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        warehouse_id INTEGER,
        units_sold INTEGER NOT NULL,
        start_stock INTEGER,
        end_stock INTEGER,
        interval_hours REAL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)

    # Índices para consultas rápidas
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_product_time ON stock_history(product_id, recorded_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_product_time ON sales_events(product_id, recorded_at)")

    conn.commit()
    conn.close()
    print("Base de datos inicializada correctamente en:", DB_PATH)

if __name__ == "__main__":
    init_db()
