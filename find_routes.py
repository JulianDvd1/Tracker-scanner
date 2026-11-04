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

# Ver qué rutas llama a través del bff
pos = 0
while True:
    pos = js.find('m(', pos)
    if pos == -1:
        break
    snippet = js[pos:pos+150]
    if '"' in snippet or "'" in snippet:
        print("Llamada m():", snippet[:100])
    pos += 2
