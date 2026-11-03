import os
import urllib.request
import zipfile
import shutil

# URL directa del release de tu repositorio:
DEFAULT_RELEASE_URL = "https://github.com/JulianDvd1/Tracker-scanner/releases/download/latest/catalog.db.zip"
DB_PATH = os.path.join(os.path.dirname(__file__), "catalog.db")
ZIP_PATH = os.path.join(os.path.dirname(__file__), "catalog.db.zip")

def sync_catalog(release_url: str = DEFAULT_RELEASE_URL):
    print(f" Descargando catálogo actualizado desde GitHub...")
    try:
        urllib.request.urlretrieve(release_url, ZIP_PATH)
        print(" Extrayendo base de datos...")
        with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
            zip_ref.extractall(os.path.dirname(__file__))
        os.remove(ZIP_PATH)
        print(" ¡Catálogo local actualizado exitosamente!")
    except Exception as e:
        print(f" Error al sincronizar: {e}")

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not url:
        print("Uso: python sync.py <URL_DEL_RELEASE_ZIP>")
    else:
        sync_catalog(url)
