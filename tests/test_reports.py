import io
import json
import threading
import unittest
import urllib.request
import urllib.error
import zipfile
from datetime import date,timedelta
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
from smart_company.reports import Reports,metadata,detect_text,freshness,MAX_FILE
from smart_company.data import Store
from smart_company.service import Research
from smart_company.server import make_handler

class DetectionTests(unittest.TestCase):
    def test_annual_russian(self):
        r=metadata('Годовой отчет за 2025 год. Сравнение с 2024 годом.'.encode(),'report.txt',date(2026,10,5))
        self.assertEqual(r['period_end'],'2025-12-31');self.assertEqual(r['type'],'annual');self.assertEqual(r['status'],'detected')
    def test_quarter_roman(self):
        r=detect_text('Отчет за III квартал 2025 года');self.assertEqual(r['period_end'],'2025-09-30');self.assertEqual(r['quarter'],3)
    def test_half_year(self):
        r=detect_text('Финансовая отчетность за 6 месяцев 2026 года');self.assertEqual(r['period_end'],'2026-06-30');self.assertEqual(r['months'],6)
    def test_months_ended(self):
        r=detect_text('За девять месяцев, закончившихся 30 сентября 2025 года');self.assertEqual(r['period_end'],'2025-09-30')
    def test_second_quarter_ended(self):
        r=detect_text('For three months ended 30 June 2026');self.assertEqual(r['period_end'],'2026-06-30');self.assertEqual(r['quarter'],2)
    def test_english_annual(self):
        self.assertEqual(detect_text('Financial statements for the year ended 31 December 2025')['period_end'],'2025-12-31')
    def test_filename_requires_confirmation(self):
        r=metadata(b'No readable reporting period','Q3_2025.txt',date(2026,10,5));self.assertEqual(r['status'],'needs_review');self.assertEqual(r['year'],2025)
    def test_conflict(self):
        r=metadata('Годовой отчет 2025'.encode(),'annual_report_2024.txt',date(2026,10,5));self.assertEqual(r['year'],2025);self.assertEqual(r['status'],'needs_review')
    def test_arbitrary_date_not_period(self):
        r=metadata('Дата подписания: 30 июня 2026.'.encode(),'report.txt');self.assertIsNone(r['period_end'])
    def test_future_period_requires_review(self):
        r=metadata(b'Annual report 2029','report.txt',date(2026,10,5));self.assertEqual(r['status'],'needs_review')
    def test_broken_pdf_saved_metadata_unknown(self):
        r=metadata(b'%PDF-corrupted','report.pdf');self.assertEqual(r['status'],'needs_review')
    def test_pdf_text(self):
        from reportlab.pdfgen.canvas import Canvas
        stream=io.BytesIO();c=Canvas(stream);c.drawString(30,700,'Annual report 2025');c.save()
        r=metadata(stream.getvalue(),'report.pdf',date(2026,10,5));self.assertEqual(r['year'],2025);self.assertEqual(r['source'],'content')
    def test_docx_text(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="urn:test"><w:p><w:t>Отчет за 1 квартал 2026 года</w:t></w:p></w:document>')
        self.assertEqual(metadata(out.getvalue(),'report.docx',date(2026,10,5))['period_end'],'2026-03-31')
    def test_freshness_uses_period_not_upload_date(self):
        record=dict(type='annual',period_end='2023-12-31',status='detected',uploaded_at='2026-10-05')
        self.assertTrue(freshness(record,date(2026,10,5))['stale'])
    def test_fresh_and_unknown(self):
        self.assertFalse(freshness(dict(type='quarterly',period_end='2026-06-30',status='detected'),date(2026,10,5))['stale'])
        self.assertEqual(freshness(dict(status='needs_review'))['freshness'],'unknown')

class PersistenceTests(unittest.TestCase):
    def test_isolation_restart_duplicate_and_download(self):
        with TemporaryDirectory() as path:
            r=Reports(Store(path));raw=b'Annual report 2024'
            result=r.upload('SBER','../../report.txt',raw);ident=result['items'][0]['id']
            self.assertEqual(result['items'][0]['filename'],'report.txt')
            self.assertEqual(r.records('LKOH')['items'],[])
            r=Reports(Store(path));self.assertEqual(len(r.records('SBER')['items']),1)
            self.assertTrue(r.upload('SBER','renamed.txt',raw)['duplicate'])
            self.assertEqual(r.download('SBER',ident)[1],raw)
            with self.assertRaises(KeyError):r.download('LKOH',ident)
    def test_correction_persisted(self):
        with TemporaryDirectory() as path:
            r=Reports(Store(path));item=r.upload('SBER','scan.txt',b'unknown')['items'][0]
            r.correct('SBER',item['id'],dict(type='quarterly',year=2025,months=3,quarter=4))
            saved=Reports(Store(path)).records('SBER')['items'][0]
            self.assertEqual(saved['period_end'],'2025-12-31');self.assertEqual(saved['status'],'confirmed')
    def test_multiple_different_files_retained(self):
        with TemporaryDirectory() as path:
            r=Reports(Store(path));r.upload('SBER','a.txt',b'Annual report 2023');r.upload('SBER','b.txt',b'Annual report 2024')
            self.assertEqual(len(r.records('SBER')['items']),2)
    def test_reject_unsupported_and_invalid_ticker(self):
        with TemporaryDirectory() as path:
            r=Reports(Store(path))
            with self.assertRaises(ValueError):r.upload('SBER','file.exe',b'hello')
            with self.assertRaises(ValueError):r.upload('../SBER','a.txt',b'hello')
    def test_pdf_snapshot_receives_uploads(self):
        with TemporaryDirectory() as path:
            store=Store(path);store.write('snapshot-SBER',{'company':{'ticker':'SBER'}})
            Reports(store).upload('SBER','a.txt',b'Annual report 2024')
            self.assertEqual(len(store.read('snapshot-SBER')['uploaded_reports']['items']),1)

class UploadHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.research=Research(Store(self.tmp.name))
        self.research.provider.catalog=lambda *a,**kw:{'data':[{'ticker':'SBER'}]}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.research))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        with urllib.request.urlopen(self.url+'/api/bootstrap') as r:self.token=json.load(r)['csrf']
    def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def test_upload_list_download(self):
        req=urllib.request.Request(self.url+'/api/reports/SBER?filename=report.txt',data=b'Annual report 2024',headers={'X-CSRF-Token':self.token})
        with urllib.request.urlopen(req) as response:ident=json.load(response)['items'][0]['id']
        with urllib.request.urlopen(self.url+'/api/reports/SBER') as response:self.assertEqual(len(json.load(response)['items']),1)
        with urllib.request.urlopen(self.url+'/api/reports/SBER/'+ident) as response:
            self.assertIn('attachment',response.headers['Content-Disposition']);self.assertEqual(response.read(),b'Annual report 2024')
    def test_upload_csrf(self):
        req=urllib.request.Request(self.url+'/api/reports/SBER?filename=r.txt',data=b'x')
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code,403)
