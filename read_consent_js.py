import urllib.request

url = 'https://oauth.dropi.co/_next/static/chunks/app/oauth/consent/page-67647bfa5e651b24.js'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://oauth.dropi.co/oauth/consent'
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as r:
    js = r.read().decode('utf-8')

pos = js.find('accepted')
print(js[pos-200:pos+800])
