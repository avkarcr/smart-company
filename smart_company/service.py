from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime
from zoneinfo import ZoneInfo
from .analysis import DEFAULT_SETTINGS, settings_checked, technical, fundamentals, multiples
from .reports import Reports
from .data import Provider, Store, SECTORS, default_dossier, now

class Research:
    def __init__(self,store=None):
        self.store=store or Store(); self.provider=Provider(self.store); self.reports=Reports(self.store)
    def settings(self):
        saved=self.store.read('settings')
        if saved is not None and 'enabled' not in saved:
            # Preserve the prior user's explicit weights and do not activate new combinations silently.
            saved={**saved,'combinations_enabled':False}
        return settings_checked(saved if saved is not None else DEFAULT_SETTINGS)
    def company(self,ticker,refresh=False):
        catalog=self.provider.catalog()
        company=next((c for c in catalog['data'] if c['ticker']==ticker),None)
        if not company: raise KeyError('Акция не найдена в справочнике МОЕХ')
        dossier=self.store.read('dossier-'+ticker,default_dossier(ticker))
        with ThreadPoolExecutor(max_workers=3) as pool:
            a=pool.submit(self.provider.candles,ticker,company['board'],refresh)
            b=pool.submit(self.provider.news,company,dossier,refresh)
            c=pool.submit(self.provider.disclosure,ticker,dossier,refresh)
            candles,news,disclosure=a.result(),b.result(),c.result()
        settings=self.settings(); tech=technical(candles['data'],settings); fund=fundamentals(dossier)
        warnings=[]
        if catalog.get('error'): warnings.append(catalog['error'])
        if candles.get('error'): warnings.append(candles['error'])
        if not tech['as_of'] or (datetime.now(ZoneInfo('Europe/Moscow')).date()-date.fromisoformat(tech['as_of'])).days>5: warnings.append('Котировки старше 5 календарных дней или отсутствуют.')
        if tech.get('coverage',0)<settings['min_coverage']: warnings.append('Недостаточное покрытие включенных индикаторов.')
        verdict='wait'
        if not warnings and fund['complete'] and tech['signal']==fund['signal']:
            verdict=tech['signal']
        explanation='Технический и фундаментальный сигналы согласованы.' if verdict!='wait' else 'Ждем: сигналы расходятся, нейтральны или недостаточно проверенных данных.'
        snapshot=dict(uploaded_reports=self.reports.records(ticker),company=company,dossier=dossier,sector=SECTORS[dossier.get('sector','other')],technical=tech,fundamental=fund,multiples=multiples(dossier),news=news,disclosure=disclosure,candles=candles['data'],sources={'catalog':catalog.get('fetched_at'),'candles':candles.get('fetched_at'),'moex':'https://iss.moex.com/iss/reference/'},settings=settings,generated_at=now(),verdict=verdict,explanation=explanation,warnings=warnings)
        self.store.write('snapshot-'+ticker,snapshot)
        return snapshot
