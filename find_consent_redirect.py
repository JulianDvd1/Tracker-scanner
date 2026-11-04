import urllib.request
import re

url = 'https://oauth.dropi.co/_next/static/chunks/app/oauth/consent/page-67647bfa5e651b24.js'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://oauth.dropi.co/oauth/consent'
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as r:
    js = r.read().decode('utf-8')

# Buscar donde se redirige tras aceptar el consentimiento
matches = [m.start() for m in re.finditer(r'accepted:\s*!0', js)]
for m in matches:
    print("Match accepted true at", m)
    print(js[max(0, m-200):min(len(js), m+500)])
    print("="*60)

# O buscar redirect_uri
for m in re.finditer(r'redirect_uri', js):
    print("redirect_uri at", m.start())
    print(js[max(0, m.start()-100):min(len(js), m.start()+200)])
    print("="*60)
