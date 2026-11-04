import urllib.request
import re

url = 'https://oauth.dropi.co/_next/static/chunks/app/oauth/authorize/page-01ffa24ae7750dac.js'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://oauth.dropi.co/oauth/authorize'
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as r:
    html = r.read().decode('utf-8')

# Ver dónde se define la redirección después de consent
# Busquemos chunks de consent
url_layout = 'https://oauth.dropi.co/oauth/consent'
req2 = urllib.request.Request(url_layout, headers=headers)
try:
    with urllib.request.urlopen(req2) as r2:
        c_html = r2.read().decode('utf-8')
        print("Consent HTML len:", len(c_html))
        scripts = re.findall(r'<script[^>]*src=[\'"]([^\'"]+)[\'"]', c_html)
        print("Scripts in consent:", scripts)
except Exception as e:
    print("Error getting consent page:", e)
