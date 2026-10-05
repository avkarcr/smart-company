"""Browser acceptance tests on synthetic data; no third-party network required."""
import json
import math
import threading
from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
from smart_company.server import make_handler
from smart_company.service import Research
from smart_company.data import Store
from playwright.sync_api import sync_playwright, expect

with TemporaryDirectory() as tmp:
    research=Research(Store(tmp))
    catalog=[dict(ticker='SBER',name='Сбербанк',full_name='Тестовый эмитент — синтетические данные',isin='TEST',board='TQBR',sector='finance')]
    catalog.append(dict(ticker='LKOH',name='ЛУКОЙЛ',full_name='Тестовый эмитент',isin='TEST2',board='TQBR',sector='energy'))
    candles=[dict(begin=str(date.today()-timedelta(days=260-i)),open=100+i/5,close=100+i/5+math.sin(i/8),high=102+i/5,low=98+i/5,volume=1000+i) for i in range(260)]
    def bundle(data):return dict(data=data,error=None,cached=False,fetched_at='2026-10-05T12:00:00+03:00')
    research.provider.catalog=lambda *a,**kw:bundle(catalog)
    research.provider.candles=lambda *a,**kw:bundle(candles)
    research.provider.news=lambda *a,**kw:bundle([])
    research.provider.disclosure=lambda *a,**kw:bundle([])
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(research));threading.Thread(target=server.serve_forever,daemon=True).start()
    out=Path('test-results');out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':1050})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{server.server_port}')
        page.get_by_role('button',name='Сбербанк SBER',exact=True).wait_for()
        page.screenshot(path=str(out/'home.png'),full_page=True)
        page.locator('#search').fill('sber');page.locator('#search').press('Enter')
        page.locator('#refresh-card').wait_for()
        assert page.locator('.verdict h3').inner_text()=='Ждать'
        page.screenshot(path=str(out/'card.png'),full_page=True)
        page.get_by_role('button',name='Настройки анализа').click()
        page.locator('[name="threshold"]').fill('85')
        page.get_by_role('button',name='Сохранить и пересчитать').click()
        page.locator('#refresh-card').wait_for()
        assert research.settings()['threshold']==85
        page.get_by_role('button',name='Досье и отчеты',exact=True).click()
        page.get_by_role('button',name='Добавить отчет').click()
        assert page.locator('.report-editor').count()==1
        page.locator('.remove-report').click()
        page.get_by_role('button',name='Сохранить и обновить карточку').click()
        page.locator('#refresh-card').wait_for()
        page.locator('#report-files').set_input_files([
            {'name':'annual.txt','mimeType':'text/plain','buffer':'Годовой отчет за 2023 год'.encode()},
            {'name':'quarter.txt','mimeType':'text/plain','buffer':'Отчет за 1 квартал 2025 года'.encode()}])
        expect(page.locator('#upload-status')).to_contain_text('Обработано: 2.')
        expect(page.locator('.report-list article')).to_have_count(2)
        expect(page.locator('.report-list')).to_contain_text('Годовой')
        expect(page.locator('.report-list')).to_contain_text('Данные устарели')
        page.locator('#search').fill('LKOH');page.locator('#search').press('Enter')
        expect(page.locator('.card-head h2')).to_have_text('ЛУКОЙЛ')
        expect(page.locator('.report-list article')).to_have_count(0)
        page.locator('#search').fill('SBER');page.locator('#search').press('Enter')
        expect(page.locator('.card-head h2')).to_have_text('Сбербанк')
        expect(page.locator('.report-list article')).to_have_count(2)
        page.reload();page.locator('#refresh-card').wait_for()
        expect(page.locator('.report-list article')).to_have_count(2)
        page.locator('#report-files').set_input_files([{'name':'again.txt','mimeType':'text/plain','buffer':'Годовой отчет за 2023 год'.encode()}])
        expect(page.locator('#upload-status')).to_contain_text('Уже были загружены: 1.')
        expect(page.locator('.report-list article')).to_have_count(2)
        page.screenshot(path=str(out/'uploads-desktop.png'),full_page=True)
        response=page.request.get(f'http://127.0.0.1:{server.server_port}/api/company/SBER/pdf')
        assert response.status==200 and response.body().startswith(b'%PDF')
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(out/'mobile.png'),full_page=True)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.locator('#search').fill('ZZZZZZ')
        assert 'Ничего не найдено' in page.locator('#results').inner_text()
        assert not errors,errors
        browser.close()
    server.shutdown()
    print('Browser acceptance passed: search, company, settings, dossier, PDF, mobile, empty search, no JS errors, multi-file upload, company isolation, reload persistence, stale warning, deduplication')
