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
import os
import json
import re

# Page configuration
st.set_page_config(page_title="Market Trends Dashboard", layout="wide", initial_sidebar_state="collapsed")

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
    /* 상단 헤더 숨김 및 간격 축소 */
    header[data-testid="stHeader"], .stAppHeader, .viewerBadge_container__oz27K, div[data-testid="stConnectionStatus"] {
        display: none !important;
        height: 0px !important;
    }
    .block-container { padding-top: 0.1rem !important; padding-bottom: 0 !important; }
    
    /* 탭 간격 최적화 */
    .stTabs [data-baseweb="tab-list"] {
        margin-top: -1.2rem !important;
        margin-bottom: 0.2rem !important;
    }
    
    /* 요소 간의 여백 최소화 */
    div[data-testid="element-container"] {
        margin-top: 0.05rem !important;
        margin-bottom: 0.05rem !important;
    }
    div[data-testid="stVerticalBlock"] > div:has(> .element-container) { padding-top: 0 !important; padding-bottom: 0 !important; }
    .main-header { font-size: 1.2rem; font-weight: 700; background: -webkit-linear-gradient(45deg, #f3ec78, #af4261); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; line-height: 1.1; }
    h3 { font-size: 0.85rem !important; margin: 0.4rem 0 0.2rem 0 !important; }
    h4 { font-size: 0.75rem !important; margin: 0.3rem 0 0.2rem 0 !important; }
    .stTabs [data-baseweb="tab-list"] button p { font-size: 0.78rem; }
    .stButton > button { margin-top: 0 !important; margin-bottom: 0.1rem !important; padding: 2px 10px !important; font-size: 0.75rem !important; }
    
    /* 모든 표의 크기 */
    table {
        width: 100% !important;
        max-width: 100% !important;
        border-collapse: collapse;
        margin: 0 !important;
    }
    table, th, td {
        font-size: 0.51rem !important;
        padding: 1px 2px !important;
        letter-spacing: -0.06em !important;
        font-stretch: ultra-condensed !important;
        line-height: 1.1 !important;
    }
    
    div[data-testid="stHorizontalBlock"] {
        column-gap: 0.1rem !important;
    }
    
    .block-container {
        padding-bottom: 50px !important;
    }
    
    .stPlotlyChart {
        touch-action: pan-y !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header" style="text-align:center; margin-bottom: 0.5rem;">Market Indicators Dashboard</p>', unsafe_allow_html=True)

# Refresh Button Placement (Aligned Right above selector, ensuring mobile responsiveness)
col_top_left, col_top_right = st.columns([5, 1])
with col_top_right:
    st.markdown(
        """
        <style>
        div[data-testid="column"]:has(button[key="header_data_refresh"]) {
            display: flex;
            justify-content: flex-end;
            width: 100%;
        }
        </style>
        """, unsafe_allow_html=True
    )
    if st.button("refresh", key="header_data_refresh"):
        st.cache_data.clear()
        st.rerun()

# Global Selectors (Sync Country and Period)
c_sel1, c_sel2 = st.columns([1, 1])

with c_sel1:
    # Country Selection
    if 'selected_country' not in st.session_state:
        st.session_state.selected_country = "미국"
        
    country_options = ["미국", "한국"]
    selected_country = st.radio(
        "Country",
        options=country_options,
        index=country_options.index(st.session_state.selected_country),
        horizontal=True,
        label_visibility="collapsed",
        key="country_radio_global"
    )
    st.session_state.selected_country = selected_country

with c_sel2:
    # Period Selection
    selected_period = st.radio(
        "Period",
        options=["12m", "6m", "3m", "1m"],
        index=2,
        horizontal=True,
        label_visibility="collapsed",
        key="period_radio"
    )

active_period_days = None
if selected_period == "12m": active_period_days = 365
elif selected_period == "6m": active_period_days = 182
elif selected_period == "3m": active_period_days = 91
elif selected_period == "1m": active_period_days = 30

# 고충격 역사적 사건 데이터베이스 정의 (하락률 칼럼 추가)
static_historical_events = [
    {"title": "코로나 19 팬데믹 폭락", "period": "2020.02 ~ 2020.03", "fall_rate": "-35%"},
    {"title": "인플레이션 및 금리 인상 하락장", "period": "2021.11 ~ 2022.10", "fall_rate": "-37%"},
    {"title": "실리콘밸리 은행(SVB) 파산 사태", "period": "2023.03 ~ 2023.03", "fall_rate": "-9%"},
    {"title": "엔 캐리 트레이드 청산 우려 폭락", "period": "2024.07 ~ 2024.08", "fall_rate": "-15%"},
    {"title": "미-중 무역 전쟁 재발 우려 폭락", "period": "2025.03 ~ 2025.04", "fall_rate": "-18%"}
]

def parse_period(period_str):
    if '~' in period_str:
        try:
            start_str, end_str = period_str.split(' ~ ')
            if '-' in start_str:
                return pd.to_datetime(start_str), pd.to_datetime(end_str)
            else:
                s_year, s_mon = map(int, start_str.split('.'))
                e_year, e_mon = map(int, end_str.split('.'))
                start_date = datetime.date(s_year, s_mon, 1)
                _, last_day = calendar.monthrange(e_year, e_mon)
                end_date = datetime.date(e_year, e_mon, last_day)
                return pd.to_datetime(start_date), pd.to_datetime(end_date)
        except Exception:
            dt = pd.to_datetime(datetime.date.today())
            return dt - datetime.timedelta(days=7), dt + datetime.timedelta(days=7)
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

COMMON_CONFIG = {
    'scrollZoom': True,
    'displayModeBar': True,
    'doubleClick': 'reset'
}
COMMON_LAYOUT = dict(
    template="plotly_dark",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    dragmode=False,
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="rgba(20,20,20,0.15)",
        font_size=10,
        font_family="sans-serif",
        font_color="white"
    )
)

def color_bg(cnt):
    if cnt==4: return "#595959", "#FFF"
    elif cnt==3: return "#E06666", "#FFF"
    elif cnt==2: return "#FFD700", "#000"
    return "#A9D08E", "#000"

TS = "width:100%;border-collapse:collapse;"
TH = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;"
TD = "text-align:center;padding:2px 4px;border:1px solid #555;"

def crosshair_xaxis(**kwargs):
    return dict(
        showgrid=False,
        tickfont_size=8,
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikecolor='rgba(150,150,150,0.5)', 
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
        spikecolor='rgba(150,150,150,0.5)',
        spikethickness=1,
        spikedash='dot',
        **kwargs
    )

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
        data = yf.download(tickers, period='10d', progress=False)['Close']
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        data = data.ffill().bfill()
        # Find the most recent active trading day (where values changed compared to the previous day)
        diff_all = data.diff()
        valid_days = diff_all.index[(diff_all != 0).any(axis=1)]
        if len(valid_days) >= 1:
            latest_valid_day = valid_days[-1]
            diff = diff_all.loc[latest_valid_day]
            return {'상승': str(int((diff > 0).sum())), '보합': str(int((diff == 0).sum())), '하락': str(int((diff < 0).sum()))}
        # Fallback if no diff found (e.g. data hasn't loaded properly) but we have at least 2 rows
        if len(data) >= 2:
            diff = data.iloc[-1] - data.iloc[-2]
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
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2018-10-01"
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

# 한국 데이터 빌드 (FGI 50 고정 해결을 위해 NaN + Time Interpolation 처리)
@st.cache_data(ttl=60)
def fetch_korean_market_data_v2():
    # 1. KOSPI 지수 다운로드
    kospi = yf.download('^KS11', start="2018-10-01", progress=False)
    if isinstance(kospi.columns, pd.MultiIndex): kospi.columns = kospi.columns.get_level_values(0)
    kospi_df = kospi[['Close']].rename(columns={'Close': 'KOSPI'})
    
    # 2. 한국 공포탐욕지수 & 실시간 VKOSPI 가져오기
    headers = {'User-Agent': 'Mozilla/5.0'}
    realtime_score = 50
    realtime_vkospi = 20.0
    history_records = {}
    
    # 2-1. Vercel API에서 기본값 조회
    try:
        res = requests.get('https://feargree-api.vercel.app/api', headers=headers, timeout=8)
        if res.status_code == 200:
            api_data = res.json()
            realtime_score = int(api_data['kr']['score'])
            realtime_vkospi = float(api_data['kr']['vkospi'])
            # API에서 전달되는 소수의 히스토리 파싱
            for h in api_data.get('history', []):
                try:
                    h_date = pd.to_datetime(h['date']).normalize()
                    history_records[h_date] = float(h['kr'])
                except:
                    pass
    except Exception:
        pass
        
    # 2-2. feargreed.co.kr 메인 HTML에서 COMMENTS 시황코멘트 파싱하여 상세 한국 FGI 데이터 복원
    try:
        res_web = requests.get('http://feargreed.co.kr', headers=headers, timeout=8)
        if res_web.status_code == 200:
            html = res_web.content.decode('utf-8', errors='ignore')
            if 'const COMMENTS = [' in html:
                part = html.split('const COMMENTS = [')[1].split('];')[0]
                # date:를 기준으로 각 항목 블록 분할
                blocks = part.split('date:')
                for b in blocks[1:]:
                    try:
                        # 날짜 추출: 싱글쿼트 안의 날짜 문자열 (예: '2026년 7월 5일 (토) ...')
                        date_match = re.search(r"'([^']+)'", b)
                        if not date_match:
                            continue
                        date_str = date_match.group(1)
                        
                        # kr: { score: XX, ... } 에서 score 바로 추출 (정확한 정규식)
                        score_match = re.search(r"kr:\s*\{\s*score:\s*(\d+)", b)
                        if score_match:
                            kr_score = int(score_match.group(1))
                            
                            # 날짜 문자열에서 숫자 추출 (년, 월, 일)
                            digits = re.findall(r"\d+", date_str)
                            if len(digits) >= 3:
                                year = int(digits[0])
                                month = int(digits[1])
                                day = int(digits[2])
                                if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                                    dt_norm = pd.to_datetime(f"{year}-{month:02d}-{day:02d}").normalize()
                                    history_records[dt_norm] = float(kr_score)
                    except:
                        pass
    except Exception:
        pass
    
    kospi_df.index = kospi_df.index.normalize()
    today_norm = pd.to_datetime(datetime.date.today()).normalize()
    history_records[today_norm] = float(realtime_score)
    
    # KOSPI 지수 데이터 외에 공포탐욕지수 히스토리 날짜들을 포함하도록 통합 인덱스 생성
    union_index = kospi_df.index.union(pd.DatetimeIndex(list(history_records.keys()))).sort_values()
    
    # 과거 시계열용 VKOSPI 프록시: KOSPI 지수의 20일 역사적 Volatility 산출
    kospi_close = kospi_df['KOSPI']
    returns = kospi_close.pct_change()
    rolling_vol = returns.rolling(20).std() * np.sqrt(252) * 100
    rolling_vol = rolling_vol.ffill().bfill()
    
    # 5. 통합 인덱스 기준으로 공포탐욕지수 시계열 빌드
    # NaN으로 초기화 후 실제 데이터만 삽입 (보간법 제거 - 실제 데이터만 표시)
    fg_series = pd.Series(np.nan, index=union_index, dtype=float)
    for dt_norm, val in history_records.items():
        if dt_norm in fg_series.index:
            fg_series[dt_norm] = val
    
    # 실제 데이터가 있는 날짜 이전은 50.0으로 채우고, 이후는 forward fill (보간 없음)
    # 첫 데이터 날짜 이전은 기본값 50으로 채움
    first_valid = fg_series.first_valid_index()
    if first_valid is not None:
        fg_series.loc[:first_valid] = fg_series.loc[:first_valid].fillna(50.0)
    # 실제 데이터 사이의 빈 날짜는 forward fill (직전 값 유지)
    fg_series = fg_series.ffill().fillna(50.0)
    
    # 통합 DataFrame 빌드
    df_kr = pd.DataFrame(index=union_index)
    df_kr['KOSPI'] = kospi_close.reindex(union_index).ffill().bfill()
    df_kr['FearGreedIndex'] = fg_series
    df_kr['VKOSPI'] = rolling_vol.reindex(union_index).ffill().bfill()
    
    # 최신 날짜의 VKOSPI를 API 실시간 VKOSPI 값으로 업데이트
    latest_valid_idx = df_kr.index[-1]
    df_kr.loc[latest_valid_idx, 'VKOSPI'] = float(realtime_vkospi)
    
    df_kr['(FGI-VIX)/5'] = (df_kr['FearGreedIndex'] - df_kr['VKOSPI']) / 5
    df_kr = df_kr.ffill().bfill()
    
    # 슬로프합 지표 산출
    df_kr_s = df_kr.copy().reset_index()
    df_kr_s.rename(columns={df_kr_s.columns[0]: 'Date'}, inplace=True)
    df_kr_s['Date'] = pd.to_datetime(df_kr_s['Date'])
    df_kr_s = df_kr_s.sort_values('Date').reset_index(drop=True)
    df_kr_s['슬로프'] = df_kr_s['KOSPI'].diff()
    sl_kr = df_kr_s['슬로프'].values
    
    df_kr_s['슬로프5일합'] = slope_sum_lagged(sl_kr, 5)
    df_kr_s['슬로프10일합'] = slope_sum_lagged(sl_kr, 10)
    df_kr_s['슬로프20일합'] = slope_sum_lagged(sl_kr, 20)
    df_kr_s['슬로프40일합'] = slope_sum_lagged(sl_kr, 40)
    
    # KOSPI 기준 상하한 임계값 설정
    df_kr_s['5일상한'] = 30;  df_kr_s['5일하한'] = -30
    df_kr_s['10일상한'] = 50; df_kr_s['10일하한'] = -50
    df_kr_s['20일상한'] = 70; df_kr_s['20일하한'] = -70
    df_kr_s['40일상한'] = 100; df_kr_s['40일하한'] = -100
    
    max_val_kr = float(df_kr_s['KOSPI'].max()) * 1.5
    for days in [5, 10, 20, 40]:
        sc = f'슬로프{days}일합'
        dc = f'{days}일하한'
        diff = df_kr_s[dc] - df_kr_s[sc]
        df_kr_s[f'{days}일_초록'] = np.where((diff >= 0) & (diff < 15), max_val_kr, 0)
        df_kr_s[f'{days}일_주황'] = np.where((diff >= 15) & (diff < 30), max_val_kr, 0)
        df_kr_s[f'{days}일_빨강'] = np.where((diff >= 30) & (diff < 45), max_val_kr, 0)
        df_kr_s[f'{days}일_검정'] = np.where(diff >= 45, max_val_kr, 0)
        
    df_kr_s.set_index('Date', inplace=True)
    return df_kr_s[~df_kr_s.index.duplicated(keep='first')]

# D램 가격 크롤링 및 로컬 DB 적재
DB_FILE = 'dram_price_history.json'

def update_and_get_dram_history():
    history = {}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except:
            pass
            
    scraped_prices = {}
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get('https://www.dramexchange.com', headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for t in soup.find_all('table'):
                for tr in t.find_all('tr'):
                    tds = [td.text.strip() for td in tr.find_all(['td', 'th']) if td.text.strip()]
                    if len(tds) >= 6 and ('DDR' in tds[0] or 'SLC' in tds[0] or 'MLC' in tds[0] or 'MicroSD' in tds[0]):
                        name = tds[0]
                        avg_price_str = tds[5].replace(',', '')
                        try:
                            scraped_prices[name] = float(avg_price_str)
                        except:
                            pass
    except Exception:
        pass
        
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    if scraped_prices:
        history[today_str] = scraped_prices
        try:
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except:
            pass
            
    if not history:
        history[today_str] = scraped_prices if scraped_prices else {
            'DDR4 8Gb (1Gx8) 3200': 3.54,
            'DDR4 16Gb (2Gx8) 3200': 7.375,
            'DDR5 16Gb (2Gx8) 4800/5600': 4.667
        }
        
    records = []
    for dt_str, prices in history.items():
        row = {'Date': pd.to_datetime(dt_str)}
        row.update(prices)
        records.append(row)
        
    df_dram = pd.DataFrame(records).sort_values('Date').set_index('Date')
    return df_dram

with st.spinner('데이터 로딩 중...'):
    df = fetch_and_process_data()
    df_kr = fetch_korean_market_data_v2()
    df_dram = update_and_get_dram_history()

# 탭 구성: 공탐변동 / 슬로프합 / 등락현황
tab_names = ['공탐변동', '슬로프합', '등락현황']
tabs = st.tabs(tab_names)

# ── Tab 1: 공탐변동 ──
with tabs[0]:
    if selected_country == "미국":
        five_years_ago = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
        df1 = df[df.index >= five_years_ago]

        color_cond_map = [
            ((df1['FearGreedIndex']<=9)&(df1['VIX']>=26),                                                          '#595959', '#FFFFFF', 'rgba(0,0,0,0.15)'),
            ((df1['FearGreedIndex']>=10)&(df1['FearGreedIndex']<=19)&(df1['VIX']>=22)&(df1['VIX']<=25),            '#E06666', '#FFFFFF', 'rgba(220,30,30,0.15)'),
            ((df1['FearGreedIndex']>=20)&(df1['FearGreedIndex']<=29)&(df1['VIX']>=18)&(df1['VIX']<=21),            '#FFD700', '#000000', 'rgba(255,220,0,0.15)'),
            ((df1['FearGreedIndex']>=30)&(df1['FearGreedIndex']<=39)&(df1['VIX']>=14)&(df1['VIX']<=17),            '#A9D08E', '#000000', 'rgba(0,128,0,0.15)'),
        ]

        date_color_map = {}
        for cond, bg, fg, _ in reversed(color_cond_map):
            for d in df1[cond].index:
                date_color_map[d] = (bg, fg)
        all_detected_sorted = sorted(date_color_map.keys(), reverse=True)[:50]

        TH_SIG = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;"
        TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
        
        date_cells = "".join([f"<td style='background:{date_color_map[d][0]};color:{date_color_map[d][1]};font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        vix_cells = "".join([f"<td style='background:{date_color_map[d][0]};color:{date_color_map[d][1]};font-weight:bold;{TD_SIG}'>{df1.loc[d, 'VIX']:.2f}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        fgi_cells = "".join([f"<td style='background:{date_color_map[d][0]};color:{date_color_map[d][1]};font-weight:bold;{TD_SIG}'>{df1.loc[d, 'FearGreedIndex']:.1f}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        fv5_cells = "".join([f"<td style='background:{date_color_map[d][0]};color:{date_color_map[d][1]};font-weight:bold;{TD_SIG}'>{df1.loc[d, '(FGI-VIX)/5']:.2f}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        
        st.markdown(
            f"<div style='margin-bottom:0.2rem;'>"
            f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 50개)</span>"
            f"<div style='overflow-x:auto;margin-top:3px;'>"
            f"<table style='border-collapse:collapse;font-size:0.55rem;'>"
            f"<tbody>"
            f"<tr><th style='{TH_SIG}'>날짜</th>{date_cells}</tr>"
            f"<tr><th style='{TH_SIG}'>VIX</th>{vix_cells}</tr>"
            f"<tr><th style='{TH_SIG}'>FGI</th>{fgi_cells}</tr>"
            f"<tr><th style='{TH_SIG}'>FV5</th>{fv5_cells}</tr>"
            f"</tbody>"
            f"</table></div></div>",
            unsafe_allow_html=True
        )

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        for ev in static_historical_events:
            s_d, e_d = parse_period(ev['period'])
            fig.add_vrect(x0=s_d, x1=e_d, fillcolor="gray", opacity=0.3, layer="below", line_width=0,
                          annotation_text=ev['title'], annotation_position="top left", annotation_font_size=9, annotation_font_color="white")
        
        hd1 = [fmt_date_kor(d) for d in df1.index]
        
        fig.add_trace(go.Scatter(x=hd1, y=df1['QQQ'], name='QQQ', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig.add_trace(go.Scatter(x=hd1, y=df1['VIX'], name='VIX', line=dict(color='rgba(0, 0, 255, 0.75)', width=0.5), hovertemplate='VIX: %{y:.2f}<extra></extra>'), secondary_y=True)
        fig.add_trace(go.Scatter(x=hd1, y=df1['FearGreedIndex'], name='FGI', line=dict(color='rgba(128, 0, 128, 0.75)', width=0.5), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
        fig.add_trace(go.Scatter(x=hd1, y=df1['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='rgba(255, 165, 0, 0.75)', width=0.5), hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
        
        # 색깔 감지 그래프 윤곽선 추가: 두께 0.25, 색깔 흰색
        for cond, _bg, _fg, fc in color_cond_map:
            fig.add_trace(go.Bar(
                x=hd1, y=cond.astype(int)*200, 
                marker_color=fc, showlegend=False, hoverinfo='skip',
                marker_line_width=0.25,
                marker_line_color='white'
            ), secondary_y=True)
        
        if active_period_days:
            target_date = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices = [i for i, d in enumerate(df1.index) if d >= pd.to_datetime(target_date)]
            initial_x_range = [detected_indices[0], len(hd1) - 1] if detected_indices else None
            if detected_indices:
                qqq_1y = df1['QQQ'].iloc[detected_indices[0]:]
                q_min, q_max = float(qqq_1y.min()), float(qqq_1y.max())
                qqq_y_range = [q_min * 0.95, q_max * 1.05]
            else:
                qqq_y_range = [float(df1['QQQ'].min()) * 0.95, float(df1['QQQ'].max()) * 1.05]
        else:
            initial_x_range = None
            q_min, q_max = float(df1['QQQ'].min()), float(df1['QQQ'].max())
            qqq_y_range = [q_min * 0.95, q_max * 1.05]

        fig.update_layout(
            **COMMON_LAYOUT, 
            height=320, 
            margin=dict(l=0,r=50,t=30,b=10),
            showlegend=False,
            barmode='overlay',
            bargap=0,
            shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))]
        )
        if initial_x_range:
            fig.update_xaxes(range=initial_x_range, type='category', **crosshair_xaxis())
        else:
            fig.update_xaxes(type='category', **crosshair_xaxis())
            
        fig.update_yaxes(range=qqq_y_range, **crosshair_yaxis(), secondary_y=False)
        fig.update_yaxes(**crosshair_yaxis(range=[-10,120]), secondary_y=True)

        st.plotly_chart(fig, width='stretch', config=COMMON_CONFIG)

        st.markdown("<hr style='margin: 0.3rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)
        st.markdown("#### 📌 역사적 대폭락/하락장 주요 사건 및 하락률")
        
        # 하락률 컬럼이 추가된 역사적 사건 렌더링 (Google RSS 제외)
        rows_html = ""
        for idx, ev in enumerate(static_historical_events):
            rows_html += f"<tr><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>{ev['title']}</td><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>{ev['period']}</td><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;color:#FF6B9D;font-weight:bold;'>{ev['fall_rate']}</td></tr>"
        st.markdown(f"<div style='margin-right: 100px;'><table style='width:100%;border-collapse:collapse;'><thead style='background:#1F4E79;color:white;'><tr><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>사건 내용</th><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>날짜</th><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>하락률</th></tr></thead><tbody>{rows_html}</tbody></table></div>", unsafe_allow_html=True)

    elif selected_country == "한국":
        five_years_ago = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
        df1_kr = df_kr[df_kr.index >= five_years_ago]
        
        color_cond_map_kr = [
            ((df1_kr['FearGreedIndex']<=9)&(df1_kr['VKOSPI']>=26),                                                          '#595959', '#FFFFFF', 'rgba(0,0,0,0.15)'),
            ((df1_kr['FearGreedIndex']>=10)&(df1_kr['FearGreedIndex']<=19)&(df1_kr['VKOSPI']>=22),                          '#E06666', '#FFFFFF', 'rgba(220,30,30,0.15)'),
            ((df1_kr['FearGreedIndex']>=20)&(df1_kr['FearGreedIndex']<=29)&(df1_kr['VKOSPI']>=18),                          '#FFD700', '#000000', 'rgba(255,220,0,0.15)'),
            ((df1_kr['FearGreedIndex']>=30)&(df1_kr['FearGreedIndex']<=39)&(df1_kr['VKOSPI']>=14),                          '#A9D08E', '#000000', 'rgba(0,128,0,0.15)'),
        ]

        date_color_map_kr = {}
        for cond, bg, fg, _ in reversed(color_cond_map_kr):
            for d in df1_kr[cond].index:
                date_color_map_kr[d] = (bg, fg)
        all_detected_sorted_kr = sorted(date_color_map_kr.keys(), reverse=True)[:50]

        TH_SIG = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;"
        TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
        
        date_cells_kr = "".join([f"<td style='background:{date_color_map_kr[d][0]};color:{date_color_map_kr[d][1]};font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        vix_cells_kr = "".join([f"<td style='background:{date_color_map_kr[d][0]};color:{date_color_map_kr[d][1]};font-weight:bold;{TD_SIG}'>{df1_kr.loc[d, 'VKOSPI']:.2f}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        fgi_cells_kr = "".join([f"<td style='background:{date_color_map_kr[d][0]};color:{date_color_map_kr[d][1]};font-weight:bold;{TD_SIG}'>{df1_kr.loc[d, 'FearGreedIndex']:.1f}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        fv5_cells_kr = "".join([f"<td style='background:{date_color_map_kr[d][0]};color:{date_color_map_kr[d][1]};font-weight:bold;{TD_SIG}'>{df1_kr.loc[d, '(FGI-VIX)/5']:.2f}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        
        st.markdown(
            f"<div style='margin-bottom:0.2rem;'>"
            f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 50개)</span>"
            f"<div style='overflow-x:auto;margin-top:3px;'>"
            f"<table style='border-collapse:collapse;font-size:0.55rem;'>"
            f"<tbody>"
            f"<tr><th style='{TH_SIG}'>날짜</th>{date_cells_kr}</tr>"
            f"<tr><th style='{TH_SIG}'>VKOSPI</th>{vix_cells_kr}</tr>"
            f"<tr><th style='{TH_SIG}'>FGI</th>{fgi_cells_kr}</tr>"
            f"<tr><th style='{TH_SIG}'>FV5</th>{fv5_cells_kr}</tr>"
            f"</tbody>"
            f"</table></div></div>",
            unsafe_allow_html=True
        )

        fig_kr = make_subplots(specs=[[{"secondary_y": True}]])
        hd1_kr = [fmt_date_kor(d) for d in df1_kr.index]
        
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['KOSPI'], name='KOSPI', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), hovertemplate='KOSPI: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['VKOSPI'], name='VKOSPI', line=dict(color='rgba(0, 0, 255, 0.75)', width=0.5), hovertemplate='VKOSPI: %{y:.2f}<extra></extra>'), secondary_y=True)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['FearGreedIndex'], name='FGI', line=dict(color='rgba(128, 0, 128, 0.75)', width=0.5), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['(FGI-VIX)/5'], name='(FGI-VKOSPI)/5', line=dict(color='rgba(255, 165, 0, 0.75)', width=0.5), hovertemplate='(FGI-VKOSPI)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
        
        # 한국 색상바 추가 (미국과 동일 양식 설정)
        for cond, _bg, _fg, fc in color_cond_map_kr:
            fig_kr.add_trace(go.Bar(
                x=hd1_kr, y=cond.astype(int)*200, 
                marker_color=fc, showlegend=False, hoverinfo='skip',
                marker_line_width=0.25,
                marker_line_color='white'
            ), secondary_y=True)
            
        if active_period_days:
            target_date_kr = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices_kr = [i for i, d in enumerate(df1_kr.index) if d >= pd.to_datetime(target_date_kr)]
            initial_x_range_kr = [detected_indices_kr[0], len(hd1_kr) - 1] if detected_indices_kr else None
            if detected_indices_kr:
                kospi_1y = df1_kr['KOSPI'].iloc[detected_indices_kr[0]:]
                k_min, k_max = float(kospi_1y.min()), float(kospi_1y.max())
                kospi_y_range = [k_min * 0.95, k_max * 1.05]
            else:
                kospi_y_range = [float(df1_kr['KOSPI'].min()) * 0.95, float(df1_kr['KOSPI'].max()) * 1.05]
        else:
            initial_x_range_kr = None
            k_min, k_max = float(df1_kr['KOSPI'].min()), float(df1_kr['KOSPI'].max())
            kospi_y_range = [k_min * 0.95, k_max * 1.05]

        fig_kr.update_layout(
            **COMMON_LAYOUT, 
            height=320, 
            margin=dict(l=0,r=50,t=30,b=10),
            showlegend=False,
            barmode='overlay',
            bargap=0,
            shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))]
        )
        if initial_x_range_kr:
            fig_kr.update_xaxes(range=initial_x_range_kr, type='category', **crosshair_xaxis())
        else:
            fig_kr.update_xaxes(type='category', **crosshair_xaxis())
            
        fig_kr.update_yaxes(range=kospi_y_range, **crosshair_yaxis(), secondary_y=False)
        fig_kr.update_yaxes(**crosshair_yaxis(range=[-10,120]), secondary_y=True)

        st.plotly_chart(fig_kr, width='stretch', config=COMMON_CONFIG)

        st.markdown("<hr style='margin: 0.3rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)
        st.markdown("#### 📊 D램 Spot 가격 vs 코스피 지수 중첩 추이 (dramexchange.com 실측 데이터)")
        
        # [D램가격 vs 코스피지수] : 코스피 지수가 끊기지 않도록 전체 시계열 매핑 및 Y축 라벨 타이틀 공백 제거
        if not df_dram.empty:
            dram_fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            # X축: 공탐변동 그래프와 완벽히 동일한 기간으로 동기화 (df1_kr의 날짜 인덱스 전체)
            dram_hd = [fmt_date_kor(d) for d in df1_kr.index]
            
            # 코스피 가격: 전체 공탐변동 지수 데이터 적용 (기타 차트와 일치하도록 width: 1.0, color opacity 0.3 적용)
            dram_fig.add_trace(go.Scatter(
                x=dram_hd, y=df1_kr['KOSPI'], name='KOSPI 지수',
                line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                hovertemplate='KOSPI: %{y:.2f}<extra></extra>'
            ), secondary_y=False)
            
            # D램 Spot 가격: 해당 날짜에 맞는 DRAM Spot 가격 데이터를 reindex하여 가져오고 ffill/bfill 보간
            df_dram_reindexed = df_dram.reindex(df1_kr.index).ffill().bfill()
            
            dram_types = ['DDR4 8Gb (1Gx8) 3200', 'DDR4 16Gb (2Gx8) 3200', 'DDR5 16Gb (2Gx8) 4800/5600']
            # 각 DRAM 가격선도 메인 차트의 보조 지표들처럼 연하고 가늘게 설정 (width: 0.5, 선명도 조절)
            colors = ['rgba(255, 215, 0, 0.45)', 'rgba(255, 107, 157, 0.45)', 'rgba(51, 153, 255, 0.45)']
            
            for d_type, col in zip(dram_types, colors):
                if d_type in df_dram_reindexed.columns:
                    dram_fig.add_trace(go.Scatter(
                        x=dram_hd, y=df_dram_reindexed[d_type], name=d_type,
                        line=dict(color=col, width=0.5),
                        hovertemplate=f'{d_type}: %{{y:.3f}}<extra></extra>'
                    ), secondary_y=True)
            
            dram_fig.update_layout(
                **COMMON_LAYOUT,
                height=300,
                margin=dict(l=0,r=50,t=30,b=10),
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                ),
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))]
            )
            
            # Y축 제목 공백 제거(기타 그래프들과 통일)
            if initial_x_range_kr:
                dram_fig.update_xaxes(range=initial_x_range_kr, type='category', **crosshair_xaxis())
            else:
                dram_fig.update_xaxes(type='category', **crosshair_xaxis())
            dram_fig.update_yaxes(**crosshair_yaxis(), secondary_y=False)
            dram_fig.update_yaxes(**crosshair_yaxis(), secondary_y=True)
            
            st.plotly_chart(dram_fig, width='stretch', config=COMMON_CONFIG)
        else:
            st.info("수집된 D램 Spot 가격 데이터가 없습니다.")

# ── Tab 2: 슬로프합 ──
with tabs[1]:
    if selected_country == "미국":
        all_fd = []
        for days_t in [5, 10, 20, 40]:
            dfc = f'{days_t}일하한'
            sfc = f'슬로프{days_t}일합'
            all_fd.extend(df[df[dfc]-df[sfc]>=0].index.tolist())
        dc_top = Counter(all_fd)
        parent_dates = sorted(list(set(all_fd)), reverse=True)
        
        if parent_dates:
            r30 = parent_dates[:30]
            dates_row = []
            counts_row = []
            for dt in r30:
                cnt = dc_top.get(dt, 1)
                bg = "#595959" if cnt==4 else "#E06666" if cnt==3 else "#FFD700" if cnt==2 else "#A9D08E"
                fg = "#FFF" if cnt>=3 else "#000"
                dates_row.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                
                detected = []
                for days in [5, 10, 20, 40]:
                    dc_col = f'{days}일하한'
                    sc_col = f'슬로프{days}일합'
                    val_diff = df.loc[dt, dc_col] - df.loc[dt, sc_col]
                    if val_diff >= 0:
                        if 0 <= val_diff < 10:
                            color = '#A9D08E'
                        elif 10 <= val_diff < 20:
                            color = '#FFD700'
                        elif 20 <= val_diff < 30:
                            color = '#E06666'
                        else:
                            color = '#595959'
                        detected.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                    else:
                        detected.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                
                val_str = "<br>".join(detected)
                counts_row.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{val_str}</td>")
            
            top_html_transposed = f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 30개)</span>
            <table style='border-collapse:collapse;margin-top:3px;'>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                    {"".join(dates_row)}
                </tr>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>이탈</th>
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
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=rn,col=1,secondary_y=False)
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(0, 0, 255, 0.75)',width=0.5),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=rn,col=1,secondary_y=True)
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[uc],name='상한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='upper',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[dc],name='하한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='lower',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            
            for cn, fc in [(gc,'rgba(76,175,80,0.15)'),(oc,'rgba(255,220,0,0.15)'),(rc,'rgba(220,30,30,0.15)'),(bc,'rgba(0,0,0,0.15)')]:
                fig_dsi.add_trace(go.Bar(
                    x=hd_df, y=df[cn], marker_color=fc, showlegend=False, hoverinfo='skip',
                    marker_line_width=0.25,
                    marker_line_color='white'
                ),row=rn,col=1,secondary_y=False)
        
        if active_period_days:
            target_date_dsi = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices_dsi = [i for i, d in enumerate(df.index) if d >= pd.to_datetime(target_date_dsi)]
            initial_x_range_dsi = [detected_indices_dsi[0], len(hd_df) - 1] if detected_indices_dsi else None
            if detected_indices_dsi:
                qqq_1y_dsi = df['QQQ'].iloc[detected_indices_dsi[0]:]
                qmin_dsi, qmax_dsi = float(qqq_1y_dsi.min()), float(qqq_1y_dsi.max())
            else:
                qmin_dsi, qmax_dsi = float(df['QQQ'].min()), float(df['QQQ'].max())
        else:
            initial_x_range_dsi = None
            qmin_dsi, qmax_dsi = float(df['QQQ'].min()), float(df['QQQ'].max())

        layout_params = COMMON_LAYOUT.copy()
        layout_params.pop('shapes', None)
        fig_dsi.update_layout(
            **layout_params, 
            height=1200, 
            margin=dict(l=0,r=50,t=30,b=10),
            showlegend=False,
            barmode='overlay',
            bargap=0,
            shapes=[
                dict(type="rect", xref="paper", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                dict(type="rect", xref="paper", yref="y3 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                dict(type="rect", xref="paper", yref="y5 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                dict(type="rect", xref="paper", yref="y7 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5))
            ]
        )
        for i in range(1, 5):
            fig_dsi.update_yaxes(range=[qmin_dsi*0.95,qmax_dsi*1.05],**crosshair_yaxis(),secondary_y=False,row=i,col=1)
            fig_dsi.update_yaxes(range=[-120,180],tick0=-120,dtick=20,**crosshair_yaxis(),secondary_y=True,row=i,col=1)
        
        if initial_x_range_dsi:
            fig_dsi.update_xaxes(range=initial_x_range_dsi, type='category', **crosshair_xaxis())
        else:
            fig_dsi.update_xaxes(type='category', **crosshair_xaxis())
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

        if sel == '종합':
            uds = sorted(list(set(all_fd2)), reverse=True)
            if uds:
                rh = ""
                for dt in uds:
                    cnt = dcnt.get(dt, 1); bg, fg = color_bg(cnt)
                    rh += f"<tr><td style='background:{bg};color:{fg};font-weight:bold;{TD}'>{fmt_date_kor(dt)}</td><td style='background:{bg};color:{fg};{TD}'></td><td style='background:{bg};color:{fg};{TD}'></td></tr>"
                st.markdown(f"<div style='max-height:400px;overflow-y:auto;margin-top:4px;margin-right:100px;'><table style='{TS}'><thead><tr style='background:#1F4E79;color:white;position:sticky;top:0;'><th style='{TH}'>날짜</th><th style='{TH}'>색깔</th><th style='{TH}'>차이</th></tr></thead><tbody>{rh}</tbody></table></div>", unsafe_allow_html=True)
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
                st.markdown(f"<div style='max-height:400px;overflow-y:auto;margin-top:4px;margin-right:100px;'><table style='{TS}'><thead><tr style='background:#1F4E79;color:white;position:sticky;top:0;'><th style='{TH}'>날짜</th><th style='{TH}'>색깔</th><th style='{TH}'>차이</th></tr></thead><tbody>{rh}</tbody></table></div>", unsafe_allow_html=True)
            else:
                st.info("하한을 하회하는 이탈 신호 데이터가 없습니다.")

    elif selected_country == "한국":
        all_fd_kr = []
        for days_t in [5, 10, 20, 40]:
            dfc = f'{days_t}일하한'
            sfc = f'슬로프{days_t}일합'
            all_fd_kr.extend(df_kr[df_kr[dfc]-df_kr[sfc]>=0].index.tolist())
        dc_top_kr = Counter(all_fd_kr)
        parent_dates_kr = sorted(list(set(all_fd_kr)), reverse=True)
        
        if parent_dates_kr:
            r30_kr = parent_dates_kr[:30]
            dates_row_kr = []
            counts_row_kr = []
            for dt in r30_kr:
                cnt = dc_top_kr.get(dt, 1)
                bg = "#595959" if cnt==4 else "#E06666" if cnt==3 else "#FFD700" if cnt==2 else "#A9D08E"
                fg = "#FFF" if cnt>=3 else "#000"
                dates_row_kr.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                
                detected = []
                for days in [5, 10, 20, 40]:
                    dc_col = f'{days}일하한'
                    sc_col = f'슬로프{days}일합'
                    val_diff = df_kr.loc[dt, dc_col] - df_kr.loc[dt, sc_col]
                    if val_diff >= 0:
                        if 0 <= val_diff < 15:
                            color = '#A9D08E'
                        elif 15 <= val_diff < 30:
                            color = '#FFD700'
                        elif 30 <= val_diff < 45:
                            color = '#E06666'
                        else:
                            color = '#595959'
                        detected.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                    else:
                        detected.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                
                val_str = "<br>".join(detected)
                counts_row_kr.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{val_str}</td>")
            
            top_html_transposed_kr = f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 30개)</span>
            <table style='border-collapse:collapse;margin-top:3px;'>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                    {"".join(dates_row_kr)}
                </tr>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>이탈</th>
                    {"".join(counts_row_kr)}
                </tr>
            </table>
            </div>
            """
            st.markdown(top_html_transposed_kr, unsafe_allow_html=True)

        fig_dsi_kr = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
            subplot_titles=('슬로프 5일합','슬로프 10일합','슬로프 20일합','슬로프 40일합'),
            specs=[[{"secondary_y": True}]]*4)
            
        CHARTS_KR = [
            (1, 5,  '5일상한',  '5일하한',  '슬로프5일합',  '5일_초록',  '5일_주황',  '5일_빨강',  '5일_검정'),
            (2, 10, '10일상한', '10일하한', '슬로프10일합', '10일_초록', '10일_주황', '10일_빨강', '10일_검정'),
            (3, 20, '20일상한', '20일하한', '슬로프20일합', '20일_초록', '20일_주황', '20일_빨강', '20일_검정'),
            (4, 40, '40일상한', '40일하한', '슬로프40일합', '40일_초록', '40일_주황', '40일_빨강', '40일_검정'),
        ]
        hd_df_kr = [fmt_date_kor(d) for d in df_kr.index]
        for rn, days, uc, dc, sc, gc, oc, rc, bc in CHARTS_KR:
            sf = (rn == 1)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr['KOSPI'],name='KOSPI 가격',line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),showlegend=sf,legendgroup='kospi',hovertemplate='KOSPI: %{y:.2f}<extra></extra>'),row=rn,col=1,secondary_y=False)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(0, 0, 255, 0.75)',width=0.5),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=rn,col=1,secondary_y=True)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[uc],name='상한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='upper_kr',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[dc],name='하한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='lower_kr',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            
            for cn, fc in [(gc,'rgba(76,175,80,0.15)'),(oc,'rgba(255,220,0,0.15)'),(rc,'rgba(220,30,30,0.15)'),(bc,'rgba(0,0,0,0.15)')]:
                fig_dsi_kr.add_trace(go.Bar(
                    x=hd_df_kr, y=df_kr[cn], marker_color=fc, showlegend=False, hoverinfo='skip',
                    marker_line_width=0.25,
                    marker_line_color='white'
                ),row=rn,col=1,secondary_y=False)
                
        if active_period_days:
            target_date_dsi_kr = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices_dsi_kr = [i for i, d in enumerate(df_kr.index) if d >= pd.to_datetime(target_date_dsi_kr)]
            initial_x_range_dsi_kr = [detected_indices_dsi_kr[0], len(hd_df_kr) - 1] if detected_indices_dsi_kr else None
            if detected_indices_dsi_kr:
                kospi_1y_dsi = df_kr['KOSPI'].iloc[detected_indices_dsi_kr[0]:]
                kmin_dsi, kmax_dsi = float(kospi_1y_dsi.min()), float(kospi_1y_dsi.max())
            else:
                kmin_dsi, kmax_dsi = float(df_kr['KOSPI'].min()), float(df_kr['KOSPI'].max())
        else:
            initial_x_range_dsi_kr = None
            kmin_dsi, kmax_dsi = float(df_kr['KOSPI'].min()), float(df_kr['KOSPI'].max())

        layout_params_kr = COMMON_LAYOUT.copy()
        layout_params_kr.pop('shapes', None)
        fig_dsi_kr.update_layout(
            **layout_params_kr, 
            height=1200, 
            margin=dict(l=0,r=50,t=30,b=10),
            showlegend=False,
            barmode='overlay',
            bargap=0,
            shapes=[
                dict(type="rect", xref="paper", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                dict(type="rect", xref="paper", yref="y3 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                dict(type="rect", xref="paper", yref="y5 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                dict(type="rect", xref="paper", yref="y7 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5))
            ]
        )
        for i in range(1, 5):
            fig_dsi_kr.update_yaxes(range=[kmin_dsi*0.95,kmax_dsi*1.05],**crosshair_yaxis(),secondary_y=False,row=i,col=1)
            fig_dsi_kr.update_yaxes(range=[-150,220],tick0=-150,dtick=30,**crosshair_yaxis(),secondary_y=True,row=i,col=1)
            
        if initial_x_range_dsi_kr:
            fig_dsi_kr.update_xaxes(range=initial_x_range_dsi_kr, type='category', **crosshair_xaxis())
        else:
            fig_dsi_kr.update_xaxes(type='category', **crosshair_xaxis())
        fig_dsi_kr.update_annotations(font_size=10)

        st.plotly_chart(fig_dsi_kr, width='stretch', config=COMMON_CONFIG)

        st.markdown("#### 하한 미만 세부 분석 표")
        all_fd2_kr = []
        for days in [5, 10, 20, 40]:
            dc2 = f'{days}일하한'
            sc2 = f'슬로프{days}일합'
            all_fd2_kr.extend(df_kr[df_kr[dc2]-df_kr[sc2]>=0].index.tolist())
        dcnt_kr = Counter(all_fd2_kr)
        sel_kr = st.selectbox('기간 선택 (한국)', ['종합', 5, 10, 20, 40], format_func=lambda x: f'{x}일합' if isinstance(x, int) else x)

        if sel_kr == '종합':
            uds_kr = sorted(list(set(all_fd2_kr)), reverse=True)
            if uds_kr:
                rh = ""
                for dt in uds_kr:
                    cnt = dcnt_kr.get(dt, 1); bg, fg = color_bg(cnt)
                    rh += f"<tr><td style='background:{bg};color:{fg};font-weight:bold;{TD}'>{fmt_date_kor(dt)}</td><td style='background:{bg};color:{fg};{TD}'></td><td style='background:{bg};color:{fg};{TD}'></td></tr>"
                st.markdown(f"<div style='max-height:400px;overflow-y:auto;margin-top:4px;margin-right:100px;'><table style='{TS}'><thead><tr style='background:#1F4E79;color:white;position:sticky;top:0;'><th style='{TH}'>날짜</th><th style='{TH}'>색깔</th><th style='{TH}'>차이</th></tr></thead><tbody>{rh}</tbody></table></div>", unsafe_allow_html=True)
            else:
                st.info("하한을 하회하는 이탈 신호 데이터가 없습니다.")
        else:
            dc3 = f'{sel_kr}일하한'; sc3 = f'슬로프{sel_kr}일합'
            dff_kr = df_kr[df_kr[dc3]-df_kr[sc3]>=0].copy()
            dff_kr['차이'] = dff_kr[dc3]-dff_kr[sc3]
            dff_kr = dff_kr.sort_index(ascending=False)
            if len(dff_kr) > 0:
                rh = ""
                for dt, row in dff_kr.iterrows():
                    dv = row['차이']
                    cn, bh, fh = ('초록','#A9D08E','#000') if 0<=dv<15 else ('노랑','#FFD700','#000') if 15<=dv<30 else ('빨강','#E06666','#FFF') if 30<=dv<45 else ('검정','#595959','#FFF')
                    cnt = dcnt_kr.get(dt, 1); bg, fg = color_bg(cnt)
                    rh += f"<tr><td style='background:{bg};color:{fg};font-weight:bold;{TD}'>{fmt_date_kor(dt)}</td><td style='background:{bh};color:{fh};font-weight:bold;{TD}'>{cn}</td><td style='{TD}'>{dv:.1f}</td></tr>"
                st.markdown(f"<div style='max-height:400px;overflow-y:auto;margin-top:4px;margin-right:100px;'><table style='{TS}'><thead><tr style='background:#1F4E79;color:white;position:sticky;top:0;'><th style='{TH}'>날짜</th><th style='{TH}'>색깔</th><th style='{TH}'>차이</th></tr></thead><tbody>{rh}</tbody></table></div>", unsafe_allow_html=True)
            else:
                st.info("하한을 하회하는 이탈 신호 데이터가 없습니다.")

# ── Tab 3: 등락현황 ──
with tabs[2]:
    st.markdown("### 국내외 증시 등락 현황")
    with st.spinner("국내외 등락현황 데이터를 가져오는 중..."):
        kp_s, kd_s = fetch_korean_market_status()
        ndx_s = fetch_nasdaq100_status()
        kp_b, kd_b, ndx_b = fetch_historical_breadth()
        kp_p, kd_p, qqq_p = fetch_index_prices()
    
    CM = {'상한가':'#CC0000','상승':'#FF6B9D','보합':'#DDDDDD','하락':'#87CEEB','하한가':'#3399FF'}
    
    def build_table_transposed_kr(sd, title):
        cols_headers = []
        cols_values = []
        for k in ['상한가','상승','보합','하락','하한가']:
            c = CM.get(k, '#FFF')
            cols_headers.append(f"<th style='padding:2px 6px;border:1px solid #444;color:white;background:#1F4E79;text-align:center;'>{k}</th>")
            cols_values.append(f"<td style='padding:2px 6px;border:1px solid #444;font-weight:bold;color:{c};text-align:center;'>{sd.get(k,'0')}</td>")
        return f"""
        <div style='margin-bottom: 0.2rem;'>
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
            cols_headers.append(f"<th style='padding:2px 6px;border:1px solid #444;color:white;background:#1F4E79;text-align:center;'>{k}</th>")
            cols_values.append(f"<td style='padding:2px 6px;border:1px solid #444;font-weight:bold;color:{c};text-align:center;'>{sd.get(k,'0')}</td>")
        return f"""
        <div style='margin-bottom: 0.2rem;'>
            <span style='font-size:0.75rem; font-weight:600;'>{title}</span>
            <table style='border-collapse:collapse;width:100%;margin-top:2px;'>
                <tr>{"".join(cols_headers)}</tr>
                <tr>{"".join(cols_values)}</tr>
            </table>
        </div>
        """

    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        st.markdown(build_table_transposed_kr(kp_s, "🇰🇷 코스피 등락 현황 (당일)"), unsafe_allow_html=True)
    with c2:
        st.markdown(build_table_transposed_kr(kd_s, "🇰🇷 코스닥 등락 현황 (당일)"), unsafe_allow_html=True)
    with c3:
        st.markdown(build_table_transposed_us(ndx_s, "🇺🇸 나스닥 100 등락 현황 (당일 - 상하한가 제외)"), unsafe_allow_html=True)
        
    st.markdown("<hr style='margin: 0.3rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)
    st.markdown("### 📈 대표 종목 기준 등락현황 시계열 추이 (최근 90영업일)")
    
    def make_line_fig(df_b, title, ps=None, pname="지수", is_us=False):
        fig = make_subplots(subplot_titles=(title,), specs=[[{"secondary_y": True}]])
        if not df_b.empty:
            dfp = df_b.copy()
            dfp.index = pd.to_datetime(dfp.index)
            hd = [fmt_date_kor(d) for d in dfp.index]
            
            if is_us:
                configs = [
                    ('상승','rgba(255, 107, 157, 0.1)','상승'),
                    ('보합','rgba(170, 170, 170, 0.3)','보합'),
                    ('하락','rgba(135, 206, 235, 0.1)','하락')
                ]
            else:
                configs = [
                    ('상한가','rgba(204, 0, 0, 0.5)','상한가'),
                    ('상승','rgba(255, 107, 157, 0.1)','상승'),
                    ('보합','rgba(170, 170, 170, 0.3)','보합'),
                    ('하락','rgba(135, 206, 235, 0.1)','하락'),
                    ('하한가','rgba(51, 153, 255, 0.5)','하한가')
                ]
                
            for cn, color, ln in configs:
                if cn in dfp.columns:
                    fig.add_trace(go.Scatter(
                        x=hd,
                        y=dfp[cn],
                        mode='lines',
                        name=ln,
                        line=dict(color=color, width=0.5),
                        fill='tozeroy',  
                        hovertemplate=f'{ln}: %{{y}}<extra></extra>'
                    ), secondary_y=False)
                    
            if ps is not None and len(ps) > 0:
                pf = ps[ps.index >= dfp.index.min()].tail(90)
                fig.add_trace(go.Scatter(
                    x=hd,
                    y=pf.values,
                    mode='lines',
                    name=pname,
                    line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),  
                    hovertemplate=f'{pname}: %{{y:.2f}}<extra></extra>'
                ), secondary_y=True)
                
        if active_period_days:
            target_date_3 = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices_3 = [i for i, d in enumerate(dfp.index) if d >= pd.to_datetime(target_date_3)]
            if detected_indices_3:
                initial_x_range_3 = [detected_indices_3[0], len(hd) - 1]
            else:
                initial_x_range_3 = None
        else:
            initial_x_range_3 = None

        fig.update_layout(
            **COMMON_LAYOUT,
            height=300, 
            margin=dict(l=0, r=50, t=30, b=10),
            showlegend=False,
            shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))]
        )
        if initial_x_range_3:
            fig.update_xaxes(range=initial_x_range_3, type='category', **crosshair_xaxis())
        else:
            fig.update_xaxes(type='category', **crosshair_xaxis())
            
        fig.update_yaxes(**crosshair_yaxis(), secondary_y=False)
        fig.update_yaxes(**crosshair_yaxis(), secondary_y=True)
        fig.update_annotations(font_size=10)
        return fig
        
    st.plotly_chart(make_line_fig(kp_b,"코스피 대표 종목 등락현황 추이 (영역형)",kp_p,"코스피", is_us=False),width='stretch',config=COMMON_CONFIG)
    st.plotly_chart(make_line_fig(kd_b,"코스닥 대표 종목 등락현황 추이 (영역형)",kd_p,"코스닥", is_us=False),width='stretch',config=COMMON_CONFIG)
    st.plotly_chart(make_line_fig(ndx_b,"나스닥 100 대표 종목 등락현황 추이 (영역형 - 상하한 제외)",qqq_p,"QQQ", is_us=True),width='stretch',config=COMMON_CONFIG)
