import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import datetime
import calendar
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Page config for Premium UI
st.set_page_config(page_title="US Market Trends", layout="wide", initial_sidebar_state="collapsed")

# Custom CSS for glassmorphism and modern look
st.markdown("""
<style>
    .css-18e3th9 { padding-top: 2rem; }
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 2rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px rgba(118, 75, 162, 0.3);
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 800;
        background: -webkit-linear-gradient(45deg, #f3ec78, #af4261);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">QQQ vs VIX vs Fear & Greed Dashboard</p>', unsafe_allow_html=True)
st.markdown("최근 5년간의 미국 시장 트렌드와 주요 사건을 한눈에 분석합니다.")

events_data = [
    {'title': 'COVID-19 팬데믹', 'period': '2020.02 ~ 2020.03'},
    {'title': '인플레이션 및 금리 인상', 'period': '2021.11 ~ 2022.10'},
    {'title': '미국 지방은행 위기 (SVB 등)', 'period': '2023.03 ~ 2023.03'},
    {'title': 'AI 수익성 의문 및 엔 캐리', 'period': '2024.07 ~ 2024.08'},
    {'title': '관세 및 무역 갈등 (4월 크래시)', 'period': '2025.03 ~ 2025.04'},
    {'title': '중동 지정학적 위기 (이란 갈등)', 'period': '2026.01 ~ 2026.02'}
]

def parse_period(period_str):
    start_str, end_str = period_str.split(' ~ ')
    s_year, s_mon = map(int, start_str.split('.'))
    e_year, e_mon = map(int, end_str.split('.'))
    start_date = datetime.date(s_year, s_mon, 1)
    _, last_day = calendar.monthrange(e_year, e_mon)
    end_date = datetime.date(e_year, e_mon, last_day)
    return pd.to_datetime(start_date), pd.to_datetime(end_date)

@st.cache_data(ttl=3600)
def fetch_and_process_data():
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=5*365)
    start_date_str = start_date.strftime('%Y-%m-%d')
    
    # 1. Fetch Data
    qqq = yf.download('QQQ', start=start_date_str, progress=False)
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq_df = qqq[['Close']].rename(columns={'Close': 'QQQ'})
    
    vix = yf.download('^VIX', start=start_date_str, progress=False)
    if isinstance(vix.columns, pd.MultiIndex): vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[['Close']].rename(columns={'Close': 'VIX'})
    
    # Fetch FGI
    url = f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start_date_str}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            res = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-10-01", headers=headers)
            res.raise_for_status()
    except Exception:
        res = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-10-01", headers=headers)
        res.raise_for_status()
        
    data = res.json()['fear_and_greed_historical']['data']
    fg_df = pd.DataFrame(data)
    fg_df['Date'] = pd.to_datetime(fg_df['x'], unit='ms')
    fg_df = fg_df.set_index('Date').rename(columns={'y': 'FearGreedIndex'})[['FearGreedIndex']]
    
    # Merge
    df = qqq_df.join(vix_df, how='outer').join(fg_df, how='outer').ffill().bfill()
    df['(FGI-VIX)/5'] = (df['FearGreedIndex'] - df['VIX']) / 5
    df['(FGI-VIX)/5 2MA'] = df['(FGI-VIX)/5'].rolling(window=2).mean().bfill()
    
    return df

col1, col2 = st.columns([8, 1])
with col2:
    if st.button("🔄 Data Refresh"):
        st.cache_data.clear()

with st.spinner("Fetching market data..."):
    df = fetch_and_process_data()

# Create Plotly Figure
fig = make_subplots(specs=[[{"secondary_y": True}]])

# Add Shading for Events
for event in events_data:
    s_date, e_date = parse_period(event['period'])
    fig.add_vrect(
        x0=s_date, x1=e_date,
        fillcolor="gray", opacity=0.3, layer="below", line_width=0,
        annotation_text=event['title'], annotation_position="top left",
        annotation_font_size=10, annotation_font_color="white"
    )

# QQQ Line
fig.add_trace(
    go.Scatter(x=df.index, y=df['QQQ'], name='QQQ', line=dict(color='#00d2ff', width=2)),
    secondary_y=False,
)

# Secondary axis indicators
fig.add_trace(go.Scatter(x=df.index, y=df['VIX'], name='VIX', line=dict(color='#ff2a2a', width=1)), secondary_y=True)
fig.add_trace(go.Scatter(x=df.index, y=df['FearGreedIndex'], name='FGI', line=dict(color='#a64dff', width=1)), secondary_y=True)
fig.add_trace(go.Scatter(x=df.index, y=df['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='#ffb347', width=1)), secondary_y=True)

# Shade calculations mapped to Area charts
shade_red = ((df['FearGreedIndex'] <= 9) & (df['VIX'] >= 26)).astype(int) * 200
shade_orange = ((df['FearGreedIndex'] >= 10) & (df['FearGreedIndex'] <= 19) & (df['VIX'] >= 22) & (df['VIX'] <= 25)).astype(int) * 200
shade_yellow = ((df['FearGreedIndex'] >= 20) & (df['FearGreedIndex'] <= 29) & (df['VIX'] >= 18) & (df['VIX'] <= 21)).astype(int) * 200
shade_green = ((df['FearGreedIndex'] >= 30) & (df['FearGreedIndex'] <= 39) & (df['VIX'] >= 14) & (df['VIX'] <= 17)).astype(int) * 200

fig.add_trace(go.Scatter(x=df.index, y=shade_red, fill='tozeroy', name='Red Zone', line=dict(width=0), fillcolor='rgba(255,0,0,0.3)', showlegend=False), secondary_y=True)
fig.add_trace(go.Scatter(x=df.index, y=shade_orange, fill='tozeroy', name='Orange Zone', line=dict(width=0), fillcolor='rgba(255,165,0,0.3)', showlegend=False), secondary_y=True)
fig.add_trace(go.Scatter(x=df.index, y=shade_yellow, fill='tozeroy', name='Yellow Zone', line=dict(width=0), fillcolor='rgba(255,255,0,0.3)', showlegend=False), secondary_y=True)
fig.add_trace(go.Scatter(x=df.index, y=shade_green, fill='tozeroy', name='Green Zone', line=dict(width=0), fillcolor='rgba(0,128,0,0.3)', showlegend=False), secondary_y=True)


fig.update_layout(
    template="plotly_dark",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    height=600,
    margin=dict(l=20, r=20, t=40, b=20),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

fig.update_yaxes(title_text="QQQ Price ($)", secondary_y=False, showgrid=False)
fig.update_yaxes(title_text="Indicators", secondary_y=True, range=[-10, 120], showgrid=False)
fig.update_xaxes(showgrid=False)

st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown("### 주요 시장 사건 요약")
event_df = pd.DataFrame(events_data)
st.table(event_df)
