import unittest
from copy import deepcopy
from tempfile import TemporaryDirectory
from smart_company.analysis import aggregate, settings_checked, DEFAULT_SETTINGS
from smart_company.indicators import INDICATORS
from smart_company.data import Store
from smart_company.service import Research

def row(i,g,s='buy'):return dict(id=i,group=g,signal=s)

class IndicatorTests(unittest.TestCase):
    def test_registry_complete(self):
        self.assertEqual(len(INDICATORS),21)
        self.assertEqual(set(DEFAULT_SETTINGS['weights']),{r['id'] for r in INDICATORS})
    def test_global_switch_retains_weight(self):
        s=deepcopy(DEFAULT_SETTINGS);s['enabled']['rsi']=False
        r=aggregate([row('rsi','momentum')],s)
        self.assertEqual(r['configured'],0);self.assertEqual(r['signal'],'wait');self.assertEqual(s['weights']['rsi'],3)
    def test_duplicate_family_does_not_add_budget(self):
        s=deepcopy(DEFAULT_SETTINGS);s['combinations_enabled']=False
        a=aggregate([row('stoch','momentum'),row('cci','momentum','sell')],s)
        b=aggregate([row('stoch','momentum'),row('williams','momentum'),row('cci','momentum','sell')],s)
        self.assertEqual(a['votes'],b['votes'])
    def test_confirmed_combination_and_budget(self):
        rows=[row('ema50','trend'),row('macd','trend'),row('cmf','volume')]
        result=aggregate(rows,DEFAULT_SETTINGS)
        self.assertEqual(result['combinations'][0]['status'],'confirmed')
        self.assertEqual(result['combination_pool'],10)
        self.assertAlmostEqual(sum(result['votes'].values()),100,places=1)
        self.assertAlmostEqual(sum(r['effective_weight'] for r in rows),90,places=1)
    def test_conflict_votes_wait(self):
        r=aggregate([row('ema50','trend'),row('macd','trend'),row('cmf','volume','sell')],DEFAULT_SETTINGS)
        self.assertEqual(r['combinations'][0]['status'],'unconfirmed');self.assertEqual(r['votes']['wait'],10)
    def test_disabled_participant_disables_combination(self):
        s=deepcopy(DEFAULT_SETTINGS);s['enabled']['cmf']=False
        r=aggregate([row('ema50','trend'),row('macd','trend'),row('cmf','volume')],s)
        self.assertEqual(r['combination_pool'],0);self.assertEqual(r['combinations'][0]['status'],'disabled')
    def test_missing_participant_no_confirmation(self):
        r=aggregate([row('ema50','trend'),row('macd','trend'),row('cmf','volume',None)],DEFAULT_SETTINGS)
        self.assertEqual(r['combinations'][0]['status'],'missing');self.assertEqual(r['signal'],'wait')
    def test_count_ignores_weights_and_combinations(self):
        s=deepcopy(DEFAULT_SETTINGS);s['mode']='count'
        r=aggregate([row('ema50','trend'),row('macd','trend'),row('cmf','volume','sell')],s)
        self.assertEqual(r['votes']['buy'],66.67);self.assertEqual(r['combination_pool'],0)
    def test_switch_validation(self):
        with self.assertRaises(ValueError):settings_checked({'enabled':{'rsi':'false'}})
        with self.assertRaises(ValueError):settings_checked({'combinations_enabled':1})
    def test_persistent_global_and_legacy_migration(self):
        with TemporaryDirectory() as path:
            store=Store(path);store.write('settings',dict(threshold=85,min_coverage=80,mode='weighted',weights={'rsi':2},groups={'trend':1}))
            old=Research(store).settings();self.assertFalse(old['combinations_enabled']);self.assertEqual(old['weights']['rsi'],2)
            old['enabled']['rsi']=False;store.write('settings',old)
            self.assertFalse(Research(Store(path)).settings()['enabled']['rsi'])
