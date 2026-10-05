"""Deterministic, inspectable rules; scores are NOT probabilities."""
import math
from copy import deepcopy
from .indicators import RECOMMENDED, FAMILIES, COMBINATIONS, INDICATORS
from datetime import date
import numpy as np
import pandas as pd

GROUPS = {"trend": "Тренд", "momentum": "Импульс", "volume": "Объем", "volatility": "Волатильность"}
DEFAULT_SETTINGS = deepcopy(RECOMMENDED)

def settings_checked(data):
    if not isinstance(data,dict): raise ValueError('Настройки должны быть объектом')
    result = {**deepcopy(DEFAULT_SETTINGS), **data}
    for key in ('enabled','combination_rules'):
        if not isinstance(result[key],dict) or any(type(v) is not bool for v in result[key].values()):
            raise ValueError('Переключатели должны быть true/false')
        result[key]={**DEFAULT_SETTINGS[key],**result[key]}
    if type(result['combinations_enabled']) is not bool: raise ValueError('Неверный переключатель сочетаний')
    for key in ("threshold", "min_coverage"):
        v = float(result[key])
        if not math.isfinite(v) or not 51 <= v <= 100:
            raise ValueError(f"{key}: допустимо 51–100")
        result[key] = v
    if result["mode"] not in ("weighted", "count"):
        raise ValueError("Неизвестный режим голосования")
    for key in ("weights", "groups"):
        if not isinstance(result[key], dict):
            raise ValueError("Веса должны быть объектом")
        result[key] = {k: float(v) for k, v in result[key].items()}
        if any(not math.isfinite(v) or not 0 <= v <= 10 for v in result[key].values()):
            raise ValueError("Вес должен быть от 0 до 10")
    return result

def wilder(s, n=14):
    s = s.astype(float)
    out = pd.Series(np.nan, index=s.index)
    valid = s.dropna()
    if len(valid) < n:
        return out
    start = s.index.get_loc(valid.index[n-1])
    out.iloc[start] = valid.iloc[:n].mean()
    for i in range(start+1, len(s)):
        out.iloc[i] = (out.iloc[i-1]*(n-1)+s.iloc[i])/n
    return out

def aggregate(rows, settings):
    def active(r):
        return settings.get('enabled',{}).get(r['id'],True) and settings['weights'].get(r['id'],1)>0 and settings['groups'].get(r['group'],1)>0
    configured=[r for r in rows if active(r)]
    valid=[r for r in configured if r['signal'] is not None]
    coverage=100*len(valid)/len(configured) if configured else 0
    effective={}
    for group in GROUPS:
        members=[r for r in valid if r['group']==group]
        if settings['mode']=='count':
            effective.update({r['id']:1. for r in members});continue
        families={}
        for r in members: families.setdefault(FAMILIES.get(r['id'],r['id']),[]).append(r)
        budgets={k:max(settings['weights'].get(r['id'],1) for r in rs) for k,rs in families.items()}
        budget=sum(budgets.values())
        for family,rs in families.items():
            weight_sum=sum(settings['weights'].get(r['id'],1) for r in rs)
            for r in rs:
                effective[r['id']]=settings['groups'].get(group,1)*budgets[family]/budget*settings['weights'].get(r['id'],1)/weight_sum
    total=sum(effective.values())
    effective={k:v/total for k,v in effective.items()} if total else {}
    base={side:sum(effective[r['id']] for r in valid if r['signal']==side)*100 for side in ('buy','sell','wait')}
    lookup={r['id']:r for r in rows}; combinations=[]
    for rule in COMBINATIONS:
        status='disabled'; side='wait'
        selected=[lookup.get(i) for i in rule['members']]
        if settings.get('combinations_enabled',False) and settings['mode']=='weighted' and settings.get('combination_rules',{}).get(rule['id'],True):
            if any(r is None or not active(r) for r in selected): status='disabled'
            elif any(r['signal'] is None for r in selected):status='missing'
            elif len({r['signal'] for r in selected})==1 and selected[0]['signal'] in ('buy','sell'):
                status='confirmed';side=selected[0]['signal']
            else:status='unconfirmed'
        combinations.append({**rule,'status':status,'signal':side,'contribution':0})
    eligible=[c for c in combinations if c['status']!='disabled']
    pool=10 if eligible and total else 0
    votes={side:value*(1-pool/100) for side,value in base.items()}
    for c in eligible:
        c['contribution']=pool/len(eligible)
        votes[c['signal']]+=c['contribution']
    signal='wait'
    if coverage>=settings['min_coverage']:
        for side in ('buy','sell'):
            if votes[side]>=settings['threshold']:signal=side
    for r in rows:
        r['enabled']=active(r)
        r['effective_weight']=round(effective.get(r['id'],0)*(100-pool),2)
    return dict(signal=signal,votes={k:round(v,2) for k,v in votes.items()},base_votes={k:round(v,2) for k,v in base.items()},coverage=round(coverage,1),available=len(valid),configured=len(configured),threshold=settings['threshold'],combinations=combinations,combination_pool=pool)

def technical(candles, settings):
    df = pd.DataFrame(candles)
    if df.empty:
        return {"rows": [], **aggregate([],settings), "price": None, "range": None, "as_of": None}
    df = df.sort_values('begin').drop_duplicates('begin').reset_index(drop=True)
    for col in ('open','high','low','close','volume'):
        df[col] = pd.to_numeric(df[col],errors='coerce')
    df = df[(df.close>0)&(df.high>=df.low)&(df.volume>0)].reset_index(drop=True)
    if df.empty:
        return technical([],settings)
    c,h,l,v = (df[x] for x in ('close','high','low','volume'))
    rows = []
    def add(key, name, group, series, rule, explanation, minimum=1):
        val = float(series.iloc[-1]) if len(series) and pd.notna(series.iloc[-1]) else None
        if val is not None and not math.isfinite(val): val = None
        if len(df) < minimum: val = None
        rows.append(dict(id=key,name=name,group=group,value=round(val,4) if val is not None else None,signal=rule(val) if val is not None else None,rule=explanation))
    def sign(x, band=0): return 'buy' if x>band else 'sell' if x < -band else 'wait'
    def oscillator(x, low, high): return 'buy' if x<low else 'sell' if x>high else 'wait'
    for n in (20,50,100,200):
        add(f'sma{n}', f'SMA {n}', 'trend', (c/c.rolling(n).mean()-1)*100, lambda x:sign(x,.5), 'Цена выше/ниже SMA на 0,5%; иначе ждать.', n)
    for n in (12,26,50,200):
        add(f'ema{n}', f'EMA {n}', 'trend', (c/c.ewm(span=n,adjust=False,min_periods=n).mean()-1)*100, lambda x:sign(x,.5), 'Цена выше/ниже EMA на 0,5%; иначе ждать.', n)
    macd = c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean()
    add('macd','MACD 12/26/9','trend', macd-macd.ewm(span=9,adjust=False).mean(),sign,'MACD выше/ниже сигнальной линии.', 35)
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2
    kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    add('ichimoku','Ichimoku: Tenkan / Kijun','trend',tenkan-kijun,sign,'Пересечение линий; это не полный анализ облака.',26)
    delta=c.diff(); gain=wilder(delta.clip(lower=0)); loss=wilder(-delta.clip(upper=0))
    rsi=100-100/(1+gain/loss.replace(0,np.nan)); rsi=rsi.mask((loss==0)&(gain>0),100).mask((gain==0)&(loss>0),0).mask((gain==0)&(loss==0),50)
    add('rsi','RSI 14','momentum',rsi,lambda x:oscillator(x,30,70),'Ниже 30: buy; выше 70: sell; иначе ждать.',15)
    span=(h.rolling(14).max()-l.rolling(14).min()).replace(0,np.nan)
    stoch=100*(c-l.rolling(14).min())/span
    add('stoch','Stochastic %K 14','momentum',stoch,lambda x:oscillator(x,20,80),'Ниже 20 / выше 80.',14)
    add('williams','Williams %R 14','momentum',stoch-100,lambda x:oscillator(x,-80,-20),'Ниже −80 / выше −20.',14)
    tp=(h+l+c)/3; mean=tp.rolling(20).mean(); mad=tp.rolling(20).apply(lambda x:np.abs(x-x.mean()).mean(),raw=True)
    add('cci','CCI 20','momentum',(tp-mean)/(.015*mad.replace(0,np.nan)),lambda x:oscillator(x,-100,100),'Ниже −100 / выше 100.',20)
    add('roc','ROC 12, %','momentum',c.pct_change(12)*100,lambda x:sign(x,1),'Рост/падение за 12 сессий больше 1%.',13)
    add('momentum','Momentum 10','momentum',c-c.shift(10),sign,'Разница цен за 10 сессий.',11)
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=wilder(tr)
    mid=c.rolling(20).mean(); sd=c.rolling(20).std(ddof=0)
    add('bollinger','Bollinger z-score 20','volatility',(c-mid)/sd.replace(0,np.nan),lambda x:oscillator(x,-2,2),'Возврат к среднему: ниже −2 / выше +2.',20)
    add('keltner','Keltner 20 / ATR 14','volatility',(c-c.ewm(span=20,adjust=False).mean())/atr.replace(0,np.nan),lambda x:sign(x,2),'Пробой канала: выше +2 ATR / ниже −2 ATR.',20)
    obv=(np.sign(c.diff()).fillna(0)*v).cumsum()
    add('obv','OBV / SMA 20','volume',obv-obv.rolling(20).mean(),sign,'OBV выше/ниже своей средней.',20)
    mf=((2*c-h-l)/(h-l).replace(0,np.nan)*v).fillna(0)
    add('cmf','Chaikin Money Flow 20','volume',mf.rolling(20).sum()/v.rolling(20).sum(),lambda x:sign(x,.05),'Выше 0,05 / ниже −0,05.',20)
    flow=tp*v; pos=flow.where(tp.diff()>0,0).rolling(14).sum(); neg=flow.where(tp.diff()<0,0).rolling(14).sum()
    mfi=(100-100/(1+pos/neg.replace(0,np.nan))).mask((neg==0)&(pos>0),100).mask((neg==0)&(pos==0),50)
    add('mfi','Money Flow Index 14','volume',mfi,lambda x:oscillator(x,20,80),'Ниже 20 / выше 80.',15)
    price=float(c.iloc[-1]); a=atr.iloc[-1]
    price_range=[round(max(0,price-2*float(a)),2),round(price+2*float(a),2)] if pd.notna(a) else None
    return {"rows":rows, **aggregate(rows,settings), "price":price,"range":price_range,"as_of":str(df.iloc[-1]['begin'])[:10],"bars":len(df),"change":round((price/float(c.iloc[-2])-1)*100,2) if len(c)>1 else None}

def fundamentals(dossier, today=None):
    today=today or date.today()
    reports=sorted(dossier.get('reports',[]),key=lambda r:r['period_end'],reverse=True)[:2]
    reasons=[]; metrics={}; signal='wait'; complete=False
    if len(reports)<2:
        reasons.append('Нужны два последних официальных отчета с проверенными показателями и ссылками на страницы.')
    else:
        latest,prev=reports
        if not dossier.get('latest_confirmed'): reasons.append('Не подтверждено, что выбраны два последних доступных отчета.')
        if not all(r.get('verified') for r in reports): reasons.append('Показатели отчетов еще не проверены.')
        if latest['standard']!=prev['standard'] or latest['months']!=prev['months'] or latest['currency']!=prev['currency']:
            reasons.append('Периоды, валюты или стандарты несопоставимы; автоматическое сравнение отключено.')
        if (today-date.fromisoformat(latest['period_end'])).days>400: reasons.append('Последний отчет старше 400 дней.')
        required=('revenue','net_income','equity')
        if not all(isinstance(r.get(k),(int,float)) for r in reports for k in required): reasons.append('Не хватает выручки, чистой прибыли или капитала.')
        if not reasons:
            complete=True
            for key in ('revenue','net_income'):
                if prev[key]>0:
                    metrics[key+'_growth']=round((latest[key]/prev[key]-1)*100,2)
            if latest['equity']>0: metrics['roe_period']=round(latest['net_income']/((latest['equity']+prev['equity'])/2)*100,2) if (latest['equity']+prev['equity'])>0 else None
            rev=metrics.get('revenue_growth'); profit=metrics.get('net_income_growth')
            if latest['net_income']<0 or latest['equity']<=0 or (profit is not None and profit < -20):
                signal='sell'
            elif rev is not None and profit is not None and rev>5 and profit>5 and latest['net_income']>0:
                signal='buy'
            reasons.append('Правило: рост выручки и прибыли >5% при положительном капитале — buy; падение прибыли >20% или убыток/отрицательный капитал — sell; иначе ждать.')
            reasons.append('Сравнение двух одинаковых по длительности периодов; рост не обязательно год к году. ROE за период, не годовой.')
    plans=dossier.get('plans',[])
    if any(p.get('impact')=='risk' for p in plans):
        signal='wait'; reasons.append('Есть отмеченные риски стратегии/M&A: итог требует ручной оценки.')
    if not dossier.get('qualitative_reviewed'):
        signal='wait'; reasons.append('Планы развития, M&A и существенные риски еще не проверены.')
    return dict(reports=reports,metrics=metrics,signal=signal,complete=complete and bool(dossier.get('qualitative_reviewed')),reasons=reasons)

def multiples(dossier):
    reports=sorted(dossier.get('reports',[]),key=lambda r:r['period_end'],reverse=True)
    if not reports or not reports[0].get('verified'): return {'values':{},'note':'Для расчета нужен проверенный отчет и общая капитализация всех классов акций.'}
    r=reports[0]; cap=dossier.get('market_cap'); values={}
    def ratio(name,a,b):
        if isinstance(a,(int,float)) and isinstance(b,(int,float)) and a>=0 and b>0: values[name]=round(a/b,2)
    ratio('P/B',cap,r.get('equity'))
    if r['months']==12:
        ratio('P/E',cap,r.get('net_income')); ratio('P/S',cap,r.get('revenue'))
        if dossier.get('sector')!='finance':
            debt=r.get('debt'); cash=r.get('cash'); eb=r.get('ebitda')
            if all(isinstance(x,(int,float)) for x in (cap,debt,cash)):
                ratio('EV/EBITDA',cap+debt-cash,eb)
            if all(isinstance(x,(int,float)) for x in (debt,cash,eb)) and eb>0: values['Net debt/EBITDA']=round((debt-cash)/eb,2)
    return {'values':values,'note':'P/E, P/S и EV/EBITDA только по 12-месячному отчету; кварталы не умножаются на 4. Для банков EV/EBITDA не применяется. Дешевизна без сравнения с отраслью не доказана. Капитализация введена пользователем; проверьте ее дату и валюту.'}
