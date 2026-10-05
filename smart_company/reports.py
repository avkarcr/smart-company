"""Persistent per-company originals and conservative reporting-period detection."""
import calendar
import hashlib
import io
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .data import now

MAX_FILE = 20 * 1024 * 1024
EXTENSIONS = {'.pdf', '.docx', '.txt'}
YEAR = r'(20\d{2})'
MONTHS = {'марта':3,'июня':6,'сентября':9,'декабря':12,'march':3,'june':6,'september':9,'december':12}

def period(year, months, kind=None, quarter=None):
    year, months = int(year), int(months)
    if not 2000 <= year <= 2100 or months not in (3,6,9,12):
        raise ValueError('Неверный отчетный период')
    kind = kind or ('annual' if months==12 else 'quarterly')
    if kind not in ('annual','quarterly'): raise ValueError('Выберите тип отчета')
    if kind=='annual': months=12; quarter=None
    elif quarter is not None:
        quarter=int(quarter)
        if quarter not in (1,2,3,4): raise ValueError('Квартал: 1–4')
        months=quarter*3
    end=date(year,months,calendar.monthrange(year,months)[1])
    label=f'{year} год' if kind=='annual' else f'{quarter} квартал {year}' if quarter else f'{months} месяцев {year}'
    return dict(type=kind,year=year,months=12 if kind=='annual' else (3 if quarter else months),quarter=quarter,period_end=end.isoformat(),period_label=label)

def detect_text(text):
    t=re.sub(r'\s+',' ',text.lower().replace('ё','е').replace('_',' '))[:16000]
    candidates=[]
    def add(pattern, fn):
        for m in re.finditer(pattern,t):
            result=fn(m)
            if result:candidates.append((m.start(),result,m.group(0)))
    add(r'(?:годов\w*\s+(?:отчет\w*|отчетност\w*)|annual\s+report)[^\d]{0,70}'+YEAR, lambda m:period(m[1],12))
    add(r'(?:за\s+|for\s+)(?:год\w*\s*[,，]?\s*(?:закончивш\w*|завершивш\w*)[^\d]{0,8}(?:31[ .]+(?:декабря|december|12)[ .]+)?|the year ended\s+(?:31 december\s+)?)'+YEAR,lambda m:period(m[1],12))
    add(r'(?:отчет\w*|отчетност\w*)\s*(?:за\s+)?'+YEAR+r'\s*(?:год|г\.)',lambda m:period(m[1],12))
    add(r'\b([1-4])\s*(?:квартал\w*|кв\.?|quarter)\s*(?:за\s*)?'+YEAR,lambda m:period(m[2],int(m[1])*3,'quarterly',m[1]))
    add(r'\b(i{1,3}|iv)\s*квартал\w*\s*'+YEAR,lambda m:period(m[2],{'i':3,'ii':6,'iii':9,'iv':12}[m[1]],'quarterly',{'i':1,'ii':2,'iii':3,'iv':4}[m[1]]))
    add(r'\bq([1-4])[ .-]*'+YEAR,lambda m:period(m[2],int(m[1])*3,'quarterly',m[1]))
    add(r'\b'+YEAR+r'[ .-]*q([1-4])',lambda m:period(m[1],int(m[2])*3,'quarterly',m[2]))
    add(r'\b(3|6|9|12)\s*(?:месяц\w*|months?)\s*(?:за\s*)?'+YEAR,lambda m:period(m[2],m[1]))
    add(r'(?:перв\w*\s+)?полугод\w*\s*'+YEAR,lambda m:period(m[1],6))
    add(r'\bh1[ .-]*'+YEAR,lambda m:period(m[1],6))
    # Full reporting-end phrases, not arbitrary comparative dates from a balance sheet.
    duration=r'(три|трех|шесть|шести|девять|девяти|двенадцать|двенадцати|3|6|9|12|three|six|nine|twelve)'
    count={'три':3,'трех':3,'шесть':6,'шести':6,'девять':9,'девяти':9,'двенадцать':12,'двенадцати':12,'three':3,'six':6,'nine':9,'twelve':12}
    def dated(m):
        duration=count.get(m[1],int(m[1]) if m[1].isdigit() else 0)
        end_month=MONTHS[m[3]]
        if duration==3:return period(m[4],end_month,'quarterly',end_month//3)
        return period(m[4],duration) if duration==end_month else None
    add(duration+r'\s*(?:месяц\w*|months?)[^\d]{0,65}(\d{1,2})[ .]+('+ '|'.join(MONTHS)+r')[ .]+'+YEAR,dated)
    add(r'(?:year|год)[^\d]{0,35}31[ .]+(?:december|декабря|12)[ .]+'+YEAR,lambda m:period(m[1],12))
    add(r'(?:промежуточн\w*|interim)[^\d]{0,100}(?:на|as at|ended)?\s*(?:30|31)[ .]+('+ '|'.join(MONTHS)+r')[ .]+'+YEAR,lambda m:period(m[2],MONTHS[m[1]]))
    if not candidates:return None
    candidates.sort(key=lambda c:c[0])
    _, found, evidence=candidates[0]
    return {**found,'evidence':evidence[:200]}

def extract_text(raw,extension):
    if extension=='.txt':
        try:return raw.decode('utf-8-sig')[:150000]
        except UnicodeDecodeError:return raw.decode('cp1251')[:150000]
    if extension=='.pdf':
        if not raw.startswith(b'%PDF-'):raise ValueError('Файл не является PDF')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(''):raise ValueError('PDF защищен паролем')
        chunks=[]
        for page in reader.pages[:8]:
            content=page.get_contents()
            if content and len(content.get_data())>10*1024*1024:raise ValueError('Слишком сложная страница PDF')
            chunks.append((page.extract_text() or '')[:20000])
        return '\n'.join(chunks)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info=archive.getinfo('word/document.xml')
        if info.file_size>10*1024*1024:raise ValueError('Документ слишком большой для распознавания')
        tree=ET.fromstring(archive.read(info))
        return ' '.join(e.text or '' for e in tree.iter() if e.tag.endswith('}t'))[:150000]

def metadata(raw,filename,today=None):
    today=today or datetime.now(ZoneInfo('Europe/Moscow')).date()
    warning=None
    try:
        content=extract_text(raw,Path(filename).suffix.lower())
    except Exception:
        content='';warning='Текст не извлечен: проверьте формат, защиту паролем или наличие текстового слоя.'
    found=detect_text(content)
    source='content'
    hint=detect_text(Path(filename).stem)
    if not found:
        found=hint;source='filename'
    if not found:
        return dict(type=None,period_end=None,period_label='Период не определен',status='needs_review',source=None,evidence='',warning=warning or 'Не удалось определить период и тип. Уточните вручную; для скана без текста нужен OCR.')
    conflict=hint and source=='content' and (hint['period_end']!=found['period_end'] or hint['type']!=found['type'])
    future=date.fromisoformat(found['period_end'])>today
    if conflict:warning='Период в имени файла отличается от содержания. Проверьте и уточните вручную.'
    elif future:warning='Определен будущий период. Проверьте распознавание.'
    elif source=='filename':warning=warning or 'Период определен только по имени файла; подтвердите его вручную.'
    return {**found,'status':'needs_review' if conflict or future or source=='filename' else 'detected','source':source,'warning':warning}

def freshness(record,today=None):
    today=today or datetime.now(ZoneInfo('Europe/Moscow')).date()
    if record.get('status')=='needs_review' or not record.get('period_end'):
        return dict(stale=False,freshness='unknown',freshness_message='Свежесть нельзя оценить до уточнения периода.')
    age=(today-date.fromisoformat(record['period_end'])).days
    limit=450 if record['type']=='annual' else 210
    stale=age>limit
    return dict(stale=stale,freshness='stale' if stale else 'within_window',freshness_message=f'Данные устарели: с конца периода прошло {age} дней.' if stale else 'В пределах срока актуальности; наличие более новых отчетов не проверено.')

class Reports:
    def __init__(self,store):self.store=store
    def records(self,ticker):
        self._ticker(ticker)
        rows=self.store.read('uploads-'+ticker,[])
        rows=sorted(rows,key=lambda r:(r.get('period_end') or '',r['uploaded_at']),reverse=True)
        items=[{**r,**freshness(r)} for r in rows]
        known=[r for r in items if r.get('period_end') and r.get('status')!='needs_review']
        latest=next(iter(known),None)
        warning='Последний распознанный отчет устарел. Загрузите более свежий отчет.' if latest and latest['stale'] else None
        if rows and not known:warning='Периоды загруженных отчетов требуют уточнения; актуальность данных неизвестна.'
        return dict(items=items,warning=warning)
    @staticmethod
    def _ticker(ticker):
        if not re.fullmatch(r'[A-Z0-9_-]{1,24}',ticker):raise ValueError('Неверный тикер')
    def upload(self,ticker,filename,raw):
        self._ticker(ticker)
        filename=filename.replace('\\','/').rsplit('/',1)[-1]
        filename=''.join(c for c in filename if ord(c)>=32)[:180]
        if Path(filename).suffix.lower() not in EXTENSIONS:raise ValueError('Поддерживаются PDF, DOCX и TXT')
        if not 0<len(raw)<=MAX_FILE:raise ValueError('Размер файла: от 1 байта до 20 МБ')
        ident=hashlib.sha256(raw).hexdigest()
        with self.store.lock:
            rows=self.store.read('uploads-'+ticker,[])
            if any(r['id']==ident for r in rows):return dict(duplicate=True,**self.records(ticker))
        record=dict(id=ident,filename=filename,size=len(raw),uploaded_at=now(),**metadata(raw,filename))
        folder=self.store.root/'reports'/ticker;folder.mkdir(parents=True,exist_ok=True)
        with self.store.lock:
            rows=self.store.read('uploads-'+ticker,[])
            if any(r['id']==ident for r in rows):return dict(duplicate=True,**self.records(ticker))
            fd,path=tempfile.mkstemp(dir=folder)
            try:
                with os.fdopen(fd,'wb') as f:f.write(raw)
                os.replace(path,folder/ident)
                self.store.write('uploads-'+ticker,rows+[record])
            finally:
                if os.path.exists(path):os.unlink(path)
        self.sync_snapshot(ticker)
        return dict(duplicate=False,**self.records(ticker))
    def sync_snapshot(self,ticker):
        snapshot=self.store.read('snapshot-'+ticker)
        if snapshot:
            snapshot['uploaded_reports']=self.records(ticker)
            self.store.write('snapshot-'+ticker,snapshot)
    def download(self,ticker,ident):
        record=next((r for r in self.records(ticker)['items'] if r['id']==ident),None)
        if not record:raise KeyError('Файл не найден у этой компании')
        return record,(self.store.root/'reports'/ticker/ident).read_bytes()
    def correct(self,ticker,ident,data):
        found=period(data['year'],data.get('months',12),data['type'],data.get('quarter'))
        if date.fromisoformat(found['period_end'])>datetime.now(ZoneInfo('Europe/Moscow')).date():raise ValueError('Период не может быть в будущем')
        with self.store.lock:
            rows=self.store.read('uploads-'+ticker,[])
            record=next((r for r in rows if r['id']==ident),None)
            if not record:raise KeyError('Файл не найден')
            record.update(found,status='confirmed',source='manual',warning=None,corrected_at=now())
            self.store.write('uploads-'+ticker,rows)
        self.sync_snapshot(ticker)
        return self.records(ticker)
