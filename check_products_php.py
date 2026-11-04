import urllib.request

url = 'https://plugins.svn.wordpress.org/wc-dropi-integration/trunk/clasess/Products.php'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as r:
    code = r.read().decode('utf-8', errors='ignore')

for line in code.split('\n'):
    if any(k in line.lower() for k in ['image', 'gallery', 'foto', 'media', 'http', 's3', 'cloudfront']):
        print(line.strip())
