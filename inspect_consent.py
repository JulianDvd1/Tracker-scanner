import urllib.request

url = 'https://oauth.dropi.co/_next/static/chunks/app/oauth/authorize/page-01ffa24ae7750dac.js'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://oauth.dropi.co/oauth/authorize'
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as r:
    js = r.read().decode('utf-8')

pos = js.find('/oauth/consent')
print("Consent endpoint snippet:")
print(js[pos-100:pos+300])

# Ver que hace la función que llama a consent
pos2 = js.find('m("POST","/oauth/consent"')
print("\nPOST consent snippet:")
print(js[pos2-150:pos2+350])
