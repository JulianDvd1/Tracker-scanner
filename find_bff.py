with open('inspect_js.py', 'r') as f:
    pass

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

# Buscar 'bff' o llamadas fetch
pos = 0
while True:
    pos = js.find('bff', pos)
    if pos == -1:
        break
    print("--- ENCONTRADO 'bff' ---")
    print(js[max(0, pos-200):min(len(js), pos+200)])
    pos += 3
