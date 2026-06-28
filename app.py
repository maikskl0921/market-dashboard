# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime
import calendar
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from collections import Counter
import io
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import urllib.request

# Page configuration
st.set_page_config(page_title="US Market Trends", layout="wide", initial_sidebar_state="collapsed")

KOR_WEEKDAY = ['월', '화', '수', '목', '금', '토', '일']

def fmt_date_kor(dt):
    if isinstance(dt, str):
        try:
            dt = pd.to_datetime(dt)
        except:
            return dt
    wd = KOR_WEEKDAY[dt.weekday()]
    return dt.strftime(f'%Y-%m-%d({wd})')

# CSS Overrides
st.markdown("""
<style>
    .block-container { padding-top: 0.6rem !important; padding-bottom: 0 !important; }
    div[data-testid="stVerticalBlock"] > div:has(> .element-container) { padding-top: 0; padding-bottom: 0; }
    .main-header { font-size: 1.35rem; font-weight: 700; background: -webkit-linear-gradient(45deg, #f3ec78, #af4261); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; line-height: 1.3; }
    h3 { font-size: 0.95rem !important; margin: 0.2rem 0 !important; }
    h4 { font-size: 0.85rem !important; margin: 0.15rem 0 !important; }
    .stTabs [data-baseweb="tab-list"] button p { font-size: 0.82rem; }
    .stButton > button { margin-top: 0 !important; margin-bottom: 0.2rem !important; }
</style>
""", unsafe_allow_html=True)

# ── 헤더와 데이터 새로고침 버튼 배치 (가려짐 방지를 위해 마진용 빈 div 배치) ──
col_hdr, col_btn = st.columns([6, 1])
with col_hdr:
    st.markdown('<p class="main-header">US Market Indicators Dashboard</p>', unsafe_allow_html=True)
with col_btn:
    st.markdown("<div style='height: 1.6rem;'></div>", unsafe_allow_html=True)
    if st.button("🔄 데이터 새로고침", key="header_data_refresh"):
        st.cache_data.clear()
        st.rerun()

# ── 2. 미국 주식 시장 하락에 매우 중요한 역사적/실시간 주요 시장 사건 데이터 ──
static_historical_events = [
    {'title': 'COVID-19 팬데믹 및 연준 무제한 양적완화 시작 (지수 폭락 후 급반등)', 'period': '2020.02 ~ 2020.03'},
    {'title': '글로벌 인플레이션 고조 및 고강도 금리 인상 사이클 진입', 'period': '2021.11 ~ 2022.10'},
    {'title': '미국 실리콘밸리은행(SVB) 파산 및 중소형 지방은행 연쇄 위기', 'period': '2023.03 ~ 2023.03'},
    {'title': 'AI 거품론(수익성 의문) 대두 및 엔 캐리 트레이드 청산 크래시', 'period': '2024.07 ~ 2024.08'},
    {'title': '미국 관세 장벽 격화 및 글로벌 무역 분쟁 재점화 (4월 대규모 크래시)', 'period': '2025.03 ~ 2025.04'},
    {'title': '중동 지정학적 위기 고조 (이란 갈등 격화 및 유가 급등)', 'period': '2026.01 ~ 2026.02'}
]

@st.cache_data(ttl=3600)
def fetch_live_market_events_filtered():
    events = list(static_historical_events)
    try:
        url = "https://news.google.com/rss/search?q=US+stock+market+drop+crash+OR+financial+panic+OR+fed+rate+inflation&hl=ko&gl=KR&ceid=KR:ko"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows) AppleWebKit/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            items = root.findall('.//item')
            for item in items[:5]:
                title = item.find('title').text if item.find('title') is not None else ""
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                if ' - ' in title:
                    title = title.rsplit(' - ', 1)[0]
                
                # 미국 시장에 강한 하락 충격을 주는 키워드 필터링
                keywords = ['하락', '폭락', '급락', '우려', '공포', '위기', '금리', '경고', '쇼크', '침체', '전쟁', '갈등']
                if any(kw in title for kw in keywords):
                    try:
                        dt = pd.to_datetime(pub_date)
                        date_str = dt.strftime('%Y.%m.%d')
                    except:
                        date_str = pub_date[:16] if pub_date else "최근"
                    
                    if not any(e['title'] == title for e in events):
                        events.append({'title': title, 'period': date_str})
    except Exception:
        pass
    return events

events_data = fetch_live_market_events_filtered()

def parse_period(period_str):
    if '~' in period_str:
        start_str, end_str = period_str.split(' ~ ')
        s_year, s_mon = map(int, start_str.split('.'))
        e_year, e_mon = map(int, end_str.split('.'))
        start_date = datetime.date(s_year, s_mon, 1)
        _, last_day = calendar.monthrange(e_year, e_mon)
        end_date = datetime.date(e_year, e_mon, last_day)
        return pd.to_datetime(start_date), pd.to_datetime(end_date)
    else:
        try:
            dt = pd.to_datetime(period_str)
            return dt - datetime.timedelta(days=7), dt + datetime.timedelta(days=7)
        except:
            dt = pd.to_datetime(datetime.date.today())
            return dt - datetime.timedelta(days=7), dt + datetime.timedelta(days=7)

def slope_sum_lagged(slope_arr, n):
    s = slope_arr
    result = np.full(len(s), np.nan)
    for i in range(len(s)):
        start_idx = i - n
        end_idx = i - 1
        if start_idx < 0:
            continue
        window = s[start_idx: end_idx + 1]
        if np.any(np.isnan(window)):
            continue
        result[i] = np.sum(window)
    return result

# ── 공통 Plotly 레이아웃 설정 ──
COMMON_CONFIG = {'scrollZoom': False, 'displayModeBar': True}
COMMON_LAYOUT = dict(
    template="plotly_dark",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    dragmode=False, # 초기 줌 비활성화
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="rgba(20,20,20,0.95)",
        font_size=11,
        font_family="sans-serif",
        font_color="white"
    ),
)

# 십자선 지시선 색상을 어둡게 (rgba(50,50,50,0.5))
def crosshair_xaxis(**kwargs):
    return dict(
        showgrid=False,
        tickfont_size=8,
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikecolor='rgba(50,50,50,0.5)',
        spikethickness=1,
        spikedash='dot',
        **kwargs
    )

def crosshair_yaxis(**kwargs):
    return dict(
        showgrid=False,
        tickfont_size=8,
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikecolor='rgba(50,50,50,0.5)',
        spikethickness=1,
        spikedash='dot',
        **kwargs
    )

# ── 5. 부모 window 객체에 직접 접근하여 2초 롱프레스 드래그 줌을 동작시키는 JS ──
LONGPRESS_ZOOM_JS = """
<script>
(function() {
    function enableLongPressZoom() {
        var parentDoc = window.parent.document;
        var parentPlotly = window.parent.Plotly;
        if (!parentDoc || !parentPlotly) return;
        
        var plots = parentDoc.querySelectorAll('.js-plotly-plot');
        plots.forEach(function(plot) {
            if (plot._longPressAttached) return;
            plot._longPressAttached = true;
            
            var timer = null;
            var isZoomActive = false;
            var startX = 0, startY = 0;

            plot.addEventListener('pointerdown', function(e) {
                startX = e.clientX;
                startY = e.clientY;
                if (timer) clearTimeout(timer);
                
                timer = setTimeout(function() {
                    isZoomActive = true;
                    try {
                        parentPlotly.relayout(plot, {dragmode: 'zoom'});
                        plot.style.outline = '2px solid #00d2ff';
                        plot.style.cursor = 'crosshair';
                    } catch(err) {
                        console.error("Relayout error:", err);
                    }
                }, 2000);
            });

            plot.addEventListener('pointermove', function(e) {
                if (!isZoomActive && timer) {
                    var diffX = Math.abs(e.clientX - startX);
                    var diffY = Math.abs(e.clientY - startY);
                    if (diffX > 5 || diffY > 5) {
                        clearTimeout(timer);
                        timer = null;
                    }
                }
            });

            plot.addEventListener('pointerup', function(e) {
                if (timer) { clearTimeout(timer); timer = null; }
                if (isZoomActive) {
                    setTimeout(function() {
                        isZoomActive = false;
                        plot.style.outline = 'none';
                        plot.style.cursor = '';
                        try {
                            parentPlotly.relayout(plot, {dragmode: false});
                        } catch(err) {}
                    }, 3000); 
                }
            });

            plot.addEventListener('pointerleave', function(e) {
                if (timer) { clearTimeout(timer); timer = null; }
            });
            
            plot.addEventListener('dblclick', function() {
                plot.style.outline = 'none';
                plot.style.cursor = '';
                isZoomActive = false;
                try {
                    parentPlotly.relayout(plot, {dragmode: false, 'xaxis.autorange': true, 'yaxis.autorange': true});
                } catch(err) {}
            });
        });
    }
    
    setInterval(enableLongPressZoom, 1000);
})();
</script>
"""

@st.cache_data(ttl=300)
def fetch_korean_market_status():
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get("https://finance.naver.com/sise/", headers=headers)
        res.encoding = 'cp949'
        soup = BeautifulSoup(res.text, 'html.parser')
        kp_box = soup.select_one('#tab_sel1_risefall')
        kd_box = soup.select_one('#tab_sel2_risefall')
        def parse_box(box):
            if not box:
                return {'상한가': '0', '상승': '0', '보합': '0', '하락': '0', '하한가': '0'}
            mapping = {'상한가': 'dd.uup a', '상승': 'dd.up a', '보합': 'dd.noc a', '하락': 'dd.dn a', '하한가': 'dd.ddn a'}
            return {k: (box.select_one(v).text.strip() if box.select_one(v) else '0') for k, v in mapping.items()}
        return parse_box(kp_box), parse_box(kd_box)
    except Exception:
        d = {'상한가': 'N/A', '상승': 'N/A', '보합': 'N/A', '하락': 'N/A', '하한가': 'N/A'}
        return d, d

@st.cache_data(ttl=300)
def fetch_nasdaq100_status():
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get("https://en.wikipedia.org/wiki/Nasdaq-100", headers=headers)
        res.raise_for_status()
        tables = pd.read_html(io.StringIO(res.text))
        df_tickers = next((t for t in tables if 'Ticker' in t.columns or 'Symbol' in t.columns), None)
        col = 'Ticker' if 'Ticker' in df_tickers.columns else 'Symbol'
        tickers = [t.replace('.', '-') for t in df_tickers[col].tolist()]
        data = yf.download(tickers, period='2d', progress=False)['Close']
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        last_two = data.tail(2)
        if len(last_two) == 2:
            diff = last_two.iloc[1] - last_two.iloc[0]
            return {'상승': str(int((diff > 0).sum())), '보합': str(int((diff == 0).sum())), '하락': str(int((diff < 0).sum()))}
        return {'상승': 'N/A', '보합': 'N/A', '하락': 'N/A'}
    except Exception:
        return {'상승': 'N/A', '보합': 'N/A', '하락': 'N/A'}

@st.cache_data(ttl=1800)
def fetch_historical_breadth():
    kospi_tickers = ['005930.KS','000660.KS','373220.KS','207940.KS','005490.KS','005380.KS','051910.KS','035420.KS','000270.KS','006400.KS','035720.KS','068270.KS','105560.KS','055550.KS','003550.KS','012330.KS','032830.KS','096770.KS','086790.KS','015760.KS','000810.KS','018260.KS','323410.KS','033780.KS','009150.KS','011780.KS','010950.KS','010130.KS','001040.KS','003490.KS','034730.KS','000120.KS','047810.KS','011200.KS','009830.KS','066570.KS','028050.KS','017670.KS','000100.KS','024110.KS','039490.KS','010140.KS','004020.KS','161390.KS','000080.KS','035250.KS','271560.KS','036460.KS','002790.KS']
    kosdaq_tickers = ['247540.KQ','086520.KQ','293490.KQ','253450.KQ','035900.KQ','058470.KQ','196170.KQ','028300.KQ','036570.KQ','095610.KQ','068760.KQ','039030.KQ','145020.KQ','041510.KQ','086900.KQ','067160.KQ','036830.KQ','214370.KQ','137400.KQ','098460.KQ','178920.KQ','078600.KQ','084370.KQ','046890.KQ','038540.KQ','064550.KQ','065350.KQ','263750.KQ','112040.KQ','357780.KQ','042700.KQ','122870.KQ','078340.KQ','054040.KQ','041960.KQ','032640.KQ','069080.KQ','060310.KQ','067630.KQ','108380.KQ','166090.KQ','117730.KQ','237690.KQ','052690.KQ','119850.KQ','352820.KQ','950130.KQ']
    ndx_tickers = ['MSFT','AAPL','NVDA','AMZN','META','GOOGL','GOOG','TSLA','AVGO','PEP','COST','AZN','CSCO','AMD','TMUS','QCOM','INTC','TXN','AMGN','INTU','ISRG','HON','AMAT','BKNG','ADP','MDLZ','GILD','ADI','LRCX','REGN','VRTX','MU','PANW','SBUX','KLAC','SNPS','CDNS','MRVL','NFLX','ORLY','ABNB','CTAS','PYPL','ASML','KDP','ROST','MNST','PAYX','FTNT','MCHP','DXCM','EXC','BIIB','IDXX','CPRT','VRSK','PCAR','ODFL','CSGP','CHTR','CEG','ANSS','TEAM','FAST','GEHC','ON','ILMN','EA','FANG','DLTR','NXPI','WDAY','MRNA','ALGN','DDOG','APP','CRWD','CDW','CTSH','ADSK','ROP','XEL','KHC','EBAY']
    
    def calc_kr(tickers):
        try:
            df_p = yf.download(tickers, period='130d', progress=False)['Close']
            if isinstance(df_p.columns, pd.MultiIndex): df_p.columns = df_p.columns.get_level_values(0)
            df_d = df_p.diff().dropna(how='all')
            df_r = df_p.pct_change(fill_method=None) * 100
            df_b = pd.DataFrame({
                '상한가': (df_r >= 29).sum(axis=1),
                '상승': ((df_d > 0) & (df_r < 29)).sum(axis=1),
                '보합': (df_d == 0).sum(axis=1),
                '하락': ((df_d < 0) & (df_r > -29)).sum(axis=1),
                '하한가': (df_r <= -29).sum(axis=1)
            })
            df_b = df_b[df_b.sum(axis=1) > 0]
            return df_b.tail(90)
        except Exception:
            return pd.DataFrame(columns=['상한가','상승','보합','하락','하한가'])
            
    def calc_us(tickers):
        try:
            df_p = yf.download(tickers, period='130d', progress=False)['Close']
            if isinstance(df_p.columns, pd.MultiIndex): df_p.columns = df_p.columns.get_level_values(0)
            df_d = df_p.diff().dropna(how='all')
            df_b = pd.DataFrame({
                '상승': (df_d > 0).sum(axis=1),
                '보합': (df_d == 0).sum(axis=1),
                '하락': (df_d < 0).sum(axis=1)
            })
            df_b = df_b[df_b.sum(axis=1) > 0]
            return df_b.tail(90)
        except Exception:
            return pd.DataFrame(columns=['상승','보합','하락'])
            
    return calc_kr(kospi_tickers), calc_kr(kosdaq_tickers), calc_us(ndx_tickers)

@st.cache_data(ttl=1800)
def fetch_index_prices():
    try:
        def get_s(ticker):
            s = yf.download(ticker, period='130d', progress=False)['Close']
            if isinstance(s, pd.DataFrame): s = s.iloc[:,0]
            s.index = pd.to_datetime(s.index).normalize()
            return s
        return get_s('^KS11'), get_s('^KQ11'), get_s('QQQ')
    except Exception:
        e = pd.Series(dtype=float)
        return e, e, e

@st.cache_data(ttl=3600)
def fetch_and_process_data():
    start_date_str = "2018-10-01"
    qqq = yf.download('QQQ', start=start_date_str, progress=False)
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq_df = qqq[['Close']].rename(columns={'Close': 'QQQ'})
    vix = yf.download('^VIX', start=start_date_str, progress=False)
    if isinstance(vix.columns, pd.MultiIndex): vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[['Close']].rename(columns={'Close': 'VIX'})
    url = f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start_date_str}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            res = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-10-01", headers=headers)
            res.raise_for_status()
    except Exception:
        res = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-10-01", headers=headers)
        res.raise_for_status()
    qqq_df.index = qqq_df.index.normalize()
    vix_df.index = vix_df.index.normalize()
    data = res.json()['fear_and_greed_historical']['data']
    fg_df = pd.DataFrame(data)
    fg_df['Date'] = pd.to_datetime(fg_df['x'], unit='ms').dt.normalize()
    fg_df = fg_df.set_index('Date').rename(columns={'y': 'FearGreedIndex'})[['FearGreedIndex']]
    fg_df = fg_df[~fg_df.index.duplicated(keep='last')]
    df = qqq_df.join(vix_df, how='outer').join(fg_df, how='outer').ffill().bfill()
    df['(FGI-VIX)/5'] = (df['FearGreedIndex'] - df['VIX']) / 5
    df['(FGI-VIX)/5 2MA'] = df['(FGI-VIX)/5'].rolling(window=2).mean().bfill()
    df_s = df.copy().reset_index()
    df_s.rename(columns={df_s.columns[0]: 'Date'}, inplace=True)
    df_s['Date'] = pd.to_datetime(df_s['Date'])
    df_s = df_s.sort_values('Date').reset_index(drop=True)
    df_s['슬로프'] = df_s['QQQ'].diff()
    sl = df_s['슬로프'].values
    df_s['슬로프5일합'] = slope_sum_lagged(sl, 5)
    df_s['슬로프10일합'] = slope_sum_lagged(sl, 10)
    df_s['슬로프20일합'] = slope_sum_lagged(sl, 20)
    df_s['슬로프40일합'] = slope_sum_lagged(sl, 40)
    df_s['5일상한'] = 20;  df_s['5일하한'] = -20
    df_s['10일상한'] = 30; df_s['10일하한'] = -30
    df_s['20일상한'] = 40; df_s['20일하한'] = -40
    df_s['40일상한'] = 50; df_s['40일하한'] = -50
    max_val = float(df_s['QQQ'].max()) * 1.5
    for days in [5, 10, 20, 40]:
        sc = f'슬로프{days}일합'
        dc = f'{days}일하한'
        diff = df_s[dc] - df_s[sc]
        df_s[f'{days}일_초록'] = np.where((diff >= 0) & (diff < 10), max_val, 0)
        df_s[f'{days}일_주황'] = np.where((diff >= 10) & (diff < 20), max_val, 0)
        df_s[f'{days}일_빨강'] = np.where((diff >= 20) & (diff < 30), max_val, 0)
        df_s[f'{days}일_검정'] = np.where(diff >= 30, max_val, 0)
    df_s.set_index('Date', inplace=True)
    return df_s[~df_s.index.duplicated(keep='first')]

with st.spinner('데이터 로딩 중...'):
    df = fetch_and_process_data()

st.components.v1.html(LONGPRESS_ZOOM_JS, height=0)

tab_names = [
    '📊 QQQ vs VIX vs Fear & Greed', 
    '📈 슬로프합 지표', 
    '📈 등락현황'
]
tabs = st.tabs(tab_names)

# ── Tab 1 ──
with tabs[0]:
    five_years_ago = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
    df1 = df[df.index >= five_years_ago]

    # ── 색깔 조건 정의 (탭2 color_bg 색상표와 동일하게 맞춤) ──
    # 검정(4개): #595959 / 빨강(3개): #E06666 / 노랑(2개): #FFD700 / 초록(1개): #A9D08E
    color_cond_map = [
        ((df1['FearGreedIndex']<=9)&(df1['VIX']>=26),                                                          '#595959', '#FFFFFF', 'rgba(0,0,0,0.55)'),
        ((df1['FearGreedIndex']>=10)&(df1['FearGreedIndex']<=19)&(df1['VIX']>=22)&(df1['VIX']<=25),            '#E06666', '#FFFFFF', 'rgba(220,30,30,0.4)'),
        ((df1['FearGreedIndex']>=20)&(df1['FearGreedIndex']<=29)&(df1['VIX']>=18)&(df1['VIX']<=21),            '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
        ((df1['FearGreedIndex']>=30)&(df1['FearGreedIndex']<=39)&(df1['VIX']>=14)&(df1['VIX']<=17),            '#A9D08E', '#000000', 'rgba(0,128,0,0.3)'),
    ]

    # ── 통합 색깔 감지 날짜표 (그래프 위) ──
    # 모든 조건의 날짜를 합쳐서 날짜별 색깔 매핑
    date_color_map = {}
    for cond, bg, fg, _ in reversed(color_cond_map):  # 우선순위: 검정 > 빨강 > 노랑 > 초록
        for d in df1[cond].index:
            date_color_map[d] = (bg, fg)
    # 최근 10개 날짜 추출
    all_detected_sorted = sorted(date_color_map.keys(), reverse=True)[:10]

    TH_SIG = "border:1px solid #555;padding:3px 6px;text-align:center;background:#1F4E79;color:white;font-size:0.62rem;"
    TD_SIG = "border:1px solid #555;padding:3px 5px;text-align:center;font-size:0.62rem;"
    if all_detected_sorted:
        date_cells = "".join([
            f"<td style='background:{date_color_map[d][0]};color:{date_color_map[d][1]};font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>"
            for d in all_detected_sorted
        ])
        st.markdown(
            f"<div style='margin-bottom:0.4rem;'>"
            f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 10개)</span>"
            f"<div style='overflow-x:auto;margin-top:3px;'>"
            f"<table style='border-collapse:collapse;font-size:0.62rem;'>"
            f"<tbody><tr><th style='{TH_SIG}'>날짜</th>{date_cells}</tr></tbody>"
            f"</table></div></div>",
            unsafe_allow_html=True
        )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for ev in events_data:
        s_d, e_d = parse_period(ev['period'])
        fig.add_vrect(x0=s_d, x1=e_d, fillcolor="gray", opacity=0.3, layer="below", line_width=0,
                      annotation_text=ev['title'], annotation_position="top left", annotation_font_size=9, annotation_font_color="white")
    
    hd1 = [fmt_date_kor(d) for d in df1.index]
    
    fig.add_trace(go.Scatter(
        x=hd1, y=df1['QQQ'], name='QQQ', 
        line=dict(color='#00d2ff', width=2), 
        hovertemplate='QQQ: %{y:.2f}<extra></extra>'
    ), secondary_y=False)
    
    fig.add_trace(go.Scatter(
        x=hd1, y=df1['VIX'], name='VIX', 
        line=dict(color='#ff2a2a', width=1), 
        hovertemplate='VIX: %{y:.2f}<extra></extra>'
    ), secondary_y=True)
    
    fig.add_trace(go.Scatter(
        x=hd1, y=df1['FearGreedIndex'], name='FGI', 
        line=dict(color='#a64dff', width=1), 
        hovertemplate='FGI: %{y:.1f}<extra></extra>'
    ), secondary_y=True)
    
    fig.add_trace(go.Scatter(
        x=hd1, y=df1['(FGI-VIX)/5'], name='(FGI-VIX)/5', 
        line=dict(color='#ffb347', width=1), 
        hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'
    ), secondary_y=True)
    
    for cond, _bg, _fg, fc in color_cond_map:
        fig.add_trace(go.Scatter(x=hd1, y=cond.astype(int)*200, fill='tozeroy', line=dict(width=0), fillcolor=fc, showlegend=False, hoverinfo='skip'), secondary_y=True)
    
    fig.update_layout(**COMMON_LAYOUT, height=550, margin=dict(l=10,r=10,t=30,b=10), legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="left",x=0,font_size=10))
    fig.update_yaxes(title_text="QQQ ($)", title_font_size=9, **crosshair_yaxis(), secondary_y=False)
    fig.update_yaxes(title_text="Indicators", title_font_size=9, **crosshair_yaxis(range=[-10,120]), secondary_y=True)
    fig.update_xaxes(**crosshair_xaxis())

    st.plotly_chart(fig, width='stretch', config=COMMON_CONFIG)

    st.markdown("---")
    st.markdown("#### 📌 실시간 주요 시장 사건 (위기/하락 중심)")
    
    # 주요 사건 표: 글씨/패딩 크기를 4/5로 축소 (0.85rem → 0.68rem, padding 6px → 5px)
    news_df = pd.DataFrame(events_data)
    if not news_df.empty:
        news_df.index = news_df.index + 1
        news_df.columns = ['사건 내용', '날짜']
        
        rows_html = ""
        for idx, row in news_df.iterrows():
            rows_html += f"<tr><td style='border:1px solid #555;padding:5px;text-align:center;font-size:0.68rem;'>{row['사건 내용']}</td><td style='border:1px solid #555;padding:5px;text-align:center;font-size:0.68rem;'>{row['날짜']}</td></tr>"
        st.markdown(f"<table style='width:100%;border-collapse:collapse;font-size:0.68rem;'><thead style='background:#1F4E79;color:white;'><tr><th style='border:1px solid #555;padding:5px;text-align:center;font-size:0.68rem;'>사건 내용</th><th style='border:1px solid #555;padding:5px;text-align:center;font-size:0.68rem;'>날짜</th></tr></thead><tbody>{rows_html}</tbody></table>", unsafe_allow_html=True)

# ── Tab 2 ──
with tabs[1]:
    all_fd = []
    for days_t in [5, 10, 20, 40]:
        dfc = f'{days_t}일하한'
        sfc = f'슬로프{days_t}일합'
        all_fd.extend(df[df[dfc]-df[sfc]>=0].index.tolist())
    dc_top = Counter(all_fd)
    parent_dates = sorted(list(set(all_fd)), reverse=True)
    
    if parent_dates:
        r10 = parent_dates[:10]
        dates_row = []
        counts_row = []
        for dt in r10:
            cnt = dc_top.get(dt, 1)
            bg = "#595959" if cnt==4 else "#E06666" if cnt==3 else "#FFD700" if cnt==2 else "#A9D08E"
            fg = "#FFF" if cnt>=3 else "#000"
            dates_row.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:3px 5px;border:1px solid #555;font-size:0.72rem;'>{fmt_date_kor(dt)}</td>")
            counts_row.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:3px 5px;border:1px solid #555;font-size:0.72rem;'>이탈 {cnt}개</td>")
        
        # 종합 최근 이탈 신호 (최근 10개) 표 행열 전환
        top_html_transposed = f"""
        <div style='margin-bottom:0.3rem;overflow-x:auto;'>
        <span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 10개 - 행열전환)</span>
        <table style='border-collapse:collapse;font-size:0.72rem;margin-top:3px;'>
            <tr>
                <th style='border:1px solid #555;padding:3px 8px;background:#1F4E79;color:white;text-align:center;font-size:0.72rem;'>날짜</th>
                {"".join(dates_row)}
            </tr>
            <tr>
                <th style='border:1px solid #555;padding:3px 8px;background:#1F4E79;color:white;text-align:center;font-size:0.72rem;'>이탈 수</th>
                {"".join(counts_row)}
            </tr>
        </table>
        </div>
        """
        st.markdown(top_html_transposed, unsafe_allow_html=True)

    fig_dsi = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=('슬로프 5일합','슬로프 10일합','슬로프 20일합','슬로프 40일합'),
        specs=[[{"secondary_y": True}]]*4)
    CHARTS = [
        (1, 5,  '5일상한',  '5일하한',  '슬로프5일합',  '5일_초록',  '5일_주황',  '5일_빨강',  '5일_검정'),
        (2, 10, '10일상한', '10일하한', '슬로프10일합', '10일_초록', '10일_주황', '10일_빨강', '10일_검정'),
        (3, 20, '20일상한', '20일하한', '슬로프20일합', '20일_초록', '20일_주황', '20일_빨강', '20일_검정'),
        (4, 40, '40일상한', '40일하한', '슬로프40일합', '40일_초록', '40일_주황', '40일_빨강', '40일_검정'),
    ]
    hd_df = [fmt_date_kor(d) for d in df.index]
    for rn, days, uc, dc, sc, gc, oc, rc, bc in CHARTS:
        sf = (rn == 1)
        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',line=dict(color='#1F4E79',width=1.5),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=rn,col=1,secondary_y=False)
        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[sc],name=f'슬로프 {days}일합계',line=dict(color='#87CEEB',width=1.2),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=rn,col=1,secondary_y=True)
        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[uc],name='상한선',line=dict(color='#FFEB3B',width=1,dash='dash'),showlegend=sf,legendgroup='upper',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[dc],name='하한선',line=dict(color='#FFEB3B',width=1,dash='dash'),showlegend=sf,legendgroup='lower',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
        for cn, fc in [(gc,'rgba(76,175,80,0.3)'),(oc,'rgba(255,220,0,0.35)'),(rc,'rgba(220,30,30,0.4)'),(bc,'rgba(0,0,0,0.55)')]:
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[cn],fill='tozeroy',line=dict(width=0),fillcolor=fc,showlegend=False,hoverinfo='skip'),row=rn,col=1,secondary_y=False)
    
    fig_dsi.update_layout(**COMMON_LAYOUT, height=2100, margin=dict(l=10,r=10,t=60,b=10), legend=dict(orientation="h",yanchor="bottom",y=1.005,xanchor="left",x=0,font_size=9))
    qmin, qmax = float(df['QQQ'].min()), float(df['QQQ'].max())
    for i in range(1, 5):
        fig_dsi.update_yaxes(range=[qmin*0.95,qmax*1.05],**crosshair_yaxis(),secondary_y=False,row=i,col=1)
        fig_dsi.update_yaxes(range=[-120,180],tick0=-120,dtick=20,**crosshair_yaxis(),secondary_y=True,row=i,col=1)
    fig_dsi.update_xaxes(**crosshair_xaxis())
    fig_dsi.update_annotations(font_size=10)

    st.plotly_chart(fig_dsi, width='stretch', config=COMMON_CONFIG)

    st.markdown("#### 하한 미만 세부 분석 표")
    all_fd2 = []
    for days in [5, 10, 20, 40]:
        dc2 = f'{days}일하한'
        sc2 = f'슬로프{days}일합'
        all_fd2.extend(df[df[dc2]-df[sc2]>=0].index.tolist())
    dcnt = Counter(all_fd2)
    sel = st.selectbox('기간 선택', ['종합', 5, 10, 20, 40], format_func=lambda x: f'{x}일합' if isinstance(x, int) else x)

    def color_bg(cnt):
        if cnt==4: return "#595959", "#FFF"
        elif cnt==3: return "#E06666", "#FFF"
        elif cnt==2: return "#FFD700", "#000"
        return "#A9D08E", "#000"

    TS = "width:100%;border-collapse:collapse;font-size:0.62rem;"
    TH = "border:1px solid #555;padding:4px 6px;text-align:center;background:#1F4E79;color:white;"
    TD = "text-align:center;padding:3px 5px;border:1px solid #555;"

    # ── 3. 하한 미만 세부 분석 표 세로형 복원 및 2. 가운데 정렬 ──
    if sel == '종합':
        uds = sorted(list(set(all_fd2)), reverse=True)
        if uds:
            rh = ""
            for dt in uds:
                cnt = dcnt.get(dt, 1); bg, fg = color_bg(cnt)
                rh += f"<tr><td style='background:{bg};color:{fg};font-weight:bold;{TD}'>{fmt_date_kor(dt)}</td><td style='background:{bg};color:{fg};{TD}'></td><td style='background:{bg};color:{fg};{TD}'></td></tr>"
            st.markdown(f"<div style='max-height:400px;overflow-y:auto;margin-top:4px;'><table style='{TS}'><thead><tr style='background:#1F4E79;color:white;position:sticky;top:0;'><th style='{TH}'>날짜</th><th style='{TH}'>색깔</th><th style='{TH}'>차이</th></tr></thead><tbody>{rh}</tbody></table></div>", unsafe_allow_html=True)
        else:
            st.info("하한을 하회하는 이탈 신호 데이터가 없습니다.")
    else:
        dc3 = f'{sel}일하한'; sc3 = f'슬로프{sel}일합'
        dff = df[df[dc3]-df[sc3]>=0].copy()
        dff['차이'] = dff[dc3]-dff[sc3]
        dff = dff.sort_index(ascending=False)
        if len(dff) > 0:
            rh = ""
            for dt, row in dff.iterrows():
                dv = row['차이']
                cn, bh, fh = ('초록','#A9D08E','#000') if 0<=dv<10 else ('노랑','#FFD700','#000') if 10<=dv<20 else ('빨강','#E06666','#FFF') if 20<=dv<30 else ('검정','#595959','#FFF')
                cnt = dcnt.get(dt, 1); bg, fg = color_bg(cnt)
                rh += f"<tr><td style='background:{bg};color:{fg};font-weight:bold;{TD}'>{fmt_date_kor(dt)}</td><td style='background:{bh};color:{fh};font-weight:bold;{TD}'>{cn}</td><td style='{TD}'>{dv:.1f}</td></tr>"
            st.markdown(f"<div style='max-height:400px;overflow-y:auto;margin-top:4px;'><table style='{TS}'><thead><tr style='background:#1F4E79;color:white;position:sticky;top:0;'><th style='{TH}'>날짜</th><th style='{TH}'>색깔</th><th style='{TH}'>차이</th></tr></thead><tbody>{rh}</tbody></table></div>", unsafe_allow_html=True)
        else:
            st.info("하한을 하회하는 이탈 신호 데이터가 없습니다.")

# ── Tab 3 ──
with tabs[2]:
    st.markdown("### 국내외 증시 등락 현황")
    with st.spinner("국내외 등락현황 데이터를 가져오는 중..."):
        kp_s, kd_s = fetch_korean_market_status()
        ndx_s = fetch_nasdaq100_status()
        kp_b, kd_b, ndx_b = fetch_historical_breadth()
        kp_p, kd_p, qqq_p = fetch_index_prices()
    
    CM = {'상한가':'#CC0000','상승':'#FF6B9D','보합':'#DDDDDD','하락':'#87CEEB','하한가':'#3399FF'}
    
    # ── 4번 요청: 국내외 등락 현황 표 행열 전환 및 2. 가운데 정렬 ──
    def build_table_transposed_kr(sd, title):
        cols_headers = []
        cols_values = []
        for k in ['상한가','상승','보합','하락','하한가']:
            c = CM.get(k, '#FFF')
            cols_headers.append(f"<th style='padding:2px 6px;border:1px solid #444;font-size:0.55rem;color:white;background:#1F4E79;text-align:center;'>{k}</th>")
            cols_values.append(f"<td style='padding:2px 6px;border:1px solid #444;font-size:0.55rem;font-weight:bold;color:{c};text-align:center;'>{sd.get(k,'0')}</td>")
        return f"""
        <div style='margin-bottom: 0.5rem;'>
            <span style='font-size:0.75rem; font-weight:600;'>{title}</span>
            <table style='border-collapse:collapse;width:100%;margin-top:2px;'>
                <tr>{"".join(cols_headers)}</tr>
                <tr>{"".join(cols_values)}</tr>
            </table>
        </div>
        """
        
    def build_table_transposed_us(sd, title):
        cols_headers = []
        cols_values = []
        for k in ['상승','보합','하락']:
            c = CM.get(k, '#FFF')
            cols_headers.append(f"<th style='padding:2px 6px;border:1px solid #444;font-size:0.55rem;color:white;background:#1F4E79;text-align:center;'>{k}</th>")
            cols_values.append(f"<td style='padding:2px 6px;border:1px solid #444;font-size:0.55rem;font-weight:bold;color:{c};text-align:center;'>{sd.get(k,'0')}</td>")
        return f"""
        <div style='margin-bottom: 0.5rem;'>
            <span style='font-size:0.75rem; font-weight:600;'>{title}</span>
            <table style='border-collapse:collapse;width:100%;margin-top:2px;'>
                <tr>{"".join(cols_headers)}</tr>
                <tr>{"".join(cols_values)}</tr>
            </table>
        </div>
        """

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(build_table_transposed_kr(kp_s, "🇰🇷 코스피 등락 현황 (당일)"), unsafe_allow_html=True)
    with c2:
        st.markdown(build_table_transposed_kr(kd_s, "🇰🇷 코스닥 등락 현황 (당일)"), unsafe_allow_html=True)
    with c3:
        st.markdown(build_table_transposed_us(ndx_s, "🇺🇸 나스닥 100 등락 현황 (당일 - 상하한가 제외)"), unsafe_allow_html=True)
        
    st.markdown("---")
    st.markdown("### 📈 대표 종목 기준 등락현황 시계열 추이 (최근 90영업일)")
    
    # ── 7번 요청: 지수를 제외한 그래프는 영역형(Area)으로 채우기 ──
    def make_line_fig(df_b, title, ps=None, pname="지수", is_us=False):
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        if not df_b.empty:
            dfp = df_b.copy()
            dfp.index = pd.to_datetime(dfp.index)
            hd = [fmt_date_kor(d) for d in dfp.index]
            
            # 6. 미국 나스닥 100은 상한/하한가 제외
            if is_us:
                configs = [('상승','#FF6B9D','상승'),('보합','#AAAAAA','보합'),('하락','#87CEEB','하락')]
            else:
                configs = [('상한가','#CC0000','상한가'),('상승','#FF6B9D','상승'),('보합','#AAAAAA','보합'),('하락','#87CEEB','하락'),('하한가','#3399FF','하한가')]
                
            for cn, color, ln in configs:
                if cn in dfp.columns:
                    # 영역형 그래프 적용 (fill='tozeroy')
                    fig.add_trace(go.Scatter(
                        x=hd,
                        y=dfp[cn],
                        mode='lines',
                        name=ln,
                        line=dict(color=color, width=1.5),
                        fill='tozeroy',  
                        hovertemplate=f'{ln}: %{{y}}<extra></extra>'
                    ), secondary_y=False)
                    
            if ps is not None and len(ps) > 0:
                pf = ps[ps.index >= dfp.index.min()].tail(90)
                # 코스피지수, 코스닥지수, QQQ가격은 영역형 제외, 일반 선형(Line) 그래프
                fig.add_trace(go.Scatter(
                    x=hd,
                    y=pf.values,
                    mode='lines',
                    name=pname,
                    line=dict(color='#00C851', width=2.5),  
                    hovertemplate=f'{pname}: %{{y:.2f}}<extra></extra>'
                ), secondary_y=True)
                
        fig.update_layout(
            **COMMON_LAYOUT,
            title=dict(text=title, font=dict(size=12), x=0, xanchor='left'),
            height=420,
            margin=dict(l=10, r=10, t=60, b=10),
            legend=dict(
                orientation="h",
                yanchor="bottom", y=1.01,
                xanchor="left", x=0,
                font_size=9
            )
        )
        fig.update_xaxes(**crosshair_xaxis())
        fig.update_yaxes(title_text="종목 수", title_font_size=9, **crosshair_yaxis(), secondary_y=False)
        fig.update_yaxes(title_text=pname, title_font_size=9, **crosshair_yaxis(), secondary_y=True)
        return fig
        
    st.plotly_chart(make_line_fig(kp_b,"코스피 대표 종목 등락현황 추이 (영역형)",kp_p,"코스피", is_us=False),width='stretch',config=COMMON_CONFIG)
    st.plotly_chart(make_line_fig(kd_b,"코스닥 대표 종목 등락현황 추이 (영역형)",kd_p,"코스닥", is_us=False),width='stretch',config=COMMON_CONFIG)
    st.plotly_chart(make_line_fig(ndx_b,"나스닥 100 대표 종목 등락현황 추이 (영역형 - 상하한 제외)",qqq_p,"QQQ", is_us=True),width='stretch',config=COMMON_CONFIG)
