import os
import sys
import json
import base64
import hashlib
import secrets
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser

def generate_code_verifier():
    token = secrets.token_urlsafe(64)
    return token[:128]

def generate_code_challenge(verifier):
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).decode('utf-8').replace('=', '')

def register_client():
    url = 'https://integrations.dropi.co/oauth/register'
    payload = {
        'client_name': 'Antigravity Dropi Auth',
        'redirect_uris': ['http://localhost:8080/callback'],
        'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'],
        'token_endpoint_auth_method': 'none'
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        return data['client_id']

def exchange_code_for_token(client_id, code, verifier):
    url = 'https://integrations.dropi.co/oauth/token'
    payload = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'code': code,
        'redirect_uri': 'http://localhost:8080/callback',
        'code_verifier': verifier
    }
    encoded = urllib.parse.urlencode(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

auth_code = None

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<h1>Autenticacion con Dropi exitosa!</h1><p>Ya puedes cerrar esta ventana y regresar a Antigravity.</p>')
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'<h1>Error en la autorizacion</h1>')

    def log_message(self, format, *args):
        return

def main():
    print("Registrando cliente OAuth en Dropi...")
    client_id = register_client()
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier)

    auth_params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': 'http://localhost:8080/callback',
        'scope': 'mcp',
        'code_challenge': challenge,
        'code_challenge_method': 'S256'
    }
    auth_url = 'https://oauth.dropi.co/oauth/authorize?' + urllib.parse.urlencode(auth_params)

    print("\n" + "="*70)
    print("ENLACE DE AUTORIZACION OFICIAL DE DROPI:")
    print(auth_url)
    print("="*70 + "\n")

    server = HTTPServer(('localhost', 8080), CallbackHandler)
    server.timeout = 180  # 3 minutos de espera

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("Esperando confirmacion de login en el navegador...")
    while not auth_code:
        server.handle_request()

    print("Codigo recibido! Canjeando por Token...")
    tokens = exchange_code_for_token(client_id, auth_code, verifier)
    
    # Guardar en .env y en config
    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')

    # Guardar en dropi_tokens.json
    with open('dropi_tokens.json', 'w', encoding='utf-8') as f:
        json.dump(tokens, f, indent=2)

    print("\nAUTENTICACION COMPLETADA CON EXITO!")
    print(f"Token obtenido: {access_token[:20]}...")

if __name__ == '__main__':
    main()
