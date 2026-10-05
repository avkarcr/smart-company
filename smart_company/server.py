"""Loopback-only local HTTP server with same-origin write protection."""
import argparse
import json
import logging
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,quote
from .service import Research
from .data import SECTORS,validate_dossier
from .analysis import settings_checked
from .pdf_export import export_pdf
from .reports import MAX_FILE

STATIC=Path(__file__).parent/'static'

def make_handler(research):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def respond(self,payload,status=200,kind='application/json; charset=utf-8',filename=None):
            body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode() if kind.startswith('application/json') else payload
            self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(body)))
            if filename: self.send_header('Content-Disposition', "attachment; filename*=UTF-8''"+quote(filename,safe=''))
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)
        def host_ok(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        def do_GET(self):
            if not self.host_ok(): return self.respond({'error':'Invalid host'},403)
            try:
                url=urlsplit(self.path); path=url.path; q=parse_qs(url.query)
                if path=='/api/bootstrap':
                    return self.respond(dict(catalog=research.provider.catalog(),settings=research.settings(),sectors=SECTORS,csrf=token))
                report=re.fullmatch(r'/api/reports/([A-Z0-9_-]{1,24})(?:/([a-f0-9]{64}))?',path)
                if report:
                    ticker,ident=report.groups()
                    if not ident:return self.respond(research.reports.records(ticker))
                    record,raw=research.reports.download(ticker,ident)
                    return self.respond(raw,kind='application/octet-stream',filename=record['filename'])
                match=re.fullmatch(r'/api/company/([A-Z0-9_-]{1,24})(/pdf|/snapshot)?',path)
                if match:
                    ticker,action=match.groups()
                    if action:
                        snapshot=research.store.read('snapshot-'+ticker)
                        if not snapshot: return self.respond({'error':'Сначала откройте карточку'},404)
                        return self.respond(export_pdf(snapshot),kind='application/pdf') if action=='/pdf' else self.respond(snapshot)
                    return self.respond(research.company(ticker,q.get('refresh')==['1']))
                assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
                if path in assets:
                    filename,mime=assets[path]; return self.respond((STATIC/filename).read_bytes(),kind=mime)
                return self.respond({'error':'Не найдено'},404)
            except KeyError as exc: self.respond({'error':str(exc)},404)
            except ValueError as exc: self.respond({'error':str(exc)},400)
            except Exception:
                logging.exception('Request failed'); self.respond({'error':'Не удалось собрать карточку. Подробности в терминале.'},500)
        def do_POST(self):
            if not self.host_ok() or self.headers.get('X-CSRF-Token')!=token: return self.respond({'error':'Недопустимый запрос'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                url=urlsplit(self.path)
                upload=re.fullmatch(r'/api/reports/([A-Z0-9_-]{1,24})(?:/([a-f0-9]{64}))?',url.path)
                if upload and not upload[2]:
                    if not 0<length<=MAX_FILE:return self.respond({'error':'Максимальный размер файла — 20 МБ'},413)
                    if not any(c['ticker']==upload[1] for c in research.provider.catalog()['data']):return self.respond({'error':'Компания не найдена'},404)
                    filename=parse_qs(url.query).get('filename',[''])[0]
                    raw=self.rfile.read(length)
                    if len(raw)!=length:raise ValueError('Файл передан не полностью')
                    return self.respond(research.reports.upload(upload[1],filename,raw))
                if not 0<length<=500000: return self.respond({'error':'Допустимый размер: 1–500000 байт'},413)
                body=json.loads(self.rfile.read(length),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Числа должны быть конечными')))
                if upload and upload[2]:return self.respond(research.reports.correct(upload[1],upload[2],body))
                if self.path=='/api/settings': research.store.write('settings',settings_checked(body))
                elif self.path=='/api/catalog/refresh': return self.respond(research.provider.catalog(True))
                elif re.fullmatch(r'/api/dossier/[A-Z0-9_-]{1,24}',self.path): research.store.write('dossier-'+self.path.rsplit('/',1)[-1],validate_dossier(body))
                else: return self.respond({'error':'Не найдено'},404)
                return self.respond({'ok':True})
            except (ValueError,KeyError,TypeError) as exc: self.respond({'error':str(exc)},400)
            except Exception:
                logging.exception('Write failed'); self.respond({'error':'Не удалось сохранить'},500)
    return Handler

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    research=Research()
    print('Обновление справочника МОЕХ…',flush=True)
    result=research.provider.catalog(refresh=True)
    print(result.get('error') or f"Получено акций: {len(result['data'])}",flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(research))
    print(f'Smart Company: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()

if __name__=='__main__': main()
