import json
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys

with open('oauth_state.json', 'r') as f:
    state = json.load(f)

client_id = state['client_id']
verifier = state['verifier']

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if 'code' in params:
            code = params['code'][0]
            print(f"CODE_RECEIVED: {code}", flush=True)
            
            # Canjear por token
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
            try:
                with urllib.request.urlopen(req) as resp:
                    tokens = json.loads(resp.read().decode('utf-8'))
                    with open('dropi_tokens.json', 'w', encoding='utf-8') as tf:
                        json.dump(tokens, tf, indent=2)
                    print("SUCCESS_TOKENS_SAVED", flush=True)
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(b'<h1>Conexion exitosa con Dropi!</h1><p>Ya puedes volver a Antigravity.</p>')
            except Exception as e:
                print(f"ERROR_TOKEN_EXCHANGE: {e}", flush=True)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'<h1>Error al canjear el token</h1>')
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'<h1>No se recibio codigo de autorizacion</h1>')

print("Starting listener on localhost:8080...", flush=True)
server = HTTPServer(('localhost', 8080), CallbackHandler)
server.handle_request()
print("Listener finished.", flush=True)
