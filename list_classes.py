import urllib.request
import re

url = 'https://plugins.svn.wordpress.org/wc-dropi-integration/trunk/clasess/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as r:
    html = r.read().decode('utf-8')

for m in re.finditer(r'href=[\'"]([^\'"]+\.php)[\'"]', html):
    print(m.group(1))
