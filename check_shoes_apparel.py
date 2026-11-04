import sqlite3

conn = sqlite3.connect('catalog.db')
c = conn.cursor()
c.execute("""
    SELECT id, name, category, supplier_name, sale_price, suggested_price, margin
    FROM products 
    WHERE (category LIKE '%Moda%' OR category LIKE '%Ropa%' OR category LIKE '%Textiles%' OR name LIKE '%zapato%' OR name LIKE '%tenis%' OR name LIKE '%pantalon%' OR name LIKE '%chaqueta%' OR name LIKE '%bota%')
      AND margin >= 18000
    ORDER BY margin DESC
    LIMIT 10
""")
print("--- PRODUCTOS DE MODA, ROPA Y ZAPATOS CON ALTO MARGEN ---")
for r in c.fetchall():
    name = r[1].encode('ascii', 'ignore').decode('ascii').strip()[:35]
    prov = (r[3] or 'N/A').encode('ascii', 'ignore').decode('ascii').strip()
    print(f"ID: {r[0]} | {name} | Cat: {r[2]} | Costo: ${r[4]:,} | Sugerido: ${r[5]:,} | Margen: ${r[6]:,} COP | Prov: {prov}")
conn.close()
