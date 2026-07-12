# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import requests
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
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

# Page configuration
st.set_page_config(page_title="Market Trends Dashboard", layout="wide", initial_sidebar_state="collapsed")

KOR_WEEKDAY = ['월', '화', '수', '목', '금', '토', '일']

def calculate_indicator_stats(df_target, price_col, conditions, window=41, dd_threshold=0.05, local_min_factor=1.03):
    """
    지표의 역사적 저점 적중률, 포착률, 종합 점수를 실시간으로 계산하는 헬퍼 함수
    """
    if df_target.empty or price_col not in df_target.columns:
        return []
    
    # 1) 252일 최고점 대비 낙폭이 dd_threshold 이상인 구간
    rolling_max = df_target[price_col].rolling(252, min_periods=1).max()
    drawdown = (rolling_max - df_target[price_col]) / rolling_max
    
    # 2) 로컬 최저점: 현재 가격이 전후 window일(center=True) 기준 최저가격의 local_min_factor 이내
    local_min = df_target[price_col].rolling(window, center=True, min_periods=1).min()
    is_bottom = (df_target[price_col] <= local_min * local_min_factor) & (drawdown >= dd_threshold)
    
    total_bottoms = is_bottom.sum()
    
    stats_list = []
    for name, (cond, desc) in conditions.items():
        cond_bool = cond.reindex(df_target.index).fillna(False).astype(bool)
        total_triggered = int(cond_bool.sum())
        hit_triggered = int((cond_bool & is_bottom).sum())
        
        hit_rate = (hit_triggered / total_triggered * 100) if total_triggered > 0 else 0.0
        recall = (hit_triggered / total_bottoms * 100) if total_bottoms > 0 else 0.0
        score = (2 * hit_rate * recall) / (hit_rate + recall) if (hit_rate + recall) > 0 else 0.0
        
        stats_list.append({
            "name": name,
            "desc": desc,
            "triggered": f"{total_triggered}회",
            "hit_rate": f"**{hit_rate:.1f}%**" if hit_rate >= 40 else f"{hit_rate:.1f}%",
            "recall": f"{recall:.1f}%",
            "score": f"{score:.1f}%"
        })
    return stats_list

def render_stats_table(stats_list, title):
    st.markdown(f"#### 📊 {title}")
    tbl_md = """
| 감지 조건 | 조건 세부 내용 | 발생 횟수 | 저점 적중 (Hit Rate) | 저점 포착 (Recall) | 종합 점수 |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
    for item in stats_list:
        tbl_md += f"| {item['name']} | {item['desc']} | {item['triggered']} | {item['hit_rate']} | {item['recall']} | {item['score']} |\n"
    st.markdown(tbl_md)

def calculate_top_stats(df_target, price_col, conditions, window=41, ru_threshold=0.10, local_max_factor=0.97):
    """
    지표의 역사적 고점 적중률, 포착률, 종합 점수를 실시간으로 계산하는 헬퍼 함수
    - 252일 최저점 대비 상승률(Rally-Up) >= ru_threshold인 구간
    - 로컬 최고점: 전후 window일 기준 최고가격의 local_max_factor 이내
    """
    if df_target.empty or price_col not in df_target.columns:
        return []
    
    # 1) 252일 최저점 대비 상승률(Rally-Up)
    rolling_min = df_target[price_col].rolling(252, min_periods=1).min()
    rally_up = (df_target[price_col] - rolling_min) / (rolling_min + 1e-10)
    
    # 2) 로컬 최고점: 현재 가격이 전후 window일 기준 최고가격의 local_max_factor 이상
    local_max = df_target[price_col].rolling(window, center=True, min_periods=1).max()
    is_top = (df_target[price_col] >= local_max * local_max_factor) & (rally_up >= ru_threshold)
    
    total_tops = is_top.sum()
    
    stats_list = []
    for name, (cond, desc) in conditions.items():
        cond_bool = cond.reindex(df_target.index).fillna(False).astype(bool)
        total_triggered = int(cond_bool.sum())
        hit_triggered = int((cond_bool & is_top).sum())
        
        hit_rate = (hit_triggered / total_triggered * 100) if total_triggered > 0 else 0.0
        recall = (hit_triggered / total_tops * 100) if total_tops > 0 else 0.0
        score = (2 * hit_rate * recall) / (hit_rate + recall) if (hit_rate + recall) > 0 else 0.0
        
        stats_list.append({
            "name": name,
            "desc": desc,
            "triggered": f"{total_triggered}회",
            "hit_rate": f"**{hit_rate:.1f}%**" if hit_rate >= 40 else f"{hit_rate:.1f}%",
            "recall": f"{recall:.1f}%",
            "score": f"{score:.1f}%"
        })
    return stats_list

def render_top_stats_table(stats_list, title):
    st.markdown(f"#### 📊 {title}")
    tbl_md = """
| 감지 조건 | 조건 세부 내용 | 발생 횟수 | 고점 적중 (Hit Rate) | 고점 포착 (Recall) | 종합 점수 |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
    for item in stats_list:
        tbl_md += f"| {item['name']} | {item['desc']} | {item['triggered']} | {item['hit_rate']} | {item['recall']} | {item['score']} |\n"
    st.markdown(tbl_md)

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
    # 모바일 환경 대응 라디오 버튼 크기/간격 축소 CSS 주입
    st.markdown("""
    <style>
        div[data-testid="stRadio"] > div {
            gap: 2px !important;
        }
        div[data-testid="stRadio"] label {
            font-size: 0.75rem !important;
            padding: 2px 6px !important;
            margin-right: 2px !important;
        }
        div[data-testid="stRadio"] label div[data-testid="stMarkdownContainer"] p {
            font-size: 0.75rem !important;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Period Selection (1m, 3m, 6m, 12m, 24m, 48m 순서 정렬)
    selected_period = st.radio(
        "Period",
        options=["1M", "3M", "6M", "12M", "24M", "48M"],
        index=2, # "6M" 기본값
        horizontal=True,
        label_visibility="collapsed",
        key="period_radio"
    )

active_period_days = None
if selected_period == "48M": active_period_days = 1460
elif selected_period == "24M": active_period_days = 730
elif selected_period == "12M": active_period_days = 365
elif selected_period == "6M": active_period_days = 182
elif selected_period == "3M": active_period_days = 91
elif selected_period == "1M": active_period_days = 30

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
    template="plotly_white",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    dragmode=False,
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="rgba(0,0,0,0.1)",
        font_size=10,
        font_family="sans-serif",
        font_color="black"
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

@st.cache_data(ttl=1800)
def fetch_dram_dashboard_data():
    url = "https://moneyland.co.kr/moneyweb/api/dram_dashboard.json"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        return None

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
        ndx_tickers = ['MSFT','AAPL','NVDA','AMZN','META','GOOGL','GOOG','TSLA','AVGO','PEP','COST','AZN','CSCO','AMD','TMUS','QCOM','INTC','TXN','AMGN','INTU','ISRG','HON','AMAT','BKNG','ADP','MDLZ','GILD','ADI','LRCX','REGN','VRTX','MU','PANW','SBUX','KLAC','SNPS','CDNS','MRVL','NFLX','ORLY','ABNB','CTAS','PYPL','ASML','KDP','ROST','MNST','PAYX','FTNT','MCHP','DXCM','EXC','BIIB','IDXX','CPRT','VRSK','PCAR','ODFL','CSGP','CHTR','CEG','ANSS','TEAM','FAST','GEHC','ON','ILMN','EA','FANG','DLTR','NXPI','WDAY','MRNA','ALGN','DDOG','APP','CRWD','CDW','CTSH','ADSK','ROP','XEL','KHC','EBAY']
        _df = yf.download(ndx_tickers, period='10d', progress=False)
        data = _df['Close'] if not _df.empty and 'Close' in _df.columns else pd.DataFrame(columns=ndx_tickers)
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
            _df = yf.download(tickers, period='130d', progress=False)
            df_p = _df['Close'] if not _df.empty and 'Close' in _df.columns else pd.DataFrame(columns=tickers)
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
            _df = yf.download(tickers, period='130d', progress=False)
            df_p = _df['Close'] if not _df.empty and 'Close' in _df.columns else pd.DataFrame(columns=tickers)
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
            df = yf.download(ticker, period='130d', progress=False)
            s = df['Close'] if not df.empty and 'Close' in df.columns else pd.Series()
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
    qqq_df = qqq[['Close']].rename(columns={'Close': 'QQQ'}) if not qqq.empty and 'Close' in qqq.columns else pd.DataFrame(columns=['QQQ'])
    vix = yf.download('^VIX', start=start_date_str, progress=False)
    if isinstance(vix.columns, pd.MultiIndex): vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[['Close']].rename(columns={'Close': 'VIX'}) if not vix.empty and 'Close' in vix.columns else pd.DataFrame(columns=['VIX'])
    
    # 신규 추가: TNX (10년물 국채 금리), HYG (하이일드 채권 ETF)
    tnx = yf.download('^TNX', start=start_date_str, progress=False)
    if isinstance(tnx.columns, pd.MultiIndex): tnx.columns = tnx.columns.get_level_values(0)
    tnx_df = tnx[['Close']].rename(columns={'Close': 'TNX'}) if not tnx.empty and 'Close' in tnx.columns else pd.DataFrame(columns=['TNX'])
    
    hyg = yf.download('HYG', start=start_date_str, progress=False)
    if isinstance(hyg.columns, pd.MultiIndex): hyg.columns = hyg.columns.get_level_values(0)
    hyg_df = hyg[['Close']].rename(columns={'Close': 'HYG'}) if not hyg.empty and 'Close' in hyg.columns else pd.DataFrame(columns=['HYG'])
    
    # 2차 탐색을 위한 SKEW 및 VVIX 데이터 추가 다운로드
    skew = yf.download('^SKEW', start=start_date_str, progress=False)
    if isinstance(skew.columns, pd.MultiIndex): skew.columns = skew.columns.get_level_values(0)
    skew_df = skew[['Close']].rename(columns={'Close': 'SKEW'}) if not skew.empty and 'Close' in skew.columns else pd.DataFrame(columns=['SKEW'])
    
    vvix = yf.download('^VVIX', start=start_date_str, progress=False)
    if isinstance(vvix.columns, pd.MultiIndex): vvix.columns = vvix.columns.get_level_values(0)
    vvix_df = vvix[['Close']].rename(columns={'Close': 'VVIX'}) if not vvix.empty and 'Close' in vvix.columns else pd.DataFrame(columns=['VVIX'])
    
    # 2차 탐색 안전자산 대피 계산을 위한 TLT 다운로드 추가
    tlt = yf.download('TLT', start=start_date_str, progress=False)
    if isinstance(tlt.columns, pd.MultiIndex): tlt.columns = tlt.columns.get_level_values(0)
    tlt_df = tlt[['Close']].rename(columns={'Close': 'TLT'}) if not tlt.empty and 'Close' in tlt.columns else pd.DataFrame(columns=['TLT'])

    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2018-10-01"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    backup_file = "cnn_fgi_backup.json"
    data = None
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200:
            res = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-10-01", headers=headers, timeout=5)
            res.raise_for_status()
        res_json = res.json()
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(res_json, f)
        data = res_json['fear_and_greed_historical']['data']
    except Exception as e:
        if os.path.exists(backup_file):
            try:
                with open(backup_file, 'r', encoding='utf-8') as f:
                    res_json = json.load(f)
                data = res_json['fear_and_greed_historical']['data']
            except Exception:
                pass
        if not data:
            data = [{'x': int(datetime.datetime.now().timestamp()*1000), 'y': 50.0}]
            
    qqq_df.index = qqq_df.index.normalize()
    vix_df.index = vix_df.index.normalize()
    fg_df = pd.DataFrame(data)
    fg_df['Date'] = pd.to_datetime(fg_df['x'], unit='ms').dt.normalize()
    fg_df = fg_df.set_index('Date').rename(columns={'y': 'FearGreedIndex'})[['FearGreedIndex']]
    fg_df = fg_df[~fg_df.index.duplicated(keep='last')]
    
    # 조인
    df = qqq_df.join(vix_df, how='outer')\
               .join(tnx_df, how='outer')\
               .join(hyg_df, how='outer')\
               .join(tlt_df, how='outer')\
               .join(skew_df, how='outer')\
               .join(vvix_df, how='outer')\
               .join(fg_df, how='outer')\
               .ffill().bfill()
    df = df.reindex(qqq_df.index)
    
    # 고급 보조지표 실시간 연산 추가
    # 1) QQQ RSI (14일)
    delta = df['QQQ'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-10)
    df['QQQ_RSI'] = 100 - (100 / (1 + rs))
    
    # QQQ RSI (7일)
    gain7 = (delta.where(delta > 0, 0)).rolling(window=7).mean()
    loss7 = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
    rs7 = gain7 / (loss7 + 1e-10)
    df['QQQ_RSI7'] = 100 - (100 / (1 + rs7))
    
    # 2) QQQ 볼린저 밴드 %B (20일)
    ma20 = df['QQQ'].rolling(20).mean()
    std20 = df['QQQ'].rolling(20).std()
    df['QQQ_%B'] = (df['QQQ'] - (ma20 - 2 * std20)) / (4 * std20 + 1e-10)
    
    # 3) VIX Z-score (200일 기준)
    vix_ma200 = df['VIX'].rolling(200).mean()
    vix_std200 = df['VIX'].rolling(200).std()
    df['VIX_Z'] = (df['VIX'] - vix_ma200) / (vix_std200 + 1e-10)
    
    # VIX 퍼센타일 (252일 롤링)
    df['VIX_Pct'] = df['VIX'].rolling(252, min_periods=60).rank(pct=True)
    
    # FGI 퍼센타일
    df['FGI_Pct'] = df['FearGreedIndex'].rolling(252, min_periods=60).rank(pct=True)
    
    # QQQ 낙폭 및 드로우다운 퍼센타일
    df['QQQ_Peak'] = df['QQQ'].rolling(252, min_periods=1).max()
    df['QQQ_DD'] = (df['QQQ_Peak'] - df['QQQ']) / df['QQQ_Peak']
    df['DD_Pct'] = df['QQQ_DD'].rolling(252, min_periods=60).rank(pct=True)
    
    # 4) 금리 변화율 (10일 국채 금리 모멘텀)
    df['TNX_ROC'] = df['TNX'].pct_change(10)
    
    # 5) HYG RSI (14일)
    delta_hyg = df['HYG'].diff()
    gain_hyg = (delta_hyg.where(delta_hyg > 0, 0)).rolling(window=14).mean()
    loss_hyg = (-delta_hyg.where(delta_hyg < 0, 0)).rolling(window=14).mean()
    rs_hyg = gain_hyg / (loss_hyg + 1e-10)
    df['HYG_RSI'] = 100 - (100 / (1 + rs_hyg))
    
    # 2차 탐색용 추가 보조지표 계산
    df['SKEW_Low'] = df['SKEW'] < 110
    
    # VVIX 60일 Z-score 및 퍼센타일
    vvix_ma = df['VVIX'].rolling(60).mean()
    vvix_std = df['VVIX'].rolling(60).std()
    df['VVIX_Z'] = (df['VVIX'] - vvix_ma) / (vvix_std + 1e-10)
    df['VVIX_Pct'] = df['VVIX'].rolling(252, min_periods=60).rank(pct=True)
    
    # 안전자산 대피 (TLT 5일 수익률 - HYG 5일 수익률)
    tlt_delta = df['TLT'].pct_change(5)
    hyg_delta = df['HYG'].pct_change(5)
    df['Flight'] = tlt_delta - hyg_delta

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
    kospi = yf.download('^KS11', start="2018-01-01", progress=False)
    if isinstance(kospi.columns, pd.MultiIndex): kospi.columns = kospi.columns.get_level_values(0)
    kospi_df = kospi[['Close']].rename(columns={'Close': 'KOSPI'}) if not kospi.empty and 'Close' in kospi.columns else pd.DataFrame(columns=['KOSPI'])
    
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
    
    # 과거 시계열용 VKOSPI 프록시: KOSPI 지수의 30일 역사적 Volatility 산출
    kospi_close = kospi_df['KOSPI']
    returns = kospi_close.pct_change()
    rolling_vol = returns.rolling(30).std() * np.sqrt(252) * 100
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
    
    # KOSPI 영업일 기준으로 필터링하여 주말/공휴일 제거
    df_kr = df_kr.reindex(kospi_df.index).ffill().bfill()
    
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

@st.cache_data(ttl=3600)
def fetch_monitoring_data(num_pages=80):
    headers = {'User-Agent': 'Mozilla/5.0'}
    today_str = datetime.date.today().strftime('%Y%m%d')
    
    def fetch_page_deposit(page):
        url = f'https://finance.naver.com/sise/sise_deposit.naver?page={page}'
        try:
            r = requests.get(url, headers=headers, timeout=5)
            dfs = pd.read_html(StringIO(r.text), encoding='euc-kr')
            if len(dfs) > 0:
                df = dfs[0].dropna(how='all')
                res_df = pd.DataFrame()
                res_df['Date'] = pd.to_datetime(df.iloc[:, 0], format='%y.%m.%d', errors='coerce')
                res_df['Deposit'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')
                res_df['Margin'] = pd.to_numeric(df.iloc[:, 3], errors='coerce')
                return res_df.dropna(subset=['Date'])
        except Exception:
            pass
        return pd.DataFrame()

    def fetch_page_investor(page):
        url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={today_str}&sosok=01&page={page}'
        try:
            r = requests.get(url, headers=headers, timeout=5)
            dfs = pd.read_html(StringIO(r.text), encoding='euc-kr')
            if len(dfs) > 0:
                df = dfs[0].dropna(how='all')
                res_df = pd.DataFrame()
                res_df['Date'] = pd.to_datetime(df.iloc[:, 0], format='%y.%m.%d', errors='coerce')
                res_df['Retail'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')
                res_df['Foreign'] = pd.to_numeric(df.iloc[:, 2], errors='coerce')
                res_df['Institution'] = pd.to_numeric(df.iloc[:, 3], errors='coerce')
                return res_df.dropna(subset=['Date'])
        except Exception:
            pass
        return pd.DataFrame()

    def fetch_page_kospi(page):
        url = f'https://finance.naver.com/sise/sise_index_day.naver?code=KOSPI&page={page}'
        try:
            r = requests.get(url, headers=headers, timeout=5)
            dfs = pd.read_html(StringIO(r.text), encoding='euc-kr')
            if len(dfs) > 0:
                df = dfs[0].dropna(how='all')
                res_df = pd.DataFrame()
                res_df['Date'] = pd.to_datetime(df.iloc[:, 0], format='%Y.%m.%d', errors='coerce')
                res_df['KOSPI'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')
                res_df['TradingValue'] = pd.to_numeric(df.iloc[:, 5], errors='coerce')
                return res_df.dropna(subset=['Date'])
        except Exception:
            pass
        return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=20) as executor:
        deposits = list(executor.map(fetch_page_deposit, range(1, num_pages + 1)))
        investors = list(executor.map(fetch_page_investor, range(1, num_pages + 1)))
        kospi = list(executor.map(fetch_page_kospi, range(1, num_pages + 1)))
        
    df_dep = pd.concat([d for d in deposits if not d.empty], ignore_index=True) if any(not d.empty for d in deposits) else pd.DataFrame(columns=['Date', 'Deposit', 'Margin'])
    df_inv = pd.concat([i for i in investors if not i.empty], ignore_index=True) if any(not i.empty for i in investors) else pd.DataFrame(columns=['Date', 'Retail', 'Foreign', 'Institution'])
    df_kos = pd.concat([k for k in kospi if not k.empty], ignore_index=True) if any(not k.empty for k in kospi) else pd.DataFrame(columns=['Date', 'KOSPI', 'TradingValue'])
    
    if not df_dep.empty: df_dep = df_dep.drop_duplicates(subset=['Date']).set_index('Date')
    else: df_dep = df_dep.set_index('Date')
    
    if not df_inv.empty: df_inv = df_inv.drop_duplicates(subset=['Date']).set_index('Date')
    else: df_inv = df_inv.set_index('Date')
    
    if not df_kos.empty: df_kos = df_kos.drop_duplicates(subset=['Date']).set_index('Date')
    else: df_kos = df_kos.set_index('Date')
    
    df_merged = df_kos.join([df_dep, df_inv], how='outer').sort_index()
    
    df_merged['Retail_Cum'] = df_merged['Retail'].fillna(0).cumsum()
    df_merged['Foreign_Cum'] = df_merged['Foreign'].fillna(0).cumsum()
    df_merged['Institution_Cum'] = df_merged['Institution'].fillna(0).cumsum()
    
    return df_merged

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
    df_mon = fetch_monitoring_data()

# 탭 구성: 공탐변동 / 슬로프합 / 다중지표 / 통합지표 / 모니터링 / 메모리 / 고점지표 / 고점개발 / 고점개발2
tab_names = ['공탐변동', '슬로프합', '다중지표', '통합지표', '모니터링', '메모리', '고점지표', '고점개발', '고점개발2']
tabs = st.tabs(tab_names)

# ── Tab 1: 공탐변동 ──
with tabs[0]:
    if selected_country == "미국":
        five_years_ago = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
        df1 = df[df.index >= five_years_ago]

        color_cond_map = [
            ((df1['FearGreedIndex']<=9)&(df1['VIX']>=26),                                                          '#595959', '#FFFFFF', 'rgba(0,0,0,0.3)'),
            ((df1['FearGreedIndex']>=10)&(df1['FearGreedIndex']<=19)&(df1['VIX']>=22)&(df1['VIX']<=25),            '#E06666', '#FFFFFF', 'rgba(220,30,30,0.3)'),
            ((df1['FearGreedIndex']>=20)&(df1['FearGreedIndex']<=29)&(df1['VIX']>=18)&(df1['VIX']<=21),            '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
            ((df1['FearGreedIndex']>=30)&(df1['FearGreedIndex']<=39)&(df1['VIX']>=14)&(df1['VIX']<=17),            '#A9D08E', '#000000', 'rgba(0,128,0,0.3)'),
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
        
        fig.add_trace(go.Scatter(x=hd1, y=df1['QQQ'], name='QQQ', mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig.add_trace(go.Scatter(x=hd1, y=df1['VIX'], name='VIX', line=dict(color='rgba(0, 0, 255, 0.75)', width=0.5), hovertemplate='VIX: %{y:.2f}<extra></extra>'), secondary_y=True)
        fig.add_trace(go.Scatter(x=hd1, y=df1['FearGreedIndex'], name='FGI', line=dict(color='rgba(128, 0, 128, 0.75)', width=0.5), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
        fig.add_trace(go.Scatter(x=hd1, y=df1['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='rgba(255, 165, 0, 0.75)', width=0.5), hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
        
        # 색깔 감지 그래프 윤곽선 추가: 두께 0.25, 색깔 흰색
        max_qqq = float(df1['QQQ'].max()) * 1.2
        for cond, _bg, _fg, fc in color_cond_map:
            fig.add_trace(go.Bar(
                x=hd1, y=cond.astype(int) * max_qqq, 
                marker_color=fc, showlegend=False, hoverinfo='skip',
                marker_line_width=0.5,
                marker_line_color='white'
            ), secondary_y=False)
        
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

        st.plotly_chart(fig, width='stretch', config=COMMON_CONFIG, key="tab1_us_fgi_chart")

        # 실시간 지표검증결과 자동 계산 (QQQ 기준)
        fgi_conditions = {
            "**[검정] 극단적 패닉**": ((df['FearGreedIndex'] <= 9) & (df['VIX'] >= 26), "FGI <= 9 & VIX >= 26"),
            "**[빨강] 강한 패닉**": ((df['FearGreedIndex'] >= 10) & (df['FearGreedIndex'] <= 19) & (df['VIX'] >= 22) & (df['VIX'] <= 25), "FGI 10-19 & VIX 22-25"),
            "**[노랑] 약세 패닉**": ((df['FearGreedIndex'] >= 20) & (df['FearGreedIndex'] <= 29) & (df['VIX'] >= 18) & (df['VIX'] <= 21), "FGI 20-29 & VIX 18-21"),
            "**[초록] 주의 구간**": ((df['FearGreedIndex'] >= 30) & (df['FearGreedIndex'] <= 39) & (df['VIX'] >= 14) & (df['VIX'] <= 17), "FGI 30-39 & VIX 14-17"),
            "**공탐변동 종합 감지**": (
                ((df['FearGreedIndex'] <= 9) & (df['VIX'] >= 26)) |
                ((df['FearGreedIndex'] >= 10) & (df['FearGreedIndex'] <= 19) & (df['VIX'] >= 22) & (df['VIX'] <= 25)) |
                ((df['FearGreedIndex'] >= 20) & (df['FearGreedIndex'] <= 29) & (df['VIX'] >= 18) & (df['VIX'] <= 21)) |
                ((df['FearGreedIndex'] >= 30) & (df['FearGreedIndex'] <= 39) & (df['VIX'] >= 14) & (df['VIX'] <= 17)),
                "위 4가지 색 중 하나 이상 감지"
            )
        }
        stats = calculate_indicator_stats(df, 'QQQ', fgi_conditions)
        st.markdown("<br>", unsafe_allow_html=True)
        render_stats_table(stats, "지표검증결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")

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
            ((df1_kr['FearGreedIndex']<=9)&(df1_kr['VKOSPI']>=26),                                                          '#595959', '#FFFFFF', 'rgba(0,0,0,0.3)'),
            ((df1_kr['FearGreedIndex']>=10)&(df1_kr['FearGreedIndex']<=19)&(df1_kr['VKOSPI']>=22),                          '#E06666', '#FFFFFF', 'rgba(220,30,30,0.3)'),
            ((df1_kr['FearGreedIndex']>=20)&(df1_kr['FearGreedIndex']<=29)&(df1_kr['VKOSPI']>=18),                          '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
            ((df1_kr['FearGreedIndex']>=30)&(df1_kr['FearGreedIndex']<=39)&(df1_kr['VKOSPI']>=14),                          '#A9D08E', '#000000', 'rgba(0,128,0,0.3)'),
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
        
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['KOSPI'], name='KOSPI', mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)), hovertemplate='KOSPI: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['VKOSPI'], name='VKOSPI', line=dict(color='rgba(0, 0, 255, 0.75)', width=0.5), hovertemplate='VKOSPI: %{y:.2f}<extra></extra>'), secondary_y=True)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['FearGreedIndex'], name='FGI', line=dict(color='rgba(128, 0, 128, 0.75)', width=0.5), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['(FGI-VIX)/5'], name='(FGI-VKOSPI)/5', line=dict(color='rgba(255, 165, 0, 0.75)', width=0.5), hovertemplate='(FGI-VKOSPI)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
        
        # 한국 색상바 추가 (미국과 동일 양식 설정)
        max_kospi = float(df1_kr['KOSPI'].max()) * 1.2
        for cond, _bg, _fg, fc in color_cond_map_kr:
            fig_kr.add_trace(go.Bar(
                x=hd1_kr, y=cond.astype(int) * max_kospi, 
                marker_color=fc, showlegend=False, hoverinfo='skip',
                marker_line_width=0.5,
                marker_line_color='white'
            ), secondary_y=False)
            
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

        st.plotly_chart(fig_kr, width='stretch', config=COMMON_CONFIG, key="tab1_kr_fgi_chart")

        # 실시간 지표검증결과 자동 계산 (KOSPI 기준)
        fgi_conditions_kr = {
            "**[검정] 극단적 패닉**": ((df_kr['FearGreedIndex'] <= 9) & (df_kr['VKOSPI'] >= 26), "FGI <= 9 & VKOSPI >= 26"),
            "**[빨강] 강한 패닉**": ((df_kr['FearGreedIndex'] >= 10) & (df_kr['FearGreedIndex'] <= 19) & (df_kr['VKOSPI'] >= 22), "FGI 10-19 & VKOSPI >= 22"),
            "**[노랑] 약세 패닉**": ((df_kr['FearGreedIndex'] >= 20) & (df_kr['FearGreedIndex'] <= 29) & (df_kr['VKOSPI'] >= 18), "FGI 20-29 & VKOSPI >= 18"),
            "**[초록] 주의 구간**": ((df_kr['FearGreedIndex'] >= 30) & (df_kr['FearGreedIndex'] <= 39) & (df_kr['VKOSPI'] >= 14), "FGI 30-39 & VKOSPI >= 14"),
            "**공탐변동 종합 감지**": (
                ((df_kr['FearGreedIndex'] <= 9) & (df_kr['VKOSPI'] >= 26)) |
                ((df_kr['FearGreedIndex'] >= 10) & (df_kr['FearGreedIndex'] <= 19) & (df_kr['VKOSPI'] >= 22)) |
                ((df_kr['FearGreedIndex'] >= 20) & (df_kr['FearGreedIndex'] <= 29) & (df_kr['VKOSPI'] >= 18)) |
                ((df_kr['FearGreedIndex'] >= 30) & (df_kr['FearGreedIndex'] <= 39) & (df_kr['VKOSPI'] >= 14)),
                "위 4가지 색 중 하나 이상 감지"
            )
        }
        stats_kr = calculate_indicator_stats(df_kr, 'KOSPI', fgi_conditions_kr)
        st.markdown("<br>", unsafe_allow_html=True)
        render_stats_table(stats_kr, "지표검증결과 (2018.01 ~ 현재 KOSPI 저점 대비 실시간 자동 업데이트)")

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
            r50 = parent_dates[:50]
            dates_row = []
            counts_row = []
            for dt in r50:
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
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 50개)</span>
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
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=rn,col=1,secondary_y=False)
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(0, 0, 255, 0.75)',width=0.5),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=rn,col=1,secondary_y=True)
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[uc],name='상한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='upper',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[dc],name='하한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='lower',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            
            for cn, fc in [(gc,'rgba(76,175,80,0.3)'),(oc,'rgba(255,220,0,0.3)'),(rc,'rgba(220,30,30,0.3)'),(bc,'rgba(0,0,0,0.3)')]:
                fig_dsi.add_trace(go.Bar(
                    x=hd_df, y=df[cn], marker_color=fc, showlegend=False, hoverinfo='skip',
                    marker_line_width=0.5,
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

        st.plotly_chart(fig_dsi, width='stretch', config=COMMON_CONFIG, key="tab2_us_slope_chart")

        # 실시간 지표검증결과 자동 계산 (QQQ 슬로프합 기준)
        slope_conditions = {
            "**5일합 이탈**": (df['슬로프5일합'] <= -20, "5일슬로프합 <= -20"),
            "**10일합 이탈**": (df['슬로프10일합'] <= -30, "10일슬로프합 <= -30"),
            "**20일합 이탈**": (df['슬로프20일합'] <= -40, "20일슬로프합 <= -40"),
            "**40일합 이탈**": (df['슬로프40일합'] <= -50, "40일슬로프합 <= -50"),
            "**슬로프합 종합 감지**": (
                (df['슬로프5일합'] <= -20) | (df['슬로프10일합'] <= -30) | (df['슬로프20일합'] <= -40) | (df['슬로프40일합'] <= -50),
                "1개 이상 지표 이탈"
            ),
            "**슬로프합 강력 이탈**": (
                ((df['슬로프5일합'] <= -20).astype(int) + 
                 (df['슬로프10일합'] <= -30).astype(int) + 
                 (df['슬로프20일합'] <= -40).astype(int) + 
                 (df['슬로프40일합'] <= -50).astype(int)) >= 3,
                "3개 이상 지표 동시 이탈"
            )
        }
        stats_slope = calculate_indicator_stats(df, 'QQQ', slope_conditions)
        st.markdown("<br>", unsafe_allow_html=True)
        render_stats_table(stats_slope, "지표검증결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")

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
            r50_kr = parent_dates_kr[:50]
            dates_row_kr = []
            counts_row_kr = []
            for dt in r50_kr:
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
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 50개)</span>
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
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr['KOSPI'],name='KOSPI 가격',mode='lines+markers',line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),showlegend=sf,legendgroup='kospi',hovertemplate='KOSPI: %{y:.2f}<extra></extra>'),row=rn,col=1,secondary_y=False)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(0, 0, 255, 0.75)',width=0.5),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=rn,col=1,secondary_y=True)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[uc],name='상한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='upper_kr',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[dc],name='하한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='lower_kr',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
            
            for cn, fc in [(gc,'rgba(76,175,80,0.3)'),(oc,'rgba(255,220,0,0.3)'),(rc,'rgba(220,30,30,0.3)'),(bc,'rgba(0,0,0,0.3)')]:
                fig_dsi_kr.add_trace(go.Bar(
                    x=hd_df_kr, y=df_kr[cn], marker_color=fc, showlegend=False, hoverinfo='skip',
                    marker_line_width=0.5,
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

        st.plotly_chart(fig_dsi_kr, width='stretch', config=COMMON_CONFIG, key="tab2_kr_slope_chart")

        # 실시간 지표검증결과 자동 계산 (KOSPI 슬로프합 기준)
        slope_conditions_kr = {
            "**5일합 이탈**": (df_kr['슬로프5일합'] <= -30, "5일슬로프합 <= -30"),
            "**10일합 이탈**": (df_kr['슬로프10일합'] <= -50, "10일슬로프합 <= -50"),
            "**20일합 이탈**": (df_kr['슬로프20일합'] <= -70, "20일슬로프합 <= -70"),
            "**40일합 이탈**": (df_kr['슬로프40일합'] <= -100, "40일슬로프합 <= -100"),
            "**슬로프합 종합 감지**": (
                (df_kr['슬로프5일합'] <= -30) | (df_kr['슬로프10일합'] <= -50) | (df_kr['슬로프20일합'] <= -70) | (df_kr['슬로프40일합'] <= -100),
                "1개 이상 지표 이탈"
            ),
            "**슬로프합 강력 이탈**": (
                ((df_kr['슬로프5일합'] <= -30).astype(int) + 
                 (df_kr['슬로프10일합'] <= -50).astype(int) + 
                 (df_kr['슬로프20일합'] <= -70).astype(int) + 
                 (df_kr['슬로프40일합'] <= -100).astype(int)) >= 3,
                "3개 이상 지표 동시 이탈"
            )
        }
        stats_slope_kr = calculate_indicator_stats(df_kr, 'KOSPI', slope_conditions_kr)
        st.markdown("<br>", unsafe_allow_html=True)
        render_stats_table(stats_slope_kr, "지표검증결과 (2018.01 ~ 현재 KOSPI 저점 대비 실시간 자동 업데이트)")

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

# ── Tab 3: 다중지표 ──
with tabs[2]:
        
    if selected_country == "미국":
        df_multi = df.copy()
        
        # 49개의 후보 지표 조건들을 하나의 리스트로 통합
        all_conditions = [
            # 지표개발 19개
            (df_multi['QQQ_%B'] * (df_multi['HYG_RSI'] / 100) <= 0.010),
            (df_multi['FearGreedIndex'] * np.exp(df_multi['TNX_ROC'] * 2) / (df_multi['VIX'] + 1e-10) <= 0.35),
            (((df_multi['FearGreedIndex'] - 50) / 20 + (df_multi['QQQ_RSI'] - 50) / 15 + (df_multi['QQQ_%B'] - 0.5) / 0.25 - df_multi['VIX_Z']) <= -5.0),
            ((df_multi['QQQ_%B'] <= 0.01) & (df_multi['FearGreedIndex'] <= 6) & (df_multi['VIX'] >= 25)),
            ((df_multi['QQQ_%B'] <= -0.05) & (df_multi['FearGreedIndex'] <= 7)),
            ((df_multi['슬로프10일합'] <= -40) & (df_multi['VIX'] >= 30) & (df_multi['FearGreedIndex'] <= 9)),
            ((df_multi['슬로프40일합'] <= -70) & (df_multi['FearGreedIndex'] <= 8) & (df_multi['QQQ_%B'] <= 0.02)),
            ((df_multi['HYG_RSI'] <= 18) & (df_multi['VIX'] >= 32)),
            ((df_multi['FearGreedIndex'] <= 8) & (df_multi['VIX'] >= 28) & (df_multi['HYG_RSI'] <= 22)),
            ((df_multi['슬로프5일합'] <= -35) & (df_multi['QQQ_RSI'] <= 22) & (df_multi['VIX'] >= 28)),
            ((df_multi['QQQ_RSI7'] <= 15) & (df_multi['FearGreedIndex'] <= 15)),
            ((df_multi['QQQ_RSI7'] <= 18) & (df_multi['FearGreedIndex'] <= 12)),
            ((df_multi['QQQ_RSI7'] <= 20) & (df_multi['FearGreedIndex'] <= 12)),
            ((df_multi['QQQ_RSI7'] <= 22) & (df_multi['FearGreedIndex'] <= 12)),
            ((df_multi['VVIX_Z'] >= 3.0) & (df_multi['FearGreedIndex'] <= 15)),
            ((df_multi['VVIX_Z'] >= 2.5) & (df_multi['FearGreedIndex'] <= 20)),
            ((df_multi['VVIX_Pct'] >= 0.90) & (df_multi['FearGreedIndex'] <= 10)),
            ((df_multi['VVIX_Pct'] >= 0.90) & (df_multi['QQQ_RSI7'] <= 22)),
            ((df_multi['FearGreedIndex'].diff(7) <= -20) & (df_multi['VIX_Pct'] >= 0.85)),
            # 적중집중 10개
            (((30 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 18) & (df_multi['VVIX_Pct'] >= 0.70)),
            (((25 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 12) & (df_multi['VVIX_Pct'] >= 0.70)),
            (((df_multi['VVIX'] / (df_multi['QQQ_RSI7'] + 1e-5)) >= 5.0) & (df_multi['FearGreedIndex'] <= 18) & (df_multi['QQQ_DD'] >= 0.05)),
            (((df_multi['VIX'] * df_multi['VVIX'] / 1000) >= 2.5) & (df_multi['FearGreedIndex'] <= 10) & (df_multi['QQQ_DD'] >= 0.04)),
            (((df_multi['VIX'] * df_multi['VVIX'] / 1000) >= 2.5) & (df_multi['FearGreedIndex'] <= 10) & (df_multi['QQQ_DD'] >= 0.05)),
            (((25 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 15) & (df_multi['VVIX_Pct'] >= 0.70)),
            (((20 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 10) & (df_multi['VVIX_Pct'] >= 0.70)),
            (((30 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 18) & (df_multi['VVIX_Pct'] >= 0.80)),
            ((np.log(np.maximum(df_multi['VVIX_Z'] + 5.0, 1e-5)) * df_multi['VIX_Pct'] >= 1.0) & (df_multi['FearGreedIndex'] <= 12) & (df_multi['QQQ_%B'] <= 0.15)),
            ((df_multi['FearGreedIndex'] * np.exp(df_multi['TNX_ROC'] * 3) <= 15) & (df_multi['QQQ_RSI7'] <= 28) & (df_multi['VIX_Pct'] >= 0.80)),
            # 균형집중 10개
            (((df_multi['VVIX'] / (df_multi['QQQ_RSI7'] + 1e-5)) >= 4.5) & (df_multi['FearGreedIndex'] <= 30) & (df_multi['QQQ_DD'] >= 0.05)),
            (((df_multi['VVIX'] / (df_multi['QQQ_RSI7'] + 1e-5)) >= 3.5) & (df_multi['FearGreedIndex'] <= 22) & (df_multi['QQQ_DD'] >= 0.05)),
            ((df_multi['QQQ_%B'] <= 0.10) & (df_multi['QQQ_RSI7'] <= 40) & (df_multi['FearGreedIndex'] <= 30) & (df_multi['VIX_Pct'] >= 0.60) & (df_multi['VVIX_Pct'] >= 0.50)),
            ((100 / (df_multi['QQQ_RSI7'] + 1e-5) + df_multi['DD_Pct'] * 3 >= 7.0) & (df_multi['FGI_Pct'] <= 0.30)),
            ((100 / (df_multi['QQQ_RSI7'] + 1e-5) + df_multi['DD_Pct'] * 4 >= 8.0) & (df_multi['FGI_Pct'] <= 0.30)),
            ((df_multi['QQQ_%B'] <= 0.15) & (df_multi['QQQ_RSI7'] <= 35) & (df_multi['FearGreedIndex'] <= 20) & (df_multi['VIX_Pct'] >= 0.60) & (df_multi['VVIX_Pct'] >= 0.50)),
            (((25 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 18) & (df_multi['VVIX_Pct'] >= 0.50) & (df_multi['DD_Pct'] >= 0.70)),
            (((30 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 25) & (df_multi['VVIX_Pct'] >= 0.50) & (df_multi['DD_Pct'] >= 0.40)),
            ((df_multi['VIX_Z'] * df_multi['VVIX_Z'] >= 1.2) & (df_multi['FearGreedIndex'] <= 12) & (df_multi['QQQ_DD'] >= 0.05)),
            ((df_multi['VIX_Z'] * df_multi['VVIX_Z'] >= 1.5) & (df_multi['FearGreedIndex'] <= 12) & (df_multi['QQQ_DD'] >= 0.05)),
            # 포착집중 10개
            (((df_multi['VVIX'] / (df_multi['QQQ_RSI7'] + 1e-5)) >= 2.5) & (df_multi['FearGreedIndex'] <= 40) & (df_multi['QQQ_DD'] >= 0.05)),
            (((df_multi['VVIX'] / (df_multi['QQQ_RSI7'] + 1e-5)) >= 3.0) & (df_multi['FearGreedIndex'] <= 45) & (df_multi['QQQ_DD'] >= 0.05)),
            ((df_multi['QQQ_%B'] <= 0.25) & (df_multi['QQQ_RSI7'] <= 50) & (df_multi['FearGreedIndex'] <= 40) & (df_multi['VIX_Pct'] >= 0.40) & (df_multi['VVIX_Pct'] >= 0.40)),
            ((140 / (df_multi['QQQ_RSI7'] + 1e-5) + df_multi['DD_Pct'] * 2 >= 6.0) & (df_multi['FGI_Pct'] <= 0.35)),
            ((df_multi['QQQ_%B'] <= 0.20) & (df_multi['QQQ_RSI7'] <= 50) & (df_multi['FearGreedIndex'] <= 45) & (df_multi['VIX_Pct'] >= 0.40) & (df_multi['VVIX_Pct'] >= 0.40)),
            ((100 / (df_multi['QQQ_RSI7'] + 1e-5) + df_multi['DD_Pct'] * 2 >= 5.0) & (df_multi['FGI_Pct'] <= 0.35)),
            (((40 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 25) & (df_multi['VVIX_Pct'] >= 0.30) & (df_multi['DD_Pct'] >= 0.50)),
            (((35 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 20) & (df_multi['VVIX_Pct'] >= 0.30) & (df_multi['DD_Pct'] >= 0.50)),
            ((df_multi['VIX_Z'] * df_multi['VVIX_Z'] >= 0.5) & (df_multi['FearGreedIndex'] <= 18) & (df_multi['QQQ_DD'] >= 0.05)),
            ((df_multi['VIX_Z'] * df_multi['VVIX_Z'] >= 0.8) & (df_multi['FearGreedIndex'] <= 18) & (df_multi['QQQ_DD'] >= 0.05))
        ]
        
        # 합산(개수 세기)
        df_multi['multi_count'] = sum(cond.fillna(False).astype(int) for cond in all_conditions)
        
        # 날짜 범위 설정 (기간 필터링)
        if active_period_days:
            target_date_multi = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices = [i for i, d in enumerate(df_multi.index) if d >= pd.to_datetime(target_date_multi)]
            initial_x_range_multi = [detected_indices[0], len(df_multi.index) - 1] if detected_indices else None
            if detected_indices:
                qqq_1y = df_multi['QQQ'].iloc[detected_indices[0]:]
                q_min, q_max = float(qqq_1y.min()), float(qqq_1y.max())
                qqq_y_range = [q_min * 0.95, q_max * 1.05]
            else:
                qqq_y_range = [float(df_multi['QQQ'].min()) * 0.95, float(df_multi['QQQ'].max()) * 1.05]
        else:
            initial_x_range_multi = None
            q_min, q_max = float(df_multi['QQQ'].min()), float(df_multi['QQQ'].max())
            qqq_y_range = [q_min * 0.95, q_max * 1.05]

        max_qqq_multi = float(df_multi['QQQ'].max()) * 1.2
        
        # 색상 매핑
        cond_map = [
            ((df_multi['multi_count'] >= 1) & (df_multi['multi_count'] <= 7), '#E06666', '1~7개 감지'), # 빨간색
            ((df_multi['multi_count'] >= 8) & (df_multi['multi_count'] <= 14), '#FF8C00', '8~14개 감지'), # 주황색 (실제 렌더링은 Gold 사용)
            ((df_multi['multi_count'] >= 15) & (df_multi['multi_count'] <= 21), '#FFFF99', '15~21개 감지'), # 노란색
            ((df_multi['multi_count'] >= 22) & (df_multi['multi_count'] <= 28), '#A9D08E', '22~28개 감지'), # 초록색
            ((df_multi['multi_count'] >= 29) & (df_multi['multi_count'] <= 35), '#87CEEB', '29~35개 감지'), # 파란색
            ((df_multi['multi_count'] >= 36) & (df_multi['multi_count'] <= 42), '#000080', '36~42개 감지'), # 남색
            ((df_multi['multi_count'] >= 43) & (df_multi['multi_count'] <= 49), '#800080', '43~49개 감지'), # 보라색
        ]
        
        # 표 생성을 위한 데이터 준비 (최근 50개)
        df_sig = df_multi[df_multi['multi_count'] >= 1].sort_index(ascending=False).head(50)
        
        if not df_sig.empty:
            dates_row_multi = []
            counts_row_multi = []
            
            for dt, row in df_sig.iterrows():
                cnt = row['multi_count']
                bg = '#E06666'
                for c, color, lbl in cond_map:
                    if c.loc[dt]:
                        bg = color
                        break
                
                fg = "#FFF" if bg in ['#E06666', '#000080', '#800080', '#87CEEB'] else "#000"
                
                dates_row_multi.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                counts_row_multi.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{int(cnt)}</td>")
                
            top_html_multi = f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 갯수 감지 신호 (최근 50개)</span>
            <table style='border-collapse:collapse;margin-top:3px;'>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                    {"".join(dates_row_multi)}
                </tr>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>갯수</th>
                    {"".join(counts_row_multi)}
                </tr>
            </table>
            </div>
            """
            st.markdown(top_html_multi, unsafe_allow_html=True)
        else:
            st.info("조건을 만족하는 감지 신호가 없습니다.")

        # 색깔별로 막대그래프를 그리기 위해 figure 생성
        fig_multi = make_subplots(specs=[[{"secondary_y": True}]])
        hd_multi = [fmt_date_kor(d) for d in df_multi.index]
        
        # QQQ 라인 그래프 (슬로프합탭과 동일한 설정)
        fig_multi.add_trace(go.Scatter(
            x=hd_multi, y=df_multi['QQQ'], name='QQQ 가격', mode='lines+markers',
            line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
            marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
            hovertemplate='QQQ: %{y:.2f}<extra></extra>'
        ), secondary_y=False)
        
        # 감지 막대그래프 추가
        for cond, color, label in cond_map:
            fig_multi.add_trace(go.Bar(
                x=hd_multi, y=cond.astype(int) * max_qqq_multi,
                marker_color=color.replace('#', 'rgba(') if '#' not in color else color,
                opacity=0.7,
                showlegend=False,
                hoverinfo='skip',
                marker_line_width=0.5,
                marker_line_color='white'
            ), secondary_y=False)
            
        fig_multi.update_layout(
            **COMMON_LAYOUT, 
            height=400, 
            margin=dict(l=0, r=50, t=30, b=10),
            showlegend=False,
            barmode='overlay',
            bargap=0,
            shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))]
        )
        if initial_x_range_multi:
            fig_multi.update_xaxes(range=initial_x_range_multi, type='category', **crosshair_xaxis())
        else:
            fig_multi.update_xaxes(type='category', **crosshair_xaxis())
            
        fig_multi.update_yaxes(range=qqq_y_range, **crosshair_yaxis(), secondary_y=False, title_text="")
        fig_multi.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
        
        st.plotly_chart(fig_multi, width='stretch', config=COMMON_CONFIG, key="tab5_multi_chart")
        
        # 지표 검증 결과
        multi_conditions = {
            "**빨간색**": (cond_map[0][0], cond_map[0][2]),
            "**주황색**": (cond_map[1][0], cond_map[1][2]),
            "**노란색**": (cond_map[2][0], cond_map[2][2]),
            "**초록색**": (cond_map[3][0], cond_map[3][2]),
            "**파란색**": (cond_map[4][0], cond_map[4][2]),
            "**남색**":   (cond_map[5][0], cond_map[5][2]),
            "**보라색**": (cond_map[6][0], cond_map[6][2]),
        }
        stats_multi = calculate_indicator_stats(df_multi, 'QQQ', multi_conditions)
        st.markdown("<br>", unsafe_allow_html=True)
        render_stats_table(stats_multi, "지표검증결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")

    else:
        st.info("한국 데이터는 향후 지원 예정입니다. 국가 선택을 '미국'으로 변경해 주세요.")


# ── Tab 4: 통합지표 ──
with tabs[3]:
            
    if selected_country == "미국":
        with st.spinner("통합지표 데이터를 계산 중입니다..."):
            df_pre = df.copy()
            
            _vol = yf.download('QQQ', start="2018-10-01", progress=False)
            vol_data = _vol['Volume'] if not _vol.empty and 'Volume' in _vol.columns else pd.Series()
            if isinstance(vol_data, pd.DataFrame): 
                vol_data = vol_data.iloc[:, 0]
            vol_data.index = vol_data.index.normalize()
            df_pre['Volume'] = vol_data.reindex(df_pre.index).ffill()
            
            ema12 = df_pre['QQQ'].ewm(span=12, adjust=False).mean()
            ema26 = df_pre['QQQ'].ewm(span=26, adjust=False).mean()
            df_pre['MACD'] = ema12 - ema26
            df_pre['MACD_Signal'] = df_pre['MACD'].ewm(span=9, adjust=False).mean()
            df_pre['MACD_Hist'] = df_pre['MACD'] - df_pre['MACD_Signal']
            
            df_pre['SKEW_Z'] = (df_pre['SKEW'] - df_pre['SKEW'].rolling(252).mean()) / (df_pre['SKEW'].rolling(252).std() + 1e-5)
            df_pre['Vol_Z'] = (df_pre['Volume'] - df_pre['Volume'].rolling(50).mean()) / (df_pre['Volume'].rolling(50).std() + 1e-5)
            
            x_arr = np.arange(10)
            var_x = np.var(x_arr)
            def calc_slope(y):
                if len(y) < 10: return 0
                return np.cov(x_arr, y)[0,1] / var_x
            df_pre['QQQ_Slope10'] = df_pre['QQQ'].rolling(10).apply(calc_slope, raw=True)
            df_pre['QQQ_Vel'] = df_pre['QQQ'].pct_change(5)
            df_pre['QQQ_Accel'] = df_pre['QQQ_Vel'].diff(3)
            df_pre['VVIX_Vel'] = df_pre['VVIX'].diff(3)
            
            delta = df_pre['QQQ'].diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            rs14 = up.rolling(14).mean() / (down.rolling(14).mean() + 1e-5)
            df_pre['QQQ_RSI14'] = 100 - (100 / (1 + rs14))
            rs7 = up.rolling(7).mean() / (down.rolling(7).mean() + 1e-5)
            df_pre['QQQ_RSI7'] = 100 - (100 / (1 + rs7))

            df_pre['DD_Sq'] = df_pre['QQQ_DD'] ** 2
            df_pre['FGI_Proxy'] = 100 - (df_pre['VIX'] / df_pre['VIX'].rolling(252).max() * 100)
            if 'TNX_ROC' not in df_pre.columns:
                df_pre['TNX_ROC'] = df_pre['TNX'].pct_change(10)
            if 'VIX_Pct' not in df_pre.columns:
                df_pre['VIX_Pct'] = (df_pre['VIX'] - df_pre['VIX'].rolling(252).min()) / (df_pre['VIX'].rolling(252).max() - df_pre['VIX'].rolling(252).min() + 1e-5)

        # ---------------- 1차 연구: 4대 후보 AND 조합 ----------------
        macro1 = (df_pre['SKEW_Z'] > 0.5) | (df_pre['HYG_RSI'] <= 25)
        micro1 = (df_pre['MACD_Hist'] < -1.0) & (df_pre['QQQ_Slope10'] < -1.0)
        c1_1 = (macro1 & micro1) | ((np.log(df_pre['VVIX'] + 1e-5) * df_pre['DD_Sq'] * 100 > 1.0) & (df_pre['QQQ_%B'] <= 0.02))
        
        liq1 = (df_pre['Vol_Z'] > 1.5) | (df_pre['HYG_RSI'] < 20)
        psy1 = (df_pre['FearGreedIndex'] <= 15) | (df_pre['VIX_Pct'] >= 0.9)
        dd_guard1 = df_pre['QQQ_DD'] >= 0.06
        c2_1 = (liq1 & psy1 & dd_guard1) | ((df_pre['VVIX_Vel'].diff(3) > 5.0) & (df_pre['QQQ_RSI7'] <= 25) & (df_pre['QQQ_DD'] >= 0.04))
        
        grav1 = (df_pre['QQQ_Accel'] < -0.015) & (df_pre['DD_Sq'] * df_pre['VVIX'] > 1.0)
        vol_shock1 = (df_pre['QQQ_%B'] < 0.0) & (df_pre['Vol_Z'] > 1.0) & (df_pre['HYG_RSI'] <= 30)
        c3_1 = (grav1 | vol_shock1) & (df_pre['QQQ_RSI14'] <= 45) & (df_pre['QQQ_DD'] >= 0.05)
        
        opt1 = (df_pre['VVIX_Z'] > 1.5) | (df_pre['VIX_Pct'] > 0.85)
        rate1 = (df_pre['TNX_ROC'] > 0.1) | (df_pre['SKEW_Z'] > 1.0)
        tech1 = (df_pre['QQQ_RSI7'] <= 35) | (df_pre['QQQ_%B'] <= 0.05)
        c4_1 = (opt1 | rate1) & tech1 & (df_pre['QQQ_DD'] >= 0.04) & (df_pre['FearGreedIndex'] <= 40)
        
        c_all_1 = c1_1 & c2_1 & c3_1 & c4_1
        
        # ---------------- 2차 연구 ----------------
        ke2 = 0.5 * np.maximum(df_pre['Vol_Z'], 0.1) * (np.abs(df_pre['QQQ_Vel']) * 100)**2
        pe2 = df_pre['VIX'] * (df_pre['QQQ_DD'] * 100)
        c2_2 = (ke2*10 > pe2) & (df_pre['Vol_Z'] > 0.5) & (df_pre['QQQ_%B'] <= 0.05)
        
        phase2 = np.sin((df_pre['FGI_Proxy'] / 100) * np.pi) 
        c4_2 = (phase2 < 0.5) & (df_pre['QQQ_Vel'] < -0.02) & (df_pre['VIX_Z'] > 1.0)
        
        # 통합(OR) 합집합 생성
        c_or_final = c_all_1 | c2_2 | c4_2

        triggered_dates = df_pre[c_or_final].index.sort_values(ascending=False)
        recent_50 = triggered_dates[:50]
        if len(recent_50) > 0:
            dates_row = ""
            for dt in recent_50:
                dates_row += f"<td style='background:#800080;color:white;font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
            
            table_html = f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 3대 기발한 아이디어 감지 신호 (최근 50개)</span>
            <table style='border-collapse:collapse;margin-top:3px;'>
                <tr>
                    <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                    {dates_row}
                </tr>
            </table>
            </div>
            """
            st.markdown(table_html, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            
        pre_conditions = {
            "**최종 3대 통합 괴물지표 (OR)**": (c_or_final, '4종 통합(AND) + 물리에너지 + 푸리에 파동'),
            "4종 통합(AND)": (c_all_1, '연구 조건 4종 일치'),
            "물리학적 에너지 역전 법칙": (c2_2, '투매 운동에너지 > 공포 응축에너지'),
            "푸리에 변환 모방 위상 천이": (c4_2, '공포 삼각함수 파동 교차'),
        }

        if active_period_days:
            target_date = datetime.date.today() - datetime.timedelta(days=active_period_days)
            df_pre_plot = df_pre[df_pre.index >= pd.to_datetime(target_date)]
            if not df_pre_plot.empty:
                qqq_y_range = [float(df_pre_plot['QQQ'].min()) * 0.95, float(df_pre_plot['QQQ'].max()) * 1.05]
                initial_x_range = [df_pre_plot.index[0].strftime("%Y-%m-%d"), df_pre_plot.index[-1].strftime("%Y-%m-%d")]
            else:
                qqq_y_range = None
                initial_x_range = None
        else:
            df_pre_plot = df_pre.copy()
            if not df_pre_plot.empty:
                qqq_y_range = [float(df_pre_plot['QQQ'].min()) * 0.95, float(df_pre_plot['QQQ'].max()) * 1.05]
                initial_x_range = [df_pre_plot.index[0].strftime("%Y-%m-%d"), df_pre_plot.index[-1].strftime("%Y-%m-%d")]
            else:
                qqq_y_range = None
                initial_x_range = None
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        fig_pre = make_subplots(specs=[[{"secondary_y": True}]])
        hd_pre = [fmt_date_kor(d) for d in df_pre_plot.index]
        
        fig_pre.add_trace(go.Scatter(
            x=hd_pre, y=df_pre_plot['QQQ'], name='QQQ 가격', mode='lines+markers',
            line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
            marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
            hovertemplate='QQQ: %{y:.2f}<extra></extra>'
        ), secondary_y=False)
        
        fig_pre.add_trace(go.Bar(
            x=hd_pre, y=c_or_final.reindex(df_pre_plot.index).astype(int) * qqq_y_range[1], name='통합 감지 신호 (OR)',
            marker_color='rgba(128, 0, 128, 0.7)',
            marker_line_width=0.5,
            marker_line_color='white',
            hovertemplate='신호 감지<extra></extra>'
        ), secondary_y=False)
        
        fig_pre.update_layout(
            **COMMON_LAYOUT,
            height=350,
            margin=dict(l=0, r=50, t=10, b=10),
            showlegend=False,
            shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.0))]
        )
        fig_pre.update_xaxes(type='category', **crosshair_xaxis())
        if initial_x_range:
            fig_pre.update_xaxes(range=initial_x_range)
        
        fig_pre.update_yaxes(title_text="", range=qqq_y_range, **crosshair_yaxis(), secondary_y=False)
        fig_pre.update_yaxes(range=[0, 1.2], showticklabels=False, showgrid=False, secondary_y=True)
        
        st.plotly_chart(fig_pre, width='stretch', config=COMMON_CONFIG, key="pre_chart_final_or")
        
        stats_pre = calculate_indicator_stats(df_pre, 'QQQ', pre_conditions)
        render_stats_table(stats_pre, "통합지표 통합 검증 결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")
        
    else:
        st.info("한국 데이터는 향후 지원 예정입니다.")

# ── Tab 5: 모니터링 ──
with tabs[4]:
    st.markdown("### 국내 증시 자금 및 매매동향 모니터링")
    
    # 1. 3대 모니터링 요약 표 (상단 가로 배치)
    if not df_mon.empty:
        df_mon_latest = df_mon.dropna(subset=['KOSPI']).tail(6)
        
        def format_change_cell(val_today, val_yesterday, divisor, unit):
            if pd.isna(val_today) or pd.isna(val_yesterday):
                return "<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>-</td>"
            diff = val_today - val_yesterday
            pct = (diff / abs(val_yesterday)) * 100 if val_yesterday != 0 else 0
            
            color = "red" if diff > 0 else "blue" if diff < 0 else "#ccc"
            diff_val = diff / divisor
            
            if divisor != 1:
                diff_str = f"{diff_val:.2f}{unit}"
            else:
                diff_str = f"{int(diff_val):,d}{unit}"
                
            display_str = f"{diff_str} ({pct:.2f}%)"
            return f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;font-weight:bold;color:{color};'>{display_str}</td>"
            
        def build_monitoring_table_1(df):
            rows = []
            for i in range(len(df) - 1, 0, -1):
                row_today = df.iloc[i]
                row_yesterday = df.iloc[i - 1]
                date_str = df.index[i].strftime('%Y-%m-%d')
                
                margin_today = f"{row_today['Margin']/10000:.2f}조" if pd.notna(row_today['Margin']) else "-"
                deposit_today = f"{row_today['Deposit']/10000:.2f}조" if pd.notna(row_today['Deposit']) else "-"
                
                margin_change_td = format_change_cell(row_today['Margin'], row_yesterday['Margin'], 10000, "조")
                deposit_change_td = format_change_cell(row_today['Deposit'], row_yesterday['Deposit'], 10000, "조")
                
                rows.append(
                    f"<tr>"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;font-weight:bold;'>{date_str}</td>"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>{margin_today}</td>"
                    f"{margin_change_td}"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>{deposit_today}</td>"
                    f"{deposit_change_td}"
                    f"</tr>"
                )
            return (
                f"<div style='margin-bottom: 0.5rem;'>"
                f"<span style='font-size:0.75rem; font-weight:600;'>📊 1. 신용잔고 · 고객예탁금 (최근 5일)</span>"
                f"<table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;line-height:1.2;'>"
                f"<thead>"
                f"<tr style='background:#1F4E79;color:white;'>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>날짜</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>신용잔고</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>신용잔고 증감</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>예탁금</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>예탁금 증감</th>"
                f"</tr>"
                f"</thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                f"</table>"
                f"</div>"
            )
            
        def build_monitoring_table_2(df):
            rows = []
            for i in range(len(df) - 1, 0, -1):
                row_today = df.iloc[i]
                row_yesterday = df.iloc[i - 1]
                date_str = df.index[i].strftime('%Y-%m-%d')
                
                val_today = f"{row_today['TradingValue']/1000000:.2f}조" if pd.notna(row_today['TradingValue']) else "-"
                change_td = format_change_cell(row_today['TradingValue'], row_yesterday['TradingValue'], 1000000, "조")
                
                rows.append(
                    f"<tr>"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;font-weight:bold;'>{date_str}</td>"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>{val_today}</td>"
                    f"{change_td}"
                    f"</tr>"
                )
            return (
                f"<div style='margin-bottom: 0.5rem;'>"
                f"<span style='font-size:0.75rem; font-weight:600;'>📊 2. 일일거래대금 (최근 5일)</span>"
                f"<table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;line-height:1.2;'>"
                f"<thead>"
                f"<tr style='background:#1F4E79;color:white;'>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>날짜</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>거래대금</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>거래대금 증감</th>"
                f"</tr>"
                f"</thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                f"</table>"
                f"</div>"
            )

        def build_monitoring_table_3(df):
            rows = []
            for i in range(len(df) - 1, 0, -1):
                row_today = df.iloc[i]
                row_yesterday = df.iloc[i - 1]
                date_str = df.index[i].strftime('%Y-%m-%d')
                
                def val_str(v):
                    if pd.isna(v): return "-"
                    return f"{int(v):,d}억"
                    
                r_today = val_str(row_today['Retail'])
                f_today = val_str(row_today['Foreign'])
                i_today = val_str(row_today['Institution'])
                
                r_change = format_change_cell(row_today['Retail'], row_yesterday['Retail'], 1, "억")
                f_change = format_change_cell(row_today['Foreign'], row_yesterday['Foreign'], 1, "억")
                i_change = format_change_cell(row_today['Institution'], row_yesterday['Institution'], 1, "억")
                
                rows.append(
                    f"<tr>"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;font-weight:bold;'>{date_str}</td>"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>{r_today}</td>"
                    f"{r_change}"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>{f_today}</td>"
                    f"{f_change}"
                    f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;'>{i_today}</td>"
                    f"{i_change}"
                    f"</tr>"
                )
            return (
                f"<div style='margin-bottom: 0.5rem;'>"
                f"<span style='font-size:0.75rem; font-weight:600;'>📊 3. 투자자별 일일 순매수 (최근 5일)</span>"
                f"<table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;line-height:1.2;'>"
                f"<thead>"
                f"<tr style='background:#1F4E79;color:white;'>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>날짜</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>개인</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>개인증감</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>외국인</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>외국인 증감</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>기관</th>"
                f"<th style='padding:3px 6px;border:1px solid #444;'>기관 증감</th>"
                f"</tr>"
                f"</thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                f"</table>"
                f"</div>"
            )

        t1, t2, t3 = st.columns(3, gap="small")
        with t1:
            st.markdown(build_monitoring_table_1(df_mon_latest), unsafe_allow_html=True)
        with t2:
            st.markdown(build_monitoring_table_2(df_mon_latest), unsafe_allow_html=True)
        with t3:
            st.markdown(build_monitoring_table_3(df_mon_latest), unsafe_allow_html=True)
            
        st.markdown("<hr style='margin: 0.3rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)
        
        # 2. 3대 모니터링 시계열 차트 (슬로프합 스타일 동기화)
        if not df_mon.empty:
            df_mon_plot = df_mon.copy()
            
            # Determine X range based on active_period_days or entire range
            hd_mon = [fmt_date_kor(d) for d in df_mon_plot.index]
            if active_period_days:
                target_start = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=active_period_days))
                detected_indices = [i for i, d in enumerate(df_mon_plot.index) if d >= target_start]
                initial_x_range_mon = [detected_indices[0], len(hd_mon) - 1] if detected_indices else None
            else:
                initial_x_range_mon = None
                
            # KOSPI Y-range calculation for better scaling
            if active_period_days and detected_indices:
                k_prices = df_mon_plot['KOSPI'].iloc[detected_indices[0]:]
                kmin, kmax = float(k_prices.min()), float(k_prices.max())
            else:
                kmin, kmax = float(df_mon_plot['KOSPI'].min()), float(df_mon_plot['KOSPI'].max())
                
            fig_mon = make_subplots(
                rows=3, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.06,
                subplot_titles=(
                    "코스피 지수 & 신용융자잔고 · 고객예탁금 추이",
                    "코스피 지수 & 일일거래대금 추이",
                    "코스피 지수 & 투자자 순매수 (일일 및 누적) 추이"
                ),
                specs=[[{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": True}]]
            )
            
            # Helper to add KOSPI trace with Slope Sum style
            def add_kospi_trace(row_idx, show_leg=False):
                fig_mon.add_trace(go.Scatter(
                    x=hd_mon, y=df_mon_plot['KOSPI'], 
                    name="코스피 지수", 
                    mode='lines+markers',
                    line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                    marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
                    showlegend=show_leg,
                    hovertemplate='코스피: %{y:,.2f}<extra></extra>'
                ), row=row_idx, col=1, secondary_y=False)

            # Row 1: KOSPI vs Margin & Deposit
            add_kospi_trace(1)
            fig_mon.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Margin']/10000, name="신용잔고 (조원)", line=dict(color="#e74c3c", width=1.0), hovertemplate='신용잔고: %{y:.2f}조<extra></extra>'), row=1, col=1, secondary_y=True)
            fig_mon.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Deposit']/10000, name="고객예탁금 (조원)", line=dict(color="#3498db", width=1.0), hovertemplate='고객예탁금: %{y:.2f}조<extra></extra>'), row=1, col=1, secondary_y=True)
            
            # Row 2: KOSPI vs TradingValue
            add_kospi_trace(2)
            fig_mon.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['TradingValue']/1000000, name="거래대금 (조원)", line=dict(color="#9b59b6", width=1.0), hovertemplate='거래대금: %{y:.2f}조<extra></extra>'), row=2, col=1, secondary_y=True)
            
            # Row 3: KOSPI vs Investors (Daily + Cumulative)
            add_kospi_trace(3)
            
            # Cumulative (Holdings)
            fig_mon.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Retail_Cum']/10000, name="개인 누적 (조원)", line=dict(color="#2ecc71", width=1.0), hovertemplate='개인 누적: %{y:.2f}조<extra></extra>'), row=3, col=1, secondary_y=True)
            fig_mon.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Foreign_Cum']/10000, name="외국인 누적 (조원)", line=dict(color="#e67e22", width=1.0), hovertemplate='외국인 누적: %{y:.2f}조<extra></extra>'), row=3, col=1, secondary_y=True)
            fig_mon.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Institution_Cum']/10000, name="기관 누적 (조원)", line=dict(color="#34495e", width=1.0), hovertemplate='기관 누적: %{y:.2f}조<extra></extra>'), row=3, col=1, secondary_y=True)
            

            
            fig_mon.update_layout(
                **COMMON_LAYOUT,
                height=900,
                margin=dict(l=0, r=50, t=30, b=10),
                showlegend=False # Remove legends from charts
            )
            fig_mon.update_annotations(font_size=10)
            
            # Set border shape and axes to each row
            for i in range(1, 4):
                fig_mon.add_shape(type="rect", xref="x domain", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2), row=i, col=1)
                fig_mon.update_yaxes(range=[kmin*0.95, kmax*1.05], **crosshair_yaxis(), secondary_y=False, row=i, col=1)
                fig_mon.update_yaxes(**crosshair_yaxis(), secondary_y=True, row=i, col=1)
                fig_mon.update_xaxes(type='category', **crosshair_xaxis(), row=i, col=1)
                
            if initial_x_range_mon:
                fig_mon.update_xaxes(range=initial_x_range_mon, row=3, col=1)
                
            st.plotly_chart(fig_mon, width='stretch', config=COMMON_CONFIG, key="mon_subplots")
        else:
            st.info("모니터링 데이터가 없습니다.")

    st.markdown("<hr style='margin: 1.0rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)
    st.markdown("### 국내외 증시 등락 현황")
    with st.spinner("국내외 등락현황 데이터를 가져오는 중..."):
        kp_b, kd_b, ndx_b = fetch_historical_breadth()
        kp_p, kd_p, qqq_p = fetch_index_prices()
        
    def build_historical_breadth_table(df_b, title, is_us=False):
        df_sub = df_b.tail(5)
        headers = ["<th style='padding:3px 6px;border:1px solid #444;color:white;background:#1F4E79;text-align:center;'>날짜</th>"]
        cols = ['상한가', '상승', '보합', '하락', '하한가'] if not is_us else ['상승', '보합', '하락']
        for col in cols:
            headers.append(f"<th style='padding:3px 6px;border:1px solid #444;color:white;background:#1F4E79;text-align:center;'>{col}</th>")
        rows = []
        CM = {'상한가':'#CC0000','상승':'#FF6B9D','보합':'#DDDDDD','하락':'#87CEEB','하한가':'#3399FF'}
        for idx, row in df_sub.iloc[::-1].iterrows():
            date_str = pd.to_datetime(idx).strftime('%Y-%m-%d')
            row_html = [f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;font-weight:bold;'>{date_str}</td>"]
            for col in cols:
                val = row.get(col, 0)
                c = CM.get(col, '#FFF')
                row_html.append(f"<td style='padding:3px 6px;border:1px solid #444;font-weight:bold;color:{c};text-align:center;'>{int(val) if pd.notna(val) else '0'}</td>")
            rows.append(f"<tr>{''.join(row_html)}</tr>")
        return f"""
        <div style='margin-bottom: 0.5rem;'>
            <span style='font-size:0.75rem; font-weight:600;'>{title}</span>
            <table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;'>
                <thead><tr>{''.join(headers)}</tr></thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """

    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        st.markdown(build_historical_breadth_table(kp_b, "🇰🇷 코스피 등락 현황 (최근 5일)"), unsafe_allow_html=True)
    with c2:
        st.markdown(build_historical_breadth_table(kd_b, "🇰🇷 코스닥 등락 현황 (최근 5일)"), unsafe_allow_html=True)
    with c3:
        st.markdown(build_historical_breadth_table(ndx_b, "🇺🇸 나스닥 100 등락 현황 (최근 5일 - 상하한가 제외)", is_us=True), unsafe_allow_html=True)
        
    st.markdown("<hr style='margin: 0.3rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)
    st.markdown("### 📈 대표 종목 기준 등락현황 시계열 추이 (최근 90영업일)")

    # ★ 3개 시장(코스피/코스닥/나스닥)의 날짜를 합쳐서 통합 category 배열 생성
    # 한국/미국 거래일이 달라 shared_xaxes + category에서 충돌 방지용
    all_breadth_dates = set()
    for _df_tmp in [kp_b, kd_b, ndx_b]:
        if not _df_tmp.empty:
            all_breadth_dates.update(pd.to_datetime(_df_tmp.index))
    unified_breadth_dates = sorted(list(all_breadth_dates))
    unified_breadth_hd = [fmt_date_kor(d) for d in unified_breadth_dates]

    fig_breadth = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=(
            "코스피 대표 종목 등락현황 추이 (꺾은선형)",
            "코스닥 대표 종목 등락현황 추이 (꺾은선형)",
            "나스닥 100 대표 종목 등락현황 추이 (꺾은선형 - 상하한 제외)"
        ),
        specs=[[{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": True}]]
    )

    def add_breadth_traces(row_idx, df_b, ps, pname, is_us):
        if not df_b.empty:
            dfp = df_b.copy()
            dfp.index = pd.to_datetime(dfp.index)
            # ★ fmt_date_kor 문자열을 x축으로 사용 (슬로프합 차트와 동일 방식)
            xvals = [fmt_date_kor(d) for d in dfp.index]
            if is_us:
                configs = [
                    ('상승','rgba(255, 107, 157, 0.75)','상승'),
                    ('보합','rgba(170, 170, 170, 0.75)','보합'),
                    ('하락','rgba(135, 206, 235, 0.75)','하락')
                ]
            else:
                configs = [
                    ('상한가','rgba(204, 0, 0, 0.75)','상한가'),
                    ('상승','rgba(255, 107, 157, 0.75)','상승'),
                    ('보합','rgba(170, 170, 170, 0.75)','보합'),
                    ('하락','rgba(135, 206, 235, 0.75)','하락'),
                    ('하한가','rgba(51, 153, 255, 0.75)','하한가')
                ]
            for cn, color, ln in configs:
                if cn in dfp.columns:
                    fig_breadth.add_trace(go.Scatter(
                        x=xvals, y=dfp[cn],
                        mode='lines', name=ln,
                        line=dict(color=color, width=0.5),
                        hovertemplate=f'{ln}: %{{y}}<extra></extra>',
                        showlegend=False
                    ), row=row_idx, col=1, secondary_y=False)
            if ps is not None and len(ps) > 0:
                ps_aligned = ps.reindex(dfp.index, method='nearest', tolerance=pd.Timedelta('3 days'))
                fig_breadth.add_trace(go.Scatter(
                    x=xvals, y=ps_aligned.values,
                    mode='lines+markers', name=pname,
                    line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                    marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
                    hovertemplate=f'{pname}: %{{y:.2f}}<extra></extra>',
                    showlegend=False
                ), row=row_idx, col=1, secondary_y=True)

    add_breadth_traces(1, kp_b, kp_p, "코스피", is_us=False)
    add_breadth_traces(2, kd_b, kd_p, "코스닥", is_us=False)
    add_breadth_traces(3, ndx_b, qqq_p, "QQQ", is_us=True)

    # X범위 계산 (통합 category 인덱스 기반)
    initial_x_range_3 = None
    if unified_breadth_dates and active_period_days:
        target_date_3 = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=active_period_days))
        detected_3 = [i for i, d in enumerate(unified_breadth_dates) if d >= target_date_3]
        initial_x_range_3 = [detected_3[0], len(unified_breadth_hd) - 1] if detected_3 else None

    fig_breadth.update_layout(
        **COMMON_LAYOUT,
        height=850,
        margin=dict(l=0, r=50, t=30, b=10),
        showlegend=False
    )
    fig_breadth.update_annotations(font_size=10)

    for i in range(1, 4):
        fig_breadth.add_shape(type="rect", xref="x domain", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2), row=i, col=1)
        fig_breadth.update_yaxes(**crosshair_yaxis(), secondary_y=False, row=i, col=1)
        fig_breadth.update_yaxes(**crosshair_yaxis(), secondary_y=True, row=i, col=1)
        # ★ 통합 categoryarray 명시 지정으로 shared_xaxes 충돌 방지
        fig_breadth.update_xaxes(
            type='category',
            categoryorder='array',
            categoryarray=unified_breadth_hd,
            **crosshair_xaxis(),
            row=i, col=1
        )

    if initial_x_range_3:
        fig_breadth.update_xaxes(range=initial_x_range_3, row=3, col=1)

    st.plotly_chart(fig_breadth, width='stretch', config=COMMON_CONFIG, key="tab5_breadth_subplots")

# ── Tab 6: 메모리 ──
with tabs[5]:
    dram_data = fetch_dram_dashboard_data()
    if dram_data:
        as_of = dram_data.get('as_of', '')
        st.markdown(f"### 메모리 가격 · DRAM <span style='font-size:0.75rem;color:#8b93a3;float:right;'>기준일: {as_of}</span>", unsafe_allow_html=True)
        
        dxi = dram_data.get('dxi', {'value': 0, 'chg': 0})
        spot_groups = dram_data.get('spot', [])
        
        def get_chg_badge(chg):
            if chg is None: return "-"
            color = "#ff5b5b" if chg >= 0 else "#3b82f6"
            arrow = "▲" if chg >= 0 else "▼"
            bg = "rgba(255,91,91,.12)" if chg >= 0 else "rgba(59,130,246,.12)"
            return f"<span style='color:{color};background:{bg};padding:1px 5px;border-radius:4px;font-weight:600;'>{arrow} {abs(chg):.2f}%</span>"
            
        st.markdown(
            f"<div style='background:#171a21;border:1px solid #262b36;border-radius:10px;padding:6px 12px;margin-bottom:6px;'>"
            f"<table style='width:100%;border-collapse:collapse;border:none !important;margin:0 !important;'>"
            f"<tr style='background:transparent !important;border:none !important;'>"
            f"  <td style='border:none !important;padding:2px 4px !important;font-size:0.75rem;color:#8b93a3;'>DXI 지수</td>"
            f"  <td style='border:none !important;padding:2px 4px !important;font-size:0.85rem;font-weight:700;text-align:right;'>{int(round(dxi.get('value', 0))):,}</td>"
            f"  <td style='border:none !important;padding:2px 4px !important;font-size:0.75rem;text-align:right;'>{get_chg_badge(dxi.get('chg', 0))}</td>"
            f"</tr>"
            f"</table>"
            f"</div>", unsafe_allow_html=True
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 현물가 장기 추이")
        
        # ETF KPI Data
        net_flow = 0
        flow_color = "#ff5b5b"
        flow_arrow = "+"
        price = 0
        premium = 0
        etf_tmp = dram_data.get('etf', {})
        if etf_tmp:
            net_flow = etf_tmp.get('net_flow', 0)
            flow_color = "#ff5b5b" if net_flow >= 0 else "#3b82f6"
            flow_arrow = "+" if net_flow >= 0 else ""
            price = etf_tmp.get('price', 0)
            nav = etf_tmp.get('nav', 1)
            premium = ((price - nav) / nav) * 100
        
        # Data parsing
        monthly_data = dram_data.get('monthly', {})
        dr_m = monthly_data.get('dram', {}) or monthly_data.get('ddr4_8gb', {}) or {'m': [], 'v': []}
        na_m = monthly_data.get('nand', {}) or {'m': [], 'v': []}
        
        customs = dram_data.get('customs', {})
        dr_c = customs.get('dram', {}) if customs else {'m': [], 'v': []}
        na_c = customs.get('nand', {}) if customs else {'m': [], 'v': []}
        
        etf = dram_data.get('etf', {})
        etf_series = etf.get('series', {}) if etf else {'d': [], 'px': []}
        
        five_years_ago_kr = pd.to_datetime('2018-01-01')
        df1_kr = df_kr[df_kr.index >= five_years_ago_kr]
        
        year_prefix = as_of[:4] if as_of else "2026"
        kospi_prices_for_etf = []
        for d_str in etf_series.get('d', []):
            target_dt = pd.to_datetime(f"{year_prefix}-{d_str}")
            if target_dt in df1_kr.index:
                kospi_prices_for_etf.append(df1_kr.loc[target_dt, 'KOSPI'])
            else:
                avail_dates = df1_kr.index[df1_kr.index <= target_dt]
                if not avail_dates.empty:
                    kospi_prices_for_etf.append(df1_kr.loc[avail_dates[-1], 'KOSPI'])
                else:
                    kospi_prices_for_etf.append(None)
        
        if active_period_days:
            start_date = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=active_period_days))
        else:
            start_date = pd.to_datetime('2025-01-01')
            
        df_filtered = df1_kr[df1_kr.index >= start_date]
        if not df_filtered.empty:
            k_min, k_max = df_filtered['KOSPI'].min(), df_filtered['KOSPI'].max()
            kospi_y_range = [k_min * 0.95, k_max * 1.05]
        else:
            kospi_y_range = None

        # 1) 개요 (Overview)
        st.markdown("##### 메모리 차트")
        
        # Collect all unique dates to form a sorted category array for x-axis
        monthly_dates = [pd.to_datetime(m + "-01") for m in dr_m.get('m', [])]
        customs_dates = [pd.to_datetime(m + "-01") for m in dr_c.get('m', [])]
        
        all_dates = set(df1_kr.index)
        all_dates.update(monthly_dates)
        all_dates.update(customs_dates)
        
        # Spot dates
        parsed_spot_dict = {}
        for grp in spot_groups:
            for row in grp[2]:
                tid = row[3]
                series_data = dram_data.get('series', {}).get(str(tid), {'d': [], 'v': []})
                spot_d = series_data.get('d', [])
                parsed = []
                for dt_str in spot_d:
                    if len(dt_str) == 5:
                        d_obj = pd.to_datetime(f"{datetime.date.today().year}-{dt_str}")
                    else:
                        d_obj = pd.to_datetime(dt_str)
                    parsed.append(d_obj)
                    all_dates.add(d_obj)
                parsed_spot_dict[tid] = parsed
                
        sorted_dates = sorted(list(all_dates))
        hd_mem = [fmt_date_kor(d) for d in sorted_dates]
        
        # Determine initial range indices based on active_period_days or 2025-01-01
        if active_period_days:
            target_start = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=active_period_days))
        else:
            target_start = pd.to_datetime('2025-01-01')
            
        detected_indices = [i for i, d in enumerate(sorted_dates) if d >= target_start]
        initial_x_range_idx = [detected_indices[0], len(sorted_dates)-1] if detected_indices else [0, len(sorted_dates)-1]
        
        titles = ["개요"] + [grp[1] for grp in spot_groups]
        fig_mem = make_subplots(
            rows=1+len(spot_groups), cols=1, 
            shared_xaxes=True, vertical_spacing=0.03,
            subplot_titles=titles, 
            specs=[[{"secondary_y": True}]] * (1+len(spot_groups))
        )
        
        # 1) Overview Row
        kospi_hd = [fmt_date_kor(d) for d in df1_kr.index]
        fig_mem.add_trace(go.Scatter(
            x=kospi_hd, y=df1_kr['KOSPI'], name='KOSPI 지수',
            mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
            marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
            hovertemplate='KOSPI: %{y:.2f}<extra></extra>'
        ), row=1, col=1, secondary_y=False)
        
        m_hd = [fmt_date_kor(d) for d in monthly_dates]
        fig_mem.add_trace(go.Scatter(
            x=m_hd, y=dr_m.get('v'), name='DRAM 현물 ($)', line=dict(color='rgba(255, 91, 91, 0.75)', width=0.5),
            hovertemplate='DRAM 현물: $%{y:.2f}<extra></extra>'
        ), row=1, col=1, secondary_y=True)
        fig_mem.add_trace(go.Scatter(
            x=m_hd, y=na_m.get('v'), name='NAND 웨이퍼 ($)', line=dict(color='rgba(217, 154, 43, 0.75)', width=0.5),
            hovertemplate='NAND 웨이퍼: $%{y:.2f}<extra></extra>'
        ), row=1, col=1, secondary_y=True)
        
        c_hd = [fmt_date_kor(d) for d in customs_dates]
        fig_mem.add_trace(go.Scatter(
            x=c_hd, y=dr_c.get('v'), name='수출 DRAM (k$/kg)', line=dict(color='rgba(255, 91, 91, 0.75)', width=0.5, dash='dot'),
            hovertemplate='수출 DRAM: %{y:.2f}k/kg<extra></extra>'
        ), row=1, col=1, secondary_y=True)
        fig_mem.add_trace(go.Scatter(
            x=c_hd, y=na_c.get('v'), name='수출 NAND (k$/kg)', line=dict(color='rgba(217, 154, 43, 0.75)', width=0.5, dash='dot'),
            hovertemplate='수출 NAND: %{y:.2f}k/kg<extra></extra>'
        ), row=1, col=1, secondary_y=True)
        
        # 2) 6 Spot Group Rows
        colors = ['#ff5b5b', '#3b82f6', '#d99a2b', '#10b981', '#8b5cf6', '#f43f5e', '#f59e0b', '#06b6d4', '#6366f1']
        for idx, grp in enumerate(spot_groups):
            row_idx = idx + 2
            
            # KOSPI on left
            fig_mem.add_trace(go.Scatter(
                x=kospi_hd, y=df1_kr['KOSPI'], name=f'KOSPI ({grp[1]})',
                mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
                hovertemplate='KOSPI: %{y:.2f}<extra></extra>', showlegend=False
            ), row=row_idx, col=1, secondary_y=False)
            
            # Series items on right
            for c_idx, row in enumerate(grp[2]):
                item_name = row[0]
                tid = row[3]
                series_data = dram_data.get('series', {}).get(str(tid), {'v': []})
                spot_v = series_data.get('v', [])
                parsed_dates = parsed_spot_dict[tid]
                s_hd = [fmt_date_kor(d) for d in parsed_dates]
                c = colors[c_idx % len(colors)]
                
                fig_mem.add_trace(go.Scatter(
                    x=s_hd, y=spot_v, name=item_name, line=dict(color=c, width=1.5),
                    hovertemplate=f'{item_name}: %{{y:.3f}}<extra></extra>', showlegend=False
                ), row=row_idx, col=1, secondary_y=True)

        fig_mem.update_layout(
            **COMMON_LAYOUT,
            height=2000, 
            margin=dict(l=0, r=0, t=30, b=10),
            showlegend=False,
        )
        fig_mem.update_annotations(font_size=10)
        # Set layout properties
        
        for i in range(1, 8):
            # Apply rectangle shape to each row
            fig_mem.add_shape(type="rect", xref="x domain", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2), row=i, col=1)
            
            # Apply crosshair configs to X and Y axes of each subplot
            fig_mem.update_xaxes(type='category', categoryorder='array', categoryarray=hd_mem, **crosshair_xaxis(), row=i, col=1)
            if kospi_y_range:
                fig_mem.update_yaxes(title_text="", range=kospi_y_range, **crosshair_yaxis(), secondary_y=False, row=i, col=1)
            else:
                fig_mem.update_yaxes(title_text="", **crosshair_yaxis(), secondary_y=False, row=i, col=1)
            fig_mem.update_yaxes(title_text="", **crosshair_yaxis(), secondary_y=True, row=i, col=1)

        # Set initial range for the shared x-axis
        fig_mem.update_xaxes(range=initial_x_range_idx, row=7, col=1)
        
        st.plotly_chart(fig_mem, width='stretch', config=COMMON_CONFIG, key="tab4_merged_all_chart")
        
        # 3. 현물가 상세 표
        def format_price(p):
            if p is None: return "-"
            return f"${p:,.2f}" if p >= 100 else f"${p:.3f}" if p < 20 else f"${p:.2f}"
            
        st.markdown("<br>\n\n#### 현물가 상세", unsafe_allow_html=True)
        tbl_html = """
        <table style="width:100%;border-collapse:collapse;font-size:0.6rem !important;">
            <thead>
                <tr style="background:#1F4E79;color:white;">
                    <th style="padding:2px;border:1px solid #444;">품목명</th>
                    <th style="padding:2px;border:1px solid #444;text-align:right;">가격</th>
                    <th style="padding:2px;border:1px solid #444;text-align:right;">변동률</th>
                </tr>
            </thead>
            <tbody>
        """
        for grp in spot_groups:
            tbl_html += f"<tr><td colspan='3' style='background:#171a21;font-weight:bold;padding:3px;border:1px solid #444;font-size:0.65rem !important;'>{grp[1]}</td></tr>"
            for row in grp[2]:
                tbl_html += f"<tr>"
                tbl_html += f"<td style='padding:2px;border:1px solid #444;'>{row[0]}</td>"
                tbl_html += f"<td style='padding:2px;border:1px solid #444;text-align:right;font-weight:bold;'>{format_price(row[1])}</td>"
                tbl_html += f"<td style='padding:2px;border:1px solid #444;text-align:right;'>{get_chg_badge(row[2])}</td>"
                tbl_html += f"</tr>"
        tbl_html += "</tbody></table>"
        st.markdown(tbl_html, unsafe_allow_html=True)
        
    else:
        st.info("메모리 데이터를 가져오는 데 실패했습니다. 나중에 다시 시도해 주세요.")

# ── Tab 7: 고점지표 ──
with tabs[6]:
    if selected_country == "미국":
        # ===== 저점 감지일 수집 (4개 탭 종합) =====
        # 공탐변동 저점
        _bottom_fgi = (
            ((df['FearGreedIndex'] <= 9) & (df['VIX'] >= 26)) |
            ((df['FearGreedIndex'] >= 10) & (df['FearGreedIndex'] <= 19) & (df['VIX'] >= 22) & (df['VIX'] <= 25)) |
            ((df['FearGreedIndex'] >= 20) & (df['FearGreedIndex'] <= 29) & (df['VIX'] >= 18) & (df['VIX'] <= 21)) |
            ((df['FearGreedIndex'] >= 30) & (df['FearGreedIndex'] <= 39) & (df['VIX'] >= 14) & (df['VIX'] <= 17))
        )
        # 슬로프합 저점
        _bottom_slope = (
            (df['슬로프5일합'] <= -20) | (df['슬로프10일합'] <= -30) |
            (df['슬로프20일합'] <= -40) | (df['슬로프40일합'] <= -50)
        )
        # 다중지표 저점 (multi_count >= 1)
        _multi_conds_for_bottom = [
            (df['QQQ_%B'] * (df['HYG_RSI'] / 100) <= 0.010),
            (df['FearGreedIndex'] * np.exp(df['TNX_ROC'] * 2) / (df['VIX'] + 1e-10) <= 0.35),
            (((df['FearGreedIndex'] - 50) / 20 + (df['QQQ_RSI'] - 50) / 15 + (df['QQQ_%B'] - 0.5) / 0.25 - df['VIX_Z']) <= -5.0),
            ((df['QQQ_%B'] <= 0.01) & (df['FearGreedIndex'] <= 6) & (df['VIX'] >= 25)),
            ((df['QQQ_%B'] <= -0.05) & (df['FearGreedIndex'] <= 7)),
        ]
        _multi_cnt = sum(c.fillna(False).astype(int) for c in _multi_conds_for_bottom)
        _bottom_multi = _multi_cnt >= 1
        
        # 지표상 저점 감지일 (OR 합집합)
        is_bottom_day = (_bottom_fgi | _bottom_slope | _bottom_multi).reindex(df.index).fillna(False)
        
        # ===== 실제 QQQ 차트상 저점 산출 (지표 통계 함수와 동일한 정밀 수식) =====
        _rolling_max = df['QQQ'].rolling(252, min_periods=1).max()
        _drawdown = (_rolling_max - df['QQQ']) / _rolling_max
        _local_min = df['QQQ'].rolling(41, center=True, min_periods=1).min()
        is_actual_bottom = (df['QQQ'] <= _local_min * 1.03) & (_drawdown >= 0.05)
        
        # 지표 감지일 + 실제 QQQ 차트상 저점의 합집합 생성 (상호 배제 강화)
        is_any_bottom = (is_bottom_day | is_actual_bottom).reindex(df.index).fillna(False)
        
        # ===== 고점지표용 보조지표 전처리 =====
        df_top = df.copy()
        
        # Rally-Up: 252일 최저점 대비 상승률
        df_top['QQQ_Low252'] = df_top['QQQ'].rolling(252, min_periods=1).min()
        df_top['QQQ_RU'] = (df_top['QQQ'] - df_top['QQQ_Low252']) / (df_top['QQQ_Low252'] + 1e-10)
        
        # RSI 다이버전스 (가격은 20일 신고가 근처인데 RSI7이 20일전 고점보다 낮음)
        df_top['QQQ_20H'] = df_top['QQQ'].rolling(20).max()
        df_top['RSI7_20H'] = df_top['QQQ_RSI7'].rolling(20).max()
        df_top['RSI_Div'] = (df_top['QQQ'] >= df_top['QQQ_20H'] * 0.99) & (df_top['QQQ_RSI7'] < df_top['RSI7_20H'] - 5)
        
        # MACD
        _ema12 = df_top['QQQ'].ewm(span=12, adjust=False).mean()
        _ema26 = df_top['QQQ'].ewm(span=26, adjust=False).mean()
        df_top['MACD'] = _ema12 - _ema26
        df_top['MACD_Signal'] = df_top['MACD'].ewm(span=9, adjust=False).mean()
        df_top['MACD_Hist'] = df_top['MACD'] - df_top['MACD_Signal']
        
        # 이격도
        df_top['QQQ_MA20'] = df_top['QQQ'].rolling(20).mean()
        df_top['QQQ_MA50'] = df_top['QQQ'].rolling(50).mean()
        df_top['MA20_Dev'] = (df_top['QQQ'] - df_top['QQQ_MA20']) / (df_top['QQQ_MA20'] + 1e-10) * 100
        df_top['MA50_Dev'] = (df_top['QQQ'] - df_top['QQQ_MA50']) / (df_top['QQQ_MA50'] + 1e-10) * 100
        
        # 가속도
        df_top['QQQ_Vel'] = df_top['QQQ'].pct_change(5)
        df_top['QQQ_Accel'] = df_top['QQQ_Vel'].diff(3)
        
        # SKEW Z-Score
        df_top['SKEW_Z'] = (df_top['SKEW'] - df_top['SKEW'].rolling(252).mean()) / (df_top['SKEW'].rolling(252).std() + 1e-5)
        
        # 모든 저점일 마스크 (고점에서 제외)
        _not_bottom = ~is_any_bottom.reindex(df_top.index).fillna(False)
        
        # ===== 소분류 탭 구성 =====
        top_sub_tabs = st.tabs(['공탐변동', '슬로프합', '다중지표', '통합지표'])
        
        # ── 소분류 1: 공탐변동 고점 ──
        with top_sub_tabs[0]:
            five_years_ago_top = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
            df_top1 = df_top[df_top.index >= five_years_ago_top].copy()
            _not_bottom1 = _not_bottom.reindex(df_top1.index).fillna(True)
            
            # 백테스트 결과 기반 4개 조건 + 저점일 제외 (더 넓은 범위의 감지를 위해 완화)
            top_fgi_cond_map = [
                (((df_top1['VIX_Pct']<=0.08)&(df_top1['FGI_Pct']>=0.82)) & _not_bottom1,  '#800080', '#FFFFFF', 'rgba(128,0,128,0.3)'),
                (((df_top1['VIX_Pct']<=0.12)&(df_top1['FearGreedIndex']>=72)) & _not_bottom1, '#E06666', '#FFFFFF', 'rgba(220,30,30,0.3)'),
                (((df_top1['VIX_Pct']<=0.18)&(df_top1['FearGreedIndex']>=65)) & _not_bottom1, '#FF8C00', '#000000', 'rgba(255,140,0,0.3)'),
                ((df_top1['(FGI-VIX)/5']>=11) & _not_bottom1,                            '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
            ]
            
            date_color_map_top = {}
            for cond, bg, fg, _ in reversed(top_fgi_cond_map):
                for d in df_top1[cond].index:
                    date_color_map_top[d] = (bg, fg)
            all_detected_top = sorted(date_color_map_top.keys(), reverse=True)[:50]
            
            TH_SIG = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;"
            TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
            
            if all_detected_top:
                date_cells = "".join([f"<td style='background:{date_color_map_top[d][0]};color:{date_color_map_top[d][1]};font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>" for d in all_detected_top])
                vix_cells = "".join([f"<td style='background:{date_color_map_top[d][0]};color:{date_color_map_top[d][1]};font-weight:bold;{TD_SIG}'>{df_top1.loc[d, 'VIX']:.2f}</td>" for d in all_detected_top])
                fgi_cells = "".join([f"<td style='background:{date_color_map_top[d][0]};color:{date_color_map_top[d][1]};font-weight:bold;{TD_SIG}'>{df_top1.loc[d, 'FearGreedIndex']:.1f}</td>" for d in all_detected_top])
                fv5_cells = "".join([f"<td style='background:{date_color_map_top[d][0]};color:{date_color_map_top[d][1]};font-weight:bold;{TD_SIG}'>{df_top1.loc[d, '(FGI-VIX)/5']:.2f}</td>" for d in all_detected_top])
                
                st.markdown(
                    f"<div style='margin-bottom:0.2rem;'>"
                    f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 고점 과열 감지 날짜 (최근 50개, 저점 감지일 제외)</span>"
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
            
            fig_top1 = make_subplots(specs=[[{"secondary_y": True}]])
            hd_top1 = [fmt_date_kor(d) for d in df_top1.index]
            
            fig_top1.add_trace(go.Scatter(x=hd_top1, y=df_top1['QQQ'], name='QQQ', mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
            fig_top1.add_trace(go.Scatter(x=hd_top1, y=df_top1['VIX'], name='VIX', line=dict(color='rgba(0, 0, 255, 0.75)', width=0.5), hovertemplate='VIX: %{y:.2f}<extra></extra>'), secondary_y=True)
            fig_top1.add_trace(go.Scatter(x=hd_top1, y=df_top1['FearGreedIndex'], name='FGI', line=dict(color='rgba(128, 0, 128, 0.75)', width=0.5), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
            fig_top1.add_trace(go.Scatter(x=hd_top1, y=df_top1['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='rgba(255, 165, 0, 0.75)', width=0.5), hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
            
            max_qqq_top1 = float(df_top1['QQQ'].max()) * 1.2
            for cond, _bg, _fg, fc in top_fgi_cond_map:
                fig_top1.add_trace(go.Bar(x=hd_top1, y=cond.astype(int).values * max_qqq_top1, marker_color=fc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
            
            if active_period_days:
                target_date_t1 = datetime.date.today() - datetime.timedelta(days=active_period_days)
                detected_t1 = [i for i, d in enumerate(df_top1.index) if d >= pd.to_datetime(target_date_t1)]
                initial_x_t1 = [detected_t1[0], len(hd_top1) - 1] if detected_t1 else None
                if detected_t1:
                    qqq_1y_t1 = df_top1['QQQ'].iloc[detected_t1[0]:]
                    qqq_yr_t1 = [float(qqq_1y_t1.min()) * 0.95, float(qqq_1y_t1.max()) * 1.05]
                else:
                    qqq_yr_t1 = [float(df_top1['QQQ'].min()) * 0.95, float(df_top1['QQQ'].max()) * 1.05]
            else:
                initial_x_t1 = None
                qqq_yr_t1 = [float(df_top1['QQQ'].min()) * 0.95, float(df_top1['QQQ'].max()) * 1.05]
            
            fig_top1.update_layout(**COMMON_LAYOUT, height=320, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0,
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
            if initial_x_t1:
                fig_top1.update_xaxes(range=initial_x_t1, type='category', **crosshair_xaxis())
            else:
                fig_top1.update_xaxes(type='category', **crosshair_xaxis())
            fig_top1.update_yaxes(range=qqq_yr_t1, **crosshair_yaxis(), secondary_y=False)
            fig_top1.update_yaxes(**crosshair_yaxis(range=[-10,120]), secondary_y=True)
            
            st.plotly_chart(fig_top1, width='stretch', config=COMMON_CONFIG, key="top_tab_fgi_chart")
            
            # 고점 검증결과 표
            _nb = _not_bottom
            top_fgi_conditions = {
                "**[보라] VIX 극저+FGI 극고**": (((df['VIX_Pct']<=0.08)&(df['FGI_Pct']>=0.82))&_nb, "VIX_Pct≤0.08 & FGI_Pct≥0.82"),
                "**[빨강] VIX 바닥+탐욕**": (((df['VIX_Pct']<=0.12)&(df['FearGreedIndex']>=72))&_nb, "VIX_Pct≤0.12 & FGI≥72"),
                "**[주황] VIX 저위+과열**": (((df['VIX_Pct']<=0.18)&(df['FearGreedIndex']>=65))&_nb, "VIX_Pct≤0.18 & FGI≥65"),
                "**[노랑] FGI-VIX 확장**": ((df['(FGI-VIX)/5']>=11)&_nb, "(FGI-VIX)/5 ≥ 11"),
                "**공탐변동 고점 종합**": (
                    (((df['VIX_Pct']<=0.08)&(df['FGI_Pct']>=0.82)) |
                    ((df['VIX_Pct']<=0.12)&(df['FearGreedIndex']>=72)) |
                    ((df['VIX_Pct']<=0.18)&(df['FearGreedIndex']>=65)) |
                    (df['(FGI-VIX)/5']>=11)) & _nb,
                    "위 4가지 중 하나 이상 감지 (저점일 제외)"
                )
            }
            stats_top1 = calculate_top_stats(df, 'QQQ', top_fgi_conditions)
            st.markdown("<br>", unsafe_allow_html=True)
            render_top_stats_table(stats_top1, "고점 지표검증결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
        
        # ── 소분류 2: 슬로프합 고점 ──
        with top_sub_tabs[1]:
            fig_top_sl = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                subplot_titles=('슬로프 5일합 (상한돌파 고점)','슬로프 10일합 (상한돌파 고점)','슬로프 20일합 (상한돌파 고점)','슬로프 40일합 (상한돌파 고점)'),
                specs=[[{"secondary_y": True}]]*4)
            
            SLOPE_TOP_CHARTS = [
                (1, 5,  '5일상한',  '슬로프5일합',  15),
                (2, 10, '10일상한', '슬로프10일합', 25),
                (3, 20, '20일상한', '슬로프20일합', 30),
                (4, 40, '40일상한', '슬로프40일합', 40),
            ]
            
            # 상한 돌파 신호 감지표 (저점일 제외)
            all_top_sl = []
            for _, days_t, _, sfc, thresh in SLOPE_TOP_CHARTS:
                _cond_sl = (df[sfc]>=thresh) & _not_bottom
                all_top_sl.extend(df[_cond_sl].index.tolist())
            dc_top_sl = Counter(all_top_sl)
            parent_dates_sl = sorted(list(set(all_top_sl)), reverse=True)
            
            if parent_dates_sl:
                r50_sl = parent_dates_sl[:50]
                dates_row_sl = []
                counts_row_sl = []
                for dt in r50_sl:
                    cnt = dc_top_sl.get(dt, 1)
                    bg = "#595959" if cnt==4 else "#E06666" if cnt==3 else "#FFD700" if cnt==2 else "#A9D08E"
                    fg = "#FFF" if cnt>=3 else "#000"
                    dates_row_sl.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    
                    detected_items = []
                    for _, days, _, sc_col, th in SLOPE_TOP_CHARTS:
                        if dt in df.index and df.loc[dt, sc_col] >= th:
                            val_diff = df.loc[dt, sc_col] - th
                            if 0 <= val_diff < 10:
                                color = '#A9D08E'
                            elif 10 <= val_diff < 20:
                                color = '#FFD700'
                            elif 20 <= val_diff < 30:
                                color = '#E06666'
                            else:
                                color = '#595959'
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    
                    val_str = "<br>".join(detected_items)
                    counts_row_sl.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{val_str}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 슬로프합 상한 돌파 고점 신호 (최근 50개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_sl)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>돌파</th>
                        {"".join(counts_row_sl)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            hd_top_sl = [fmt_date_kor(d) for d in df.index]
            for rn, days, uc, sc, thresh in SLOPE_TOP_CHARTS:
                sf = (rn == 1)
                fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=rn,col=1,secondary_y=False)
                fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=df[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(0, 0, 255, 0.75)',width=0.5),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=rn,col=1,secondary_y=True)
                fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=df[uc],name='상한선',line=dict(color='rgba(128, 0, 128, 0.75)',width=0.5,dash='dash'),showlegend=sf,legendgroup='upper_top',hoverinfo='skip'),row=rn,col=1,secondary_y=True)
                
                # 상한 돌파 막대 (저점일 제외, 저점 슬로프합과 동일한 색상/투명도 구조)
                diff_val = df[sc] - thresh
                top_cond_vals = [
                    (((diff_val >= 0) & (diff_val < 10)) & _not_bottom, 'rgba(76,175,80,0.3)'),
                    (((diff_val >= 10) & (diff_val < 20)) & _not_bottom, 'rgba(255,220,0,0.3)'),
                    (((diff_val >= 20) & (diff_val < 30)) & _not_bottom, 'rgba(220,30,30,0.3)'),
                    ((diff_val >= 30) & _not_bottom, 'rgba(0,0,0,0.3)'),
                ]
                for tc, tfc in top_cond_vals:
                    fig_top_sl.add_trace(go.Bar(x=hd_top_sl, y=tc.astype(int).values * float(df['QQQ'].max()) * 1.2, marker_color=tfc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'),row=rn,col=1,secondary_y=False)
            
            if active_period_days:
                target_date_tsl = datetime.date.today() - datetime.timedelta(days=active_period_days)
                detected_tsl = [i for i, d in enumerate(df.index) if d >= pd.to_datetime(target_date_tsl)]
                initial_x_tsl = [detected_tsl[0], len(hd_top_sl) - 1] if detected_tsl else None
                if detected_tsl:
                    qqq_1y_tsl = df['QQQ'].iloc[detected_tsl[0]:]
                    qmin_tsl, qmax_tsl = float(qqq_1y_tsl.min()), float(qqq_1y_tsl.max())
                else:
                    qmin_tsl, qmax_tsl = float(df['QQQ'].min()), float(df['QQQ'].max())
            else:
                initial_x_tsl = None
                qmin_tsl, qmax_tsl = float(df['QQQ'].min()), float(df['QQQ'].max())
            
            layout_params_tsl = COMMON_LAYOUT.copy()
            layout_params_tsl.pop('shapes', None)
            fig_top_sl.update_layout(**layout_params_tsl, height=1200, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0,
                shapes=[
                    dict(type="rect", xref="paper", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                    dict(type="rect", xref="paper", yref="y3 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                    dict(type="rect", xref="paper", yref="y5 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)),
                    dict(type="rect", xref="paper", yref="y7 domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5))
                ])
            for i in range(1, 5):
                fig_top_sl.update_yaxes(range=[qmin_tsl*0.95,qmax_tsl*1.05],**crosshair_yaxis(),secondary_y=False,row=i,col=1)
                fig_top_sl.update_yaxes(range=[-120,180],tick0=-120,dtick=20,**crosshair_yaxis(),secondary_y=True,row=i,col=1)
            if initial_x_tsl:
                fig_top_sl.update_xaxes(range=initial_x_tsl, type='category', **crosshair_xaxis())
            else:
                fig_top_sl.update_xaxes(type='category', **crosshair_xaxis())
            fig_top_sl.update_annotations(font_size=10)
            
            st.plotly_chart(fig_top_sl, width='stretch', config=COMMON_CONFIG, key="top_tab_slope_chart")
            
            # 슬로프합 고점 검증결과 표
            slope_top_conditions = {
                "**5일합 상한돌파**": ((df['슬로프5일합'] >= 15) & _nb, "슬로프5일합 ≥ 15"),
                "**10일합 상한돌파**": ((df['슬로프10일합'] >= 25) & _nb, "슬로프10일합 ≥ 25"),
                "**20일합 상한돌파**": ((df['슬로프20일합'] >= 30) & _nb, "슬로프20일합 ≥ 30"),
                "**40일합 상한돌파**": ((df['슬로프40일합'] >= 40) & _nb, "슬로프40일합 ≥ 40"),
                "**슬로프합 고점 종합**": (
                    ((df['슬로프5일합'] >= 15) | (df['슬로프10일합'] >= 25) | (df['슬로프20일합'] >= 30) | (df['슬로프40일합'] >= 40)) & _nb,
                    "1개 이상 상한선 돌파 (저점일 제외)"
                )
            }
            stats_top_sl = calculate_top_stats(df, 'QQQ', slope_top_conditions)
            st.markdown("<br>", unsafe_allow_html=True)
            render_top_stats_table(stats_top_sl, "고점 지표검증결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
        
        # ── 소분류 3: 다중지표 고점 ──
        with top_sub_tabs[2]:
            _nb_top = _not_bottom.reindex(df_top.index).fillna(True)
            
            # QQQ_RU 백분위 추가 (저점 DD_Pct 대칭용)
            df_top['RU_Pct'] = df_top['QQQ_RU'].rolling(252, min_periods=60).rank(pct=True)
            
            # 49개 고점 후보 조건들 (저점 49개 조건과 1:1 완벽히 매칭 및 반전된 조건식)
            top_multi_conditions_list = [
                # 지표개발 반전 19개
                (df_top['QQQ_%B'] * (df_top['HYG_RSI'] / 100) >= 0.75) & _nb_top,
                ((100 - df_top['FearGreedIndex']) * np.exp(-df_top['TNX_ROC'] * 2) / (df_top['VIX'] + 1e-10) >= 6.0) & _nb_top,
                (((df_top['FearGreedIndex'] - 50) / 20 + (df_top['QQQ_RSI'] - 50) / 15 + (df_top['QQQ_%B'] - 0.5) / 0.25 - df_top['VIX_Z']) >= 4.0) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.99) & (df_top['FearGreedIndex'] >= 94) & (df_top['VIX'] <= 12)) & _nb_top,
                ((df_top['QQQ_%B'] >= 1.05) & (df_top['FearGreedIndex'] >= 93)) & _nb_top,
                ((df_top['슬로프10일합'] >= 40) & (df_top['VIX'] <= 12) & (df_top['FearGreedIndex'] >= 91)) & _nb_top,
                ((df_top['슬로프40일합'] >= 70) & (df_top['FearGreedIndex'] >= 92) & (df_top['QQQ_%B'] >= 0.98)) & _nb_top,
                ((df_top['HYG_RSI'] >= 82) & (df_top['VIX'] <= 11)) & _nb_top,
                ((df_top['FearGreedIndex'] >= 92) & (df_top['VIX'] <= 13) & (df_top['HYG_RSI'] >= 78)) & _nb_top,
                ((df_top['슬로프5일합'] >= 35) & (df_top['QQQ_RSI'] >= 78) & (df_top['VIX'] <= 13)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 85) & (df_top['FearGreedIndex'] >= 85)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 82) & (df_top['FearGreedIndex'] >= 88)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 80) & (df_top['FearGreedIndex'] >= 88)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 78) & (df_top['FearGreedIndex'] >= 88)) & _nb_top,
                ((df_top['VVIX_Z'] <= -2.5) & (df_top['FearGreedIndex'] >= 85)) & _nb_top,
                ((df_top['VVIX_Z'] <= -2.0) & (df_top['FearGreedIndex'] >= 80)) & _nb_top,
                ((df_top['VVIX_Pct'] <= 0.10) & (df_top['FearGreedIndex'] >= 90)) & _nb_top,
                ((df_top['VVIX_Pct'] <= 0.10) & (df_top['QQQ_RSI7'] >= 78)) & _nb_top,
                ((df_top['FearGreedIndex'].diff(7) >= 20) & (df_top['VIX_Pct'] <= 0.15)) & _nb_top,
                # 적중집중 반전 10개
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 72) & (df_top['VVIX_Pct'] <= 0.30)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 60) & (df_top['VVIX_Pct'] <= 0.30)) & _nb_top,
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 6.5) & (df_top['FearGreedIndex'] >= 82) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                (((1000 / (df_top['VIX'] * df_top['VVIX'] + 1e-5)) >= 1.0) & (df_top['FearGreedIndex'] >= 90) & (df_top['QQQ_RU'] >= 0.25)) & _nb_top,
                (((1000 / (df_top['VIX'] * df_top['VVIX'] + 1e-5)) >= 1.0) & (df_top['FearGreedIndex'] >= 90) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 65) & (df_top['VVIX_Pct'] <= 0.30)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 50) & (df_top['VVIX_Pct'] <= 0.30)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 72) & (df_top['VVIX_Pct'] <= 0.20)) & _nb_top,
                ((np.log(np.maximum(-df_top['VVIX_Z'] + 5.0, 1e-5)) * (1 - df_top['VIX_Pct']) >= 1.0) & (df_top['FearGreedIndex'] >= 88) & (df_top['QQQ_%B'] >= 0.85)) & _nb_top,
                (((100 - df_top['FearGreedIndex']) * np.exp(-df_top['TNX_ROC'] * 3) <= 15) & (df_top['QQQ_RSI7'] >= 72) & (df_top['VIX_Pct'] <= 0.20)) & _nb_top,
                # 균형집중 반전 10개
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 5.5) & (df_top['FearGreedIndex'] >= 70) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 4.5) & (df_top['FearGreedIndex'] >= 78) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.90) & (df_top['QQQ_RSI7'] >= 60) & (df_top['FearGreedIndex'] >= 70) & (df_top['VIX_Pct'] <= 0.40) & (df_top['VVIX_Pct'] <= 0.50)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 3 >= 2.5) & (df_top['FGI_Pct'] >= 0.70)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 4 >= 3.0) & (df_top['FGI_Pct'] >= 0.70)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.85) & (df_top['QQQ_RSI7'] >= 65) & (df_top['FearGreedIndex'] >= 80) & (df_top['VIX_Pct'] <= 0.40) & (df_top['VVIX_Pct'] <= 0.50)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 60) & (df_top['VVIX_Pct'] <= 0.50) & (df_top['RU_Pct'] >= 0.70)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 70) & (df_top['VVIX_Pct'] <= 0.50) & (df_top['RU_Pct'] >= 0.40)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 0.8) & (df_top['FearGreedIndex'] >= 88) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 1.0) & (df_top['FearGreedIndex'] >= 88) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                # 포착집중 반전 10개
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 3.5) & (df_top['FearGreedIndex'] >= 60) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 4.0) & (df_top['FearGreedIndex'] >= 55) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.75) & (df_top['QQQ_RSI7'] >= 50) & (df_top['FearGreedIndex'] >= 60) & (df_top['VIX_Pct'] <= 0.60) & (df_top['VVIX_Pct'] <= 0.60)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 2 >= 2.0) & (df_top['FGI_Pct'] >= 0.65)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.80) & (df_top['QQQ_RSI7'] >= 50) & (df_top['FearGreedIndex'] >= 55) & (df_top['VIX_Pct'] <= 0.60) & (df_top['VVIX_Pct'] <= 0.60)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 2 >= 1.5) & (df_top['FGI_Pct'] >= 0.65)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 45) & (df_top['VVIX_Pct'] <= 0.70) & (df_top['RU_Pct'] >= 0.50)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 50) & (df_top['VVIX_Pct'] <= 0.70) & (df_top['RU_Pct'] >= 0.50)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 0.3) & (df_top['FearGreedIndex'] >= 82) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 0.5) & (df_top['FearGreedIndex'] >= 82) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top,
            ]
            
            df_top['top_multi_count'] = sum(cond.reindex(df_top.index).fillna(False).astype(int) for cond in top_multi_conditions_list)
            
            if active_period_days:
                target_date_tm = datetime.date.today() - datetime.timedelta(days=active_period_days)
                detected_tm = [i for i, d in enumerate(df_top.index) if d >= pd.to_datetime(target_date_tm)]
                initial_x_tm = [detected_tm[0], len(df_top.index) - 1] if detected_tm else None
                if detected_tm:
                    qqq_1y_tm = df_top['QQQ'].iloc[detected_tm[0]:]
                    qqq_yr_tm = [float(qqq_1y_tm.min()) * 0.95, float(qqq_1y_tm.max()) * 1.05]
                else:
                    qqq_yr_tm = [float(df_top['QQQ'].min()) * 0.95, float(df_top['QQQ'].max()) * 1.05]
            else:
                initial_x_tm = None
                qqq_yr_tm = [float(df_top['QQQ'].min()) * 0.95, float(df_top['QQQ'].max()) * 1.05]
            
            max_qqq_tm = float(df_top['QQQ'].max()) * 1.2
            
            # 색상 매핑 (저점 다중지표 탭과 100% 동일하게 49개 기준으로 빨주노초파남보 설정)
            top_cond_map = [
                ((df_top['top_multi_count'] >= 1) & (df_top['top_multi_count'] <= 7), 'rgba(224,102,102,0.5)', '#E06666', '1~7개 감지'), # 빨간색
                ((df_top['top_multi_count'] >= 8) & (df_top['top_multi_count'] <= 14), 'rgba(255,140,0,0.5)', '#FF8C00', '8~14개 감지'), # 주황색
                ((df_top['top_multi_count'] >= 15) & (df_top['top_multi_count'] <= 21), 'rgba(255,255,153,0.5)', '#FFFF99', '15~21개 감지'), # 노란색
                ((df_top['top_multi_count'] >= 22) & (df_top['top_multi_count'] <= 28), 'rgba(169,208,142,0.5)', '#A9D08E', '22~28개 감지'), # 초록색
                ((df_top['top_multi_count'] >= 29) & (df_top['top_multi_count'] <= 35), 'rgba(135,206,235,0.5)', '#87CEEB', '29~35개 감지'), # 파란색
                ((df_top['top_multi_count'] >= 36) & (df_top['top_multi_count'] <= 42), 'rgba(0,0,128,0.5)', '#000080', '36~42개 감지'), # 남색
                ((df_top['top_multi_count'] >= 43) & (df_top['top_multi_count'] <= 49), 'rgba(128,0,128,0.5)', '#800080', '43~49개 감지'), # 보라색
            ]
            
            # 감지 신호표 (1개 이상 감지된 날 기준)
            df_sig_tm = df_top[df_top['top_multi_count'] >= 1].sort_index(ascending=False).head(50)
            if not df_sig_tm.empty:
                dates_row_tm = []
                counts_row_tm = []
                for dt, row in df_sig_tm.iterrows():
                    cnt = row['top_multi_count']
                    bg = '#E06666'
                    for c, bar_c, tbl_c, lbl in top_cond_map:
                        if c.loc[dt]:
                            bg = tbl_c
                            break
                    fg = "#FFF" if bg in ['#E06666', '#000080', '#800080'] else "#000"
                    dates_row_tm.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    counts_row_tm.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{int(cnt)}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 고점 감지 신호 (최근 50개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_tm)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>갯수</th>
                        {"".join(counts_row_tm)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            fig_top_multi = make_subplots(specs=[[{"secondary_y": True}]])
            hd_top_multi = [fmt_date_kor(d) for d in df_top.index]
            
            fig_top_multi.add_trace(go.Scatter(x=hd_top_multi, y=df_top['QQQ'], name='QQQ 가격', mode='lines+markers',
                line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
                hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
            
            # 그래프 막대: top_cond_map의 bar_color 사용 (표와 동일 계열)
            for cond, bar_color, tbl_color, label in top_cond_map:
                fig_top_multi.add_trace(go.Bar(x=hd_top_multi, y=cond.astype(int).values * max_qqq_tm,
                    marker_color=bar_color, showlegend=False, hoverinfo='skip',
                    marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
            
            fig_top_multi.update_layout(**COMMON_LAYOUT, height=400, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0,
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
            if initial_x_tm:
                fig_top_multi.update_xaxes(range=initial_x_tm, type='category', **crosshair_xaxis())
            else:
                fig_top_multi.update_xaxes(type='category', **crosshair_xaxis())
            fig_top_multi.update_yaxes(range=qqq_yr_tm, **crosshair_yaxis(), secondary_y=False, title_text="")
            fig_top_multi.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
            
            st.plotly_chart(fig_top_multi, width='stretch', config=COMMON_CONFIG, key="top_tab_multi_chart")
            
            # 다중지표 고점 검증결과 (저점 다중지표 탭과 동일하게 7단계 구간 통계)
            top_multi_verify = {
                "**빨간색**": (top_cond_map[0][0], top_cond_map[0][3]),
                "**주황색**": (top_cond_map[1][0], top_cond_map[1][3]),
                "**노란색**": (top_cond_map[2][0], top_cond_map[2][3]),
                "**초록색**": (top_cond_map[3][0], top_cond_map[3][3]),
                "**파란색**": (top_cond_map[4][0], top_cond_map[4][3]),
                "**남색**":   (top_cond_map[5][0], top_cond_map[5][3]),
                "**보라색**": (top_cond_map[6][0], top_cond_map[6][3]),
            }
            stats_top_multi = calculate_top_stats(df_top, 'QQQ', top_multi_verify)
            st.markdown("<br>", unsafe_allow_html=True)
            render_top_stats_table(stats_top_multi, "지표검증결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
        
        # ── 소분류 4: 통합지표 고점 ──
        with top_sub_tabs[3]:
            _nb_top2 = _not_bottom.reindex(df_top.index).fillna(True)
            
            # 후보1: 과열 에너지 공식
            energy_top = (df_top['FearGreedIndex']/100) * df_top['QQQ_%B'] * (df_top['QQQ_RSI7']/100)
            c_top_1 = ((energy_top >= 0.55) & (df_top['VIX_Pct'] <= 0.20)) & _nb_top2
            
            # 후보2: RSI 다이버전스 + Rally-Up 복합
            c_top_2 = ((df_top['RSI_Div']) & (df_top['QQQ_RU'] >= 0.30)) & _nb_top2
            
            # 후보3: MACD 전환 + %B 과매수 + VIX 안일
            c_top_3 = ((df_top['MACD_Hist'].diff() < 0) & (df_top['MACD_Hist'] > 0) & (df_top['QQQ_%B'] >= 0.90) & (df_top['VIX_Pct'] <= 0.20)) & _nb_top2
            
            # 후보4: SKEW 급등 + VIX 저위 + RSI7 과매수
            c_top_4 = ((df_top['SKEW'] >= 145) & (df_top['VIX'] <= 15) & (df_top['QQQ_RSI7'] >= 70)) & _nb_top2
            
            # 후보5: 통합 (OR)
            c_top_all = c_top_1 | c_top_2 | c_top_3 | c_top_4
            
            # 감지 신호표
            triggered_dates_top = df_top[c_top_all].index.sort_values(ascending=False)
            recent_50_top = triggered_dates_top[:50]
            if len(recent_50_top) > 0:
                dates_row_top = ""
                for dt in recent_50_top:
                    cnt = int(c_top_1.loc[dt]) + int(c_top_2.loc[dt]) + int(c_top_3.loc[dt]) + int(c_top_4.loc[dt])
                    bg = '#800080' if cnt >= 3 else '#E06666' if cnt >= 2 else '#FF8C00'
                    fg = '#FFF'
                    dates_row_top += f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 4대 통합 고점 감지 신호 (최근 50개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                        {dates_row_top}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
            
            # 차트
            if active_period_days:
                target_date_tt = datetime.date.today() - datetime.timedelta(days=active_period_days)
                df_top_plot = df_top[df_top.index >= pd.to_datetime(target_date_tt)]
                if not df_top_plot.empty:
                    qqq_yr_tt = [float(df_top_plot['QQQ'].min()) * 0.95, float(df_top_plot['QQQ'].max()) * 1.05]
                    initial_x_tt = [df_top_plot.index[0].strftime("%Y-%m-%d"), df_top_plot.index[-1].strftime("%Y-%m-%d")]
                else:
                    qqq_yr_tt = None
                    initial_x_tt = None
            else:
                df_top_plot = df_top.copy()
                if not df_top_plot.empty:
                    qqq_yr_tt = [float(df_top_plot['QQQ'].min()) * 0.95, float(df_top_plot['QQQ'].max()) * 1.05]
                    initial_x_tt = [df_top_plot.index[0].strftime("%Y-%m-%d"), df_top_plot.index[-1].strftime("%Y-%m-%d")]
                else:
                    qqq_yr_tt = None
                    initial_x_tt = None
            
            fig_top_final = make_subplots(specs=[[{"secondary_y": True}]])
            hd_top_final = [fmt_date_kor(d) for d in df_top_plot.index]
            
            fig_top_final.add_trace(go.Scatter(
                x=hd_top_final, y=df_top_plot['QQQ'], name='QQQ 가격', mode='lines+markers',
                line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
                hovertemplate='QQQ: %{y:.2f}<extra></extra>'
            ), secondary_y=False)
            
            fig_top_final.add_trace(go.Bar(
                x=hd_top_final, y=c_top_all.reindex(df_top_plot.index).astype(int).values * (qqq_yr_tt[1] if qqq_yr_tt else 600), name='통합 고점 감지 (OR)',
                marker_color='rgba(128, 0, 128, 0.7)',
                marker_line_width=0.5, marker_line_color='white',
                hovertemplate='고점 신호 감지<extra></extra>'
            ), secondary_y=False)
            
            fig_top_final.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0,r=50,t=10,b=10), showlegend=False,
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.0))])
            fig_top_final.update_xaxes(type='category', **crosshair_xaxis())
            if initial_x_tt:
                fig_top_final.update_xaxes(range=initial_x_tt)
            fig_top_final.update_yaxes(title_text="", range=qqq_yr_tt, **crosshair_yaxis(), secondary_y=False)
            fig_top_final.update_yaxes(range=[0, 1.2], showticklabels=False, showgrid=False, secondary_y=True)
            
            st.plotly_chart(fig_top_final, width='stretch', config=COMMON_CONFIG, key="top_tab_final_chart")
            
            # 통합지표 고점 검증결과 표
            top_final_conditions = {
                "**최종 4대 통합 고점지표 (OR)**": (c_top_all, '과열에너지 + RSI다이버전스·RU + MACD전환 + SKEW경고'),
            }
            stats_top_final = calculate_top_stats(df_top, 'QQQ', top_final_conditions)
            render_top_stats_table(stats_top_final, "통합 고점지표 검증 결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
    
    else:
        st.info("한국 데이터는 향후 지원 예정입니다. 국가 선택을 '미국'으로 변경해 주세요.")

# ── Tab 8: 고점개발 ──
with tabs[7]:
    if selected_country == "미국":
        # 1. 저점 및 실제 QQQ 저점 수집 (상호 배제용)
        _bottom_fgi = (
            ((df['FearGreedIndex'] <= 9) & (df['VIX'] >= 26)) |
            ((df['FearGreedIndex'] >= 10) & (df['FearGreedIndex'] <= 19) & (df['VIX'] >= 22) & (df['VIX'] <= 25)) |
            ((df['FearGreedIndex'] >= 20) & (df['FearGreedIndex'] <= 29) & (df['VIX'] >= 18) & (df['VIX'] <= 21)) |
            ((df['FearGreedIndex'] >= 30) & (df['FearGreedIndex'] <= 39) & (df['VIX'] >= 14) & (df['VIX'] <= 17))
        )
        _bottom_slope = (
            (df['슬로프5일합'] <= -20) | (df['슬로프10일합'] <= -30) |
            (df['슬로프20일합'] <= -40) | (df['슬로프40일합'] <= -50)
        )
        _multi_conds_for_bottom = [
            (df['QQQ_%B'] * (df['HYG_RSI'] / 100) <= 0.010),
            (df['FearGreedIndex'] * np.exp(df['TNX_ROC'] * 2) / (df['VIX'] + 1e-10) <= 0.35),
            (((df['FearGreedIndex'] - 50) / 20 + (df['QQQ_RSI'] - 50) / 15 + (df['QQQ_%B'] - 0.5) / 0.25 - df['VIX_Z']) <= -5.0),
            ((df['QQQ_%B'] <= 0.01) & (df['FearGreedIndex'] <= 6) & (df['VIX'] >= 25)),
            ((df['QQQ_%B'] <= -0.05) & (df['FearGreedIndex'] <= 7)),
        ]
        _multi_cnt = sum(c.fillna(False).astype(int) for c in _multi_conds_for_bottom)
        _bottom_multi = _multi_cnt >= 1
        
        is_bottom_day = (_bottom_fgi | _bottom_slope | _bottom_multi).reindex(df.index).fillna(False)
        
        _rolling_max = df['QQQ'].rolling(252, min_periods=1).max()
        _drawdown = (_rolling_max - df['QQQ']) / _rolling_max
        _local_min = df['QQQ'].rolling(41, center=True, min_periods=1).min()
        is_actual_bottom = (df['QQQ'] <= _local_min * 1.03) & (_drawdown >= 0.05)
        
        is_any_bottom = (is_bottom_day | is_actual_bottom).reindex(df.index).fillna(False)
        _not_bottom = ~is_any_bottom
        
        # 보조지표 구하기
        df_dev = df.copy()
        df_dev['QQQ_Low252'] = df_dev['QQQ'].rolling(252, min_periods=1).min()
        df_dev['QQQ_RU'] = (df_dev['QQQ'] - df_dev['QQQ_Low252']) / (df_dev['QQQ_Low252'] + 1e-10)
        df_dev['RU_Pct'] = df_dev['QQQ_RU'].rolling(252, min_periods=60).rank(pct=True)
        
        df_dev['QQQ_20H'] = df_dev['QQQ'].rolling(20).max()
        df_dev['RSI7_20H'] = df_dev['QQQ_RSI7'].rolling(20).max()
        df_dev['RSI_Div'] = (df_dev['QQQ'] >= df_dev['QQQ_20H'] * 0.99) & (df_dev['QQQ_RSI7'] < df_dev['RSI7_20H'] - 5)
        
        _ema12 = df_dev['QQQ'].ewm(span=12, adjust=False).mean()
        _ema26 = df_dev['QQQ'].ewm(span=26, adjust=False).mean()
        df_dev['MACD'] = _ema12 - _ema26
        df_dev['MACD_Signal'] = df_dev['MACD'].ewm(span=9, adjust=False).mean()
        df_dev['MACD_Hist'] = df_dev['MACD'] - df_dev['MACD_Signal']
        
        df_dev['QQQ_MA20'] = df_dev['QQQ'].rolling(20).mean()
        df_dev['QQQ_MA50'] = df_dev['QQQ'].rolling(50).mean()
        df_dev['MA20_Dev'] = (df_dev['QQQ'] - df_dev['QQQ_MA20']) / (df_dev['QQQ_MA20'] + 1e-10) * 100
        df_dev['MA50_Dev'] = (df_dev['QQQ'] - df_dev['QQQ_MA50']) / (df_dev['QQQ_MA50'] + 1e-10) * 100
        
        df_dev['QQQ_Vel'] = df_dev['QQQ'].pct_change(5)
        df_dev['QQQ_Accel'] = df_dev['QQQ_Vel'].diff(3)
        df_dev['SKEW_Z'] = (df_dev['SKEW'] - df_dev['SKEW'].rolling(252).mean()) / (df_dev['SKEW'].rolling(252).std() + 1e-5)
        
        # 다중지표 갯수
        conds_multi = [
            (df_dev['QQQ_%B'] * (df_dev['HYG_RSI'] / 100) >= 0.75) & _not_bottom,
            ((100 - df_dev['FearGreedIndex']) * np.exp(-df_dev['TNX_ROC'] * 2) / (df_dev['VIX'] + 1e-10) >= 6.0) & _not_bottom,
            (((df_dev['FearGreedIndex'] - 50) / 20 + (df_dev['QQQ_RSI'] - 50) / 15 + (df_dev['QQQ_%B'] - 0.5) / 0.25 - df_dev['VIX_Z']) >= 4.0) & _not_bottom,
            ((df_dev['QQQ_%B'] >= 0.99) & (df_dev['FearGreedIndex'] >= 94) & (df_dev['VIX'] <= 12)) & _not_bottom,
            ((df_dev['QQQ_%B'] >= 1.05) & (df_dev['FearGreedIndex'] >= 93)) & _not_bottom,
            ((df_dev['슬로프10일합'] >= 40) & (df_dev['VIX'] <= 12) & (df_dev['FearGreedIndex'] >= 91)) & _not_bottom,
            ((df_dev['슬로프40일합'] >= 70) & (df_dev['FearGreedIndex'] >= 92) & (df_dev['QQQ_%B'] >= 0.98)) & _not_bottom,
            ((df_dev['HYG_RSI'] >= 82) & (df_dev['VIX'] <= 11)) & _not_bottom,
            ((df_dev['FearGreedIndex'] >= 92) & (df_dev['VIX'] <= 13) & (df_dev['HYG_RSI'] >= 78)) & _not_bottom,
            ((df_dev['슬로프5일합'] >= 35) & (df_dev['QQQ_RSI'] >= 78) & (df_dev['VIX'] <= 13)) & _not_bottom,
            ((df_dev['QQQ_RSI7'] >= 85) & (df_dev['FearGreedIndex'] >= 85)) & _not_bottom,
            ((df_dev['QQQ_RSI7'] >= 82) & (df_dev['FearGreedIndex'] >= 88)) & _not_bottom,
            ((df_dev['QQQ_RSI7'] >= 80) & (df_dev['FearGreedIndex'] >= 88)) & _not_bottom,
            ((df_dev['QQQ_RSI7'] >= 78) & (df_dev['FearGreedIndex'] >= 88)) & _not_bottom,
            ((df_dev['VVIX_Z'] <= -2.5) & (df_dev['FearGreedIndex'] >= 85)) & _not_bottom,
            ((df_dev['VVIX_Z'] <= -2.0) & (df_dev['FearGreedIndex'] >= 80)) & _not_bottom,
            ((df_dev['VVIX_Pct'] <= 0.10) & (df_dev['FearGreedIndex'] >= 90)) & _not_bottom,
            ((df_dev['VVIX_Pct'] <= 0.10) & (df_dev['QQQ_RSI7'] >= 78)) & _not_bottom,
            ((df_dev['FearGreedIndex'].diff(7) >= 20) & (df_dev['VIX_Pct'] <= 0.15)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 72) & (df_dev['VVIX_Pct'] <= 0.30)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 60) & (df_dev['VVIX_Pct'] <= 0.30)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / (df_dev['VVIX'] + 1e-5)) >= 6.5) & (df_dev['FearGreedIndex'] >= 82) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            (((1000 / (df_dev['VIX'] * df_dev['VVIX'] + 1e-5)) >= 1.0) & (df_dev['FearGreedIndex'] >= 90) & (df_dev['QQQ_RU'] >= 0.25)) & _not_bottom,
            (((1000 / (df_dev['VIX'] * df_dev['VVIX'] + 1e-5)) >= 1.0) & (df_dev['FearGreedIndex'] >= 90) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 65) & (df_dev['VVIX_Pct'] <= 0.30)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 50) & (df_dev['VVIX_Pct'] <= 0.30)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 72) & (df_dev['VVIX_Pct'] <= 0.20)) & _not_bottom,
            ((np.log(np.maximum(-df_dev['VVIX_Z'] + 5.0, 1e-5)) * (1 - df_dev['VIX_Pct']) >= 1.0) & (df_dev['FearGreedIndex'] >= 88) & (df_dev['QQQ_%B'] >= 0.85)) & _not_bottom,
            (((100 - df_dev['FearGreedIndex']) * np.exp(-df_dev['TNX_ROC'] * 3) <= 15) & (df_dev['QQQ_RSI7'] >= 72) & (df_dev['VIX_Pct'] <= 0.20)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / (df_dev['VVIX'] + 1e-5)) >= 5.5) & (df_dev['FearGreedIndex'] >= 70) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / (df_dev['VVIX'] + 1e-5)) >= 4.5) & (df_dev['FearGreedIndex'] >= 78) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            ((df_dev['QQQ_%B'] >= 0.90) & (df_dev['QQQ_RSI7'] >= 60) & (df_dev['FearGreedIndex'] >= 70) & (df_dev['VIX_Pct'] <= 0.40) & (df_dev['VVIX_Pct'] <= 0.50)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / 100) + df_dev['RU_Pct'] * 3 >= 2.5) & (df_dev['FGI_Pct'] >= 0.70)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / 100) + df_dev['RU_Pct'] * 4 >= 3.0) & (df_dev['FGI_Pct'] >= 0.70)) & _not_bottom,
            ((df_dev['QQQ_%B'] >= 0.85) & (df_dev['QQQ_RSI7'] >= 65) & (df_dev['FearGreedIndex'] >= 80) & (df_dev['VIX_Pct'] <= 0.40) & (df_dev['VVIX_Pct'] <= 0.50)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 60) & (df_dev['VVIX_Pct'] <= 0.50) & (df_dev['RU_Pct'] >= 0.70)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 70) & (df_dev['VVIX_Pct'] <= 0.50) & (df_dev['RU_Pct'] >= 0.40)) & _not_bottom,
            ((df_dev['VIX_Z'] * df_dev['VVIX_Z'] >= 0.8) & (df_dev['FearGreedIndex'] >= 88) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            ((df_dev['VIX_Z'] * df_dev['VVIX_Z'] >= 1.0) & (df_dev['FearGreedIndex'] >= 88) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / (df_dev['VVIX'] + 1e-5)) >= 3.5) & (df_dev['FearGreedIndex'] >= 60) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / (df_dev['VVIX'] + 1e-5)) >= 4.0) & (df_dev['FearGreedIndex'] >= 55) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            ((df_dev['QQQ_%B'] >= 0.75) & (df_dev['QQQ_RSI7'] >= 50) & (df_dev['FearGreedIndex'] >= 60) & (df_dev['VIX_Pct'] <= 0.60) & (df_dev['VVIX_Pct'] <= 0.60)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / 100) + df_dev['RU_Pct'] * 2 >= 2.0) & (df_dev['FGI_Pct'] >= 0.65)) & _not_bottom,
            ((df_dev['QQQ_%B'] >= 0.80) & (df_dev['QQQ_RSI7'] >= 50) & (df_dev['FearGreedIndex'] >= 55) & (df_dev['VIX_Pct'] <= 0.60) & (df_dev['VVIX_Pct'] <= 0.60)) & _not_bottom,
            (((df_dev['QQQ_RSI7'] / 100) + df_dev['RU_Pct'] * 2 >= 1.5) & (df_dev['FGI_Pct'] >= 0.65)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 45) & (df_dev['VVIX_Pct'] <= 0.70) & (df_dev['RU_Pct'] >= 0.50)) & _not_bottom,
            ((df_dev['FearGreedIndex'] * df_dev['QQQ_%B'] >= 50) & (df_dev['VVIX_Pct'] <= 0.70) & (df_dev['RU_Pct'] >= 0.50)) & _not_bottom,
            ((df_dev['VIX_Z'] * df_dev['VVIX_Z'] >= 0.3) & (df_dev['FearGreedIndex'] >= 82) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
            ((df_dev['VIX_Z'] * df_dev['VVIX_Z'] >= 0.5) & (df_dev['FearGreedIndex'] >= 82) & (df_dev['QQQ_RU'] >= 0.30)) & _not_bottom,
        ]
        cnt = sum(c.fillna(False).astype(int) for c in conds_multi)
        
        # 4대 통합지표
        energy_top = (df_dev['FearGreedIndex']/100) * df_dev['QQQ_%B'] * (df_dev['QQQ_RSI7']/100)
        c_top_1 = ((energy_top >= 0.55) & (df_dev['VIX_Pct'] <= 0.20))
        c_top_2 = ((df_dev['RSI_Div']) & (df_dev['QQQ_RU'] >= 0.30))
        c_top_3 = ((df_dev['MACD_Hist'].diff() < 0) & (df_dev['MACD_Hist'] > 0) & (df_dev['QQQ_%B'] >= 0.90) & (df_dev['VIX_Pct'] <= 0.20))
        c_top_4 = ((df_dev['SKEW'] >= 145) & (df_dev['VIX'] <= 15) & (df_dev['QQQ_RSI7'] >= 70))
        c_top_all = c_top_1 | c_top_2 | c_top_3 | c_top_4

        # ──────────────────────────────────────────────────────────
        # [기존 책정안] 원래의 고점개발 위험 점수 책정안
        # ──────────────────────────────────────────────────────────
        # 공탐변동 (원래)
        score_fgi_orig = pd.Series(0.0, index=df_dev.index)
        score_fgi_orig.loc[((df_dev['(FGI-VIX)/5'] >= 11) & _not_bottom)] = 1.0
        score_fgi_orig.loc[((df_dev['VIX_Pct'] <= 0.18) & (df_dev['FearGreedIndex'] >= 65) & _not_bottom)] = 1.5
        score_fgi_orig.loc[((df_dev['VIX_Pct'] <= 0.12) & (df_dev['FearGreedIndex'] >= 72) & _not_bottom)] = 2.0
        score_fgi_orig.loc[((df_dev['VIX_Pct'] <= 0.08) & (df_dev['FGI_Pct'] >= 0.82) & _not_bottom)] = 2.5
        
        # 슬로프합 (원래)
        score_slope_orig = pd.Series(0.0, index=df_dev.index)
        slope_setups_orig = [
            ('슬로프5일합', 15, 1.0),
            ('슬로프10일합', 25, 1.5),
            ('슬로프20일합', 30, 2.0),
            ('슬로프40일합', 40, 2.5),
        ]
        for col, thresh, weight in slope_setups_orig:
            val = df_dev[col]
            c_score = pd.Series(0.0, index=df_dev.index)
            c_score.loc[((val >= thresh) & (val < thresh * 1.5))] = 1.0
            c_score.loc[((val >= thresh * 1.5) & (val < thresh * 2.0))] = 1.5
            c_score.loc[((val >= thresh * 2.0) & (val < thresh * 2.5))] = 2.0
            c_score.loc[((val >= thresh * 2.5))] = 2.5
            score_slope_orig += c_score * weight
        score_slope_orig = score_slope_orig * _not_bottom.astype(float)
        
        # 다중지표 (원래)
        score_multi_orig = pd.Series(0.0, index=df_dev.index)
        score_multi_orig.loc[((cnt >= 1) & (cnt <= 7))] = 1.0
        score_multi_orig.loc[((cnt >= 8) & (cnt <= 14))] = 2.0
        score_multi_orig.loc[((cnt >= 15) & (cnt <= 21))] = 3.0
        score_multi_orig.loc[((cnt >= 22) & (cnt <= 28))] = 4.0
        score_multi_orig.loc[((cnt >= 29) & (cnt <= 35))] = 5.0
        score_multi_orig.loc[((cnt >= 36) & (cnt <= 42))] = 6.0
        score_multi_orig.loc[((cnt >= 43))] = 7.0
        score_multi_orig = score_multi_orig * _not_bottom.astype(float)
        
        # 통합지표 (원래)
        score_unified_orig = c_top_all.astype(float) * 2.0
        score_unified_orig = score_unified_orig * _not_bottom.astype(float)
        
        df_dev['score_orig'] = score_fgi_orig + score_slope_orig + score_multi_orig + score_unified_orig

        # ──────────────────────────────────────────────────────────
        # [버전 1] 신뢰도 비례 점수 책정안 (신규 제안안)
        # ──────────────────────────────────────────────────────────
        # 공탐변동 (가중치 낮음)
        score_fgi_v1 = pd.Series(0.0, index=df_dev.index)
        score_fgi_v1.loc[((df_dev['(FGI-VIX)/5'] >= 11) & _not_bottom)] = 1.0
        score_fgi_v1.loc[((df_dev['VIX_Pct'] <= 0.18) & (df_dev['FearGreedIndex'] >= 65) & _not_bottom)] = 1.2
        score_fgi_v1.loc[((df_dev['VIX_Pct'] <= 0.12) & (df_dev['FearGreedIndex'] >= 72) & _not_bottom)] = 1.5
        score_fgi_v1.loc[((df_dev['VIX_Pct'] <= 0.08) & (df_dev['FGI_Pct'] >= 0.82) & _not_bottom)] = 1.8
        
        # 슬로프합 (가중치 보통, 중첩 제어)
        score_slope_v1 = pd.Series(0.0, index=df_dev.index)
        slope_setups_v1 = [
            ('슬로프5일합', 15, 1.0),
            ('슬로프10일합', 25, 1.2),
            ('슬로프20일합', 30, 1.5),
            ('슬로프40일합', 40, 1.8),
        ]
        for col, thresh, weight in slope_setups_v1:
            val = df_dev[col]
            c_score = pd.Series(0.0, index=df_dev.index)
            c_score.loc[((val >= thresh) & (val < thresh * 1.5))] = 1.0
            c_score.loc[((val >= thresh * 1.5) & (val < thresh * 2.0))] = 1.5
            c_score.loc[((val >= thresh * 2.0) & (val < thresh * 2.5))] = 2.0
            c_score.loc[((val >= thresh * 2.5))] = 2.5
            score_slope_v1 += c_score * weight
        score_slope_v1 = score_slope_v1 * _not_bottom.astype(float)
        
        # 다중지표 (신뢰도 높음, 가중치 대폭 강화)
        score_multi_v1 = pd.Series(0.0, index=df_dev.index)
        score_multi_v1.loc[((cnt >= 1) & (cnt <= 7))] = 2.0
        score_multi_v1.loc[((cnt >= 8) & (cnt <= 14))] = 4.0
        score_multi_v1.loc[((cnt >= 15) & (cnt <= 21))] = 6.0
        score_multi_v1.loc[((cnt >= 22) & (cnt <= 28))] = 8.0
        score_multi_v1.loc[((cnt >= 29))] = 10.0
        score_multi_v1 = score_multi_v1 * _not_bottom.astype(float)
        
        # 통합지표 (신뢰도 높음, 가중치 강화)
        score_unified_v1 = c_top_all.astype(float) * 4.0
        score_unified_v1 = score_unified_v1 * _not_bottom.astype(float)
        
        df_dev['score_v1'] = score_fgi_v1 + score_slope_v1 + score_multi_v1 + score_unified_v1

        # ──────────────────────────────────────────────────────────
        # [버전 2] 가중치 일괄 상향 및 임계치 하향 조정안 (기획 제안안)
        # ──────────────────────────────────────────────────────────
        # 공탐변동 (각 등급 0.5~1.0점씩 상향 보강)
        score_fgi_v2 = pd.Series(0.0, index=df_dev.index)
        score_fgi_v2.loc[((df_dev['(FGI-VIX)/5'] >= 11) & _not_bottom)] = 2.0
        score_fgi_v2.loc[((df_dev['VIX_Pct'] <= 0.18) & (df_dev['FearGreedIndex'] >= 65) & _not_bottom)] = 3.0
        score_fgi_v2.loc[((df_dev['VIX_Pct'] <= 0.12) & (df_dev['FearGreedIndex'] >= 72) & _not_bottom)] = 4.0
        score_fgi_v2.loc[((df_dev['VIX_Pct'] <= 0.08) & (df_dev['FGI_Pct'] >= 0.82) & _not_bottom)] = 5.0
        
        # 슬로프합 (일수별 가중치 보강)
        score_slope_v2 = pd.Series(0.0, index=df_dev.index)
        slope_setups_v2 = [
            ('슬로프5일합', 15, 2.0),
            ('슬로프10일합', 25, 2.5),
            ('슬로프20일합', 30, 3.0),
            ('슬로프40일합', 40, 3.5),
        ]
        for col, thresh, weight in slope_setups_v2:
            val = df_dev[col]
            c_score = pd.Series(0.0, index=df_dev.index)
            c_score.loc[((val >= thresh) & (val < thresh * 1.5))] = 1.0
            c_score.loc[((val >= thresh * 1.5) & (val < thresh * 2.0))] = 1.5
            c_score.loc[((val >= thresh * 2.0) & (val < thresh * 2.5))] = 2.0
            c_score.loc[((val >= thresh * 2.5))] = 2.5
            score_slope_v2 += c_score * weight
        score_slope_v2 = score_slope_v2 * _not_bottom.astype(float)
        
        # 다중지표 (누적 감지 등급별 점수 개편)
        score_multi_v2 = pd.Series(0.0, index=df_dev.index)
        score_multi_v2.loc[((cnt >= 1) & (cnt <= 7))] = 1.5
        score_multi_v2.loc[((cnt >= 8) & (cnt <= 14))] = 3.0
        score_multi_v2.loc[((cnt >= 15) & (cnt <= 21))] = 4.5
        score_multi_v2.loc[((cnt >= 22) & (cnt <= 28))] = 6.0
        score_multi_v2.loc[((cnt >= 29) & (cnt <= 35))] = 7.5
        score_multi_v2.loc[((cnt >= 36) & (cnt <= 42))] = 9.0
        score_multi_v2.loc[((cnt >= 43))] = 10.5
        score_multi_v2 = score_multi_v2 * _not_bottom.astype(float)
        
        # 통합지표 (감지 시 3.5점 부여)
        score_unified_v2 = c_top_all.astype(float) * 3.5
        score_unified_v2 = score_unified_v2 * _not_bottom.astype(float)
        
        df_dev['score_v2'] = score_fgi_v2 + score_slope_v2 + score_multi_v2 + score_unified_v2

        # ──────────────────────────────────────────────────────────
        # [백분위수 동적 연산] 감지일(점수 > 0) 대상 분포 기준
        # ──────────────────────────────────────────────────────────
        # 버전 1 분위수 (초록 80%, 노랑 15%, 빨강 3.75%, 검정 1.25%)
        scores_v1_active = df_dev.loc[df_dev['score_v1'] > 0, 'score_v1']
        if not scores_v1_active.empty:
            q80_v1 = float(scores_v1_active.quantile(0.80))
            q95_v1 = float(scores_v1_active.quantile(0.95))
            q9875_v1 = float(scores_v1_active.quantile(0.9875))
        else:
            q80_v1, q95_v1, q9875_v1 = 4.0, 7.0, 10.0
            
        # 버전 2 분위수 (초록 80%, 노랑 15%, 빨강 3.75%, 검정 1.25%)
        scores_v2_active = df_dev.loc[df_dev['score_v2'] > 0, 'score_v2']
        if not scores_v2_active.empty:
            q80_v2 = float(scores_v2_active.quantile(0.80))
            q95_v2 = float(scores_v2_active.quantile(0.95))
            q9875_v2 = float(scores_v2_active.quantile(0.9875))
        else:
            q80_v2, q95_v2, q9875_v2 = 3.5, 6.5, 9.5

        # 날짜 연산 (최근 5년)
        five_years_ago_dev = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
        df_dev_plot = df_dev[df_dev.index >= five_years_ago_dev].copy()
        
        if active_period_days:
            target_date_dev = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_dev = [i for i, d in enumerate(df_dev_plot.index) if d >= pd.to_datetime(target_date_dev)]
            initial_x_dev = [detected_dev[0], len(df_dev_plot.index) - 1] if detected_dev else None
            if detected_dev:
                qqq_1y_dev = df_dev_plot['QQQ'].iloc[detected_dev[0]:]
                qqq_yr_dev = [float(qqq_1y_dev.min()) * 0.95, float(qqq_1y_dev.max()) * 1.05]
            else:
                qqq_yr_dev = [float(df_dev_plot['QQQ'].min()) * 0.95, float(df_dev_plot['QQQ'].max()) * 1.05]
        else:
            initial_x_dev = None
            qqq_yr_dev = [float(df_dev_plot['QQQ'].min()) * 0.95, float(df_dev_plot['QQQ'].max()) * 1.05]
            
        max_qqq_dev = float(df_dev_plot['QQQ'].max()) * 1.2
        hd_dev = [fmt_date_kor(d) for d in df_dev_plot.index]

        # ──────────────────────────────────────────────────────────
        # [렌더링 1] 🔵 [기존 책정안] 원래의 고점개발 위험 점수 그래프
        # ──────────────────────────────────────────────────────────
        st.subheader("🔵 [기존 책정안] 원래의 고점개발 위험 점수 그래프")
        st.markdown("""
        * **공탐변동(1~2.5점), 슬로프합(1~2.5점), 다중지표(1~7점), 통합지표(2점)** 기존 가중치 유지.
        * **기존 점수대 등급**: 5점 이하(초록) / 10점 이하(노랑) / 15점 이하(빨강) / 15점 초과(검정)
        """)
        
        fig_orig = make_subplots(specs=[[{"secondary_y": True}]])
        fig_orig.add_trace(go.Scatter(x=hd_dev, y=df_dev_plot['QQQ'], name='QQQ 가격', mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
        
        dev_cond_orig = [
            ((df_dev_plot['score_orig'] > 0) & (df_dev_plot['score_orig'] <= 5.0),   'rgba(169,208,142,0.5)', '#A9D08E'),
            ((df_dev_plot['score_orig'] > 5.0) & (df_dev_plot['score_orig'] <= 10.0),  'rgba(255,255,153,0.5)', '#FFFF99'),
            ((df_dev_plot['score_orig'] > 10.0) & (df_dev_plot['score_orig'] <= 15.0), 'rgba(224,102,102,0.5)', '#E06666'),
            ((df_dev_plot['score_orig'] > 15.0),                                  'rgba(89,89,89,0.5)',    '#595959'),
        ]
        for cond, bar_color, _ in dev_cond_orig:
            fig_orig.add_trace(go.Bar(x=hd_dev, y=cond.astype(int).values * max_qqq_dev, marker_color=bar_color, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
            
        fig_orig.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0,r=50,t=10,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
        if initial_x_dev:
            fig_orig.update_xaxes(range=initial_x_dev, type='category', **crosshair_xaxis())
        else:
            fig_orig.update_xaxes(type='category', **crosshair_xaxis())
        fig_orig.update_yaxes(range=qqq_yr_dev, **crosshair_yaxis(), secondary_y=False)
        fig_orig.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
        st.plotly_chart(fig_orig, width='stretch', config=COMMON_CONFIG, key="top_dev_orig_chart")
        
        # 최근 50개 시그널 표 orig
        df_sig_orig = df_dev_plot[df_dev_plot['score_orig'] > 0].sort_index(ascending=False).head(50)
        if not df_sig_orig.empty:
            dates_row_orig = []
            scores_row_orig = []
            for dt, row in df_sig_orig.iterrows():
                val = row['score_orig']
                bg = '#A9D08E'
                for c, bar_c, tbl_c in dev_cond_orig:
                    if c.loc[dt]:
                        bg = tbl_c
                        break
                fg = "#FFF" if bg in ['#E06666', '#595959'] else "#000"
                dates_row_orig.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                scores_row_orig.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{val:.2f}</td>")
            st.markdown(f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><table style='border-collapse:collapse;margin-top:3px;'><tr><th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>{''.join(dates_row_orig)}</tr><tr><th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>점수</th>{''.join(scores_row_orig)}</tr></table></div>", unsafe_allow_html=True)
            
        # 검증 통계 orig
        top_verify_orig = {
            "**초록색 구간 (5.0점 이하)**": ((df_dev['score_orig'] > 0) & (df_dev['score_orig'] <= 5.0), "5.0점 이하 과열"),
            "**노란색 구간 (10.0점 이하)**": ((df_dev['score_orig'] > 5.0) & (df_dev['score_orig'] <= 10.0), "5.0점 초과 10.0점 이하 과열"),
            "**빨간색 구간 (15.0점 이하)**": ((df_dev['score_orig'] > 10.0) & (df_dev['score_orig'] <= 15.0), "10.0점 초과 15.0점 이하 과열"),
            "**검은색 구간 (15.0점 초과)**": ((df_dev['score_orig'] > 15.0), "15.0점 초과 극단적 과열"),
            "**종합 감지 (기존)**": (df_dev['score_orig'] > 0, "과열 점수가 감지된 모든 날"),
        }
        stats_orig = calculate_top_stats(df_dev, 'QQQ', top_verify_orig)
        render_top_stats_table(stats_orig, "기존 책정안 지표 검증 결과")

        st.markdown("<hr style='border: 2px solid #555; margin: 3rem 0;'>", unsafe_allow_html=True)

        # ──────────────────────────────────────────────────────────
        # [렌더링 2] 🔴 [버전 1] 신뢰도 비례 점수 책정안 (신규 제안안)
        # ──────────────────────────────────────────────────────────
        st.subheader("🔴 [버전 1] 신뢰도 비례 점수 책정안 (신규 제안안)")
        st.markdown("""
        * **다중지표(신뢰도 극상)** 및 **통합지표(신뢰도 상)** 가중치 강화.
        * **슬로프합(신뢰도 보통)** 중첩 팽창 억제 및 **공탐변동(신뢰도 보통 이하)** 가중치 하향.
        * **조정된 점수대 등급**: 초록(80%) / 노랑(15%) / 빨강(3.75%) / 검정(1.25%)
        """)
        
        fig_v1 = make_subplots(specs=[[{"secondary_y": True}]])
        fig_v1.add_trace(go.Scatter(x=hd_dev, y=df_dev_plot['QQQ'], name='QQQ 가격', mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
        
        dev_cond_v1 = [
            ((df_dev_plot['score_v1'] > 0) & (df_dev_plot['score_v1'] <= q80_v1),  'rgba(169,208,142,0.5)', '#A9D08E'),
            ((df_dev_plot['score_v1'] > q80_v1) & (df_dev_plot['score_v1'] <= q95_v1), 'rgba(255,255,153,0.5)', '#FFFF99'),
            ((df_dev_plot['score_v1'] > q95_v1) & (df_dev_plot['score_v1'] <= q9875_v1), 'rgba(224,102,102,0.5)', '#E06666'),
            ((df_dev_plot['score_v1'] > q9875_v1),                                  'rgba(89,89,89,0.5)',    '#595959'),
        ]
        for cond, bar_color, _ in dev_cond_v1:
            fig_v1.add_trace(go.Bar(x=hd_dev, y=cond.astype(int).values * max_qqq_dev, marker_color=bar_color, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
            
        fig_v1.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0,r=50,t=10,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
        if initial_x_dev:
            fig_v1.update_xaxes(range=initial_x_dev, type='category', **crosshair_xaxis())
        else:
            fig_v1.update_xaxes(type='category', **crosshair_xaxis())
        fig_v1.update_yaxes(range=qqq_yr_dev, **crosshair_yaxis(), secondary_y=False)
        fig_v1.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
        st.plotly_chart(fig_v1, width='stretch', config=COMMON_CONFIG, key="top_dev_v1_chart")
        
        # 최근 50개 시그널 표 v1
        df_sig_v1 = df_dev_plot[df_dev_plot['score_v1'] > 0].sort_index(ascending=False).head(50)
        if not df_sig_v1.empty:
            dates_row_v1 = []
            scores_row_v1 = []
            for dt, row in df_sig_v1.iterrows():
                val = row['score_v1']
                bg = '#A9D08E'
                for c, bar_c, tbl_c in dev_cond_v1:
                    if c.loc[dt]:
                        bg = tbl_c
                        break
                fg = "#FFF" if bg in ['#E06666', '#595959'] else "#000"
                dates_row_v1.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                scores_row_v1.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{val:.2f}</td>")
            st.markdown(f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><table style='border-collapse:collapse;margin-top:3px;'><tr><th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>{''.join(dates_row_v1)}</tr><tr><th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>점수</th>{''.join(scores_row_v1)}</tr></table></div>", unsafe_allow_html=True)
            
        # 검증 통계 v1
        top_verify_v1 = {
            f"**초록색 구간 ({q80_v1:.2f}점 이하, 80%)**": ((df_dev['score_v1'] > 0) & (df_dev['score_v1'] <= q80_v1), f"{q80_v1:.2f}점 이하 (하위 80%)"),
            f"**노란색 구간 ({q95_v1:.2f}점 이하, 15%)**": ((df_dev['score_v1'] > q80_v1) & (df_dev['score_v1'] <= q95_v1), f"{q80_v1:.2f}점 초과 {q95_v1:.2f}점 이하 (중간 15%)"),
            f"**빨간색 구간 ({q9875_v1:.2f}점 이하, 3.75%)**": ((df_dev['score_v1'] > q95_v1) & (df_dev['score_v1'] <= q9875_v1), f"{q95_v1:.2f}점 초과 {q9875_v1:.2f}점 이하 (상위 3.75%)"),
            f"**검은색 구간 ({q9875_v1:.2f}점 초과, 1.25%)**": ((df_dev['score_v1'] > q9875_v1), f"{q9875_v1:.2f}점 초과 극단적 과열 (최상위 1.25%)"),
            "**종합 감지 (v1)**": (df_dev['score_v1'] > 0, "과열 점수가 감지된 모든 날"),
        }
        stats_v1 = calculate_top_stats(df_dev, 'QQQ', top_verify_v1)
        render_top_stats_table(stats_v1, "버전 1 (신규 제안안) 지표 검증 결과")
        
        st.markdown("<hr style='border: 2px solid #555; margin: 3rem 0;'>", unsafe_allow_html=True)

        # ──────────────────────────────────────────────────────────
        # [렌더링 2] 가중치 일괄 상향 및 임계치 하향 조정안 (기획 제안안)
        # ──────────────────────────────────────────────────────────
        st.subheader("🟢 [버전 2] 가중치 일괄 상향 및 임계치 하향 조정안 (기획 제안안)")
        st.markdown("""
        * **공탐변동, 슬로프합, 다중지표, 통합지표** 가중치를 일괄 상향 보강. (슬로프합 중첩 기여 인정)
        * **조정된 종합 등급 임계치**: 초록(80%) / 노랑(15%) / 빨강(3.75%) / 검정(1.25%)
        """)
        
        fig_v2 = make_subplots(specs=[[{"secondary_y": True}]])
        fig_v2.add_trace(go.Scatter(x=hd_dev, y=df_dev_plot['QQQ'], name='QQQ 가격', mode='lines+markers', line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5), marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
        
        dev_cond_v2 = [
            ((df_dev_plot['score_v2'] > 0) & (df_dev_plot['score_v2'] <= q80_v2),   'rgba(169,208,142,0.5)', '#A9D08E'),
            ((df_dev_plot['score_v2'] > q80_v2) & (df_dev_plot['score_v2'] <= q95_v2),  'rgba(255,255,153,0.5)', '#FFFF99'),
            ((df_dev_plot['score_v2'] > q95_v2) & (df_dev_plot['score_v2'] <= q9875_v2),  'rgba(224,102,102,0.5)', '#E06666'),
            ((df_dev_plot['score_v2'] > q9875_v2),                                  'rgba(89,89,89,0.5)',    '#595959'),
        ]
        for cond, bar_color, _ in dev_cond_v2:
            fig_v2.add_trace(go.Bar(x=hd_dev, y=cond.astype(int).values * max_qqq_dev, marker_color=bar_color, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
            
        fig_v2.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0,r=50,t=10,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
        if initial_x_dev:
            fig_v2.update_xaxes(range=initial_x_dev, type='category', **crosshair_xaxis())
        else:
            fig_v2.update_xaxes(type='category', **crosshair_xaxis())
        fig_v2.update_yaxes(range=qqq_yr_dev, **crosshair_yaxis(), secondary_y=False)
        fig_v2.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
        st.plotly_chart(fig_v2, width='stretch', config=COMMON_CONFIG, key="top_dev_v2_chart")
        
        # 최근 50개 시그널 표 v2
        df_sig_v2 = df_dev_plot[df_dev_plot['score_v2'] > 0].sort_index(ascending=False).head(50)
        if not df_sig_v2.empty:
            dates_row_v2 = []
            scores_row_v2 = []
            for dt, row in df_sig_v2.iterrows():
                val = row['score_v2']
                bg = '#A9D08E'
                for c, bar_c, tbl_c in dev_cond_v2:
                    if c.loc[dt]:
                        bg = tbl_c
                        break
                fg = "#FFF" if bg in ['#E06666', '#595959'] else "#000"
                dates_row_v2.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                scores_row_v2.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>{val:.2f}</td>")
            st.markdown(f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><table style='border-collapse:collapse;margin-top:3px;'><tr><th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>{''.join(dates_row_v2)}</tr><tr><th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>점수</th>{''.join(scores_row_v2)}</tr></table></div>", unsafe_allow_html=True)
            
        # 검증 통계 v2
        top_verify_v2 = {
            f"**초록색 구간 ({q80_v2:.2f}점 이하, 80%)**": ((df_dev['score_v2'] > 0) & (df_dev['score_v2'] <= q80_v2), f"{q80_v2:.2f}점 이하 (하위 80%)"),
            f"**노란색 구간 ({q95_v2:.2f}점 이하, 15%)**": ((df_dev['score_v2'] > q80_v2) & (df_dev['score_v2'] <= q95_v2), f"{q95_v2:.2f}점 초과 {q95_v2:.2f}점 이하 (중간 15%)"),
            f"**빨간색 구간 ({q9875_v2:.2f}점 이하, 3.75%)**": ((df_dev['score_v2'] > q95_v2) & (df_dev['score_v2'] <= q9875_v2), f"{q95_v2:.2f}점 초과 {q9875_v2:.2f}점 이하 (상위 3.75%)"),
            f"**검은색 구간 ({q9875_v2:.2f}점 초과, 1.25%)**": ((df_dev['score_v2'] > q9875_v2), f"{q9875_v2:.2f}점 초과 극단적 과열 (최상위 1.25%)"),
            "**종합 감지 (v2)**": (df_dev['score_v2'] > 0, "과열 점수가 감지된 모든 날"),
        }
        stats_v2 = calculate_top_stats(df_dev, 'QQQ', top_verify_v2)
        render_top_stats_table(stats_v2, "버전 2 (기획 제안안) 지표 검증 결과")

    else:
        st.info("한국 데이터는 향후 지원 예정입니다. 국가 선택을 '미국'으로 변경해 주세요.")

# ── Tab 9: 고점개발2 ──
with tabs[8]:
    if selected_country == "미국":
        # 1. 저점 및 실제 QQQ 저점 수집 (상호 배제용)
        _bottom_fgi = (
            ((df['FearGreedIndex'] <= 9) & (df['VIX'] >= 26)) |
            ((df['FearGreedIndex'] >= 10) & (df['FearGreedIndex'] <= 19) & (df['VIX'] >= 22) & (df['VIX'] <= 25)) |
            ((df['FearGreedIndex'] >= 20) & (df['FearGreedIndex'] <= 29) & (df['VIX'] >= 18) & (df['VIX'] <= 21)) |
            ((df['FearGreedIndex'] >= 30) & (df['FearGreedIndex'] <= 39) & (df['VIX'] >= 14) & (df['VIX'] <= 17))
        )
        _bottom_slope = (
            (df['슬로프5일합'] <= -20) | (df['슬로프10일합'] <= -30) |
            (df['슬로프20일합'] <= -40) | (df['슬로프40일합'] <= -50)
        )
        _multi_conds_for_bottom = [
            (df['QQQ_%B'] * (df['HYG_RSI'] / 100) <= 0.010),
            (df['FearGreedIndex'] * np.exp(df['TNX_ROC'] * 2) / (df['VIX'] + 1e-10) <= 0.35),
            (((df['FearGreedIndex'] - 50) / 20 + (df['QQQ_RSI'] - 50) / 15 + (df['QQQ_%B'] - 0.5) / 0.25 - df['VIX_Z']) <= -5.0),
            ((df['QQQ_%B'] <= 0.01) & (df['FearGreedIndex'] <= 6) & (df['VIX'] >= 25)),
            ((df['QQQ_%B'] <= -0.05) & (df['FearGreedIndex'] <= 7)),
        ]
        _multi_cnt = sum(c.fillna(False).astype(int) for c in _multi_conds_for_bottom)
        _bottom_multi = _multi_cnt >= 1
        
        is_bottom_day = (_bottom_fgi | _bottom_slope | _bottom_multi).reindex(df.index).fillna(False)
        
        _rolling_max = df['QQQ'].rolling(252, min_periods=1).max()
        _drawdown = (_rolling_max - df['QQQ']) / _rolling_max
        _local_min = df['QQQ'].rolling(41, center=True, min_periods=1).min()
        is_actual_bottom = (df['QQQ'] <= _local_min * 1.03) & (_drawdown >= 0.05)
        
        is_any_bottom = (is_bottom_day | is_actual_bottom).reindex(df.index).fillna(False)
        _not_bottom = ~is_any_bottom
        
        # 전처리
        df_dev2 = df.copy()
        df_dev2['QQQ_Low252'] = df_dev2['QQQ'].rolling(252, min_periods=1).min()
        df_dev2['QQQ_RU'] = (df_dev2['QQQ'] - df_dev2['QQQ_Low252']) / (df_dev2['QQQ_Low252'] + 1e-10)
        df_dev2['RU_Pct'] = df_dev2['QQQ_RU'].rolling(252, min_periods=60).rank(pct=True)
        
        df_dev2['QQQ_20H'] = df_dev2['QQQ'].rolling(20).max()
        df_dev2['RSI7_20H'] = df_dev2['QQQ_RSI7'].rolling(20).max()
        df_dev2['RSI_Div'] = (df_dev2['QQQ'] >= df_dev2['QQQ_20H'] * 0.99) & (df_dev2['QQQ_RSI7'] < df_dev2['RSI7_20H'] - 5)
        
        _ema12 = df_dev2['QQQ'].ewm(span=12, adjust=False).mean()
        _ema26 = df_dev2['QQQ'].ewm(span=26, adjust=False).mean()
        df_dev2['MACD'] = _ema12 - _ema26
        df_dev2['MACD_Signal'] = df_dev2['MACD'].ewm(span=9, adjust=False).mean()
        df_dev2['MACD_Hist'] = df_dev2['MACD'] - df_dev2['MACD_Signal']
        
        df_dev2['QQQ_MA20'] = df_dev2['QQQ'].rolling(20).mean()
        df_dev2['QQQ_MA50'] = df_dev2['QQQ'].rolling(50).mean()
        df_dev2['MA20_Dev'] = (df_dev2['QQQ'] - df_dev2['QQQ_MA20']) / (df_dev2['QQQ_MA20'] + 1e-10) * 100
        df_dev2['MA50_Dev'] = (df_dev2['QQQ'] - df_dev2['QQQ_MA50']) / (df_dev2['QQQ_MA50'] + 1e-10) * 100
        
        df_dev2['QQQ_Vel'] = df_dev2['QQQ'].pct_change(5)
        df_dev2['QQQ_Accel'] = df_dev2['QQQ_Vel'].diff(3)
        df_dev2['SKEW_Z'] = (df_dev2['SKEW'] - df_dev2['SKEW'].rolling(252).mean()) / (df_dev2['SKEW'].rolling(252).std() + 1e-5)
        
        # 15대 고점 지표 count용 리스트
        conds_15 = [
            df_dev2['RSI_Div'],
            (df_dev2['QQQ_RU'] >= 0.30) & (df_dev2['QQQ_RSI7'] >= 70),
            df_dev2['QQQ_RSI7'] >= 75,
            df_dev2['VIX_Pct'] <= 0.15,
            df_dev2['QQQ_RSI'] >= 70,
            df_dev2['QQQ_%B'] >= 0.90,
            df_dev2['QQQ_RSI7'] >= 80,
            df_dev2['VIX_Pct'] <= 0.10,
            (df_dev2['MACD_Hist'].diff() < 0) & (df_dev2['MACD_Hist'] > 0) & (df_dev2['QQQ_RSI7'] >= 65),
            (df_dev2['SKEW'] >= 145) & (df_dev2['VIX'] <= 15),
            df_dev2['QQQ_%B'] >= 1.0,
            (df_dev2['QQQ_%B'] >= 0.95) & (df_dev2['VIX'] <= 16),
            df_dev2['QQQ_RU'] >= 0.40,
            (df_dev2['VVIX_Pct'] <= 0.20) & (df_dev2['QQQ_RSI7'] >= 75),
            df_dev2['QQQ_RSI'] >= 75
        ]
        cnt_15 = sum(c.fillna(False).astype(int) for c in conds_15)
        
        # 6대 고점 특화 지표 딕셔너리 구성 (저점 배제 처리 적용)
        indicators_6 = {
            "적중 2 (SKEW 대발산 & VIX 저위 & RSI7 과열)": (
                (df_dev2['SKEW'] >= 148) & (df_dev2['VIX'] <= 13.0) & (df_dev2['QQQ_RSI7'] >= 75) & _not_bottom,
                "SKEW >= 148 & VIX <= 13.0 & QQQ_RSI7 >= 75 (적중률 57.9%)",
                "rgba(224, 102, 102, 0.5)", "#E06666" # 빨간색 계열
            ),
            "적중 4 (HYG & QQQ 초과열)": (
                (df_dev2['HYG_RSI'] >= 78) & (df_dev2['QQQ_RSI7'] >= 80) & (df_dev2['VIX'] <= 12.5) & _not_bottom,
                "HYG_RSI >= 78 & QQQ_RSI7 >= 80 & VIX <= 12.5 (적중률 37.5%)",
                "rgba(255, 140, 0, 0.5)", "#FF8C00" # 주황색 계열
            ),
            "균형 2 (RSI 다이버전스 & QQQ 랠리 성숙)": (
                (df_dev2['RSI_Div']) & (df_dev2['QQQ_RU'] >= 0.35) & (df_dev2['QQQ_RSI7'] >= 70) & _not_bottom,
                "RSI_Div & QQQ_RU >= 0.35 & QQQ_RSI7 >= 70 (적중률 39.8% / 포착률 17.6%)",
                "rgba(255, 255, 153, 0.5)", "#FFFF99" # 노란색 계열
            ),
            "균형 4 (VVIX 백분위 저위 & FGI 탐욕 & RSI7 과열)": (
                (df_dev2['VVIX_Pct'] <= 0.12) & (df_dev2['FearGreedIndex'] >= 75) & (df_dev2['QQQ_RSI7'] >= 72) & _not_bottom,
                "VVIX_Pct <= 0.12 & FGI >= 75 & QQQ_RSI7 >= 72 (적중률 100.0%)",
                "rgba(169, 208, 142, 0.5)", "#A9D08E" # 초록색 계열
            ),
            "포착 3 (15대 핵심 지표 중 3개 이상 만족 - 다중 카운트)": (
                (cnt_15 >= 3) & _not_bottom,
                "15대 핵심 고점 후보 조건 중 3가지 이상 동시 발생 (적중률 40.1% / 포착률 61.4%)",
                "rgba(135, 206, 235, 0.5)", "#87CEEB" # 파란색 계열
            ),
            "포착 4 (FGI-VIX 스프레드 확장)": (
                ((df_dev2['(FGI-VIX)/5'] >= 9.5) & (df_dev2['QQQ_RU'] >= 0.20)) & _not_bottom,
                "(FGI-VIX)/5 >= 9.5 & QQQ_RU >= 0.20 (적중률 45.6% / 포착률 24.1%)",
                "rgba(128, 0, 128, 0.5)", "#800080" # 보라색 계열
            )
        }
        
        # 날짜 범위 연산 및 5년 필터링 (루프 외부에서 1회 수행)
        five_years_ago_dev2 = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
        df_dev2_plot = df_dev2[df_dev2.index >= five_years_ago_dev2].copy()
        
        if active_period_days:
            target_date_dev2 = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_dev2 = [i for i, d in enumerate(df_dev2_plot.index) if d >= pd.to_datetime(target_date_dev2)]
            initial_x_dev2 = [detected_dev2[0], len(df_dev2_plot.index) - 1] if detected_dev2 else None
            if detected_dev2:
                qqq_1y_dev2 = df_dev2_plot['QQQ'].iloc[detected_dev2[0]:]
                qqq_yr_dev2 = [float(qqq_1y_dev2.min()) * 0.95, float(qqq_1y_dev2.max()) * 1.05]
            else:
                qqq_yr_dev2 = [float(df_dev2_plot['QQQ'].min()) * 0.95, float(df_dev2_plot['QQQ'].max()) * 1.05]
        else:
            initial_x_dev2 = None
            qqq_yr_dev2 = [float(df_dev2_plot['QQQ'].min()) * 0.95, float(df_dev2_plot['QQQ'].max()) * 1.05]
            
        max_qqq_dev2 = float(df_dev2_plot['QQQ'].max()) * 1.2
        hd_dev2 = [fmt_date_kor(d) for d in df_dev2_plot.index]
        
        # 6가지 지표 순차적으로 화면에 출력
        for idx, (name, (cond_bool, desc_str, bar_color, tbl_color)) in enumerate(indicators_6.items()):
            st.markdown(f"#### 📈 {name}")
            st.markdown(f"**조건 세부 내용**: `{desc_str}`")
            
            cond_plot = cond_bool.reindex(df_dev2_plot.index).fillna(False)
            
            fig_dev2 = make_subplots(specs=[[{"secondary_y": True}]])
            
            # QQQ 가격 선 그래프 (슬로프합 디자인 동기화)
            fig_dev2.add_trace(go.Scatter(
                x=hd_dev2, y=df_dev2_plot['QQQ'], name='QQQ 가격', mode='lines+markers',
                line=dict(color='rgba(0, 100, 0, 1.0)', width=1.5),
                marker=dict(symbol='circle', color='white', size=1.3, opacity=0.5, line=dict(width=0)),
                hovertemplate='QQQ: %{y:.2f}<extra></extra>'
            ), secondary_y=False)
            
            # 고점 신호 오버레이 막대 그래프
            fig_dev2.add_trace(go.Bar(
                x=hd_dev2, y=cond_plot.astype(int).values * max_qqq_dev2,
                name='고점 감지 신호',
                marker_color=bar_color,
                marker_line_width=0.5, marker_line_color='white',
                hovertemplate='고점 감지일<extra></extra>'
            ), secondary_y=False)
            
            fig_dev2.update_layout(**COMMON_LAYOUT, height=330, margin=dict(l=0,r=50,t=10,b=10), showlegend=False, barmode='overlay', bargap=0,
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
            if initial_x_dev2:
                fig_dev2.update_xaxes(range=initial_x_dev2, type='category', **crosshair_xaxis())
            else:
                fig_dev2.update_xaxes(type='category', **crosshair_xaxis())
            fig_dev2.update_yaxes(range=qqq_yr_dev2, **crosshair_yaxis(), secondary_y=False)
            fig_dev2.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
            
            st.plotly_chart(fig_dev2, width='stretch', config=COMMON_CONFIG, key=f"top_dev2_chart_{idx}")
            
            # 최근 고점 감지 신호 날짜 리스트표 생성
            df_sig_dev2 = df_dev2_plot[cond_plot].sort_index(ascending=False).head(50)
            if not df_sig_dev2.empty:
                dates_row_dev2 = []
                desc_row_dev2 = []
                for dt, row in df_sig_dev2.iterrows():
                    bg = tbl_color
                    fg = "#FFF" if bg in ['#E06666', '#800080', '#FF8C00'] else "#000"
                    dates_row_dev2.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;padding:2px 4px;border:1px solid #555;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    desc_row_dev2.append(f"<td style='text-align:center;padding:2px 4px;border:1px solid #555;vertical-align:middle;line-height:1.15;white-space:nowrap;'>감지됨</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 최근 감지 신호 (최근 50개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_dev2)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 6px;background:#1F4E79;color:white;text-align:center;white-space:nowrap;'>여부</th>
                        {"".join(desc_row_dev2)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
                
            # 검증결과 통계 테이블 생성
            top_dev2_verify = {
                name: (cond_bool, desc_str)
            }
            stats_top_dev2 = calculate_top_stats(df_dev2, 'QQQ', top_dev2_verify)
            st.markdown("<br>", unsafe_allow_html=True)
            render_top_stats_table(stats_top_dev2, f"'{name}' 검증 결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
            st.markdown("<hr style='border: 1px dashed #555; margin: 1.5rem 0;'>", unsafe_allow_html=True)
    else:
        st.info("한국 데이터는 향후 지원 예정입니다. 국가 선택을 '미국'으로 변경해 주세요.")
