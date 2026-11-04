import urllib.request
import re

url = 'https://oauth.dropi.co/_next/static/chunks/app/oauth/authorize/page-01ffa24ae7750dac.js'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://oauth.dropi.co/oauth/authorize'
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as r:
    js = r.read().decode('utf-8')

# Buscar donde se llama a g( o consent
matches = [m.start() for m in re.finditer(r'POST.*consent', js)]
for m in matches:
    print("Match at", m)
    print(js[max(0, m-200):min(len(js), m+500)])
    print("="*60)

# Buscar donde se redirige window.location o router.push
for m in re.finditer(r'window\.location', js):
    print("Window location at", m.start())
    print(js[max(0, m.start()-100):min(len(js), m.start()+200)])
    print("="*60)
