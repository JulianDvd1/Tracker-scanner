import json
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys

class SimpleLoggerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print("\n" + "="*50, flush=True)
        print("PETICION RECIBIDA EN LOCALHOST:8080!", flush=True)
        print("PATH:", self.path, flush=True)
        print("HEADERS:", dict(self.headers), flush=True)
        print("="*50 + "\n", flush=True)
        
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        with open('received_callback.json', 'w', encoding='utf-8') as f:
            json.dump({'path': self.path, 'params': params}, f, indent=2)
            
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'<h1>Recibido en Antigravity! Puedes volver a la consola.</h1>')

print("Starting SimpleLoggerHandler on 0.0.0.0:8080...", flush=True)
server = HTTPServer(('0.0.0.0', 8080), SimpleLoggerHandler)
server.handle_request()
print("Handled request!", flush=True)
