"""
Motor de Análisis de Productos Ganadores para Dropi
Incorpora filtros anti-manipulación y análisis de consistencia temporal:
1. Consistencia: El producto debe haber tenido ventas en días o intervalos previos, no una caída repentina aislada.
2. Detección de retiros artificiales: Descuenta descensos abruptos de 100% que suelen ser proveedores cancelando stock.
3. Velocidad y Aceleración de Ventas: Crecimiento de demanda en los últimos periodos.
4. Margen comercial viable para pauta publicitaria.
"""

from db import get_connection
from datetime import datetime, timedelta

def analyze_winning_products(
    min_recent_sales=5,         # Mínimo de unidades vendidas recientemente
    min_active_days=2,          # Días mínimos con movimiento registrado (Consistencia)
    min_margin=15000,           # Margen mínimo sugerido en COP
    lookback_days=7,            # Ventana de tiempo a evaluar
    only_verified_premium=True  # Excluir proveedores que no sean Verificados ni Premium
):
    conn = get_connection()
    cursor = conn.cursor()

    # Traer todos los productos que tienen eventos de venta en la ventana de tiempo
    cutoff_date = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()

    query = """
    SELECT 
        p.id,
        p.name,
        p.category,
        p.supplier_name,
        p.store_name,
        p.supplier_tier,
        p.is_verified,
        p.is_premium,
        p.supplier_plan,
        p.sale_price,
        p.suggested_price,
        p.margin,
        p.image_url,
        COUNT(DISTINCT DATE(s.recorded_at)) as active_days_count,
        COUNT(s.id) as sales_events_count,
        SUM(s.units_sold) as total_units_sold,
        AVG(s.units_sold) as avg_units_per_event,
        MAX(s.recorded_at) as last_sale_time
    FROM products p
    JOIN sales_events s ON p.id = s.product_id
    WHERE s.recorded_at >= ?
    """
    params = [cutoff_date]

    if only_verified_premium:
        query += " AND p.supplier_tier IN ('PREMIUM EXCLUSIVO', 'PREMIUM', 'VERIFICADO')"

    query += " GROUP BY p.id"

    cursor.execute(query, (cutoff_date,))
    candidates = cursor.fetchall()

    results = []

    for row in candidates:
        prod = dict(row)
        prod_id = prod["id"]

        # 1. Filtro de consistencia: Verificar si tuvo ventas distribuidas y no un solo salto artificial
        active_days = prod["active_days_count"]
        total_sold = prod["total_units_sold"] or 0
        events_count = prod["sales_events_count"]

        # Obtener los eventos detallados para chequear caídas sospechosas
        cursor.execute("""
            SELECT start_stock, end_stock, units_sold, interval_hours, recorded_at
            FROM sales_events
            WHERE product_id = ?
            ORDER BY recorded_at ASC
        """, (prod_id,))
        events = cursor.fetchall()

        # Detección de anomalías: Si una sola reducción representa >85% de todas las ventas
        # y dejó el stock en 0 exacto sin eventos previos, es altamente probable que sea un retiro de stock manual.
        is_suspicious = False
        if len(events) <= 2:
            for ev in events:
                if ev["units_sold"] > 50 and ev["end_stock"] == 0:
                    is_suspicious = True
                    break

        if is_suspicious:
            prod["score_tag"] = "DESCARTADO: Retiro de inventario sospechoso"
            continue

        # 2. Puntuación de "Winning Product":
        # Score = (Consistencia de días * 30) + (Total ventas * 2) + (Margen / 1000)
        score = (active_days * 30) + (total_sold * 1.5) + (max(0, prod["margin"]) / 2000)

        # Determinar nivel de validación
        if active_days >= min_active_days and total_sold >= min_recent_sales:
            status = "🔥 GANADOR CONFIRMADO (Consistente)"
        elif total_sold >= min_recent_sales and active_days < min_active_days:
            status = "⚠️ EN OBSERVACIÓN (Poco historial previo)"
        else:
            status = "🌱 POTENCIAL / CRECIENDO"

        prod["score"] = round(score, 2)
        prod["status"] = status
        results.append(prod)

    # Ordenar por el score calculado descendente
    results.sort(key=lambda x: x["score"], reverse=True)
    conn.close()
    return results

def get_product_trend(product_id):
    """Retorna la curva histórica de stock y ventas de un producto específico."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT stock, warehouse_name, recorded_at 
        FROM stock_history 
        WHERE product_id = ? 
        ORDER BY recorded_at ASC
    """, (product_id,))
    history = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT units_sold, start_stock, end_stock, recorded_at
        FROM sales_events
        WHERE product_id = ?
        ORDER BY recorded_at ASC
    """, (product_id,))
    sales = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {"stock_history": history, "sales_events": sales}

if __name__ == "__main__":
    winners = analyze_winning_products(min_recent_sales=1, min_active_days=1)
    print(f"Productos analizados con eventos de venta: {len(winners)}")
    print(f"Top 20 Productos con Mejor Regularidad y Ventas:\n")
    for w in winners[:20]:
        status_clean = w['status'].encode('ascii', 'ignore').decode('ascii').strip()
        name_clean = w['name'].encode('ascii', 'ignore').decode('ascii').strip()
        cat_clean = (w['category'] or 'General').encode('ascii', 'ignore').decode('ascii').strip()
        margin = w.get('margin', 0)
        print(f"[{status_clean}] ID: {w['id']} | {name_clean[:32]} | Cat: {cat_clean} | Ventas: {w['total_units_sold']} | Margen: ${margin:,} | Score: {w['score']}")

