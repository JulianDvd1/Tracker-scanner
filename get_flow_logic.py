with open('find_consent_flow.py', 'r') as f:
    pass

import urllib.request

url = 'https://oauth.dropi.co/_next/static/chunks/app/oauth/authorize/page-01ffa24ae7750dac.js'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://oauth.dropi.co/oauth/authorize'
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as r:
    js = r.read().decode('utf-8')

pos = 15700
print(js[pos:pos+1500])
