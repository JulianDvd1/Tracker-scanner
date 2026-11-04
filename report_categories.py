import analyzer

winners = analyzer.analyze_winning_products(min_recent_sales=1, min_active_days=1)
by_category = {}
for w in winners:
    cat = w.get('category') or 'General'
    if cat not in by_category:
        by_category[cat] = []
    by_category[cat].append(w)

print("=== RESUMEN POR CATEGORIAS DE GANADORES ===")
for cat, items in sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"\n--- CATEGORIA: {cat} ({len(items)} productos con ventas consistentes) ---")
    for p in items[:3]:
        name = p['name'].encode('ascii', 'ignore').decode('ascii').strip()[:35]
        supplier = (p.get('supplier_name') or 'N/A').encode('ascii', 'ignore').decode('ascii').strip()
        margin = p.get('margin', 0)
        tier = p.get('supplier_tier', 'N/A')
        print(f" * ID: {p['id']} | {name} | Ventas: {p['total_units_sold']} | Margen: ${margin:,} COP | Prov: {supplier} ({tier})")
