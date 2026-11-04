import os
import json
import urllib.parse
from mcp.server.fastmcp import FastMCP
from analyzer import analyze_winning_products, get_product_trend
from tracker import record_snapshot

mcp = FastMCP("dropi-winning-tracker")

@mcp.tool()
def get_meta_ad_library_links(search_term: str) -> str:
    """
    Genera enlaces directos y optimizados a la Biblioteca de Anuncios de Meta (Colombia)
    para auditar creativos, copys y ofertas de la competencia para un producto específico.
    """
    encoded = urllib.parse.quote(search_term)
    url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=CO&q={encoded}&search_type=keyword_unordered&media_type=all"
    return url

@mcp.tool()
def scan_catalog_now(max_products: int = 10000, only_verified: bool = True) -> str:
    """
    Ejecuta un barrido masivo del catálogo en vivo desde la API de Dropi hasta max_products (por defecto 10.000).
    Aplica el embudo de purga anti-basura: proveedores calificados, margen >= $18.000 y stock >= 15.
    """
    record_snapshot(max_products=max_products, page_size=100, min_margin=18000.0, min_stock=15)
    return f"Barrido masivo completado exitosamente para hasta {max_products} productos."

@mcp.tool()
def get_winning_products(min_recent_sales: int = 5, min_active_days: int = 2, min_margin: float = 15000.0) -> str:
    """
    Obtiene la lista de productos ganadores clasificados por consistencia temporal, velocidad de ventas y margen comercial.
    Filtra anomalías o caídas súbitas de stock sospechosas (retiros de inventario).
    """
    winners = analyze_winning_products(
        min_recent_sales=min_recent_sales,
        min_active_days=min_active_days,
        min_margin=min_margin
    )
    if not winners:
        return "Aún no se detectan productos con suficiente historial de ventas consistentes. Sugerencia: Realizar escaneos periódicos cada pocas horas para acumular deltas de stock."
    
    return json.dumps(winners[:15], indent=2, ensure_ascii=False)

@mcp.tool()
def inspect_product_trend(product_id: int) -> str:
    """
    Examina el historial de variaciones de stock y eventos de venta de un producto por su ID para verificar su consistencia.
    """
    trend = get_product_trend(product_id)
    return json.dumps(trend, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run()
