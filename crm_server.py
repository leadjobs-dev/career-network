#!/usr/bin/env python3
"""Connections CRM local server. Run: python crm_server.py"""
import http.server, json, os, re, threading, webbrowser

PORT      = 8765
BASE      = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE, 'connections_crm.html')
ANN_FILE  = os.path.join(BASE, 'connections_annotations.json')

# Only serve JSON files matching these patterns (no path traversal)
# Match only files produced by the pipeline skills:
#   enriched_connections_YYYYMMDD.json  (get-enriched-connections output)
#   ranked_connections_YYYYMMDD.json    (rank-connections output)
ALLOWED_RE = re.compile(r'^(enriched_connections|ranked_connections)_\d{8}\.json$')


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._file(HTML_FILE, 'text/html')
        elif self.path == '/annotations':
            data = {}
            try:
                with open(ANN_FILE, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
            self._json(data)
        elif self.path == '/manifest':
            self._json(self._scan())
        elif self.path.startswith('/data/'):
            fn = self.path[6:]
            if not ALLOWED_RE.match(fn) or '..' in fn:
                self.send_response(403); self.end_headers(); return
            self._file(os.path.join(BASE, fn), 'application/json')
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == '/annotations':
            n    = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(n)
            try:
                data = json.loads(body)
                with open(ANN_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._json({'ok': True})
            except Exception as e:
                self._json({'error': str(e)})
        else:
            self.send_response(404); self.end_headers()

    def _scan(self):
        """Scan folder for enriched/ranked JSON files and return manifest."""
        network, roles = [], []
        try:
            for fn in sorted(os.listdir(BASE), reverse=True):
                if not ALLOWED_RE.match(fn):
                    continue
                fp  = os.path.join(BASE, fn)
                cnt = 0
                role_name = None
                try:
                    with open(fp, encoding='utf-8') as f:
                        data = json.load(f)
                    cnt = len(data) if isinstance(data, list) else 0
                    if isinstance(data, list) and data and data[0].get('_role_name'):
                        role_name = data[0]['_role_name']
                except Exception:
                    pass
                if fn.startswith('enriched'):
                    date_part = re.sub(r'^enriched[_\-](?:profiles|connections)?[_\-]?', '', fn).replace('.json', '')
                    network.append({'filename': fn, 'label': 'Network · ' + date_part, 'count': cnt})
                elif fn.startswith('ranked'):
                    date_part = re.sub(r'^ranked[_\-]connections[_\-]?', '', fn).replace('.json', '')
                    label = role_name or ('Role · ' + date_part)
                    roles.append({'filename': fn, 'label': label, 'count': cnt})
        except Exception:
            pass
        return {'network': network, 'roles': roles}

    def _file(self, path, ctype):
        try:
            with open(path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', ctype + '; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404); self.end_headers()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    srv = http.server.HTTPServer(('localhost', PORT), Handler)
    url = f'http://localhost:{PORT}'
    print(f'Connections CRM running at {url}')
    print('Drop enriched_*.json or ranked_*.json files here — tabs appear on refresh.')
    print('Press Ctrl+C to stop.')
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
