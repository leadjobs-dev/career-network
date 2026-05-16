#!/usr/bin/env python3
"""Connections CRM local server. Run from your project root:
    python skills/crm-connections/scripts/crm_server.py
Data files are read from data/ if that folder exists, otherwise from the
current working directory (backward-compatible with pre-data/ setups)."""
import http.server, json, os, re, threading, webbrowser

PORT        = 8765
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE   = os.path.join(_SCRIPT_DIR, '..', 'assets', 'connections_crm.html')
_CWD        = os.getcwd()
_DATA_DIR   = os.path.join(_CWD, 'data') if os.path.isdir(os.path.join(_CWD, 'data')) else _CWD
INDEX_FILE   = os.path.join(_DATA_DIR, 'connections_index.json')
PROFILES_DIR = os.path.join(_DATA_DIR, 'profiles')

RANKED_RE  = re.compile(r'^ranked[\w\-\.]+\.json$')
HANDLE_RE  = re.compile(r'^[a-zA-Z0-9\-]+$')   # safe profile handle


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._file(HTML_FILE, 'text/html')

        elif self.path == '/index':
            data = {}
            try:
                with open(INDEX_FILE, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
            self._json(data)

        elif self.path == '/manifest':
            self._json(self._scan())

        elif self.path.startswith('/profiles/'):
            handle = self.path[len('/profiles/'):]
            # Security: allow only safe handles, no path traversal
            if not HANDLE_RE.match(handle) or '..' in handle:
                self.send_response(403); self.end_headers(); return
            self._file(os.path.join(PROFILES_DIR, f'{handle}.json'), 'application/json')

        elif self.path.startswith('/data/'):
            fn = self.path[6:]
            if not RANKED_RE.match(fn) or '..' in fn:
                self.send_response(403); self.end_headers(); return
            self._file(os.path.join(_DATA_DIR, fn), 'application/json')

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == '/index':
            n    = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(n)
            try:
                data = json.loads(body)
                with open(INDEX_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._json({'ok': True})
            except Exception as e:
                self._json({'error': str(e)})
        else:
            self.send_response(404); self.end_headers()

    def _scan(self):
        roles = []
        try:
            for fn in sorted(os.listdir(_DATA_DIR), reverse=True):
                if not RANKED_RE.match(fn):
                    continue
                fp = os.path.join(_DATA_DIR, fn)
                cnt = 0
                role_name = None
                try:
                    with open(fp, encoding='utf-8') as f:
                        data = json.load(f)
                    # New format: { _meta: { roleName }, rankings: [...] }
                    if isinstance(data, dict) and '_meta' in data:
                        cnt = len(data.get('rankings', []))
                        role_name = data['_meta'].get('roleName')
                    # Legacy format: array with _role_name on each item
                    elif isinstance(data, list):
                        cnt = len(data)
                        if data and data[0].get('_role_name'):
                            role_name = data[0]['_role_name']
                except Exception:
                    pass
                date_part = re.sub(r'^ranked[\w]*_?', '', fn).replace('.json', '')
                label = role_name or ('Role · ' + date_part)
                roles.append({'filename': fn, 'label': label, 'count': cnt})
        except Exception:
            pass
        return {'roles': roles}

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
    print('Drop ranked_*.json files here — role tabs appear on refresh.')
    print('Press Ctrl+C to stop.')
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
