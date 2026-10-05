import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from smart_company.server import make_handler
from smart_company.service import Research
from smart_company.data import Store

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.research=Research(Store(self.tmp.name))
        self.research.provider.catalog=lambda *a,**k:dict(data=[],fetched_at=None,error=None)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.research))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def test_assets_and_bootstrap(self):
        with urllib.request.urlopen(self.base+'/') as r:self.assertIn(b'<!doctype html>',r.read())
        with urllib.request.urlopen(self.base+'/api/bootstrap') as r:self.assertIn('csrf',json.load(r))
    def test_write_requires_csrf(self):
        req=urllib.request.Request(self.base+'/api/settings',data=b'{}',method='POST')
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
        self.assertEqual(e.exception.code,403)
    def test_save_settings(self):
        with urllib.request.urlopen(self.base+'/api/bootstrap') as r:token=json.load(r)['csrf']
        req=urllib.request.Request(self.base+'/api/settings',data=b'{"threshold":90}',headers={'X-CSRF-Token':token},method='POST')
        with urllib.request.urlopen(req) as r:self.assertEqual(r.status,200)
        self.assertEqual(self.research.settings()['threshold'],90)
    def test_host_check(self):
        req=urllib.request.Request(self.base+'/',headers={'Host':'evil.example'})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
        self.assertEqual(e.exception.code,403)
    def test_path_traversal(self):
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(self.base+'/../../LICENSE')
        self.assertEqual(e.exception.code,404)
