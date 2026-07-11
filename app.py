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

# Page configuration
st.set_page_config(page_title="Market Trends Dashboard", layout="wide", initial_sidebar_state="collapsed")

# Configure yfinance to use a custom requests session with a User-Agent header
# This helps bypass Yahoo Finance rate limits and blockings in cloud hosting environments.
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
})
# Ensure yfinance uses the custom session globally
import yfinance as yf
try:
    import yfinance.shared as yf_shared
    yf_shared.default_session = session
except ImportError:
    try:
        yf.shared.default_session = session
    except AttributeError:
        pass

# Custom helper for downloading with the session explicitly to be safe
def yf_download_custom(tickers, **kwargs):
    if 'session' not in kwargs:
        kwargs['session'] = session
    return yf.download(tickers, **kwargs)

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
        bgcolor="rgba(240,240,240,0.85)",
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
        ndx_tickers = ['MSFT','AAPL','NVDA','AMZN','META','GOOGL','GOOG','TSLA','AVGO','PEP','COST','AZN','CSCO','AMD','TMUS','QCOM','INTC','TXN','AMGN','INTU','ISRG','HON','AMAT','BKNG','ADP','MDLZ','GILD','ADI','LRCX','REGN','VRTX','MU','PANW','SBUX','KLAC','SNPS','CDNS','MRVL','NFLX','ORLY','ABNB','CTAS','PYPL','ASML','KDP','ROST','MNST','PAYX','FTNT','MCHP','DXCM','EXC','BIIB','IDXX','CPRT','VRSK','PCAR','ODFL','CSGP','CHTR','CEG','TEAM','FAST','GEHC','ON','ILMN','EA','FANG','DLTR','NXPI','WDAY','MRNA','ALGN','DDOG','APP','CRWD','CDW','CTSH','ADSK','ROP','XEL','KHC','EBAY']
        _df = yf_download_custom(ndx_tickers, period='10d', progress=False)
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
    ndx_tickers = ['MSFT','AAPL','NVDA','AMZN','META','GOOGL','GOOG','TSLA','AVGO','PEP','COST','AZN','CSCO','AMD','TMUS','QCOM','INTC','TXN','AMGN','INTU','ISRG','HON','AMAT','BKNG','ADP','MDLZ','GILD','ADI','LRCX','REGN','VRTX','MU','PANW','SBUX','KLAC','SNPS','CDNS','MRVL','NFLX','ORLY','ABNB','CTAS','PYPL','ASML','KDP','ROST','MNST','PAYX','FTNT','MCHP','DXCM','EXC','BIIB','IDXX','CPRT','VRSK','PCAR','ODFL','CSGP','CHTR','CEG','TEAM','FAST','GEHC','ON','ILMN','EA','FANG','DLTR','NXPI','WDAY','MRNA','ALGN','DDOG','APP','CRWD','CDW','CTSH','ADSK','ROP','XEL','KHC','EBAY']
    
    def calc_kr(tickers):
        try:
            _df = yf_download_custom(tickers, period='130d', progress=False)
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
            _df = yf_download_custom(tickers, period='130d', progress=False)
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
            df = yf_download_custom(ticker, period='130d', progress=False)
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
    qqq = yf_download_custom('QQQ', start=start_date_str, progress=False)
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq_df = qqq[['Close']].rename(columns={'Close': 'QQQ'}) if not qqq.empty and 'Close' in qqq.columns else pd.DataFrame(columns=['QQQ'])
    vix = yf_download_custom('^VIX', start=start_date_str, progress=False)
    if isinstance(vix.columns, pd.MultiIndex): vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[['Close']].rename(columns={'Close': 'VIX'}) if not vix.empty and 'Close' in vix.columns else pd.DataFrame(columns=['VIX'])
    
    # 신규 추가: TNX (10년물 국채 금리), HYG (하이일드 채권 ETF)
    tnx = yf_download_custom('^TNX', start=start_date_str, progress=False)
    if isinstance(tnx.columns, pd.MultiIndex): tnx.columns = tnx.columns.get_level_values(0)
    tnx_df = tnx[['Close']].rename(columns={'Close': 'TNX'}) if not tnx.empty and 'Close' in tnx.columns else pd.DataFrame(columns=['TNX'])
    
    hyg = yf_download_custom('HYG', start=start_date_str, progress=False)
    if isinstance(hyg.columns, pd.MultiIndex): hyg.columns = hyg.columns.get_level_values(0)
    hyg_df = hyg[['Close']].rename(columns={'Close': 'HYG'}) if not hyg.empty and 'Close' in hyg.columns else pd.DataFrame(columns=['HYG'])
    
    # 2차 탐색을 위한 SKEW 및 VVIX 데이터 추가 다운로드
    skew = yf_download_custom('^SKEW', start=start_date_str, progress=False)
    if isinstance(skew.columns, pd.MultiIndex): skew.columns = skew.columns.get_level_values(0)
    skew_df = skew[['Close']].rename(columns={'Close': 'SKEW'}) if not skew.empty and 'Close' in skew.columns else pd.DataFrame(columns=['SKEW'])
    
    vvix = yf_download_custom('^VVIX', start=start_date_str, progress=False)
    if isinstance(vvix.columns, pd.MultiIndex): vvix.columns = vvix.columns.get_level_values(0)
    vvix_df = vvix[['Close']].rename(columns={'Close': 'VVIX'}) if not vvix.empty and 'Close' in vvix.columns else pd.DataFrame(columns=['VVIX'])
    
    # 2차 탐색 안전자산 대피 계산을 위한 TLT 다운로드 추가
    tlt = yf_download_custom('TLT', start=start_date_str, progress=False)
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
    kospi = yf_download_custom('^KS11', start="2018-01-01", progress=False)
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

# 탭 구성: 공탐변동 / 슬로프합 / 등락현황 / 메모리 / 지표개발 / 적중집중 / 균형집중 / 포착집중
tab_names = ['공탐변동', '슬로프합', '다중지표', '통합지표', '등락현황', '메모리']
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

# ── Tab 5: 등락 현황 ──
with tabs[4]:
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
                    ('상승','rgba(255, 107, 157, 0.5)','상승'),
                    ('보합','rgba(170, 170, 170, 0.5)','보합'),
                    ('하락','rgba(135, 206, 235, 0.5)','하락')
                ]
            else:
                configs = [
                    ('상한가','rgba(204, 0, 0, 0.5)','상한가'),
                    ('상승','rgba(255, 107, 157, 0.5)','상승'),
                    ('보합','rgba(170, 170, 170, 0.5)','보합'),
                    ('하락','rgba(135, 206, 235, 0.5)','하락'),
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
                        hovertemplate=f'{ln}: %{{y}}<extra></extra>'
                    ), secondary_y=False)
                    
            if ps is not None and len(ps) > 0:
                pf = ps[ps.index >= dfp.index.min()].tail(90)
                line_color = 'rgba(0, 100, 0, 1.0)'
                line_width = 1.5
                fig.add_trace(go.Scatter(
                    x=hd,
                    y=pf.values,
                    mode='lines+markers',
                    name=pname,
                    line=dict(color=line_color, width=line_width),  
                    marker=dict(
                        symbol='circle',
                        color='white',
                        size=1.3,
                        opacity=0.5,
                        line=dict(width=0)
                    ),
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
        
    st.plotly_chart(make_line_fig(kp_b,"코스피 대표 종목 등락현황 추이 (꺾은선형)",kp_p,"코스피", is_us=False),width='stretch',config=COMMON_CONFIG, key="tab3_kospi_breadth")
    st.plotly_chart(make_line_fig(kd_b,"코스닥 대표 종목 등락현황 추이 (꺾은선형)",kd_p,"코스닥", is_us=False),width='stretch',config=COMMON_CONFIG, key="tab3_kosdaq_breadth")
    st.plotly_chart(make_line_fig(ndx_b,"나스닥 100 대표 종목 등락현황 추이 (꺾은선형 - 상하한 제외)",qqq_p,"QQQ", is_us=True),width='stretch',config=COMMON_CONFIG, key="tab3_ndx_breadth")

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
            showlegend=False
        )
        fig_mem.update_layout(hoverlabel_bgcolor='rgba(0,0,0,0.2)')
        
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
