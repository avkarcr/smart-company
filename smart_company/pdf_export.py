"""Export the exact stored card snapshot, without silently refreshing it."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

LABEL={'buy':'ПОКУПАТЬ','sell':'ПРОДАВАТЬ','wait':'ЖДАТЬ',None:'Нет данных'}

def export_pdf(s):
    import reportlab
    candidates=[os.environ.get('SMART_COMPANY_FONT',''),'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',str(Path(reportlab.__file__).parent/'fonts/Vera.ttf')]
    font=next((p for p in candidates if p and Path(p).exists()),None)
    if not font or font.endswith('Vera.ttf'):
        raise ValueError('Для PDF с кириллицей установите fonts-dejavu-core или задайте SMART_COMPANY_FONT')
    if 'CardFont' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('CardFont',font))
    styles=getSampleStyleSheet()
    for style in styles.byName.values(): style.fontName='CardFont'
    styles['BodyText'].fontSize=9; styles['BodyText'].leading=14; styles['BodyText'].splitLongWords=True
    styles['Heading1'].fontSize=19; styles['Heading1'].leading=25
    styles['Heading2'].fontSize=12; styles['Heading2'].spaceBefore=16
    story=[]
    def p(text,style='BodyText'): return Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style])
    def text(t): story.append(p(t))
    def heading(t): story.append(p(t,'Heading2'))
    def link(label,url):
        if url: story.append(Paragraph(f'<a href="{escape(url, {chr(34): "&quot;"})}" color="#315e72">{escape(label)}</a>',styles['BodyText']))
    def table(rows,widths=None):
        t=Table([[p(x) for x in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf2f1')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#dde4e2'))]))
        story.append(t)
    c=s['company']; tech=s['technical']; f=s['fundamental']
    story.append(p(f"{c['name']} · {c['ticker']}",'Heading1'))
    text(f"{s['sector']['name']} | Снимок: {s['generated_at']}")
    heading(LABEL[s['verdict']]); text(s['explanation'])
    for w in s['warnings']: text(w)
    text(f"Цена закрытия: {tech['price']} RUB; дата: {tech['as_of']}")
    text(f"Сценарный диапазон ±2 ATR: {tech['range']}. Это диапазон волатильности, не целевая цена и не прогноз с заданной вероятностью.")
    from reportlab.graphics.shapes import Drawing, PolyLine, Line
    values=[c['close'] for c in s['candles'][-120:] if isinstance(c.get('close'),(int,float))]
    if len(values)>1:
        low,high=min(values),max(values); extent=high-low or 1
        drawing=Drawing(515,105)
        drawing.add(Line(0,10,515,10,strokeColor=colors.HexColor('#dce4de')))
        drawing.add(PolyLine([coordinate for i,v in enumerate(values) for coordinate in (i/(len(values)-1)*515,15+(v-low)/extent*80)],strokeColor=colors.HexColor('#32765c'),strokeWidth=1.5))
        story.append(drawing)
        text(f'График закрытий, последние {len(values)} сессий. Минимум {low:.2f}, максимум {high:.2f} RUB.')
    heading('Технический анализ')
    text(f"Сигнал: {LABEL[tech['signal']]}; голоса: {tech['votes']}; покрытие: {tech['coverage']}%; порог: {s['settings']['threshold']}%")
    text(f"Режим: {s['settings']['mode']}; веса групп: {s['settings']['groups']}; веса индикаторов: {s['settings']['weights']}")
    table([['Индикатор','Значение','Сигнал','Правило']]+[[r['name'],r['value'],LABEL[r['signal']],r['rule']] for r in tech['rows']],[115,65,80,255])
    heading('Фундаментальный анализ')
    for reason in f['reasons']: text(reason)
    text(str(f['metrics']))
    for r in f['reports']:
        heading(f"Отчет на {r['period_end']} · {r['standard']} · {r['months']} мес.")
        text(f"Публикация: {r['published_at']}; валюта: {r['currency']}; единицы: млн; страницы: {r['page']}; проверен: {r.get('verified',False)}")
        text('; '.join(f'{k}: {r.get(k,"—")}' for k in ('revenue','net_income','equity','debt','cash','ebitda')))
        link('Официальный отчет',r['source_url'])
    heading('Стратегия, развитие и M&A')
    for item in s['dossier'].get('plans',[]): text(item['text']+' · '+item['impact']); link('Источник',item['source_url'])
    if not s['dossier'].get('plans'): text('Нет проверенных сведений. Отсутствие записей не означает отсутствие событий.')
    heading('Совет директоров')
    for person in s['dossier'].get('board',[]):
        text(f"{person['name']} · {person.get('role','')}\n{person.get('bio','')}"); link('Биография / источник',person['source_url'])
        if person.get('linkedin'): link('LinkedIn',person['linkedin'])
    if not s['dossier'].get('board'): text('Состав совета директоров не подтвержден.')
    heading('Последние события из доступной RSS-ленты')
    for item in s['news']['data']: text(item['date']+' · '+item['title']); link(item['source'],item['url'])
    if s['news'].get('error'): text(s['news']['error'])
    heading('Документы e-disclosure')
    for r in s['disclosure']['data']: link(r['title'],r['url'])
    if s['disclosure'].get('error'): text(s['disclosure']['error'])
    heading('Отрасль: факторы для проверки'); text(s['sector']['outlook']); text('Структурные факторы, не обновляемый прогноз отрасли.')
    heading('Мультипликаторы')
    text(str(s['multiples']['values']) if s['multiples']['values'] else 'Нет достаточных данных.'); text(s['multiples']['note'])
    text(f"Капитализация, млн: {s['dossier'].get('market_cap')}; дата: {s['dossier'].get('market_cap_date')}")
    method_start=len(story)
    heading('Методика и происхождение данных')
    text('Дневные свечи без текущей незавершенной сессии. Дивиденды и сплиты автоматически не корректируются. Похожие индикаторы зависимы; доля голосов не является вероятностью. Правила не откалиброваны бэктестом. Сигналы — вспомогательные, не индивидуальная инвестиционная рекомендация.')
    text(f"Справочник получен: {s['sources']['catalog']}; свечи: {s['sources']['candles']}; новости: {s['news'].get('fetched_at')}")
    link('MOEX ISS',s['sources']['moex'])
    story[method_start:]=[KeepTogether(story[method_start:])]
    output=BytesIO()
    def footer(canvas,doc):
        canvas.setFont('CardFont',8); canvas.setFillColor(colors.HexColor('#68756f')); canvas.drawString(40,23,'Smart Company · '+c['ticker']); canvas.drawRightString(555,23,str(doc.page))
    SimpleDocTemplate(output,rightMargin=40,leftMargin=40,topMargin=38,bottomMargin=42,title=c['ticker']+' — Smart Company').build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
