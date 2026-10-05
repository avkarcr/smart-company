"""Fixed-origin public providers and atomic local JSON storage."""
import json
import os
import re
import tempfile
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date
from pathlib import Path
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

MOEX='https://iss.moex.com/iss'
SECTORS={
 'finance': {'name':'Финансы','color':'#6958bb','outlook':'Драйверы: кредитование, комиссии, стоимость риска. Проверять процентную маржу, достаточность капитала и просрочку.'},
 'energy': {'name':'Нефть и газ','color':'#b4772d','outlook':'Драйверы: цены сырья, курс рубля, экспортные объемы. Риски: налоги, ограничения экспорта, капитальные затраты.'},
 'metals': {'name':'Металлы и добыча','color':'#557ca3','outlook':'Драйверы: мировой промышленный спрос, цены металлов и курс рубля. Риски: цикличность и стоимость логистики.'},
 'tech': {'name':'Технологии','color':'#ba5591','outlook':'Драйверы: рост выручки, удержание клиентов и импортозамещение. Риски: оценка бизнеса, конкуренция, расходы на разработку.'},
 'consumer': {'name':'Потребительский сектор','color':'#38988a','outlook':'Драйверы: реальные доходы, сопоставимые продажи и маржинальность. Риски: инфляция затрат, аренда, конкуренция.'},
 'utilities': {'name':'Электроэнергетика','color':'#738a35','outlook':'Драйверы: тарифы, потребление и ввод мощностей. Риски: регулирование, долговая нагрузка и инвестиционные программы.'},
 'telecom': {'name':'Телеком','color':'#547cc4','outlook':'Драйверы: ARPU, абонентская база и цифровые услуги. Риски: долг, ставки и капитальные затраты.'},
 'transport': {'name':'Транспорт','color':'#a16851','outlook':'Драйверы: пассажиро- и грузопоток. Риски: топливо, лизинг, логистика и ограничения маршрутов.'},
 'realestate': {'name':'Недвижимость','color':'#857252','outlook':'Драйверы: продажи, ипотека и ввод объектов. Риски: ставки, проектное финансирование и запасы.'},
 'other': {'name':'Не классифицировано','color':'#777e8b','outlook':'Отрасль пока не определена. Укажите ее в досье компании.'}
}
# Editable starting classification, not an official MOEX taxonomy.
SECTOR_CODES={
 'finance':'SBER SBERP VTBR T BSPB BSPBP MOEX SVCB RENI',
 'energy':'GAZP LKOH ROSN NVTK TATN TATNP SNGS SNGSP BANE BANEP TRNFP GAZS GAZT',
 'metals':'GMKN CHMF NLMK MAGN RUAL PLZL POLY ALRS RASP SELG MTLR MTLRP',
 'tech':'YDEX ASTR VKCO POSI DIAS SOFL HHRU',
 'consumer':'MGNT LENT X5 FIXP BELU ABRD MVID OZON',
 'utilities':'IRAO HYDR FEES UPRO MSNG OGKB TGKA TGKB',
 'telecom':'MTSS RTKM RTKMP', 'transport':'AFLT FLOT NMTP FESH', 'realestate':'PIKK LSRG SMLT ETLN'
}
KNOWN={
 'SBER': {'disclosure_id':3043,'aliases':['Сбербанк','Сбер'], 'issuer_site':'https://www.sberbank.com'},
 'SBERP': {'disclosure_id':3043,'aliases':['Сбербанк','Сбер'], 'issuer_site':'https://www.sberbank.com'},
 'LKOH': {'disclosure_id':17,'aliases':['ЛУКОЙЛ'], 'issuer_site':'https://lukoil.ru'}
}

def now(): return datetime.now(ZoneInfo('Europe/Moscow')).isoformat(timespec='seconds')

def sector_for(ticker):
    return next((k for k,v in SECTOR_CODES.items() if ticker in v.split()),'other')

def default_dossier(ticker):
    return dict(sector=sector_for(ticker), reports=[], board=[], plans=[], latest_confirmed=False, qualitative_reviewed=False, market_cap=None,market_cap_date=None, **KNOWN.get(ticker,{}))

class Store:
    def __init__(self, root=None):
        self.root=Path(root or os.environ.get('SMART_COMPANY_DATA',Path.home()/'.local/share/smart-company'))
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
    def read(self,key,default=None):
        with self.lock:
            try: return json.loads((self.root/(key+'.json')).read_text())
            except (FileNotFoundError,json.JSONDecodeError): return default
    def write(self,key,value):
        with self.lock:
            fd,path=tempfile.mkstemp(dir=self.root)
            try:
                with os.fdopen(fd,'w') as f: json.dump(value,f,ensure_ascii=False,allow_nan=False)
                os.replace(path,self.root/(key+'.json'))
            finally:
                if os.path.exists(path): os.unlink(path)

class Provider:
    def __init__(self,store): self.store=store
    def get(self,url):
        request=urllib.request.Request(url,headers={'User-Agent':'SmartCompany/0.1 (local research)','Accept':'application/json, application/xml, text/html'})
        with urllib.request.urlopen(request,timeout=12) as response:
            raw=response.read(8_000_001)
            if len(raw)>8_000_000: raise ValueError('Ответ источника слишком большой')
            return raw
    def iss(self,path,**params):
        return json.loads(self.get(MOEX+path+'.json?'+urllib.parse.urlencode({'iss.meta':'off',**params})))
    @staticmethod
    def rows(data,key):
        block=data[key]; return [dict(zip(block['columns'],row)) for row in block['data']]
    def cached(self,key,fn,refresh=False,ttl=900):
        old=self.store.read('cache-'+key)
        if old and not refresh and (datetime.now().timestamp()-old['timestamp'])<ttl:
            return {**old,'cached':True,'error':None}
        try:
            result=dict(data=fn(),fetched_at=now(),timestamp=datetime.now().timestamp())
            self.store.write('cache-'+key,result)
            return {**result,'cached':False,'error':None}
        except Exception as exc:
            return {**(old or {'data':[],'fetched_at':None}), 'cached':bool(old),'error':f'{type(exc).__name__}: источник недоступен; '+('показан сохраненный снимок' if old else 'нет сохраненных данных')}
    def catalog(self,refresh=False):
        def fetch():
            rows=[]; start=0
            while True:
                page=self.rows(self.iss('/securities',engine='stock',market='shares',is_trading=1,start=start),'securities')
                if not page: break
                rows.extend(page); start+=len(page)
                if start>20000: raise ValueError('Слишком много страниц ISS')
            result=[]
            for r in rows:
                if r.get('type') not in ('common_share','preferred_share'): continue
                result.append(dict(ticker=r['secid'],name=r['shortname'] or r['name'],full_name=r['name'],isin=r.get('isin'),board=r.get('primary_boardid') or 'TQBR',sector=sector_for(r['secid'])))
            if not result: raise ValueError('Пустой справочник акций')
            return sorted(result,key=lambda x:x['ticker'])
        return self.cached('catalog',fetch,refresh,86400)
    def candles(self,ticker,board,refresh=False):
        def fetch():
            rows=[]; start=0
            today=datetime.now(ZoneInfo('Europe/Moscow')).date()
            while True:
                page=self.rows(self.iss(f'/engines/stock/markets/shares/boards/{board}/securities/{ticker}/candles',interval=24,**{'from':(today-timedelta(days=800)).isoformat(),'till':(today-timedelta(days=1)).isoformat(),'start':start}),'candles')
                if not page: break
                rows.extend(page); start+=len(page)
                if start>3000: raise ValueError('Превышен лимит свечей')
            if not rows: raise ValueError('Нет завершенных дневных свечей')
            return rows
        return self.cached('candles-'+ticker,fetch,refresh)
    def news(self,company,dossier,refresh=False):
        def fetch():
            raw=self.get('https://www.interfax.ru/rss.asp')
            root=ET.fromstring(raw)
            aliases=dossier.get('aliases') or [company['name'],company['ticker']]
            items=[]
            for item in root.findall('.//item'):
                title=item.findtext('title',''); description=item.findtext('description','')
                if not any(re.search(r'(?<!\w)'+re.escape(a)+r'(?!\w)',title+' '+description,re.I) for a in aliases if len(a)>2): continue
                tags=[name for stem,name in [('дивиденд','Дивиденды'),('прибыл','Результаты'),('отчет','Отчетность'),('поглощ','M&A'),('слияни','M&A'),('санкц','Риски'),('совет директор','Управление'),('инвестиц','Развитие')] if stem in (title+' '+description).lower()]
                link=safe_url(item.findtext('link',''))
                if link: items.append(dict(title=title,url=link,date=item.findtext('pubDate',''),tags=tags or ['Компания'],source='Интерфакс'))
            return items[:20]
        return self.cached('news-'+company['ticker'],fetch,refresh,1800)
    def disclosure(self,ticker,dossier,refresh=False):
        ident=dossier.get('disclosure_id')
        if not ident: return {'data':[],'error':'Не указан ID эмитента e-disclosure. Добавьте его в досье.','fetched_at':None}
        def fetch():
            url=f'https://www.e-disclosure.ru/portal/files.aspx?id={int(ident)}&type=4'
            parser=Links(); parser.feed(self.get(url).decode('utf-8',errors='replace'))
            result=[]
            for href,title in parser.links:
                if 'download' in href.lower() or re.search(r'\.pdf(?:\?|$)',href,re.I):
                    result.append(dict(title=title.strip() or 'Документ МСФО: проверьте период в первоисточнике',url=safe_url(urllib.parse.urljoin(url,href))))
            if not result: raise ValueError('Документы не распознаны: возможна защита сайта или отсутствие отчетов')
            return result[:20]
        return self.cached('disclosure-'+ticker,fetch,refresh,3600)

class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self.href=None; self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a': self.href=dict(attrs).get('href'); self.text=[]
    def handle_data(self,data):
        if self.href: self.text.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.href:
            self.links.append((self.href,''.join(self.text))); self.href=None

def safe_url(value):
    if not isinstance(value,str): return ''
    p=urllib.parse.urlsplit(value)
    return value if p.scheme in ('https','http') and p.hostname and not p.username else ''

def validate_dossier(d):
    if not isinstance(d,dict): raise ValueError('Досье должно быть JSON-объектом')
    if d.get('sector','other') not in SECTORS: raise ValueError('Неизвестная отрасль')
    if d.get('disclosure_id') is not None and (type(d['disclosure_id']) is not int or not 0<d['disclosure_id']<10000000): raise ValueError('Некорректный ID e-disclosure')
    for flag in ('latest_confirmed','qualitative_reviewed'):
        if flag in d and type(d[flag]) is not bool: raise ValueError('Подтверждение должно быть true/false')
    if not isinstance(d.get('aliases',[]),list) or any(not isinstance(a,str) or len(a)>100 for a in d.get('aliases',[])): raise ValueError('aliases: список коротких названий')
    for field in ('reports','board','plans'):
        if not isinstance(d.get(field,[]),list) or len(d.get(field,[]))>100: raise ValueError('Слишком много записей')
        for item in d.get(field,[]):
            if not isinstance(item,dict): raise ValueError('Записи должны быть объектами')
            for key in ('url','source_url','linkedin'):
                if item.get(key) and not safe_url(item[key]): raise ValueError('Ссылка должна начинаться с https:// или http://')
            for key in ('name','role','bio','title','text','page','source_url','url','linkedin','period_end','published_at','standard','currency'):
                if key in item and (not isinstance(item[key],str) or len(item[key])>20000): raise ValueError(f'Некорректное поле {key}')
    seen=set()
    for r in d.get('reports',[]):
        for key in ('period_end','published_at'):
            if date.fromisoformat(r[key])>date.today(): raise ValueError('Дата отчета не может быть в будущем')
        if date.fromisoformat(r['published_at'])<date.fromisoformat(r['period_end']): raise ValueError('Публикация раньше конца периода')
        if r['period_end'] in seen: raise ValueError('Нужны разные отчетные периоды')
        seen.add(r['period_end'])
        if r.get('months') not in (3,6,9,12) or r.get('standard') not in ('IFRS','RAS') or not r.get('currency'): raise ValueError('Укажите months 3/6/9/12, standard IFRS/RAS и currency')
        if not safe_url(r.get('source_url')) or not r.get('page'): raise ValueError('Для отчета обязательны source_url и page')
        if type(r.get('verified',False)) is not bool: raise ValueError('verified: true или false')
        for key in ('revenue','net_income','equity','debt','cash','ebitda'):
            val=r.get(key)
            if val is not None and (type(val) not in (int,float) or not __import__('math').isfinite(val)): raise ValueError('Показатели должны быть конечными числами в миллионах единиц валюты отчета')
    for person in d.get('board',[]):
        if not person.get('name') or not safe_url(person.get('source_url')): raise ValueError('Для директора нужны имя и источник')
    for plan in d.get('plans',[]):
        if not plan.get('text') or not safe_url(plan.get('source_url')) or plan.get('impact') not in ('positive','neutral','risk'): raise ValueError('Для плана нужны текст, источник и impact: positive/neutral/risk')
    cap=d.get('market_cap')
    if cap is not None:
        if type(cap) not in (int,float) or not __import__('math').isfinite(cap) or cap<=0: raise ValueError('Капитализация должна быть положительным числом')
        if not d.get('market_cap_date') or date.fromisoformat(d['market_cap_date'])>date.today(): raise ValueError('Укажите дату капитализации')
    return d
