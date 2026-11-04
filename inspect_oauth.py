import urllib.request
import re

url = 'https://oauth.dropi.co/oauth/authorize?response_type=code&client_id=dropi-client-24ffc689&redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback&scope=mcp&code_challenge=test&code_challenge_method=plain'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
with urllib.request.urlopen(req) as r:
    html = r.read().decode('utf-8', errors='ignore')

print("Longitud HTML:", len(html))
matches = re.findall(r'<script[^>]*src=[\'"]([^\'"]+)[\'"]', html)
for m in matches:
    print("Script:", m)

# Buscar texto o json embebido
print("\nFragmentos de texto:")
for line in html.split('\n')[:30]:
    if line.strip():
        print(line[:120])
