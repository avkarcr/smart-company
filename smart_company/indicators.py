"""Versioned starting weights, not empirically calibrated trading accuracy."""
SPECS = [
 ('sma20','SMA 20','trend',1,'Средняя за месяц; чувствительна к краткосрочному шуму.'),
 ('sma50','SMA 50','trend',2,'Среднесрочный тренд; частично дублирует EMA 50.'),
 ('sma100','SMA 100','trend',1,'Промежуточный горизонт, пересекается с SMA 50/200.'),
 ('sma200','SMA 200','trend',3,'Долгосрочный фон; медленно реагирует на разворот.'),
 ('ema12','EMA 12','trend',.5,'Быстрая средняя; уже участвует в MACD.'),
 ('ema26','EMA 26','trend',.5,'Участвует в MACD, отдельный голос ограничен.'),
 ('ema50','EMA 50','trend',3,'Основной ориентир среднесрочного направления.'),
 ('ema200','EMA 200','trend',1,'Дополняет долгосрочный фон, дублирует SMA 200.'),
 ('macd','MACD 12/26/9','trend',3,'Изменение трендового импульса; запаздывает, зависит от средних.'),
 ('ichimoku','Tenkan / Kijun','trend',2,'Дополнительная структура тренда; это не полный анализ облака.'),
 ('rsi','RSI 14','momentum',3,'Основной осциллятор; крайние значения не гарантируют разворот.'),
 ('stoch','Stochastic %K 14','momentum',1,'Положение закрытия в диапазоне; шумит в сильном тренде.'),
 ('williams','Williams %R 14','momentum',.5,'При этих настройках эквивалентен Stochastic со сдвигом шкалы.'),
 ('cci','CCI 20','momentum',1,'Отклонение типичной цены от среднего.'),
 ('roc','ROC 12','momentum',2,'Скорость изменения цены; дополняет поиск экстремумов.'),
 ('momentum','Momentum 10','momentum',.5,'Близок к ROC, низкий вес уменьшает повторный учет.'),
 ('obv','OBV / SMA 20','volume',2,'Накопленное направление объема; чувствителен к выбросам.'),
 ('cmf','Chaikin Money Flow 20','volume',3,'Основное подтверждение ценового движения объемом.'),
 ('mfi','Money Flow Index 14','volume',2,'Осциллятор цены и объема; полезен вместе с RSI.'),
 ('bollinger','Bollinger z-score 20','volatility',2,'Экстремальное отклонение; применяется как возврат к среднему.'),
 ('keltner','Keltner 20 / ATR 14','volatility',2,'Пробой диапазона; требует подтверждения трендом и объемом.'),
]
INDICATORS=[dict(id=i,name=n,group=g,recommended_weight=w,reason=r) for i,n,g,w,r in SPECS]
COMBINATIONS=[
 dict(id='trend_volume',name='Тренд + импульс + объем',members=['ema50','macd','cmf'],reason='Совпадение направления EMA 50, MACD и CMF. Средние и MACD зависимы; CMF добавляет объем.'),
 dict(id='reversal',name='Экстремум цены и денежного потока',members=['rsi','bollinger','mfi'],reason='Согласие RSI, Bollinger и MFI — кандидат на возврат к среднему, не доказанный разворот.'),
 dict(id='breakout',name='Пробой с подтверждением',members=['keltner','ema50','cmf'],reason='Пробой Keltner совпадает с направлением EMA 50 и CMF. Требует контроля ложных пробоев.'),
]
FAMILIES={**{i:'averages' for i,_,g,_,_ in SPECS if i.startswith(('sma','ema'))},'stoch':'range_position','williams':'range_position','roc':'price_change','momentum':'price_change'}
RECOMMENDED = dict(threshold=80,min_coverage=80,mode='weighted',weights={i:w for i,_,_,w,_ in SPECS},groups=dict(trend=3.5,momentum=2.5,volume=2.5,volatility=1.5),enabled={i:True for i,_,_,_,_ in SPECS},combinations_enabled=True,combination_rules={c['id']:True for c in COMBINATIONS})
