import unittest
from datetime import date,timedelta
from smart_company.analysis import technical, aggregate, settings_checked, DEFAULT_SETTINGS, fundamentals, multiples
from smart_company.data import validate_dossier, Store, Provider
from tempfile import TemporaryDirectory

def bars(n=250,flat=False):
    return [dict(begin=str(date.today()-timedelta(days=n-i)),open=100 if flat else 100+i,close=100 if flat else 100+i,high=101 if flat else 101+i,low=99 if flat else 99+i,volume=1000) for i in range(n)]

def dossier():
    return dict(sector='energy',latest_confirmed=True,qualitative_reviewed=True,reports=[dict(period_end='2025-12-31',published_at='2026-03-01',months=12,standard='IFRS',currency='RUB',source_url='https://example.org/report-2025.pdf',page='12',verified=True,revenue=120,net_income=24,equity=100),dict(period_end='2024-12-31',published_at='2025-03-01',months=12,standard='IFRS',currency='RUB',source_url='https://example.org/report-2024.pdf',page='12',verified=True,revenue=100,net_income=20,equity=90)])

class AnalysisTests(unittest.TestCase):
    def test_no_candles_no_signal(self):
        r=technical([],DEFAULT_SETTINGS);self.assertEqual(r['signal'],'wait');self.assertIsNone(r['price'])
    def test_short_history_cannot_buy(self):
        r=technical(bars(5),DEFAULT_SETTINGS);self.assertEqual(r['signal'],'wait');self.assertLess(r['coverage'],80)
    def test_flat_rsi_is_neutral(self):
        r=technical(bars(flat=True),DEFAULT_SETTINGS);rsi=next(x for x in r['rows'] if x['id']=='rsi');self.assertEqual(rsi['value'],50);self.assertEqual(rsi['signal'],'wait')
    def test_wilder_monotonic_rsi(self):
        r=technical(bars(),DEFAULT_SETTINGS);rsi=next(x for x in r['rows'] if x['id']=='rsi');self.assertEqual(rsi['value'],100);self.assertEqual(len(r['rows']),21)
    def test_neutral_votes_in_denominator(self):
        rows=[dict(id=str(i),group='trend',signal='buy' if i<7 else 'wait') for i in range(10)]
        r=aggregate(rows,DEFAULT_SETTINGS);self.assertEqual(r['votes']['buy'],70);self.assertEqual(r['signal'],'wait')
    def test_group_normalization(self):
        rows=[dict(id=str(i),group='trend',signal='buy') for i in range(10)]+[dict(id='rsi',group='momentum',signal='sell')]
        self.assertEqual(aggregate(rows,DEFAULT_SETTINGS)['votes']['buy'],50)
        s={**DEFAULT_SETTINGS,'mode':'count'};self.assertEqual(aggregate(rows,s)['signal'],'buy')
    def test_disabled_all(self):
        s={**DEFAULT_SETTINGS,'groups':dict(trend=0)};r=aggregate([dict(id='a',group='trend',signal='buy')],s);self.assertEqual(r['signal'],'wait');self.assertEqual(r['coverage'],0)
    def test_invalid_settings(self):
        for values in ({'threshold':50},{'weights':{'x':float('nan')}},{'weights':{'x':-1}}):
            with self.assertRaises(ValueError): settings_checked(values)
    def test_missing_reports_block_fundamental(self):
        self.assertFalse(fundamentals({})['complete'])
    def test_comparable_reports(self):
        r=fundamentals(dossier(),date(2026,10,5));self.assertTrue(r['complete']);self.assertEqual(r['signal'],'buy');self.assertEqual(r['metrics']['revenue_growth'],20)
    def test_incomparable_periods(self):
        d=dossier();d['reports'][0]['months']=6;self.assertFalse(fundamentals(d,date(2026,10,5))['complete'])
    def test_stale_reports(self):
        self.assertFalse(fundamentals(dossier(),date(2028,1,1))['complete'])
    def test_unverified_reports(self):
        d=dossier();d['reports'][0]['verified']=False;self.assertFalse(fundamentals(d,date(2026,10,5))['complete'])
    def test_risk_overrides_buy(self):
        d=dossier();d['plans']=[{'impact':'risk'}];self.assertEqual(fundamentals(d,date(2026,10,5))['signal'],'wait')
    def test_no_quarter_annualization(self):
        d=dossier();d['reports'][0]['months']=3;d['market_cap']=1000;self.assertNotIn('P/E',multiples(d)['values'])
    def test_negative_profit_not_negative_pe(self):
        d=dossier();d['reports'][0]['net_income']=-1;d['market_cap']=1000;self.assertNotIn('P/E',multiples(d)['values'])
    def test_no_bank_ev_ebitda(self):
        d=dossier();d.update(sector='finance',market_cap=1000);d['reports'][0].update(debt=500,cash=100,ebitda=10);self.assertNotIn('EV/EBITDA',multiples(d)['values'])
    def test_url_validation(self):
        d=dossier();d['reports'][0]['source_url']='javascript:alert(1)'
        with self.assertRaises(ValueError):validate_dossier(d)
    def test_nan_validation(self):
        d=dossier();d['reports'][0]['revenue']=float('nan')
        with self.assertRaises(ValueError):validate_dossier(d)
    def test_cached_failure_retains_timestamp(self):
        with TemporaryDirectory() as tmp:
            p=Provider(Store(tmp));first=p.cached('x',lambda:[1],True)
            def fail(): raise TimeoutError()
            second=p.cached('x',fail,True)
            self.assertEqual(second['data'],[1]);self.assertEqual(first['fetched_at'],second['fetched_at']);self.assertTrue(second['error'])
    def test_candle_pagination(self):
        with TemporaryDirectory() as tmp:
            p=Provider(Store(tmp));calls=[]
            def fake(path,**params):
                calls.append(params['start']);return {'candles':{'columns':['begin','close'],'data':[['2026-01-01',100]] if params['start']==0 else []}}
            p.iss=fake;r=p.candles('TEST','TQBR');self.assertEqual(calls,[0,1]);self.assertEqual(len(r['data']),1)

if __name__=='__main__':unittest.main()
