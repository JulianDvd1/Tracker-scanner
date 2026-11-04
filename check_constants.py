import urllib.request

for fname in ['Constants.php', 'Helper.php', 'Woocomerce.php']:
    url = f'https://plugins.svn.wordpress.org/wc-dropi-integration/trunk/clasess/{fname}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as r:
            code = r.read().decode('utf-8', errors='ignore')
            print(f"=== {fname} ===")
            for line in code.split('\n'):
                if any(k in line.lower() for k in ['http', 'media', 'gallery', 'image', 'url']):
                    print("  ", line.strip()[:100])
    except Exception as e:
        print(f"Error {fname}:", e)
