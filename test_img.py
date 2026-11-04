import sqlite3
import urllib.request
import urllib.parse

conn = sqlite3.connect('catalog.db')
c = conn.cursor()
c.execute("SELECT id, name, image_url FROM products WHERE image_url IS NOT NULL AND image_url != '' LIMIT 5")
rows = c.fetchall()
conn.close()

print("Ejemplos de image_url en DB:")
for r in rows:
    print(r[0], r[1][:25], "-->", r[2])

if rows:
    path = rows[0][2].lstrip('/')
    bases = [
        'https://app.dropi.co/',
        'https://api.dropi.co/',
        'https://s3.amazonaws.com/dropi-media/',
        'https://dropi-media.s3.amazonaws.com/',
        'https://dropi.co/',
        'https://storage.googleapis.com/dropi-media/'
    ]
    for b in bases:
        # Encodear partes de la url que tengan espacios
        parts = path.split('/')
        quoted_path = '/'.join(urllib.parse.quote(p) for p in parts)
        u = b + quoted_path
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"SUCCESS {resp.status} - Content-Type: {resp.headers.get('Content-Type')} from {b}")
                print(f"URL probada: {u}")
                break
        except Exception as e:
            print(f"Failed {b}: {e}")
