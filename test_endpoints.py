import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv('c:/Users/Julian/Downloads/Dropi/.env')
token = os.getenv('DROPI_TOKEN')

endpoints = [
    'https://api.dropi.co/integrations/products/index',
    'https://api.dropi.co/api/products/index',
    'https://api.dropi.co/api/products/search',
    'https://api.dropi.co/integrations/products/search',
    'https://api.dropi.co/api/v1/products',
    'https://api.dropi.co/api/v2/products'
]

payload = json.dumps({'pageSize': 5, 'page': 1}).encode('utf-8')
headers = {
    'Content-Type': 'application/json',
    'dropi-integration-key': token,
    'Authorization': f'Bearer {token}',
    'User-Agent': 'Mozilla/5.0'
}

for ep in endpoints:
    req = urllib.request.Request(ep, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"{ep} -> SUCCESS {resp.status}!")
            break
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')[:80]
        print(f"{ep} -> {e.code}: {body}")
    except Exception as ex:
        print(f"{ep} -> Error: {ex}")
