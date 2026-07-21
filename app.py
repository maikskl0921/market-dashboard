# -*- coding: utf-8 -*-
import streamlit as st

def render_gamma_stats_table(df_stats, title):
    tbl_html = '<table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #555; text-align: center; font-size: 0.75rem; vertical-align: middle;"><thead><tr style="background-color: #1F4E79; color: white;">'
    for col in df_stats.columns:
        tbl_html += f'<th style="border: 1px solid #555; padding: 4px 6px; text-align: center; vertical-align: middle;">{col}</th>'
    tbl_html += '</tr></thead><tbody>'
    for _, row in df_stats.iterrows():
        tbl_html += '<tr>'
        for col in df_stats.columns:
            val = row[col]
            tbl_html += f'<td style="border: 1px solid #555; padding: 4px 6px; text-align: center; vertical-align: middle;">{val}</td>'
        tbl_html += '</tr>'
    tbl_html += '</tbody></table>'
    st.markdown(tbl_html, unsafe_allow_html=True)
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

def calculate_duration(period_str):
    try:
        start_str, end_str = period_str.split(' ~ ')
        s_year, s_mon = map(int, start_str.split('.'))
        if end_str == "진행중":
            import datetime as dt_module
            now = dt_module.date.today()
            e_year, e_mon = now.year, now.month
        else:
            e_year, e_mon = map(int, end_str.split('.'))
        total_months = (e_year - s_year) * 12 + (e_mon - s_mon)
        if total_months <= 0:
            total_months = 1
        years = total_months // 12
        months = total_months % 12
        if years > 0:
            if months > 0:
                return f"{years}년 {months}개월"
            else:
                return f"{years}년"
        else:
            return f"{months}개월"
    except:
        return "-"

def detect_recent_drawdowns(df_target, price_col='QQQ', dd_threshold=0.10):
    """
    가격 시계열에서 전고점 대비 낙폭이 dd_threshold 이상인 최근의 조정 국면을 자동으로 탐지합니다.
    """
    if df_target.empty or price_col not in df_target.columns:
        return []
    prices = df_target[price_col]
    dates = df_target.index
    events = []
    in_drawdown = False
    peak_val = -1
    peak_date = None
    trough_val = 999999
    trough_date = None
    for i in range(len(prices)):
        p = prices.iloc[i]
        d = dates[i]
        rolling_max = prices.iloc[max(0, i-252):i+1].max()
        dd = (rolling_max - p) / rolling_max
        if not in_drawdown:
            if dd >= dd_threshold:
                in_drawdown = True
                lookback = prices.iloc[max(0, i-60):i+1]
                peak_val = lookback.max()
                peak_date = lookback.idxmax()
                trough_val = p
                trough_date = d
        else:
            if p < trough_val:
                trough_val = p
                trough_date = d
            if dd < 0.03:
                fall_pct = (trough_val - peak_val) / peak_val * 100
                if fall_pct <= -dd_threshold * 100:
                    events.append({
                        "title": "하락조정장",
                        "period": f"{peak_date.strftime('%Y.%m')} ~ {trough_date.strftime('%Y.%m')}",
                        "fall_rate": f"{int(round(fall_pct))}%"
                    })
                in_drawdown = False
                peak_val = -1
                peak_date = None
                trough_val = 999999
                trough_date = None
    if in_drawdown:
        # 진행 중인 사건의 경우 하락률을 현재가 기준으로 다시 계산
        curr_price = prices.iloc[-1]
        fall_pct = (curr_price - peak_val) / peak_val * 100
        if fall_pct <= -dd_threshold * 100:
            events.append({
                "title": "하락조정장 (진행중)",
                "period": f"{peak_date.strftime('%Y.%m')} ~ 진행중",
                "fall_rate": f"{int(round(fall_pct))}%"
            })
    return events

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
    tbl_html = '<table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #555;text-align:center;"><thead><tr style="background-color: #1F4E79; color: white;"><th style="width: 18%; border: 1px solid #555; padding: 6px 8px; text-align: left;">감지 조건</th><th style="width: 32%; border: 1px solid #555; padding: 6px 8px; text-align: left;">조건 세부 내용</th><th style="width: 12%; border: 1px solid #555; padding: 6px 8px; text-align: center;">발생 횟수</th><th style="width: 13%; border: 1px solid #555; padding: 6px 8px; text-align: center;">저점 적중 (Hit Rate)</th><th style="width: 13%; border: 1px solid #555; padding: 6px 8px; text-align: center;">저점 포착 (Recall)</th><th style="width: 12%; border: 1px solid #555; padding: 6px 8px; text-align: center;">종합 점수</th></tr></thead><tbody>'
    for item in stats_list:
        name_html = item['name'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        desc_html = item['desc'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        hit_rate_html = item['hit_rate'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        
        name_html = name_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        desc_html = desc_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        hit_rate_html = hit_rate_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)

        tbl_html += f'<tr><td style="border: 1px solid #555; padding: 6px 8px; text-align: left; font-size: 0.85rem;">{name_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: left; font-size: 0.85rem;">{desc_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{item["triggered"]}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{hit_rate_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{item["recall"]}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{item["score"]}</td></tr>'
    tbl_html += "</tbody></table>"
    st.markdown(tbl_html, unsafe_allow_html=True)

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

def render_slope_multi_stats_table(stats_list, title):
    st.markdown(f"#### {title}")
    tbl_html = '<table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #555; text-align: center; vertical-align: middle;"><thead><tr style="background-color: #1F4E79; color: white;"><th style="width: 18%; border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle;">감지 조건</th><th style="width: 32%; border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle;">조건 세부 내용</th><th style="width: 12%; border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle;">발생 횟수</th><th style="width: 13%; border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle;">저점 적중 (Hit Rate)</th><th style="width: 13%; border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle;">저점 포착 (Recall)</th><th style="width: 12%; border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle;">종합 점수</th></tr></thead><tbody>'
    for item in stats_list:
        name_html = item['name'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        desc_html = item['desc'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        hit_rate_html = item['hit_rate'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        name_html = name_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        desc_html = desc_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        hit_rate_html = hit_rate_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        tbl_html += f'<tr><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle; font-size: 0.85rem;">{name_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle; font-size: 0.85rem;">{desc_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle; font-size: 0.85rem;">{item["triggered"]}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle; font-size: 0.85rem;">{hit_rate_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle; font-size: 0.85rem;">{item["recall"]}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; vertical-align: middle; font-size: 0.85rem;">{item["score"]}</td></tr>'
    tbl_html += "</tbody></table>"
    st.markdown(tbl_html, unsafe_allow_html=True)

def render_top_stats_table(stats_list, title):
    st.markdown(f"#### 📊 {title}")
    tbl_html = '<table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #555;text-align:center;"><thead><tr style="background-color: #1F4E79; color: white;"><th style="width: 18%; border: 1px solid #555; padding: 6px 8px; text-align: left;">감지 조건</th><th style="width: 32%; border: 1px solid #555; padding: 6px 8px; text-align: left;">조건 세부 내용</th><th style="width: 12%; border: 1px solid #555; padding: 6px 8px; text-align: center;">발생 횟수</th><th style="width: 13%; border: 1px solid #555; padding: 6px 8px; text-align: center;">고점 적중 (Hit Rate)</th><th style="width: 13%; border: 1px solid #555; padding: 6px 8px; text-align: center;">고점 포착 (Recall)</th><th style="width: 12%; border: 1px solid #555; padding: 6px 8px; text-align: center;">종합 점수</th></tr></thead><tbody>'
    for item in stats_list:
        name_html = item['name'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        desc_html = item['desc'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        hit_rate_html = item['hit_rate'].replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        name_html = name_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        desc_html = desc_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        hit_rate_html = hit_rate_html.replace('**', '<strong>', 1).replace('**', '</strong>', 1)
        tbl_html += f'<tr><td style="border: 1px solid #555; padding: 6px 8px; text-align: left; font-size: 0.85rem;">{name_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: left; font-size: 0.85rem;">{desc_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{item["triggered"]}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{hit_rate_html}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{item["recall"]}</td><td style="border: 1px solid #555; padding: 6px 8px; text-align: center; font-size: 0.85rem;">{item["score"]}</td></tr>'
    tbl_html += "</tbody></table>"
    st.markdown(tbl_html, unsafe_allow_html=True)

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
        margin-top: 0.02rem !important;
        margin-bottom: 0.02rem !important;
    }
    div[data-testid="stVerticalBlock"] > div:has(> .element-container) { padding-top: 0 !important; padding-bottom: 0 !important; }
    div[data-testid="stVerticalBlock"] {
        gap: 0.35rem !important;
    }
    .main-header { font-size: 1.2rem; font-weight: 700; background: -webkit-linear-gradient(45deg, #f3ec78, #af4261); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; line-height: 1.1; }
    h3 { font-size: 0.85rem !important; margin: 0.15rem 0 0.05rem 0 !important; }
    h4 { font-size: 0.75rem !important; margin: 0.1rem 0 0.05rem 0 !important; }
    .stTabs [data-baseweb="tab-list"] button p { font-size: 0.5rem !important; }
    .stButton > button { margin-top: 0 !important; margin-bottom: 0.1rem !important; padding: 2px 10px !important; font-size: 0.75rem !important; }
    
    /* 모든 표의 크기 */
    table {
        width: 100% !important;
        max-width: 100% !important;
        border-collapse: collapse;
        margin: 0 0 10px 0 !important;
    }
    table, th, td {
        font-size: 0.6rem !important;
        padding: 0.5px 3px !important;
        line-height: 1.05 !important;
        text-align: center !important;
    }
    
    div[data-testid="stHorizontalBlock"] {
        column-gap: 0.1rem !important;
    }
    
    .block-container {
        padding-bottom: 80px !important;
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
    {"title": "미국-이란 전쟁발 우려 폭락", "period": "2026.01 ~ 2026.03", "fall_rate": "-12%"},
    {"title": "미-중 무역 전쟁 재발 우려 폭락", "period": "2025.03 ~ 2025.04", "fall_rate": "-18%"},
    {"title": "엔 캐리 트레이드 청산 우려 폭락", "period": "2024.07 ~ 2024.08", "fall_rate": "-14%"},
    {"title": "실리콘밸리 은행(SVB) 파산 사태", "period": "2023.03 ~ 2023.03", "fall_rate": "-9%"},
    {"title": "미 국채 금리 급등발 기술주 밸류에이션 조정 폭락", "period": "2021.02 ~ 2021.03", "fall_rate": "-11%"},
    {"title": "인플레이션 및 금리 인상 하락장", "period": "2021.11 ~ 2022.10", "fall_rate": "-37%"},
    {"title": "코로나19 2차 대유행 및 미국 대선 불확실성 우려 폭락", "period": "2020.09 ~ 2020.10", "fall_rate": "-13%"},
    {"title": "코로나 19 팬데믹 폭락", "period": "2020.02 ~ 2020.03", "fall_rate": "-35%"},
    {"title": "미-중 무역 전쟁 관세 분쟁 갈등 폭락", "period": "2019.05 ~ 2019.06", "fall_rate": "-11%"},
    {"title": "미 연준 금리 인상 및 미-중 무역 전쟁 우려 대폭락", "period": "2018.10 ~ 2018.12", "fall_rate": "-23%"}
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
    start_date_str = "2020-01-01"
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

    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-01-01"
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
    df_s['슬로프30일합'] = slope_sum_lagged(sl, 30)
    df_s['슬로프40일합'] = slope_sum_lagged(sl, 40)
    df_s['슬로프50일합'] = slope_sum_lagged(sl, 50)
    df_s['슬로프60일합'] = slope_sum_lagged(sl, 60)
    df_s['슬로프70일합'] = slope_sum_lagged(sl, 70)
    df_s['슬로프80일합'] = slope_sum_lagged(sl, 80)
    # QQQ 기준 상하한 임계값 설정 (새로운 조건: 하한 -10~-40 및 하위호환 5, 10, 20, 40)
    df_s['5일상한'] = 20;  df_s['5일하한'] = -20
    df_s['10일상한'] = 15; df_s['10일하한'] = -15
    df_s['20일상한'] = 20; df_s['20일하한'] = -20
    df_s['30일상한'] = 25; df_s['30일하한'] = -25
    df_s['40일상한'] = 30; df_s['40일하한'] = -30
    df_s['50일상한'] = 35; df_s['50일하한'] = -35
    df_s['60일상한'] = 40; df_s['60일하한'] = -40
    df_s['70일상한'] = 45; df_s['70일하한'] = -45
    
    max_val = float(df_s['QQQ'].max()) * 1.5
    for days in [5, 10, 20, 40]:
        sc = f'슬로프{days}일합'
        dc = f'{days}일하한'
        diff = df_s[dc] - df_s[sc]
        df_s[f'{days}일_초록'] = np.where((diff >= 0) & (diff < 10), max_val, 0)
        df_s[f'{days}일_주황'] = np.where((diff >= 10) & (diff < 20), max_val, 0)
        df_s[f'{days}일_빨강'] = np.where((diff >= 20) & (diff < 30), max_val, 0)
        df_s[f'{days}일_검정'] = np.where(diff >= 30, max_val, 0)
        
    # 신규 슬로프합 (당일 QQQ 포함 슬로프합) 및 감지 신호 계산 추가
    for days in [5, 10, 20, 30, 40, 50, 60, 70, 80]:
        df_s[f'신규슬로프{days}일합'] = slope_sum_lagged(sl, days)
        
    for days in [5, 10, 20, 30, 40, 50, 60, 70]:
        sc = f'신규슬로프{days}일합'
        dc = f'{days}일하한'
        diff = df_s[dc] - df_s[sc]
        df_s[f'{days}일_신규_초록'] = np.where((diff >= 0) & (diff < 10), max_val, 0)
        df_s[f'{days}일_신규_주황'] = np.where((diff >= 10) & (diff < 20), max_val, 0)
        df_s[f'{days}일_신규_빨강'] = np.where((diff >= 20) & (diff < 30), max_val, 0)
        df_s[f'{days}일_신규_검정'] = np.where(diff >= 30, max_val, 0)
        
    # (FGI-VIX)/5 의 슬로프합 추가
    fv5_sl = df_s['(FGI-VIX)/5'].diff().values
    for days in [10, 20, 30, 40, 50, 60, 70]:
        df_s[f'FV5_슬로프{days}일합'] = slope_sum_lagged(fv5_sl, days)
        
    df_s.set_index('Date', inplace=True)
    
    # ── 감마익스포저(GEX) 및 풋콜레이쇼(PCR) 데이터 가공 ──
    try:
        dix_url = "https://squeezemetrics.com/monitor/static/DIX.csv"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(dix_url, headers=headers, timeout=10)
        from io import StringIO
        dix_df = pd.read_csv(StringIO(r.text))
        dix_df['Date'] = pd.to_datetime(dix_df['date'])
        dix_df['GEX'] = dix_df['gex']
        dix_df['GEX_Bil'] = dix_df['gex'] / 1000000000.0
        dix_df.set_index('Date', inplace=True)
        
        df_s = df_s.join(dix_df[['GEX', 'GEX_Bil']], how='left')
        df_s['GEX'] = df_s['GEX'].ffill().fillna(0)
        df_s['GEX_Bil'] = df_s['GEX_Bil'].ffill().fillna(0)
    except Exception as e:
        df_s['GEX'] = 0.0
        df_s['GEX_Bil'] = 0.0
        
    try:
        pcr_raw = 0.45 + 0.15 * (df_s['VIX'] / 16.0) + 0.20 * ((100.0 - df_s['FearGreedIndex']) / 50.0)
        df_s['PutCallRatio'] = pcr_raw.clip(0.40, 1.80)
    except Exception as e:
        df_s['PutCallRatio'] = 0.80
        
    # 저점 및 고점 신호 정의 (포착률 12~17% 재조정 타겟)
    df_s['GammaPutCall_Bottom_Signal'] = (df_s['GEX_Bil'] <= -0.5) & (df_s['PutCallRatio'] >= 1.08)
    df_s['GammaPutCall_Top_Signal'] = (df_s['GEX_Bil'] >= 1.0) & (df_s['PutCallRatio'] <= 0.72)
    
    # ── 감마풋콜기타 혼합 복합 지표 산출 (볼린저, 변동성, 가속도 결합) ──
    try:
        df_s['MA20'] = df_s['QQQ'].rolling(20, min_periods=1).mean()
        df_s['STD20'] = df_s['QQQ'].rolling(20, min_periods=1).std().fillna(0)
        df_s['BB_Lower'] = df_s['MA20'] - 2 * df_s['STD20']
        df_s['BB_Upper'] = df_s['MA20'] + 2 * df_s['STD20']
        df_s['Momentum10'] = df_s['QQQ'].pct_change(10).fillna(0)
        
        # 저점/고점 혼합 스코어 계산
        df_s['Score_Bottom'] = (df_s['VIX'] / 16.0) + (df_s['PutCallRatio'] * 1.5) + ((100.0 - df_s['FearGreedIndex']) / 10.0) - (df_s['GEX_Bil'] * 2.0) + np.where(df_s['QQQ'] < df_s['BB_Lower'], 3.0, 0.0) - (df_s['Momentum10'] * 10.0)
        df_s['Score_Top'] = (16.0 / (df_s['VIX'] + 1e-10)) + (1.0 / (df_s['PutCallRatio'] + 1e-10)) + (df_s['FearGreedIndex'] / 10.0) + (df_s['GEX_Bil'] * 0.5) + np.where(df_s['QQQ'] > df_s['BB_Upper'], 2.0, 0.0) + (df_s['Momentum10'] * 10.0)
        
        # 최종 혼합 감지 신호 (포착률 10~20% 타겟)
        df_s['Hybrid_Bottom_Signal'] = df_s['Score_Bottom'] >= 20.0
        df_s['Hybrid_Top_Signal'] = df_s['Score_Top'] >= 16.5
    except Exception as e:
        df_s['Score_Bottom'] = 0.0
        df_s['Score_Top'] = 0.0
        df_s['Hybrid_Bottom_Signal'] = False
        df_s['Hybrid_Top_Signal'] = False
    
    return df_s[~df_s.index.duplicated(keep='first')]

# 한국 데이터 빌드 (FGI 50 고정 해결을 위해 NaN + Time Interpolation 처리)
@st.cache_data(ttl=60)
def fetch_korean_market_data_v2(df_us=None):
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
    df_kr_s['슬로프30일합'] = slope_sum_lagged(sl_kr, 30)
    df_kr_s['슬로프40일합'] = slope_sum_lagged(sl_kr, 40)
    df_kr_s['슬로프50일합'] = slope_sum_lagged(sl_kr, 50)
    df_kr_s['슬로프60일합'] = slope_sum_lagged(sl_kr, 60)
    df_kr_s['슬로프70일합'] = slope_sum_lagged(sl_kr, 70)
    
    # KOSPI 기준 상하한 임계값 설정 (새로운 조건: 하한 -10~-40 및 하위호환 5, 10, 20, 40)
    df_kr_s['5일상한'] = 30;  df_kr_s['5일하한'] = -30
    df_kr_s['10일상한'] = 15; df_kr_s['10일하한'] = -15
    df_kr_s['20일상한'] = 20; df_kr_s['20일하한'] = -20
    df_kr_s['30일상한'] = 25; df_kr_s['30일하한'] = -25
    df_kr_s['40일상한'] = 30; df_kr_s['40일하한'] = -30
    df_kr_s['50일상한'] = 35; df_kr_s['50일하한'] = -35
    df_kr_s['60일상한'] = 40; df_kr_s['60일하한'] = -40
    df_kr_s['70일상한'] = 45; df_kr_s['70일하한'] = -45
    
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
    df_kr_s = df_kr_s[~df_kr_s.index.duplicated(keep='first')]

    # ── KOSPI 기술적 보조지표 연산 추가 ──
    # 1) KOSPI RSI (14일)
    delta_k = df_kr_s['KOSPI'].diff()
    gain_k = (delta_k.where(delta_k > 0, 0)).rolling(window=14).mean()
    loss_k = (-delta_k.where(delta_k < 0, 0)).rolling(window=14).mean()
    rs_k = gain_k / (loss_k + 1e-10)
    df_kr_s['KOSPI_RSI'] = 100 - (100 / (1 + rs_k))
    
    # KOSPI RSI (7일)
    gain7_k = (delta_k.where(delta_k > 0, 0)).rolling(window=7).mean()
    loss7_k = (-delta_k.where(delta_k < 0, 0)).rolling(window=7).mean()
    rs7_k = gain7_k / (loss7_k + 1e-10)
    df_kr_s['KOSPI_RSI7'] = 100 - (100 / (1 + rs7_k))
    
    # 2) KOSPI 볼린저 밴드 %B (20일)
    ma20_k = df_kr_s['KOSPI'].rolling(20).mean()
    std20_k = df_kr_s['KOSPI'].rolling(20).std()
    df_kr_s['KOSPI_%B'] = (df_kr_s['KOSPI'] - (ma20_k - 2 * std20_k)) / (4 * std20_k + 1e-10)
    
    # 3) VKOSPI Z-score (200일 기준)
    vkospi_ma200 = df_kr_s['VKOSPI'].rolling(200).mean()
    vkospi_std200 = df_kr_s['VKOSPI'].rolling(200).std()
    df_kr_s['VKOSPI_Z'] = (df_kr_s['VKOSPI'] - vkospi_ma200) / (vkospi_std200 + 1e-10)
    
    # VKOSPI 퍼센타일 (252일 롤링)
    df_kr_s['VKOSPI_Pct'] = df_kr_s['VKOSPI'].rolling(252, min_periods=60).rank(pct=True)
    
    # KOSPI 낙폭 및 드로우다운 퍼센타일
    df_kr_s['KOSPI_Peak'] = df_kr_s['KOSPI'].rolling(252, min_periods=1).max()
    df_kr_s['KOSPI_DD'] = (df_kr_s['KOSPI_Peak'] - df_kr_s['KOSPI']) / df_kr_s['KOSPI_Peak']
    df_kr_s['K_DD_Pct'] = df_kr_s['KOSPI_DD'].rolling(252, min_periods=60).rank(pct=True)

    # 4) 미국(글로벌) 리스크 피처 조인
    if df_us is not None:
        global_cols = ['SKEW', 'VVIX', 'VVIX_Z', 'VVIX_Pct', 'HYG_RSI', 'TNX_ROC', 'FGI_Pct', 'VIX_Z']
        df_us_filtered = df_us[[c for c in global_cols if c in df_us.columns]].copy()
        if 'FearGreedIndex' in df_us.columns:
            df_us_filtered['US_FGI'] = df_us['FearGreedIndex']
        df_kr_s = df_kr_s.join(df_us_filtered, how='left')
        df_kr_s = df_kr_s.ffill().bfill()
        
    return df_kr_s

@st.cache_data(ttl=300, show_spinner=False)
def fetch_monitoring_data_v2(num_pages=25):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r_k1 = requests.get('https://finance.naver.com/sise/sise_index_day.naver?code=KOSPI&page=1', headers=headers, timeout=5)
        dfs_k1 = pd.read_html(StringIO(r_k1.text), encoding='euc-kr')
        df_k1 = dfs_k1[0].dropna(how='all')
        latest_dt = pd.to_datetime(df_k1.iloc[0, 0], format='%Y.%m.%d', errors='coerce')
        bizdate_str = latest_dt.strftime('%Y%m%d') if pd.notna(latest_dt) else datetime.date.today().strftime('%Y%m%d')
    except Exception:
        bizdate_str = datetime.date.today().strftime('%Y%m%d')
    
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
        url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={bizdate_str}&sosok=01&page={page}'
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
    
    # yfinance로 2020년부터 전체 KOSPI/KOSDAQ 지수 일괄 로드
    yf_kospi = yf.download('^KS11', start="2020-01-01", progress=False)
    if isinstance(yf_kospi.columns, pd.MultiIndex): yf_kospi.columns = yf_kospi.columns.get_level_values(0)
    if not yf_kospi.empty and getattr(yf_kospi.index, 'tz', None) is not None:
        yf_kospi.index = yf_kospi.index.tz_localize(None)
        
    yf_kosdaq = yf.download('^KQ11', start="2020-01-01", progress=False)
    if isinstance(yf_kosdaq.columns, pd.MultiIndex): yf_kosdaq.columns = yf_kosdaq.columns.get_level_values(0)
    if not yf_kosdaq.empty and getattr(yf_kosdaq.index, 'tz', None) is not None:
        yf_kosdaq.index = yf_kosdaq.index.tz_localize(None)
    
    if not yf_kospi.empty:
        # 네이버 KOSPI 지수 대신 yfinance KOSPI 지수로 덮어쓰거나 채움 (과거 데이터 확보)
        df_merged = df_merged.join(yf_kospi[['Close']].rename(columns={'Close': 'yf_KOSPI'}), how='outer')
        df_merged['KOSPI'] = df_merged['yf_KOSPI'].combine_first(df_merged['KOSPI'])
        df_merged.drop(columns=['yf_KOSPI'], inplace=True)
    
    if not yf_kosdaq.empty:
        df_merged = df_merged.join(yf_kosdaq[['Close']].rename(columns={'Close': 'KOSDAQ'}), how='outer')
        
    df_merged['Retail_Cum'] = df_merged['Retail'].fillna(0).cumsum()
    df_merged['Foreign_Cum'] = df_merged['Foreign'].fillna(0).cumsum()
    df_merged['Institution_Cum'] = df_merged['Institution'].fillna(0).cumsum()
    
    # 삼성전자, 하이닉스 거래대금 추가 수집 및 병합 (단위: 백만원)
    try:
        min_date = df_merged.index.min()
        if pd.notna(min_date):
            start_date_str = min_date.strftime('%Y-%m-%d')
        else:
            start_date_str = "2020-01-01"
            
        sec = yf.download('005930.KS', start=start_date_str, progress=False)
        if isinstance(sec.columns, pd.MultiIndex): sec.columns = sec.columns.get_level_values(0)
        if not sec.empty and getattr(sec.index, 'tz', None) is not None: sec.index = sec.index.tz_localize(None)
        if not sec.empty and 'Volume' in sec.columns:
            sec.loc[sec['Volume'] < 10000, 'Volume'] = np.nan
            sec['Volume'] = sec['Volume'].ffill()
        
        hynix = yf.download('000660.KS', start=start_date_str, progress=False)
        if isinstance(hynix.columns, pd.MultiIndex): hynix.columns = hynix.columns.get_level_values(0)
        if not hynix.empty and getattr(hynix.index, 'tz', None) is not None: hynix.index = hynix.index.tz_localize(None)
        if not hynix.empty and 'Volume' in hynix.columns:
            hynix.loc[hynix['Volume'] < 10000, 'Volume'] = np.nan
            hynix['Volume'] = hynix['Volume'].ffill()
        
        if not sec.empty and 'Close' in sec.columns and 'Volume' in sec.columns:
            sec_val = (sec['Close'] * sec['Volume']) / 1000000.0
        else:
            sec_val = pd.Series(dtype='float64')
            
        if not hynix.empty and 'Close' in hynix.columns and 'Volume' in hynix.columns:
            hynix_val = (hynix['Close'] * hynix['Volume']) / 1000000.0
        else:
            hynix_val = pd.Series(dtype='float64')
            
        df_sec_hynix = pd.DataFrame(index=df_merged.index)
        df_sec_hynix['SEC_Val'] = sec_val.reindex(df_merged.index).ffill().bfill().fillna(0)
        df_sec_hynix['HYNIX_Val'] = hynix_val.reindex(df_merged.index).ffill().bfill().fillna(0)
        df_sec_hynix['SEC_HYNIX_Val'] = df_sec_hynix['SEC_Val'] + df_sec_hynix['HYNIX_Val']
        
        df_merged['SEC_HYNIX_Val'] = df_sec_hynix['SEC_HYNIX_Val']
        df_merged['KOSPI_ex_SEC_HYNIX_Val'] = df_merged['TradingValue'] - df_merged['SEC_HYNIX_Val']
    except Exception as e:
        df_merged['SEC_HYNIX_Val'] = 0
        df_merged['KOSPI_ex_SEC_HYNIX_Val'] = df_merged['TradingValue']
        
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
    df_kr = fetch_korean_market_data_v2(df)
    df_dram = update_and_get_dram_history()
    df_mon = fetch_monitoring_data_v2()

# 탭 구성: 저점지표 / 고점지표 / 모니터링
tab_names = ['저점지표', '고점지표', '모니터링']
tabs = st.tabs(tab_names)

# ── Tab 1: 저점지표 ──
with tabs[0]:
    bottom_sub_tab_names = ['공탐변동', '슬로프합', '다중지표', '통합지표']
    bottom_sub_tabs = st.tabs(bottom_sub_tab_names)
    
    def render_bottom_panic_us():
        five_years_ago = pd.to_datetime('2020-01-01')
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
        all_detected_sorted = sorted(date_color_map.keys(), reverse=True)[:100]

        TH_SIG = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;"
        TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
        
        date_cells = "".join([f"<td style='background:{date_color_map[d][0]};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        vix_cells = "".join([f"<td style='color:black;font-weight:bold;{TD_SIG}'>{df1.loc[d, 'VIX']:.2f}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        fgi_cells = "".join([f"<td style='color:black;font-weight:bold;{TD_SIG}'>{df1.loc[d, 'FearGreedIndex']:.1f}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        fv5_cells = "".join([f"<td style='color:black;font-weight:bold;{TD_SIG}'>{df1.loc[d, '(FGI-VIX)/5']:.2f}</td>" for d in all_detected_sorted]) if all_detected_sorted else ""
        
        st.markdown(
            f"<div style='margin-bottom:0.2rem;'>"
            f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 100개)</span>"
            f"<div style='overflow-x:auto;margin-top:3px;'>"
            f"<table style='border-collapse:collapse;font-size:0.55rem;text-align:center;'>"
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
        
        fig.add_trace(go.Scatter(x=hd1, y=df1['QQQ'], name='QQQ', mode='lines+markers', line=dict(color='rgba(0, 0, 0, 0.5)', width=2), marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)), hovertemplate='QQQ: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig.add_trace(go.Scatter(x=hd1, y=df1['VIX'], name='VIX', line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate='VIX: %{y:.2f}<extra></extra>'), secondary_y=True)
        fig.add_trace(go.Scatter(x=hd1, y=df1['FearGreedIndex'], name='FGI', line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
        fig.add_trace(go.Scatter(x=hd1, y=df1['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='rgba(0, 128, 0, 0.8)', width=1), hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
        
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
        st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
        render_stats_table(stats, "지표검증결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")

        
        st.markdown("#### 📌 역사적 대폭락/하락장 주요 사건 및 하락률")
        
        # 실시간 가격 데이터 기반 조정 감지 및 지능형 병합 알고리즘
        detected_evs = detect_recent_drawdowns(df, 'QQQ', 0.10)
        raw_list = static_historical_events.copy()
        for dev in detected_evs:
            # 기본 감지 명칭이 없으면 하락조정장 처리
            if not dev.get('title'):
                dev['title'] = "하락조정장"
            raw_list.append(dev)
            
        # 연월 파싱용 헬퍼 함수
        def parse_to_val(ym_str):
            try:
                y, m = map(int, ym_str.split('.'))
                return y, m
            except:
                return 0, 0

        # 중복/겹침 병합 수행
        merged_list = []
        # 날짜 순 정렬하여 병합 처리
        def get_start_date_val(ev):
            y, m = parse_to_val(ev['period'].split(' ~ ')[0])
            return y * 12 + m
        
        sorted_raw = sorted(raw_list, key=get_start_date_val)
        
        for ev in sorted_raw:
            if not merged_list:
                merged_list.append(ev)
                continue
            
            prev = merged_list[-1]
            import datetime as dt_module
            now_dt = dt_module.date.today()
            
            p_s_y, p_s_m = parse_to_val(prev['period'].split(' ~ ')[0])
            p_end_str = prev['period'].split(' ~ ')[1]
            if p_end_str == "진행중":
                p_e_y, p_e_m = now_dt.year, now_dt.month
            else:
                p_e_y, p_e_m = parse_to_val(p_end_str)
                
            c_s_y, c_s_m = parse_to_val(ev['period'].split(' ~ ')[0])
            c_end_str = ev['period'].split(' ~ ')[1]
            if c_end_str == "진행중":
                c_e_y, c_e_m = now_dt.year, now_dt.month
            else:
                c_e_y, c_e_m = parse_to_val(c_end_str)
            
            p_start = p_s_y * 12 + p_s_m
            p_end = p_e_y * 12 + p_e_m
            c_start = c_s_y * 12 + c_s_m
            c_end = c_e_y * 12 + c_e_m
            
            # 기간이 겹치거나(Overlap), 연속하는 경우 병합
            if c_start <= p_end + 1:
                # 시작/끝 연월 범위 통합
                min_start = min(p_start, c_start)
                max_end = max(p_end, c_end)
                
                min_y, min_m = min_start // 12, min_start % 12
                if min_m == 0:
                    min_y -= 1
                    min_m = 12
                max_y, max_m = max_end // 12, max_end % 12
                if max_m == 0:
                    max_y -= 1
                    max_m = 12
                    
                if p_end_str.strip() == "진행중" or c_end_str.strip() == "진행중":
                    prev['period'] = f"{min_y}.{min_m:02d} ~ 진행중"
                else:
                    prev['period'] = f"{min_y}.{min_m:02d} ~ {max_y}.{max_m:02d}"
                
                # 명칭 통합: 구체적인 역사적 사건명을 우선 사용
                # 둘 다 일반 하락조정장이면 하락조정장 유지
                titles = [prev['title'], ev['title']]
                specific_title = "하락조정장"
                for t in titles:
                    if "하락조정장" not in t:
                        specific_title = t
                        break
                prev['title'] = specific_title
                
                # 하락률은 더 큰 하락률(더 마이너스인 값) 선택
                try:
                    p_rate = int(prev['fall_rate'].replace('%', ''))
                    c_rate = int(ev['fall_rate'].replace('%', ''))
                    prev['fall_rate'] = f"{min(p_rate, c_rate)}%"
                except:
                    pass
            else:
                merged_list.append(ev)
                
        # 최종 리스트를 최신순(역순)으로 재정렬
        combined_events = sorted(merged_list, key=get_start_date_val, reverse=True)

        rows_html = ""
        for idx, ev in enumerate(combined_events):
            duration = calculate_duration(ev['period'])
            rows_html += f"<tr><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>{ev['period']}</td><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>{duration}</td><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>{ev['title']}</td><td style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;color:#FF6B9D;font-weight:bold;'>{ev['fall_rate']}</td></tr>"
        st.markdown(f"<div style='margin-right: 0px;'><table style='width:100%;border-collapse:collapse;text-align:center;'><thead style='background:#1F4E79;color:white;'><tr><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>날짜</th><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>하락기간</th><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>사건 내용</th><th style='border:1px solid #555;padding:4px;text-align:center;white-space:nowrap;'>하락률</th></tr></thead><tbody>{rows_html}</tbody></table></div>", unsafe_allow_html=True)

    def render_bottom_panic_kr():
        five_years_ago = pd.to_datetime('2020-01-01')
        df1_kr = df_kr[df_kr.index >= five_years_ago]
        
        v2_black = ((df1_kr['FearGreedIndex'] <= 18) & (df1_kr['VKOSPI'] >= 26)) | ((df1_kr['FearGreedIndex'] == 50) & (df1_kr['VKOSPI'] >= 30) & (df1_kr['KOSPI_%B'] <= 0.05))
        v2_red = (((df1_kr['FearGreedIndex'] >= 19) & (df1_kr['FearGreedIndex'] <= 25)) & (df1_kr['VKOSPI'] >= 22)) | ((df1_kr['FearGreedIndex'] == 50) & (df1_kr['VKOSPI'] >= 24) & (df1_kr['VKOSPI'] < 30) & (df1_kr['KOSPI_%B'] <= 0.10))
        v2_yellow = (((df1_kr['FearGreedIndex'] >= 26) & (df1_kr['FearGreedIndex'] <= 32)) & (df1_kr['VKOSPI'] >= 18)) | ((df1_kr['FearGreedIndex'] == 50) & (df1_kr['VKOSPI'] >= 20) & (df1_kr['VKOSPI'] < 24) & (df1_kr['KOSPI_%B'] <= 0.20))
        v2_green = (((df1_kr['FearGreedIndex'] >= 33) & (df1_kr['FearGreedIndex'] <= 40)) & (df1_kr['VKOSPI'] >= 14)) | ((df1_kr['FearGreedIndex'] == 50) & (df1_kr['VKOSPI'] >= 20) & (df1_kr['VKOSPI'] < 24) & (df1_kr['KOSPI_%B'] <= 0.20))

        color_cond_map_kr = [
            (v2_black,  '#595959', '#FFFFFF', 'rgba(0,0,0,0.3)'),
            (v2_red,    '#E06666', '#FFFFFF', 'rgba(220,30,30,0.3)'),
            (v2_yellow, '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
            (v2_green,  '#A9D08E', '#000000', 'rgba(0,128,0,0.3)'),
        ]

        date_color_map_kr = {}
        for cond, bg, fg, _ in reversed(color_cond_map_kr):
            for d in df1_kr[cond].index:
                date_color_map_kr[d] = (bg, fg)
        all_detected_sorted_kr = sorted(date_color_map_kr.keys(), reverse=True)[:100]

        TH_SIG = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;"
        TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
        
        date_cells_kr = "".join([f"<td style='background:{date_color_map_kr[d][0]};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        vix_cells_kr = "".join([f"<td style='color:black;font-weight:bold;{TD_SIG}'>{df1_kr.loc[d, 'VKOSPI']:.2f}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        fgi_cells_kr = "".join([f"<td style='color:black;font-weight:bold;{TD_SIG}'>{df1_kr.loc[d, 'FearGreedIndex']:.1f}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        fv5_cells_kr = "".join([f"<td style='color:black;font-weight:bold;{TD_SIG}'>{df1_kr.loc[d, '(FGI-VIX)/5']:.2f}</td>" for d in all_detected_sorted_kr]) if all_detected_sorted_kr else ""
        
        st.markdown(
            f"<div style='margin-bottom:0.2rem;'>"
            f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 100개)</span>"
            f"<div style='overflow-x:auto;margin-top:3px;'>"
            f"<table style='border-collapse:collapse;font-size:0.55rem;text-align:center;'>"
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
        
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['KOSPI'], name='KOSPI', mode='lines+markers', line=dict(color='rgba(0, 0, 0, 0.5)', width=2), marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)), hovertemplate='KOSPI: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['VKOSPI'], name='VKOSPI', line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate='VKOSPI: %{y:.2f}<extra></extra>'), secondary_y=True)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['FearGreedIndex'], name='FGI', line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
        fig_kr.add_trace(go.Scatter(x=hd1_kr, y=df1_kr['(FGI-VIX)/5'], name='(FGI-VKOSPI)/5', line=dict(color='rgba(0, 128, 0, 0.8)', width=1), hovertemplate='(FGI-VKOSPI)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
        
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
        v2_black_all = ((df_kr['FearGreedIndex'] <= 18) & (df_kr['VKOSPI'] >= 26)) | ((df_kr['FearGreedIndex'] == 50) & (df_kr['VKOSPI'] >= 30) & (df_kr['KOSPI_%B'] <= 0.05))
        v2_red_all = (((df_kr['FearGreedIndex'] >= 19) & (df_kr['FearGreedIndex'] <= 25)) & (df_kr['VKOSPI'] >= 22)) | ((df_kr['FearGreedIndex'] == 50) & (df_kr['VKOSPI'] >= 24) & (df_kr['VKOSPI'] < 30) & (df_kr['KOSPI_%B'] <= 0.10))
        v2_yellow_all = (((df_kr['FearGreedIndex'] >= 26) & (df_kr['FearGreedIndex'] <= 32)) & (df_kr['VKOSPI'] >= 18)) | ((df_kr['FearGreedIndex'] == 50) & (df_kr['VKOSPI'] >= 20) & (df_kr['VKOSPI'] < 24) & (df_kr['KOSPI_%B'] <= 0.20))
        v2_green_all = (((df_kr['FearGreedIndex'] >= 33) & (df_kr['FearGreedIndex'] <= 40)) & (df_kr['VKOSPI'] >= 14)) | ((df_kr['FearGreedIndex'] == 50) & (df_kr['VKOSPI'] >= 20) & (df_kr['VKOSPI'] < 24) & (df_kr['KOSPI_%B'] <= 0.20))

        fgi_conditions_kr = {
            "**[검정] 극단적 패닉**": (v2_black_all, "극단적 패닉 (KR FGI <= 18 & VKOSPI >= 26)"),
            "**[빨강] 강한 패닉**": (v2_red_all, "강한 패닉 (19 <= KR FGI <= 25 & VKOSPI >= 22)"),
            "**[노랑] 약세 패닉**": (v2_yellow_all, "약세 패닉 (26 <= KR FGI <= 32 & VKOSPI >= 18)"),
            "**[초록] 주의 구간**": (v2_green_all, "주의 구간 (33 <= KR FGI <= 40 & VKOSPI >= 14)"),
            "**공탐변동 종합 감지**": (
                v2_black_all | v2_red_all | v2_yellow_all | v2_green_all,
                "위 4가지 색 중 하나 이상 감지"
            )
        }
        stats_kr = calculate_indicator_stats(df_kr, 'KOSPI', fgi_conditions_kr)
        st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
        render_stats_table(stats_kr, "지표검증결과 (2018.01 ~ 현재 KOSPI 저점 대비 실시간 자동 업데이트)")

    # ── 소분류 1: 공탐변동 ──
    with bottom_sub_tabs[0]:
        if selected_country == "미국":
            render_bottom_panic_us()
        elif selected_country == "한국":
            render_bottom_panic_kr()

    # ── 소분류 2: 슬로프합 ──
    with bottom_sub_tabs[1]:
        if selected_country == "미국":
            SLOPE_BOTTOM_CHARTS_NEW = [
                (2, 10, '신규슬로프10일합', -15),
                (3, 20, '신규슬로프20일합', -20),
                (4, 30, '신규슬로프30일합', -25),
                (5, 40, '신규슬로프40일합', -30),
                (6, 50, '신규슬로프50일합', -35),
                (7, 60, '신규슬로프60일합', -40),
                (8, 70, '신규슬로프70일합', -45),
            ]
            
            # 동시 감지 갯수 계산 및 저장
            slope_detect_count_new = sum(((df[sfc] <= thresh)).astype(int) for _, _, sfc, thresh in SLOPE_BOTTOM_CHARTS_NEW)
            df['slope_detect_count_new'] = slope_detect_count_new
            
            # 상한 돌파 신호 감지표 (하한 돌파 저점 신호 수집)
            all_top_sl_new = []
            for _, days_t, sfc, thresh in SLOPE_BOTTOM_CHARTS_NEW:
                _cond_sl = (df[sfc] <= thresh)
                all_top_sl_new.extend(df[_cond_sl].index.tolist())
            dc_top_sl_new = Counter(all_top_sl_new)
            parent_dates_sl_new = sorted(list(set(all_top_sl_new)), reverse=True)
            
            # 당일(실시간) 임시 판정
            temp_slope_vals_new = {}
            for _, days, _, th in SLOPE_BOTTOM_CHARTS_NEW:
                val_today = float(df['QQQ'].iloc[-1] - df['QQQ'].iloc[-1 - days])
                temp_slope_vals_new[days] = val_today
            
            cnt_today_new = sum(1 for _, days, _, th in SLOPE_BOTTOM_CHARTS_NEW if temp_slope_vals_new[days] <= th)
            bg_today_new = "#E06666" if cnt_today_new==1 else "#FF8C00" if cnt_today_new==2 else '#FFD700' if cnt_today_new==3 else "#A9D08E" if cnt_today_new==4 else "#87CEEB" if cnt_today_new==5 else "#000080" if cnt_today_new==6 else "#800080" if cnt_today_new >= 7 else "transparent"
            fg_today_new = "#FFF" if cnt_today_new > 0 else "#000"
            date_cell_today_new = f"<td style='background:{bg_today_new};color:{fg_today_new};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;font-size:0.55rem;white-space:nowrap;'>당일(실시간)</td>"
            
            detected_items_today_new = []
            for _, days, _, th in SLOPE_BOTTOM_CHARTS_NEW:
                val_t = temp_slope_vals_new[days]
                if val_t <= th:
                    val_diff_pct = (th - val_t) / abs(th)
                    if 0.0 <= val_diff_pct <= 0.40:
                        color = '#A9D08E'
                    elif 0.40 < val_diff_pct <= 0.60:
                        color = '#FFD700'
                    elif 0.60 < val_diff_pct <= 0.80:
                        color = '#E06666'
                    else:
                        color = '#595959'
                    detected_items_today_new.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                else:
                    detected_items_today_new.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
            val_str_today_new = "<br>".join(detected_items_today_new)
            count_cell_today_new = f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str_today_new}</td>"

            if parent_dates_sl_new:
                r100_sl_new = parent_dates_sl_new[:100]
                dates_row_sl_new = []
                counts_row_sl_new = []
                for dt in r100_sl_new:
                    cnt = dc_top_sl_new.get(dt, 1)
                    bg = "#E06666" if cnt==1 else "#FF8C00" if cnt==2 else '#FFD700' if cnt==3 else "#A9D08E" if cnt==4 else "#87CEEB" if cnt==5 else "#000080" if cnt==6 else "#800080"
                    fg = "#FFF"
                    dates_row_sl_new.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    
                    detected_items = []
                    for _, days, sc_col, th in SLOPE_BOTTOM_CHARTS_NEW:
                        if dt in df.index and df.loc[dt, sc_col] <= th:
                            val_diff_pct = (th - df.loc[dt, sc_col]) / abs(th)
                            if 0.0 <= val_diff_pct <= 0.40:
                                color = '#A9D08E'
                            elif 0.40 < val_diff_pct <= 0.60:
                                color = '#FFD700'
                            elif 0.60 < val_diff_pct <= 0.80:
                                color = '#E06666'
                            else:
                                color = '#595959'
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    
                    val_str = "<br>".join(detected_items)
                    counts_row_sl_new.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 100개, 당일 포함)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                     <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join([date_cell_today_new] + dates_row_sl_new)}
                     </tr>
                     <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>이탈</th>
                        {"".join([count_cell_today_new] + counts_row_sl_new)}
                     </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            hd_df = [fmt_date_kor(d) for d in df.index]
            bottom_slope_options_new = ["슬로프통합", "10일합", "20일합", "30일합", "40일합", "50일합", "60일합", "70일합"]
            selected_bottom_slopes_new = st.multiselect("📊 표시할 슬로프 차트 선택 (다중 선택 가능)", bottom_slope_options_new, default=["슬로프통합"], key="bottom_slope_new_multiselect")
            
            if not selected_bottom_slopes_new:
                st.info("시각화할 슬로프 지표를 다중 선택창에서 선택해 주세요 (예: 슬로프통합, 10일합 등).")
            else:
                num_charts_new = len(selected_bottom_slopes_new)
                fig_dsi_new = make_subplots(rows=num_charts_new, cols=1, shared_xaxes=True, vertical_spacing=0.03 if num_charts_new > 1 else 0.0,
                    subplot_titles=tuple(selected_bottom_slopes_new),
                    specs=[[{"secondary_y": True}]]*num_charts_new)
                
                chart_info_map_new = {
                    10: ('신규슬로프10일합', -15),
                    20: ('신규슬로프20일합', -20),
                    30: ('신규슬로프30일합', -25),
                    40: ('신규슬로프40일합', -30),
                    50: ('신규슬로프50일합', -35),
                    60: ('신규슬로프60일합', -40),
                    70: ('신규슬로프70일합', -45),
                }
                
                for idx, choice in enumerate(selected_bottom_slopes_new):
                    row_i = idx + 1
                    sf = (idx == 0)
                    
                    if choice == "슬로프통합":
                        fig_dsi_new.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=False,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        
                        detect_colors_new = {
                            1: 'rgba(224, 102, 102, 0.45)', # 빨강
                            2: 'rgba(255, 140, 0, 0.3)',   # 주황
                            3: 'rgba(255, 255, 153, 0.45)', # 노랑
                            4: 'rgba(0, 128, 0, 0.3)', # 초록
                            5: 'rgba(135, 206, 235, 0.3)', # 파랑
                            6: 'rgba(0, 0, 128, 0.3)',     # 남색
                            7: 'rgba(128, 0, 128, 0.3)'    # 보라
                        }
                        for cnt_val, bar_color in detect_colors_new.items():
                            cond_bar = (df['slope_detect_count_new'] == cnt_val)
                            fig_dsi_new.add_trace(go.Bar(
                                x=hd_df,
                                y=cond_bar.astype(int).values * float(df['QQQ'].max()) * 1.2,
                                marker_color=bar_color,
                                showlegend=False,
                                hoverinfo='skip',
                                marker_line_width=0.5,
                                marker_line_color='white'
                            ), row=row_i, col=1, secondary_y=False)
                            
                    else:
                        days = int(choice.replace("일합", ""))
                        sc, thresh = chart_info_map_new[days]
                        
                        fig_dsi_new.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        fig_dsi_new.add_trace(go.Scatter(x=hd_df,y=df[sc],name=f'신규슬로프 {days}일합계',line=dict(color='rgba(255, 0, 0, 0.8)', width=1),showlegend=True,hovertemplate=f'신규슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=row_i,col=1,secondary_y=True)
                        fig_dsi_new.add_trace(go.Scatter(x=hd_df,y=[-thresh]*len(hd_df),name='상한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='upper',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        fig_dsi_new.add_trace(go.Scatter(x=hd_df,y=[thresh]*len(hd_df),name='하한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='lower',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        
                        # 초과 비율(%)에 따른 막대 그래프 렌더링 (0% 초과부터 표시)
                        diff_pct = (thresh - df[sc]) / abs(thresh)
                        bottom_cond_vals_new = [
                            ((diff_pct >= 0.0) & (diff_pct <= 0.40), 'rgba(0, 128, 0, 0.3)'),   # 0~40%: 초록
                            ((diff_pct > 0.40) & (diff_pct <= 0.60), 'rgba(255, 220, 0, 0.3)'),    # 40~60%: 노랑
                            ((diff_pct > 0.60) & (diff_pct <= 0.80), 'rgba(220, 30, 30, 0.3)'),    # 60~80%: 빨강
                            ((diff_pct > 0.80), 'rgba(0, 0, 0, 0.3)'),                             # 80% 초과: 검정
                        ]
                        for tc, tfc in bottom_cond_vals_new:
                            fig_dsi_new.add_trace(go.Bar(x=hd_df, y=tc.astype(int).values * float(df['QQQ'].max()) * 1.2, marker_color=tfc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'),row=row_i,col=1,secondary_y=False)
                
                if active_period_days:
                    target_date_dsi = datetime.date.today() - datetime.timedelta(days=active_period_days)
                    detected_indices_dsi = [i for i, d in enumerate(df.index) if d >= pd.to_datetime(target_date_dsi)]
                    initial_x_range_dsi_new = [detected_indices_dsi[0], len(hd_df) - 1] if detected_indices_dsi else None
                    if detected_indices_dsi:
                        qqq_1y_dsi = df['QQQ'].iloc[detected_indices_dsi[0]:]
                        qmin_dsi, qmax_dsi = float(qqq_1y_dsi.min()), float(qqq_1y_dsi.max())
                    else:
                        qmin_dsi, qmax_dsi = float(df['QQQ'].min()), float(df['QQQ'].max())
                else:
                    initial_x_range_dsi_new = None
                    qmin_dsi, qmax_dsi = float(df['QQQ'].min()), float(df['QQQ'].max())
                
                chart_height_new = max(400, num_charts_new * 300)
                layout_params_new = COMMON_LAYOUT.copy()
                layout_params_new.pop('shapes', None)
                
                shapes_new = []
                for idx in range(num_charts_new):
                    y_ref = "y domain" if idx == 0 else f"y{2*idx + 1} domain"
                    shapes_new.append(dict(type="rect", xref="paper", yref=y_ref, x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)))
                    
                fig_dsi_new.update_layout(**layout_params_new, height=chart_height_new, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=shapes_new)
                
                for idx, choice in enumerate(selected_bottom_slopes_new):
                    row_i = idx + 1
                    fig_dsi_new.update_yaxes(range=[qmin_dsi*0.95,qmax_dsi*1.05],**crosshair_yaxis(),secondary_y=False,row=row_i,col=1)
                    if choice == "슬로프통합":
                        fig_dsi_new.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True, row=row_i, col=1)
                    else:
                        fig_dsi_new.update_yaxes(range=[-120,180],tick0=-120,dtick=20,**crosshair_yaxis(),secondary_y=True,row=row_i,col=1)
                
                if initial_x_range_dsi_new:
                    fig_dsi_new.update_xaxes(range=initial_x_range_dsi_new, type='category', **crosshair_xaxis())
                else:
                    fig_dsi_new.update_xaxes(type='category', **crosshair_xaxis())
                fig_dsi_new.update_annotations(font_size=10)
                
                st.plotly_chart(fig_dsi_new, width='stretch', config=COMMON_CONFIG, key="tab2_us_slope_new_chart")
            
            # 실시간 지표검증결과 자동 계산 (QQQ 신규 슬로프합 기준)
            slope_conditions_new = {
                "**10일합 이탈**": (df['신규슬로프10일합'] <= -15, "10일신규슬로프합 <= -15"),
                "**20일합 이탈**": (df['신규슬로프20일합'] <= -20, "20일신규슬로프합 <= -20"),
                "**30일합 이탈**": (df['신규슬로프30일합'] <= -25, "30일신규슬로프합 <= -25"),
                "**40일합 이탈**": (df['신규슬로프40일합'] <= -30, "40일신규슬로프합 <= -30"),
                "**50일합 이탈**": (df['신규슬로프50일합'] <= -35, "50일신규슬로프합 <= -35"),
                "**60일합 이탈**": (df['신규슬로프60일합'] <= -40, "60일신규슬로프합 <= -40"),
                "**70일합 이탈**": (df['신규슬로프70일합'] <= -45, "70일신규슬로프합 <= -45"),
                "**슬로프합 종합 감지**": (
                    (df['신규슬로프10일합'] <= -15) | (df['신규슬로프20일합'] <= -20) | (df['신규슬로프30일합'] <= -25) | 
                    (df['신규슬로프40일합'] <= -30) | (df['신규슬로프50일합'] <= -35) | (df['신규슬로프60일합'] <= -40) | (df['신규슬로프70일합'] <= -45),
                    "1개 이상 지표 이탈"
                ),
                "**슬로프합 강력 이탈**": (
                    ((df['신규슬로프10일합'] <= -15).astype(int) + 
                     (df['신규슬로프20일합'] <= -20).astype(int) + 
                     (df['신규슬로프30일합'] <= -25).astype(int) + 
                     (df['신규슬로프40일합'] <= -30).astype(int) + 
                     (df['신규슬로프50일합'] <= -35).astype(int) + 
                     (df['신규슬로프60일합'] <= -40).astype(int) + 
                     (df['신규슬로프70일합'] <= -45).astype(int)) >= 4,
                    "4개 이상 지표 동시 이탈"
                )
            }
            stats_slope_new = calculate_indicator_stats(df, 'QQQ', slope_conditions_new)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_stats_table(stats_slope_new, "지표검증결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")
            
            # 빨주노초파남보 다중 감지 검증 결과 추가
            v2_slope_rainbow_verify_us = {
                "빨간색 (1개 감지)": (df['slope_detect_count_new'] == 1, "동시 감지 1개"),
                "주황색 (2개 감지)": (df['slope_detect_count_new'] == 2, "동시 감지 2개"),
                "노란색 (3개 감지)": (df['slope_detect_count_new'] == 3, "동시 감지 3개"),
                "초록색 (4개 감지)": (df['slope_detect_count_new'] == 4, "동시 감지 4개"),
                "파란색 (5개 감지)": (df['slope_detect_count_new'] == 5, "동시 감지 5개"),
                "남색 (6개 감지)": (df['slope_detect_count_new'] == 6, "동시 감지 6개"),
                "보라색 (7개 감지)": (df['slope_detect_count_new'] == 7, "동시 감지 7개")
            }
            stats_slope_rainbow_us = calculate_indicator_stats(df, 'QQQ', v2_slope_rainbow_verify_us)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_stats_table(stats_slope_rainbow_us, "슬로프합 최종본 다중 감지 검증 결과")
            
            
        elif selected_country == "한국":
            SLOPE_BOTTOM_CHARTS_KR = [
                (2, 10, '슬로프10일합', -90),
                (3, 20, '슬로프20일합', -140),
                (4, 30, '슬로프30일합', -170),
                (5, 40, '슬로프40일합', -200),
                (6, 50, '슬로프50일합', -230),
                (7, 60, '슬로프60일합', -260),
                (8, 70, '슬로프70일합', -290),
            ]
            
            # 동시 감지 갯수 계산 및 저장
            slope_detect_count_kr = sum(((df_kr[sfc] <= thresh)).astype(int) for _, _, sfc, thresh in SLOPE_BOTTOM_CHARTS_KR)
            df_kr['slope_detect_count'] = slope_detect_count_kr
            
            # 상한 돌파 신호 감지표 (하한 돌파 저점 신호 수집)
            all_top_sl_kr = []
            for _, days_t, sfc, thresh in SLOPE_BOTTOM_CHARTS_KR:
                _cond_sl = (df_kr[sfc] <= thresh)
                all_top_sl_kr.extend(df_kr[_cond_sl].index.tolist())
            dc_top_sl_kr = Counter(all_top_sl_kr)
            parent_dates_sl_kr = sorted(list(set(all_top_sl_kr)), reverse=True)
            if parent_dates_sl_kr:
                r100_sl_kr = parent_dates_sl_kr[:100]
                dates_row_sl_kr = []
                counts_row_sl_kr = []
                for dt in r100_sl_kr:
                    cnt = dc_top_sl_kr.get(dt, 1)
                    bg = "#E06666" if cnt==1 else "#FF8C00" if cnt==2 else '#FFD700' if cnt==3 else "#A9D08E" if cnt==4 else "#87CEEB" if cnt==5 else "#000080" if cnt==6 else "#800080"
                    fg = "#FFF"
                    dates_row_sl_kr.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    
                    detected_items = []
                    for _, days, sc_col, th in SLOPE_BOTTOM_CHARTS_KR:
                        if dt in df_kr.index and df_kr.loc[dt, sc_col] <= th:
                            val_diff_pct = (th - df_kr.loc[dt, sc_col]) / abs(th)
                            if 0.0 <= val_diff_pct <= 0.40:
                                color = '#A9D08E'
                            elif 0.40 < val_diff_pct <= 0.60:
                                color = '#FFD700'
                            elif 0.60 < val_diff_pct <= 0.80:
                                color = '#E06666'
                            else:
                                color = '#595959'
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    
                    val_str = "<br>".join(detected_items)
                    counts_row_sl_kr.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 100개)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_sl_kr)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>이탈</th>
                        {"".join(counts_row_sl_kr)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            hd_df_kr = [fmt_date_kor(d) for d in df_kr.index]
            
            bottom_slope_options_kr = ["슬로프통합", "10일합", "20일합", "30일합", "40일합", "50일합", "60일합", "70일합"]
            selected_bottom_slopes_kr = st.multiselect("📊 표시할 슬로프 차트 선택 (다중 선택 가능)", bottom_slope_options_kr, default=["슬로프통합"], key="bottom_slope_multiselect_kr")
            
            if not selected_bottom_slopes_kr:
                st.info("시각화할 슬로프 지표를 다중 선택창에서 선택해 주세요 (예: 슬로프통합, 10일합 등).")
            else:
                num_charts_kr = len(selected_bottom_slopes_kr)
                fig_dsi_kr = make_subplots(rows=num_charts_kr, cols=1, shared_xaxes=True, vertical_spacing=0.03 if num_charts_kr > 1 else 0.0,
                    subplot_titles=tuple(selected_bottom_slopes_kr),
                    specs=[[{"secondary_y": True}]]*num_charts_kr)
                
                chart_info_map_kr = {
                    10: ('슬로프10일합', -15),
                    20: ('슬로프20일합', -20),
                    30: ('슬로프30일합', -25),
                    40: ('슬로프40일합', -30),
                    50: ('슬로프50일합', -35),
                    60: ('슬로프60일합', -40),
                    70: ('슬로프70일합', -45),
                }
                
                for idx, choice in enumerate(selected_bottom_slopes_kr):
                    row_i = idx + 1
                    sf = (idx == 0)
                    
                    if choice == "슬로프통합":
                        fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr['KOSPI'],name='KOSPI 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=False,legendgroup='kospi',hovertemplate='KOSPI: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        
                        detect_colors = {
                            1: 'rgba(224, 102, 102, 0.45)', # 빨강
                            2: 'rgba(255, 140, 0, 0.3)',   # 주황
                            3: 'rgba(255, 255, 153, 0.45)', # 노랑
                            4: 'rgba(0, 128, 0, 0.3)', # 초록
                            5: 'rgba(135, 206, 235, 0.3)', # 파랑
                            6: 'rgba(0, 0, 128, 0.3)',     # 남색
                            7: 'rgba(128, 0, 128, 0.3)'    # 보라
                        }
                        for cnt_val, bar_color in detect_colors.items():
                            cond_bar = (df_kr['slope_detect_count'] == cnt_val)
                            fig_dsi_kr.add_trace(go.Bar(
                                x=hd_df_kr,
                                y=cond_bar.astype(int).values * float(df_kr['KOSPI'].max()) * 1.2,
                                marker_color=bar_color,
                                showlegend=False,
                                hoverinfo='skip',
                                marker_line_width=0.5,
                                marker_line_color='white'
                            ), row=row_i, col=1, secondary_y=False)
                            
                    else:
                        days = int(choice.replace("일합", ""))
                        sc, thresh = chart_info_map_kr[days]
                        
                        fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr['KOSPI'],name='KOSPI 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=sf,legendgroup='kospi',hovertemplate='KOSPI: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=df_kr[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(255, 0, 0, 0.8)', width=1),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=row_i,col=1,secondary_y=True)
                        fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=[-thresh]*len(hd_df_kr),name='상한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='upper_kr',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        fig_dsi_kr.add_trace(go.Scatter(x=hd_df_kr,y=[thresh]*len(hd_df_kr),name='하한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='lower_kr',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        
                        # 초과 비율(%)에 따른 막대 그래프 렌더링 (0% 초과부터 표시)
                        diff_pct = (thresh - df_kr[sc]) / abs(thresh)
                        bottom_cond_vals = [
                            ((diff_pct >= 0.0) & (diff_pct <= 0.40), 'rgba(0, 128, 0, 0.3)'),
                            ((diff_pct > 0.40) & (diff_pct <= 0.60), 'rgba(255, 220, 0, 0.3)'),
                            ((diff_pct > 0.60) & (diff_pct <= 0.80), 'rgba(220, 30, 30, 0.3)'),
                            ((diff_pct > 0.80), 'rgba(0, 0, 0, 0.3)'),
                        ]
                        for tc, tfc in bottom_cond_vals:
                            fig_dsi_kr.add_trace(go.Bar(x=hd_df_kr, y=tc.astype(int).values * float(df_kr['KOSPI'].max()) * 1.2, marker_color=tfc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'),row=row_i,col=1,secondary_y=False)
                
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
                
                chart_height_kr = max(400, num_charts_kr * 300)
                layout_params_kr = COMMON_LAYOUT.copy()
                layout_params_kr.pop('shapes', None)
                
                shapes_kr = []
                for idx in range(num_charts_kr):
                    y_ref = "y domain" if idx == 0 else f"y{2*idx + 1} domain"
                    shapes_kr.append(dict(type="rect", xref="paper", yref=y_ref, x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)))
                    
                fig_dsi_kr.update_layout(**layout_params_kr, height=chart_height_kr, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=shapes_kr)
                
                for idx, choice in enumerate(selected_bottom_slopes_kr):
                    row_i = idx + 1
                    fig_dsi_kr.update_yaxes(range=[kmin_dsi*0.95,kmax_dsi*1.05],**crosshair_yaxis(),secondary_y=False,row=row_i,col=1)
                    if choice == "슬로프통합":
                        fig_dsi_kr.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True, row=row_i, col=1)
                    else:
                        fig_dsi_kr.update_yaxes(range=[-120,180],tick0=-120,dtick=20,**crosshair_yaxis(),secondary_y=True,row=row_i,col=1)
                
                if initial_x_range_dsi_kr:
                    fig_dsi_kr.update_xaxes(range=initial_x_range_dsi_kr, type='category', **crosshair_xaxis())
                else:
                    fig_dsi_kr.update_xaxes(type='category', **crosshair_xaxis())
                fig_dsi_kr.update_annotations(font_size=10)
                
                st.plotly_chart(fig_dsi_kr, width='stretch', config=COMMON_CONFIG, key="tab2_kr_slope_chart")
            
            # 실시간 지표검증결과 자동 계산 (KOSPI 슬로프합 기준)
            slope_conditions_kr = {
                "**10일합 이탈**": (df_kr['슬로프10일합'] <= -90, "10일슬로프합 <= -90"),
                "**20일합 이탈**": (df_kr['슬로프20일합'] <= -140, "20일슬로프합 <= -140"),
                "**30일합 이탈**": (df_kr['슬로프30일합'] <= -170, "30일슬로프합 <= -170"),
                "**40일합 이탈**": (df_kr['슬로프40일합'] <= -200, "40일슬로프합 <= -200"),
                "**50일합 이탈**": (df_kr['슬로프50일합'] <= -230, "50일슬로프합 <= -230"),
                "**60일합 이탈**": (df_kr['슬로프60일합'] <= -260, "60일슬로프합 <= -260"),
                "**70일합 이탈**": (df_kr['슬로프70일합'] <= -290, "70일슬로프합 <= -290"),
                "**슬로프합 종합 감지**": (
                    (df_kr['슬로프10일합'] <= -90) | (df_kr['슬로프20일합'] <= -140) | (df_kr['슬로프30일합'] <= -170) | 
                    (df_kr['슬로프40일합'] <= -200) | (df_kr['슬로프50일합'] <= -230) | (df_kr['슬로프60일합'] <= -260) | (df_kr['슬로프70일합'] <= -290),
                    "1개 이상 지표 이탈"
                ),
                "**슬로프합 강력 이탈**": (
                    ((df_kr['슬로프10일합'] <= -90).astype(int) + 
                     (df_kr['슬로프20일합'] <= -140).astype(int) + 
                     (df_kr['슬로프30일합'] <= -170).astype(int) + 
                     (df_kr['슬로프40일합'] <= -200).astype(int) + 
                     (df_kr['슬로프50일합'] <= -230).astype(int) + 
                     (df_kr['슬로프60일합'] <= -260).astype(int) + 
                     (df_kr['슬로프70일합'] <= -290).astype(int)) >= 4,
                    "4개 이상 지표 동시 이탈"
                )
            }
            df_kr_past = df_kr[df_kr.index < pd.to_datetime(datetime.date.today())]
            stats_slope_kr = calculate_indicator_stats(df_kr_past, 'KOSPI', slope_conditions_kr)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_stats_table(stats_slope_kr, "지표검증결과 (2018.01 ~ 현재 KOSPI 저점 대비 실시간 자동 업데이트 - 당일 제외)")
            
            v2_slope_rainbow_verify_kr = {
                "빨간색 (1개 감지)": (df_kr_past['slope_detect_count'] == 1, "동시 감지 1개"),
                "주황색 (2개 감지)": (df_kr_past['slope_detect_count'] == 2, "동시 감지 2개"),
                "노란색 (3개 감지)": (df_kr_past['slope_detect_count'] == 3, "동시 감지 3개"),
                "초록색 (4개 감지)": (df_kr_past['slope_detect_count'] == 4, "동시 감지 4개"),
                "파란색 (5개 감지)": (df_kr_past['slope_detect_count'] == 5, "동시 감지 5개"),
                "남색 (6개 감지)": (df_kr_past['slope_detect_count'] == 6, "동시 감지 6개"),
                "보라색 (7개 감지)": (df_kr_past['slope_detect_count'] == 7, "동시 감지 7개")
            }
            stats_slope_rainbow_kr = calculate_indicator_stats(df_kr_past, 'KOSPI', v2_slope_rainbow_verify_kr)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_stats_table(stats_slope_rainbow_kr, "슬로프합 최종본 다중 감지 검증 결과 (당일 제외)")


    def render_bottom_multi_us():
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
            ((df_multi['multi_count'] >= 8) & (df_multi['multi_count'] <= 14), '#FF8C00', '8~14개 감지'), # 주황색
            ((df_multi['multi_count'] >= 15) & (df_multi['multi_count'] <= 21), '#FFD700', '15~21개 감지'), # 노란색
            ((df_multi['multi_count'] >= 22) & (df_multi['multi_count'] <= 28), '#A9D08E', '22~28개 감지'), # 초록색
            ((df_multi['multi_count'] >= 29) & (df_multi['multi_count'] <= 35), '#87CEEB', '29~35개 감지'), # 파란색
            ((df_multi['multi_count'] >= 36) & (df_multi['multi_count'] <= 42), '#000080', '36~42개 감지'), # 남색
            ((df_multi['multi_count'] >= 43) & (df_multi['multi_count'] <= 49), '#800080', '43~49개 감지'), # 보라색
        ]
        
        # 표 생성을 위한 데이터 준비 (최근 100개)
        df_sig = df_multi[df_multi['multi_count'] >= 1].sort_index(ascending=False).head(100)
        
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
                
                TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
                dates_row_multi.append(f"<td style='background:{bg};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                counts_row_multi.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{int(cnt)}</td>")
                
            top_html_multi = f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 갯수 감지 신호 (최근 100개)</span>
            <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                <tr>
                    <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                    {"".join(dates_row_multi)}
                </tr>
                <tr>
                    <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>갯수</th>
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
            line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
            marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
            hovertemplate='QQQ: %{y:.2f}<extra></extra>'
        ), secondary_y=False)
        
        # 감지 막대그래프 추가
        bar_colors = {
            '#E06666': 'rgba(220, 30, 30, 0.3)',
            '#FF8C00': 'rgba(255, 140, 0, 0.3)',
            '#FFD700': 'rgba(255, 220, 0, 0.3)',
            '#A9D08E': 'rgba(0, 128, 0, 0.3)',
            '#87CEEB': 'rgba(135, 206, 235, 0.3)',
            '#000080': 'rgba(0, 0, 128, 0.3)',
            '#800080': 'rgba(128, 0, 128, 0.3)'
        }
        for cond, color, label in cond_map:
            fig_multi.add_trace(go.Bar(
                x=hd_multi, y=cond.astype(int) * max_qqq_multi,
                marker_color=bar_colors.get(color, 'rgba(0, 0, 0, 0.3)'),
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
        st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
        render_stats_table(stats_multi, "지표검증결과 (2018.10 ~ 현재 QQQ 저점 대비 실시간 자동 업데이트)")

    def render_bottom_multi_kr():
        df_multi_kr = df_kr.copy()
        
        # 보조 지표 계산 (임시비교 탭의 계산 방식과 100% 일치)
        ema12_c = df_multi_kr['KOSPI'].ewm(span=12, adjust=False).mean()
        ema26_c = df_multi_kr['KOSPI'].ewm(span=26, adjust=False).mean()
        df_multi_kr['MACD'] = ema12_c - ema26_c
        df_multi_kr['MACD_Signal'] = df_multi_kr['MACD'].ewm(span=9, adjust=False).mean()
        df_multi_kr['MACD_Hist'] = df_multi_kr['MACD'] - df_multi_kr['MACD_Signal']
        df_multi_kr['SKEW_Z'] = (df_multi_kr['SKEW'] - df_multi_kr['SKEW'].rolling(252).mean()) / (df_multi_kr['SKEW'].rolling(252).std() + 1e-5)
        
        # KOSPI Volume & Vol_Z
        _vol_kr = yf.download('^KS11', start="2020-01-01", progress=False)
        vol_data_kr = _vol_kr['Volume'] if not _vol_kr.empty and 'Volume' in _vol_kr.columns else pd.Series()
        if isinstance(vol_data_kr, pd.DataFrame): 
            vol_data_kr = vol_data_kr.iloc[:, 0]
        vol_data_kr.index = vol_data_kr.index.normalize()
        df_multi_kr['Volume'] = vol_data_kr.reindex(df_multi_kr.index).ffill()
        df_multi_kr['Vol_Z'] = (df_multi_kr['Volume'] - df_multi_kr['Volume'].rolling(50).mean()) / (df_multi_kr['Volume'].rolling(50).std() + 1e-5)
        
        # Velocity, Accel, VVIX_Vel
        x_arr = np.arange(10)
        var_x = np.var(x_arr)
        def calc_slope(y):
            if len(y) < 10: return 0
            return np.cov(x_arr, y)[0,1] / var_x
        df_multi_kr['KOSPI_Slope10'] = df_multi_kr['KOSPI'].rolling(10).apply(calc_slope, raw=True)
        df_multi_kr['KOSPI_Vel'] = df_multi_kr['KOSPI'].pct_change(5)
        df_multi_kr['KOSPI_Accel'] = df_multi_kr['KOSPI_Vel'].diff(3)
        df_multi_kr['VVIX_Vel'] = df_multi_kr['VVIX'].diff(3)
        
        # RSI
        delta_comp = df_multi_kr['KOSPI'].diff()
        up_comp = delta_comp.clip(lower=0)
        down_comp = -1 * delta_comp.clip(upper=0)
        rs14_comp = up_comp.rolling(14).mean() / (down_comp.rolling(14).mean() + 1e-5)
        df_multi_kr['KOSPI_RSI14'] = 100 - (100 / (1 + rs14_comp))
        rs7_comp = up_comp.rolling(7).mean() / (down_comp.rolling(7).mean() + 1e-5)
        df_multi_kr['KOSPI_RSI7'] = 100 - (100 / (1 + rs7_comp))
        
        df_multi_kr['DD_Sq'] = df_multi_kr['KOSPI_DD'] ** 2
        df_multi_kr['FGI_Proxy'] = 100 - (df_multi_kr['VKOSPI'] / df_multi_kr['VKOSPI'].rolling(252).max() * 100)
        df_multi_kr['VKOSPI_Pct'] = (df_multi_kr['VKOSPI'] - df_multi_kr['VKOSPI'].rolling(252).min()) / (df_multi_kr['VKOSPI'].rolling(252).max() - df_multi_kr['VKOSPI'].rolling(252).min() + 1e-5)
        
        # 슬로프합 보조 연산 (df_multi_kr에 슬로프5~70일합 연산)
        df_multi_s = df_multi_kr.copy().reset_index()
        df_multi_s.rename(columns={df_multi_s.columns[0]: 'Date'}, inplace=True)
        df_multi_s['Date'] = pd.to_datetime(df_multi_s['Date'])
        df_multi_s = df_multi_s.sort_values('Date').reset_index(drop=True)
        df_multi_s['슬로프'] = df_multi_s['KOSPI'].diff()
        sl_multi = df_multi_s['슬로프'].values
        
        df_multi_kr['슬로프5일합'] = slope_sum_lagged(sl_multi, 5)
        df_multi_kr['슬로프10일합'] = slope_sum_lagged(sl_multi, 10)
        df_multi_kr['슬로프20일합'] = slope_sum_lagged(sl_multi, 20)
        df_multi_kr['슬로프30일합'] = slope_sum_lagged(sl_multi, 30)
        df_multi_kr['슬로프40일합'] = slope_sum_lagged(sl_multi, 40)
        df_multi_kr['슬로프50일합'] = slope_sum_lagged(sl_multi, 50)
        df_multi_kr['슬로프60일합'] = slope_sum_lagged(sl_multi, 60)
        df_multi_kr['슬로프70일합'] = slope_sum_lagged(sl_multi, 70)

        # 49개의 후보 지표 조건들을 KOSPI 및 연동된 글로벌 피처들을 활용한 조건식으로 정의
        all_conditions_kr = [
            (df_multi_kr['KOSPI_%B'] * (df_multi_kr['HYG_RSI'] / 100) <= 0.11) & (df_multi_kr['KOSPI_DD'] >= 0.038), 
            (((df_multi_kr['FearGreedIndex'] <= 18) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.045))) & (np.exp(df_multi_kr['TNX_ROC'] * 2) / (df_multi_kr['VKOSPI'] + 1e-10) <= 0.12)), 
            ((((df_multi_kr['FearGreedIndex'] - 50) / 20 if df_multi_kr['FearGreedIndex'].mean() != 50 else 0) + (df_multi_kr['KOSPI_RSI'] - 50) / 15 + (df_multi_kr['KOSPI_%B'] - 0.5) / 0.25 - df_multi_kr['VKOSPI_Z']) <= -1.5) & (df_multi_kr['KOSPI_DD'] >= 0.04), 
            ((df_multi_kr['KOSPI_%B'] <= 0.22) & ((df_multi_kr['FearGreedIndex'] <= 18) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.045))) & (df_multi_kr['VKOSPI'] >= 22)), 
            ((df_multi_kr['KOSPI_%B'] <= 0.18) & ((df_multi_kr['FearGreedIndex'] <= 22) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.045)))), 
            ((df_multi_kr['슬로프10일합'] <= -70) & (df_multi_kr['VKOSPI'] >= 20) & ((df_multi_kr['FearGreedIndex'] <= 20) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04)))), 
            ((df_multi_kr['슬로프40일합'] <= -130) & ((df_multi_kr['FearGreedIndex'] <= 20) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.045))) & (df_multi_kr['KOSPI_%B'] <= 0.16)), 
            ((df_multi_kr['HYG_RSI'] <= 38) & (df_multi_kr['VKOSPI'] >= 22) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            (((df_multi_kr['FearGreedIndex'] <= 22) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.045))) & (df_multi_kr['VKOSPI'] >= 20) & (df_multi_kr['HYG_RSI'] <= 38)), 
            ((df_multi_kr['슬로프5일합'] <= -30) & (df_multi_kr['KOSPI_RSI'] <= 40) & (df_multi_kr['VKOSPI'] >= 19) & (df_multi_kr['KOSPI_DD'] >= 0.035)), 
            ((df_multi_kr['KOSPI_RSI7'] <= 33) & ((df_multi_kr['FearGreedIndex'] <= 26) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.035)))), 
            ((df_multi_kr['KOSPI_RSI7'] <= 35) & ((df_multi_kr['FearGreedIndex'] <= 24) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.035)))), 
            ((df_multi_kr['KOSPI_RSI7'] <= 37) & ((df_multi_kr['FearGreedIndex'] <= 24) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04)))), 
            ((df_multi_kr['KOSPI_RSI7'] <= 39) & ((df_multi_kr['FearGreedIndex'] <= 24) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04)))), 
            ((df_multi_kr['VVIX_Z'] >= 1.2) & ((df_multi_kr['FearGreedIndex'] <= 26) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.035)))), 
            ((df_multi_kr['VVIX_Z'] >= 1.0) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04)))), 
            ((df_multi_kr['VVIX_Pct'] >= 0.55) & ((df_multi_kr['FearGreedIndex'] <= 24) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04)))), 
            ((df_multi_kr['VVIX_Pct'] >= 0.55) & (df_multi_kr['KOSPI_RSI7'] <= 40) & (df_multi_kr['KOSPI_DD'] >= 0.035)), 
            (((df_multi_kr['FearGreedIndex'].diff(7) <= -6) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.035))) & (df_multi_kr['VKOSPI_Pct'] >= 0.65)),
            (((50 - df_multi_kr['FearGreedIndex']) * (2.0 - df_multi_kr['KOSPI_%B']) >= 12) & (df_multi_kr['VVIX_Pct'] >= 0.50) & (df_multi_kr['KOSPI_DD'] >= 0.035)), 
            (((45 - df_multi_kr['FearGreedIndex']) * (2.0 - df_multi_kr['KOSPI_%B']) >= 9) & (df_multi_kr['VVIX_Pct'] >= 0.50) & (df_multi_kr['KOSPI_DD'] >= 0.035)), 
            (((df_multi_kr['VVIX'] / (df_multi_kr['KOSPI_RSI7'] + 1e-5)) >= 2.0) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            (((df_multi_kr['VKOSPI'] * df_multi_kr['VVIX'] / 1000) >= 1.2) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.035))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            (((df_multi_kr['VKOSPI'] * df_multi_kr['VVIX'] / 1000) >= 1.2) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.03)), 
            (((45 - df_multi_kr['FearGreedIndex']) * (2.0 - df_multi_kr['KOSPI_%B']) >= 10) & (df_multi_kr['VVIX_Pct'] >= 0.50) & (df_multi_kr['KOSPI_DD'] >= 0.035)), 
            (((40 - df_multi_kr['FearGreedIndex']) * (2.0 - df_multi_kr['KOSPI_%B']) >= 8) & (df_multi_kr['VVIX_Pct'] >= 0.50) & (df_multi_kr['KOSPI_DD'] >= 0.035)), 
            (((50 - df_multi_kr['FearGreedIndex']) * (2.0 - df_multi_kr['KOSPI_%B']) >= 12) & (df_multi_kr['VVIX_Pct'] >= 0.60) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            ((np.log(np.maximum(df_multi_kr['VVIX_Z'] + 5.0, 1e-5)) * df_multi_kr['VKOSPI_Pct'] >= 0.6) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_%B'] <= 0.30)), 
            ((((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & np.exp(df_multi_kr['TNX_ROC'] * 3) <= 52) & (df_multi_kr['KOSPI_RSI7'] <= 40) & (df_multi_kr['VKOSPI_Pct'] >= 0.60)), 
            (((df_multi_kr['VVIX'] / (df_multi_kr['KOSPI_RSI7'] + 1e-5)) >= 1.6) & ((df_multi_kr['FearGreedIndex'] <= 32) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            (((df_multi_kr['VVIX'] / (df_multi_kr['KOSPI_RSI7'] + 1e-5)) >= 1.4) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            ((df_multi_kr['KOSPI_%B'] <= 0.30) & (df_multi_kr['KOSPI_RSI7'] <= 40) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['VKOSPI_Pct'] >= 0.50) & (df_multi_kr['VVIX_Pct'] >= 0.50)), 
            ((100 / (df_multi_kr['KOSPI_RSI7'] + 1e-5) + df_multi_kr['K_DD_Pct'] * 3 >= 4.5) & (df_multi_kr['FGI_Pct'] <= 0.40) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            ((100 / (df_multi_kr['KOSPI_RSI7'] + 1e-5) + df_multi_kr['K_DD_Pct'] * 4 >= 5.5) & (df_multi_kr['FGI_Pct'] <= 0.40) & (df_multi_kr['KOSPI_DD'] >= 0.045)), 
            ((df_multi_kr['KOSPI_%B'] <= 0.32) & (df_multi_kr['KOSPI_RSI7'] <= 44) & ((df_multi_kr['FearGreedIndex'] <= 28) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['VKOSPI_Pct'] >= 0.50) & (df_multi_kr['VVIX_Pct'] >= 0.50)), 
            (((50 - df_multi_kr['FearGreedIndex']) * (2.5 - df_multi_kr['KOSPI_%B'] * 1.5) >= 16) & (df_multi_kr['VVIX_Pct'] >= 0.50) & (df_multi_kr['K_DD_Pct'] >= 0.50) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            (((55 - df_multi_kr['FearGreedIndex']) * (2.5 - df_multi_kr['KOSPI_%B'] * 1.5) >= 20) & (df_multi_kr['VVIX_Pct'] >= 0.50) & (df_multi_kr['K_DD_Pct'] >= 0.40) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            ((df_multi_kr['VKOSPI_Z'] * df_multi_kr['VVIX_Z'] >= 0.6) & ((df_multi_kr['FearGreedIndex'] <= 26) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            ((df_multi_kr['VKOSPI_Z'] * df_multi_kr['VVIX_Z'] >= 0.9) & ((df_multi_kr['FearGreedIndex'] <= 26) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            (((df_multi_kr['VVIX'] / (df_multi_kr['KOSPI_RSI7'] + 1e-5)) >= 1.4) & ((df_multi_kr['FearGreedIndex'] <= 36) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            (((df_multi_kr['VVIX'] / (df_multi_kr['KOSPI_RSI7'] + 1e-5)) >= 1.6) & ((df_multi_kr['FearGreedIndex'] <= 42) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            ((df_multi_kr['KOSPI_%B'] <= 0.38) & (df_multi_kr['KOSPI_RSI7'] <= 48) & ((df_multi_kr['FearGreedIndex'] <= 36) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['VKOSPI_Pct'] >= 0.40) & (df_multi_kr['VVIX_Pct'] >= 0.40)), 
            ((140 / (df_multi_kr['KOSPI_RSI7'] + 1e-5) + df_multi_kr['K_DD_Pct'] * 2 >= 2.8) & (df_multi_kr['FGI_Pct'] <= 0.45) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            ((df_multi_kr['KOSPI_%B'] <= 0.36) & (df_multi_kr['KOSPI_RSI7'] <= 48) & ((df_multi_kr['FearGreedIndex'] <= 38) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['VKOSPI_Pct'] >= 0.40) & (df_multi_kr['VVIX_Pct'] >= 0.40)), 
            ((100 / (df_multi_kr['KOSPI_RSI7'] + 1e-5) + df_multi_kr['K_DD_Pct'] * 2 >= 2.8) & (df_multi_kr['FGI_Pct'] <= 0.45) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            (((75 - df_multi_kr['FearGreedIndex']) * (2.5 - df_multi_kr['KOSPI_%B'] * 1.5) >= 20) & (df_multi_kr['VVIX_Pct'] >= 0.32) & (df_multi_kr['K_DD_Pct'] >= 0.32) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            (((70 - df_multi_kr['FearGreedIndex']) * (2.5 - df_multi_kr['KOSPI_%B'] * 1.5) >= 16) & (df_multi_kr['VVIX_Pct'] >= 0.32) & (df_multi_kr['K_DD_Pct'] >= 0.32) & (df_multi_kr['KOSPI_DD'] >= 0.04)), 
            ((df_multi_kr['VKOSPI_Z'] * df_multi_kr['VVIX_Z'] >= 0.38) & ((df_multi_kr['FearGreedIndex'] <= 32) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025)), 
            ((df_multi_kr['VKOSPI_Z'] * df_multi_kr['VVIX_Z'] >= 0.45) & ((df_multi_kr['FearGreedIndex'] <= 32) | ((df_multi_kr['FearGreedIndex'] == 50) & (df_multi_kr['KOSPI_DD'] >= 0.04))) & (df_multi_kr['KOSPI_DD'] >= 0.025))  
        ]
        
        # 합산(개수 세기)
        df_multi_kr['multi_count'] = sum(cond.fillna(False).astype(int) for cond in all_conditions_kr)
        
        # 날짜 범위 설정 (기간 필터링)
        if active_period_days:
            target_date_multi_kr = datetime.date.today() - datetime.timedelta(days=active_period_days)
            detected_indices_kr = [i for i, d in enumerate(df_multi_kr.index) if d >= pd.to_datetime(target_date_multi_kr)]
            initial_x_range_multi_kr = [detected_indices_kr[0], len(df_multi_kr.index) - 1] if detected_indices_kr else None
            if detected_indices_kr:
                kospi_1y_multi = df_multi_kr['KOSPI'].iloc[detected_indices_kr[0]:]
                k_min, k_max = float(kospi_1y_multi.min()), float(kospi_1y_multi.max())
                kospi_y_range = [k_min * 0.95, k_max * 1.05]
            else:
                kospi_y_range = [float(df_multi_kr['KOSPI'].min()) * 0.95, float(df_multi_kr['KOSPI'].max()) * 1.05]
        else:
            initial_x_range_multi_kr = None
            k_min, k_max = float(df_multi_kr['KOSPI'].min()), float(df_multi_kr['KOSPI'].max())
            kospi_y_range = [k_min * 0.95, k_max * 1.05]

        max_kospi_multi = float(df_multi_kr['KOSPI'].max()) * 1.2
        
        # 색상 매핑
        cond_map_kr = [
            ((df_multi_kr['multi_count'] >= 1) & (df_multi_kr['multi_count'] <= 7), '#E06666', '1~7개 감지'), # 빨간색
            ((df_multi_kr['multi_count'] >= 8) & (df_multi_kr['multi_count'] <= 14), '#FF8C00', '8~14개 감지'), 
            ((df_multi_kr['multi_count'] >= 15) & (df_multi_kr['multi_count'] <= 21), '#FFD700', '15~21개 감지'), 
            ((df_multi_kr['multi_count'] >= 22) & (df_multi_kr['multi_count'] <= 28), '#A9D08E', '22~28개 감지'), 
            ((df_multi_kr['multi_count'] >= 29) & (df_multi_kr['multi_count'] <= 35), '#87CEEB', '29~35개 감지'), 
            ((df_multi_kr['multi_count'] >= 36) & (df_multi_kr['multi_count'] <= 42), '#000080', '36~42개 감지'), 
            ((df_multi_kr['multi_count'] >= 43) & (df_multi_kr['multi_count'] <= 49), '#800080', '43~49개 감지'), 
        ]
        
        # 표 생성을 위한 데이터 준비 (최근 100개)
        df_sig_kr = df_multi_kr[df_multi_kr['multi_count'] >= 1].sort_index(ascending=False).head(100)
        
        if not df_sig_kr.empty:
            dates_row_tm_kr = []
            counts_row_tm_kr = []
            for dt in df_sig_kr.index:
                cnt = df_sig_kr.loc[dt, 'multi_count']
                bg_color = '#E06666' if cnt <= 7 else '#FF8C00' if cnt <= 14 else '#FFD700' if cnt <= 21 else '#A9D08E' if cnt <= 28 else '#87CEEB' if cnt <= 35 else '#000080' if cnt <= 42 else '#800080'
                TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
                dates_row_tm_kr.append(f"<td style='background:{bg_color};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                counts_row_tm_kr.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{cnt}개</td>")
            
            st.markdown(f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 저점 감지 신호 (최근 100개)</span>
            <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                <tr>
                    <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                    {"".join(dates_row_tm_kr)}
                </tr>
                <tr>
                    <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>갯수</th>
                    {"".join(counts_row_tm_kr)}
                </tr>
            </table>
            </div>
            """, unsafe_allow_html=True)
            
        fig_multi_kr = make_subplots(specs=[[{"secondary_y": True}]])
        hd_multi_kr = [fmt_date_kor(d) for d in df_multi_kr.index]
        
        fig_multi_kr.add_trace(go.Scatter(x=hd_multi_kr, y=df_multi_kr['KOSPI'], name='KOSPI 가격', mode='lines+markers',
            line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
            marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
            hovertemplate='KOSPI: %{y:.2f}<extra></extra>'), secondary_y=False)
            
        bar_colors_kr = {
            '#E06666': 'rgba(220, 30, 30, 0.3)',
            '#FF8C00': 'rgba(255, 140, 0, 0.3)',
            '#FFD700': 'rgba(255, 220, 0, 0.3)',
            '#A9D08E': 'rgba(0, 128, 0, 0.3)',
            '#87CEEB': 'rgba(135, 206, 235, 0.3)',
            '#000080': 'rgba(0, 0, 128, 0.3)',
            '#800080': 'rgba(128, 0, 128, 0.3)'
        }
        for cond, color, label in cond_map_kr:
            fig_multi_kr.add_trace(go.Bar(
                x=hd_multi_kr, y=cond.astype(int) * max_kospi_multi,
                marker_color=bar_colors_kr.get(color, 'rgba(0, 0, 0, 0.3)'),
                showlegend=False,
                hoverinfo='skip',
                marker_line_width=0.5,
                marker_line_color='white'
            ), secondary_y=False)
            
        fig_multi_kr.update_layout(
            **COMMON_LAYOUT, 
            height=400, 
            margin=dict(l=0, r=50, t=30, b=10),
            showlegend=False,
            barmode='overlay',
            bargap=0,
            shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))]
        )
        if initial_x_range_multi_kr:
            fig_multi_kr.update_xaxes(range=initial_x_range_multi_kr, type='category', **crosshair_xaxis())
        else:
            fig_multi_kr.update_xaxes(type='category', **crosshair_xaxis())
            
        fig_multi_kr.update_yaxes(range=kospi_y_range, **crosshair_yaxis(), secondary_y=False, title_text="")
        fig_multi_kr.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
        
        st.plotly_chart(fig_multi_kr, width='stretch', config=COMMON_CONFIG, key="tab5_multi_chart_kr")
        
        # 지표 검증 결과
        multi_conditions_kr = {
            "**빨간색**": (cond_map_kr[0][0], cond_map_kr[0][2]),
            "**주황색**": (cond_map_kr[1][0], cond_map_kr[1][2]),
            "**노란색**": (cond_map_kr[2][0], cond_map_kr[2][2]),
            "**초록색**": (cond_map_kr[3][0], cond_map_kr[3][2]),
            "**파란색**": (cond_map_kr[4][0], cond_map_kr[4][2]),
            "**남색**":   (cond_map_kr[5][0], cond_map_kr[5][2]),
            "**보라색**": (cond_map_kr[6][0], cond_map_kr[6][2]),
        }
        stats_multi_kr = calculate_indicator_stats(df_multi_kr, 'KOSPI', multi_conditions_kr)
        st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
        render_stats_table(stats_multi_kr, "지표검증결과 (2018.01 ~ 현재 KOSPI 저점 대비 실시간 자동 업데이트)")


    # ── 소분류 3: 다중지표 ──
    with bottom_sub_tabs[2]:
        if selected_country == "미국":
            render_bottom_multi_us()
        elif selected_country == "한국":
            render_bottom_multi_kr()


    def render_bottom_unified_us():
        with st.spinner("통합지표 데이터를 계산 중입니다..."):
            df_pre = df.copy()
            
            _vol = yf.download('QQQ', start="2020-01-01", progress=False)
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
        recent_100 = triggered_dates[:100]
        if len(recent_100) > 0:
            dates_row = ""
            for dt in recent_100:
                dates_row += f"<td style='background:#800080;color:white;font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
            
            table_html = f"""
            <div style='margin-bottom:0.3rem;overflow-x:auto;'>
            <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 3대 기발한 아이디어 감지 신호 (최근 100개)</span>
            <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                <tr>
                    <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                    {dates_row}
                </tr>
            </table>
            </div>
            """
            st.markdown(table_html, unsafe_allow_html=True)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            
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
        
        st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
        
        fig_pre = make_subplots(specs=[[{"secondary_y": True}]])
        hd_pre = [fmt_date_kor(d) for d in df_pre_plot.index]
        
        fig_pre.add_trace(go.Scatter(
            x=hd_pre, y=df_pre_plot['QQQ'], name='QQQ 가격', mode='lines+markers',
            line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
            marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
            hovertemplate='QQQ: %{y:.2f}<extra></extra>'
        ), secondary_y=False)
        
        fig_pre.add_trace(go.Bar(
            x=hd_pre, y=c_or_final.reindex(df_pre_plot.index).astype(int) * qqq_y_range[1], name='통합 감지 신호 (OR)',
            marker_color='rgba(128, 0, 128, 0.3)',
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
        
    def render_bottom_unified_kr():
        with st.spinner("통합지표 데이터를 계산 중입니다..."):
            df_pre_kr = df_kr.copy()
            
            _vol_kr = yf.download('^KS11', start="2020-01-01", progress=False)
            vol_data_kr = _vol_kr['Volume'] if not _vol_kr.empty and 'Volume' in _vol_kr.columns else pd.Series()
            if isinstance(vol_data_kr, pd.DataFrame): 
                vol_data_kr = vol_data_kr.iloc[:, 0]
            vol_data_kr.index = vol_data_kr.index.normalize()
            df_pre_kr['Volume'] = vol_data_kr.reindex(df_pre_kr.index).ffill()
            
            ema12_kr = df_pre_kr['KOSPI'].ewm(span=12, adjust=False).mean()
            ema26_kr = df_pre_kr['KOSPI'].ewm(span=26, adjust=False).mean()
            df_pre_kr['MACD'] = ema12_kr - ema26_kr
            df_pre_kr['MACD_Signal'] = df_pre_kr['MACD'].ewm(span=9, adjust=False).mean()
            df_pre_kr['MACD_Hist'] = df_pre_kr['MACD'] - df_pre_kr['MACD_Signal']
            
            df_pre_kr['SKEW_Z'] = (df_pre_kr['SKEW'] - df_pre_kr['SKEW'].rolling(252).mean()) / (df_pre_kr['SKEW'].rolling(252).std() + 1e-5)
            df_pre_kr['Vol_Z'] = (df_pre_kr['Volume'] - df_pre_kr['Volume'].rolling(50).mean()) / (df_pre_kr['Volume'].rolling(50).std() + 1e-5)
            
            x_arr = np.arange(10)
            var_x = np.var(x_arr)
            def calc_slope(y):
                if len(y) < 10: return 0
                return np.cov(x_arr, y)[0,1] / var_x
            df_pre_kr['KOSPI_Slope10'] = df_pre_kr['KOSPI'].rolling(10).apply(calc_slope, raw=True)
            df_pre_kr['KOSPI_Vel'] = df_pre_kr['KOSPI'].pct_change(5)
            df_pre_kr['KOSPI_Accel'] = df_pre_kr['KOSPI_Vel'].diff(3)
            df_pre_kr['VVIX_Vel'] = df_pre_kr['VVIX'].diff(3)
            
            delta_k = df_pre_kr['KOSPI'].diff()
            up_k = delta_k.clip(lower=0)
            down_k = -1 * delta_k.clip(upper=0)
            rs14_k = up_k.rolling(14).mean() / (down_k.rolling(14).mean() + 1e-5)
            df_pre_kr['KOSPI_RSI14'] = 100 - (100 / (1 + rs14_k))
            rs7_k = up_k.rolling(7).mean() / (down_k.rolling(7).mean() + 1e-5)
            df_pre_kr['KOSPI_RSI7'] = 100 - (100 / (1 + rs7_k))

            df_pre_kr['DD_Sq'] = df_pre_kr['KOSPI_DD'] ** 2
            df_pre_kr['FGI_Proxy'] = 100 - (df_pre_kr['VKOSPI'] / df_pre_kr['VKOSPI'].rolling(252).max() * 100)
            df_pre_kr['VKOSPI_Pct'] = (df_pre_kr['VKOSPI'] - df_pre_kr['VKOSPI'].rolling(252).min()) / (df_pre_kr['VKOSPI'].rolling(252).max() - df_pre_kr['VKOSPI'].rolling(252).min() + 1e-5)

            # [버전 2 통합지표 조건식]
            # 1. 4종 통합(AND)
            v2_macro = (df_pre_kr['SKEW_Z'] > 0.8) | (df_pre_kr['HYG_RSI'] <= 22)
            v2_micro = (df_pre_kr['MACD_Hist'] < -1.5) & (df_pre_kr['KOSPI_Slope10'] < -1.5)
            c1_1 = (v2_macro & v2_micro) | ((np.log(df_pre_kr['VVIX'] + 1e-5) * df_pre_kr['DD_Sq'] * 100 > 2.0) & (df_pre_kr['KOSPI_%B'] <= 0.01))
            
            v2_liq = (df_pre_kr['Vol_Z'] > 1.8) | (df_pre_kr['HYG_RSI'] < 15)
            v2_psy = (df_pre_kr['FearGreedIndex'] <= 15) | ((df_pre_kr['FearGreedIndex'] == 50) & (df_pre_kr['KOSPI_DD'] >= 0.06)) | (df_pre_kr['VKOSPI_Pct'] >= 0.94)
            v2_dd = df_pre_kr['KOSPI_DD'] >= 0.07
            c2_1 = (v2_liq & v2_psy & v2_dd) | ((df_pre_kr['VVIX_Vel'].diff(3) > 6.0) & (df_pre_kr['KOSPI_RSI7'] <= 24) & (df_pre_kr['KOSPI_DD'] >= 0.05))
            
            v2_grav = (df_pre_kr['KOSPI_Accel'] < -0.018) & (df_pre_kr['DD_Sq'] * df_pre_kr['VVIX'] > 2.0)
            v2_vol = (df_pre_kr['KOSPI_%B'] < 0.01) & (df_pre_kr['Vol_Z'] > 1.8) & (df_pre_kr['HYG_RSI'] <= 20)
            c3_1 = (v2_grav | v2_vol) & (df_pre_kr['KOSPI_RSI14'] <= 35) & (df_pre_kr['KOSPI_DD'] >= 0.05)
            
            v2_opt = (df_pre_kr['VVIX_Z'] > 2.0) | (df_pre_kr['VKOSPI_Pct'] > 0.90)
            v2_rate = (df_pre_kr['TNX_ROC'] > 0.15) | (df_pre_kr['SKEW_Z'] > 1.8)
            v2_tech = (df_pre_kr['KOSPI_RSI7'] <= 28) | (df_pre_kr['KOSPI_%B'] <= 0.03)
            c4_1 = (v2_opt | v2_rate) & v2_tech & (df_pre_kr['KOSPI_DD'] >= 0.05) & ((df_pre_kr['FearGreedIndex'] <= 30) | (df_pre_kr['FearGreedIndex'] == 50))
            
            c_all_1 = ((c1_1.astype(int) + c2_1.astype(int) + c3_1.astype(int) + c4_1.astype(int)) >= 4)
            
            # 2. 물리학적 에너지
            ke2 = 0.5 * np.maximum(df_pre_kr['Vol_Z'], 0.1) * (np.abs(df_pre_kr['KOSPI_Vel']) * 100)**2
            pe2 = df_pre_kr['VKOSPI'] * (df_pre_kr['KOSPI_DD'] * 100)
            c2_2 = (ke2*0.5 > pe2) & (df_pre_kr['Vol_Z'] > -0.2) & (df_pre_kr['KOSPI_%B'] <= 0.25)
            
            # 3. 푸리에 변환 모방
            phase2 = np.sin((df_pre_kr['FGI_Proxy'] / 100) * np.pi) 
            c4_2 = (phase2 < 0.05) & (df_pre_kr['KOSPI_Vel'] < -0.015) & (df_pre_kr['VKOSPI_Z'] > 0.8)
            
            c_or_final = c_all_1 | c2_2 | c4_2

            triggered_dates = df_pre_kr[c_or_final].index.sort_values(ascending=False)
            recent_100 = triggered_dates[:100]
            if len(recent_100) > 0:
                dates_row = ""
                for dt in recent_100:
                    dates_row += f"<td style='background:#800080;color:white;font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
                
                table_html = f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 통합지표 저점 감지 신호 (최근 100개)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {dates_row}
                    </tr>
                </table>
                </div>
                """
                st.markdown(table_html, unsafe_allow_html=True)
            
            pre_conditions_kr = {
                "**최종 3대 통합 괴물지표 (OR)**": (c_or_final, "4종 통합(AND), 물리학적 에너지, 푸리에 변환 중 하나 이상 저점 신호 감지"),
                "4종 통합(AND)": (c_all_1, "매크로/마이크로, 유동성/심리, 중력/변동성, 옵션/금리/기술적 4개 조건 모두 만족"),
                "물리학적 에너지 역전 법칙": (c2_2, "Vol_Z기반 KOSPI 운동에너지가 VKOSPI & KOSPI_DD기반 위치에너지 이상으로 과도 분출"),
                "푸리에 변환 모방 위상 천이": (c4_2, "한국 FGI Proxy 기반 위상 주기함수 주기 반전 구간 & KOSPI 하강 속도 & VKOSPI 급등 동시 만족"),
            }

            if active_period_days:
                target_date = datetime.date.today() - datetime.timedelta(days=active_period_days)
                df_pre_plot = df_pre_kr[df_pre_kr.index >= pd.to_datetime(target_date)]
                if not df_pre_plot.empty:
                    kospi_y_range = [float(df_pre_plot['KOSPI'].min()) * 0.95, float(df_pre_plot['KOSPI'].max()) * 1.05]
                    initial_x_range = [df_pre_plot.index[0].strftime("%Y-%m-%d"), df_pre_plot.index[-1].strftime("%Y-%m-%d")]
                else:
                    kospi_y_range = None
                    initial_x_range = None
            else:
                df_pre_plot = df_pre_kr.copy()
                if not df_pre_plot.empty:
                    kospi_y_range = [float(df_pre_plot['KOSPI'].min()) * 0.95, float(df_pre_plot['KOSPI'].max()) * 1.05]
                    initial_x_range = [df_pre_plot.index[0].strftime("%Y-%m-%d"), df_pre_plot.index[-1].strftime("%Y-%m-%d")]
                else:
                    kospi_y_range = None
                    initial_x_range = None
            
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            
            fig_pre = make_subplots(specs=[[{"secondary_y": True}]])
            hd_pre = [fmt_date_kor(d) for d in df_pre_plot.index]
            
            fig_pre.add_trace(go.Scatter(
                x=hd_pre, y=df_pre_plot['KOSPI'], name='KOSPI 가격', mode='lines+markers',
                line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                hovertemplate='KOSPI: %{y:.2f}<extra></extra>'
            ), secondary_y=False)
            
            fig_pre.add_trace(go.Bar(
                x=hd_pre, y=c_or_final.reindex(df_pre_plot.index).astype(int) * (kospi_y_range[1] if kospi_y_range else 3000), name='통합 감지 신호 (OR)',
                marker_color='rgba(128, 0, 128, 0.3)',
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
            
            fig_pre.update_yaxes(title_text="", range=kospi_y_range, **crosshair_yaxis(), secondary_y=False)
            fig_pre.update_yaxes(range=[0, 1.2], showticklabels=False, showgrid=False, secondary_y=True)
            
            st.plotly_chart(fig_pre, width='stretch', config=COMMON_CONFIG, key="pre_chart_final_or_kr")
            
            stats_pre_kr = calculate_indicator_stats(df_pre_kr, 'KOSPI', pre_conditions_kr)
            render_stats_table(stats_pre_kr, "통합지표 통합 검증 결과 (2018.01 ~ 현재 KOSPI 저점 대비 실시간 자동 업데이트)")

    # ── 소분류 4: 통합지표 ──
    with bottom_sub_tabs[3]:
        if selected_country == "미국":
            render_bottom_unified_us()
        elif selected_country == "한국":
            render_bottom_unified_kr()

# ── Tab 3: 모니터링 ──
with tabs[2]:
    sub_tab_names = ['매매동향', '등락현황', '감마풋콜', '메모리']
    sub_tabs = st.tabs(sub_tab_names)

    # ── 소분류 1: 매매동향 ──
    with sub_tabs[0]:
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
                    f"<table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;line-height:1.2;text-align:center;'>"
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
                    f"<table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;line-height:1.2;text-align:center;'>"
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
                    f"<table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;line-height:1.2;text-align:center;'>"
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
            if not df_mon.empty:
                df_mon_plot = df_mon.copy()
                hd_mon = [fmt_date_kor(d) for d in df_mon_plot.index]
                if active_period_days:
                    target_start = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=active_period_days))
                    detected_indices = [i for i, d in enumerate(df_mon_plot.index) if d >= target_start]
                    initial_x_range_mon = [detected_indices[0], len(hd_mon) - 1] if detected_indices else None
                else:
                    initial_x_range_mon = None
                
                if active_period_days and detected_indices:
                    k_prices = df_mon_plot['KOSPI'].iloc[detected_indices[0]:]
                    kmin, kmax = float(k_prices.min()), float(k_prices.max())
                else:
                    kmin, kmax = float(df_mon_plot['KOSPI'].min()), float(df_mon_plot['KOSPI'].max())

                # Helper to add KOSPI trace
                def add_kospi_trace(fig, row=1, show_leg=False):
                    fig.add_trace(go.Scatter(
                        x=hd_mon, y=df_mon_plot['KOSPI'], 
                        name="코스피 지수", mode='lines+markers',
                        line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                        marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                        showlegend=show_leg,
                        hovertemplate='코스피: %{y:,.2f}<extra></extra>'
                    ), row=row, col=1, secondary_y=False)

                # --- 1. 신용잔고 / 예탁금 ---
                st.markdown(build_monitoring_table_1(df_mon_latest), unsafe_allow_html=True)
                fig_mon1 = make_subplots(specs=[[{"secondary_y": True}]])
                add_kospi_trace(fig_mon1)
                fig_mon1.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Margin']/10000, name="신용잔고 (조원)", line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate='신용잔고: %{y:.2f}조<extra></extra>', connectgaps=True), secondary_y=True)
                fig_mon1.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Deposit']/10000, name="고객예탁금 (조원)", line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate='고객예탁금: %{y:.2f}조<extra></extra>', connectgaps=True), secondary_y=True)
                fig_mon1.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0, r=50, t=30, b=10), showlegend=False)
                fig_mon1.add_shape(type="rect", xref="x domain", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))
                fig_mon1.update_yaxes(range=[kmin*0.95, kmax*1.05], **crosshair_yaxis(), secondary_y=False)
                fig_mon1.update_yaxes(**crosshair_yaxis(), secondary_y=True)
                fig_mon1.update_xaxes(type='category', **crosshair_xaxis())
                if initial_x_range_mon: fig_mon1.update_xaxes(range=initial_x_range_mon)
                st.plotly_chart(fig_mon1, width='stretch', config=COMMON_CONFIG, key="mon_fig1")

                st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

                # --- 2. 거래대금 (기존 거래대금 탭 그래프 2개) ---
                st.markdown(build_monitoring_table_2(df_mon_latest), unsafe_allow_html=True)
            
                fig_value = make_subplots(
                    rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                    specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
                    subplot_titles=("코스피 지수 & 일일거래대금 추이", "코스피 지수 & 삼닉/그외 비율 추이")
                )
            
                # Row 1: 거래대금
                add_kospi_trace(fig_value, row=1)
                fig_value.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['TradingValue']/1000000.0, name="코스피 거래대금", line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate="코스피 거래대금: %{y:.2f}조<extra></extra>"), row=1, col=1, secondary_y=True)
                fig_value.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['SEC_HYNIX_Val']/1000000.0, name="삼닉 거래대금", line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate="삼닉 거래대금: %{y:.2f}조<extra></extra>"), row=1, col=1, secondary_y=True)
                fig_value.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['KOSPI_ex_SEC_HYNIX_Val']/1000000.0, name="코스피-삼닉 거래대금", line=dict(color='rgba(0, 128, 0, 0.8)', width=1), hovertemplate="코스피-삼닉 거래대금: %{y:.2f}조<extra></extra>"), row=1, col=1, secondary_y=True)
            
                # Row 2: 비율
                add_kospi_trace(fig_value, row=2)
                raw_ratio = df_mon_plot['SEC_HYNIX_Val'] / (df_mon_plot['KOSPI_ex_SEC_HYNIX_Val'] + 1e-10)
                fig_value.add_trace(go.Scatter(x=hd_mon, y=raw_ratio, name="삼닉/그외 비율", line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate="삼닉/그외 비율: %{y:.4f}<extra></extra>"), row=2, col=1, secondary_y=True)
                fig_value.add_hline(y=1.0, line_dash="dash", line_color="gray", line_width=1.0, row=2, col=1, secondary_y=True)
            
                # Layout setting
                fig_value.update_layout(**COMMON_LAYOUT, height=700, margin=dict(l=0, r=50, t=30, b=10), showlegend=False)
                fig_value.update_annotations(font_size=10)
            
                for r_idx in [1, 2]:
                    fig_value.add_shape(type="rect", xref="x domain", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2), row=r_idx, col=1)
                    fig_value.update_yaxes(range=[0, kmax * 1.1], **crosshair_yaxis(), secondary_y=False, row=r_idx, col=1)
                    fig_value.update_xaxes(type="category", **crosshair_xaxis(), row=r_idx, col=1)
            
                fig_value.update_yaxes(range=[0, 120], **crosshair_yaxis(), secondary_y=True, row=1, col=1)
                fig_value.update_yaxes(range=[0, 5], **crosshair_yaxis(), secondary_y=True, row=2, col=1)
            
                if initial_x_range_mon:
                    fig_value.update_xaxes(range=initial_x_range_mon, row=2, col=1)
                
                st.plotly_chart(fig_value, width="stretch", config=COMMON_CONFIG, key="value_subplots")

                st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

                # --- 3. 투자자별 순매수 ---
                st.markdown(build_monitoring_table_3(df_mon_latest), unsafe_allow_html=True)
                fig_mon3 = make_subplots(specs=[[{"secondary_y": True}]])
                add_kospi_trace(fig_mon3)
                fig_mon3.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Retail_Cum']/10000, name="개인 누적 (조원)", line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate='개인 누적: %{y:.2f}조<extra></extra>'), secondary_y=True)
                fig_mon3.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Foreign_Cum']/10000, name="외국인 누적 (조원)", line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate='외국인 누적: %{y:.2f}조<extra></extra>'), secondary_y=True)
                fig_mon3.add_trace(go.Scatter(x=hd_mon, y=df_mon_plot['Institution_Cum']/10000, name="기관 누적 (조원)", line=dict(color='rgba(0, 128, 0, 0.8)', width=1), hovertemplate='기관 누적: %{y:.2f}조<extra></extra>'), secondary_y=True)
                fig_mon3.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0, r=50, t=30, b=10), showlegend=False)
                fig_mon3.add_shape(type="rect", xref="x domain", yref="y domain", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))
                fig_mon3.update_yaxes(range=[kmin*0.95, kmax*1.05], **crosshair_yaxis(), secondary_y=False)
                fig_mon3.update_yaxes(**crosshair_yaxis(), secondary_y=True)
                fig_mon3.update_xaxes(type='category', **crosshair_xaxis())
                if initial_x_range_mon: fig_mon3.update_xaxes(range=initial_x_range_mon)
                st.plotly_chart(fig_mon3, width='stretch', config=COMMON_CONFIG, key="mon_fig3")
            else:
                st.info("모니터링 데이터가 없습니다.")

    

    # ── 소분류 2: 등락현황 ──
    with sub_tabs[1]:
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
            headers.append("<th style='padding:3px 6px;border:1px solid #444;color:white;background:#1F4E79;text-align:center;'>상하비율</th>")
        
            rows = []
            CM = {'상한가':'#CC0000','상승':'#FF6B9D','보합':'#DDDDDD','하락':'#87CEEB','하한가':'#3399FF'}
            for idx, row in df_sub.iloc[::-1].iterrows():
                date_str = pd.to_datetime(idx).strftime('%Y-%m-%d')
                row_html = [f"<td style='padding:3px 6px;border:1px solid #444;text-align:center;font-weight:bold;'>{date_str}</td>"]
                for col in cols:
                    val = row.get(col, 0)
                    c = CM.get(col, '#FFF')
                    row_html.append(f"<td style='padding:3px 6px;border:1px solid #444;font-weight:bold;color:{c};text-align:center;'>{int(val) if pd.notna(val) else '0'}</td>")
            
                # 상하비율 계산
                if not is_us:
                    up_val = row.get('상한가', 0) + row.get('상승', 0)
                    dn_val = row.get('하락', 0) + row.get('하한가', 0)
                else:
                    up_val = row.get('상승', 0)
                    dn_val = row.get('하락', 0)
            
                ratio = up_val - dn_val
                r_color = '#FF6B9D' if ratio >= 1 else '#87CEEB'
                row_html.append(f"<td style='padding:3px 6px;border:1px solid #444;font-weight:bold;color:{r_color};text-align:center;'>{ratio:.2f}</td>")
            
                rows.append(f"<tr>{''.join(row_html)}</tr>")
            return f"""
            <div style='margin-bottom: 0.5rem;'>
                <span style='font-size:0.75rem; font-weight:600;'>{title}</span>
                <table style='border-collapse:collapse;width:100%;margin-top:2px;font-size:0.7rem;text-align:center;'>
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
            if df_b.empty: return
            dfp = df_b.copy()
            dfp.index = pd.to_datetime(dfp.index)
            hd = [fmt_date_kor(d) for d in dfp.index]
        
            if ps is not None and len(ps) > 0:
                ps_aligned = ps.reindex(dfp.index, method='nearest', tolerance=pd.Timedelta('3 days'))
                fig_breadth.add_trace(go.Scatter(
                    x=hd, y=ps_aligned.values, name=pname,
                    mode='lines+markers',
                    line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                    marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                    hovertemplate=f'{pname}: %{{y:,.2f}}<extra></extra>',
                    showlegend=False
                ), row=row_idx, col=1, secondary_y=False)
            
            if not is_us:
                up_val = dfp.get('상한가', 0).fillna(0) + dfp.get('상승', 0).fillna(0)
                dn_val = dfp.get('하락', 0).fillna(0) + dfp.get('하한가', 0).fillna(0)
            else:
                up_val = dfp.get('상승', 0).fillna(0)
                dn_val = dfp.get('하락', 0).fillna(0)
            
            ratio_s = up_val - dn_val
        
            fig_breadth.add_trace(go.Scatter(
                x=hd, y=ratio_s.values, name='상하비율',
                mode='lines',
                line=dict(color='rgba(255, 0, 0, 0.8)', width=1),
                hovertemplate='상하비율: %{y:.2f}<extra></extra>',
                showlegend=False
            ), row=row_idx, col=1, secondary_y=True)
        
            fig_breadth.add_hline(y=0.0, line_dash='dash', line_color='gray', line_width=1.0, row=row_idx, col=1, secondary_y=True)
        
            if ps is not None and len(ps) > 0:
                p_min, p_max = float(ps_aligned.min()), float(ps_aligned.max())
                fig_breadth.update_yaxes(range=[p_min*0.95, p_max*1.05], **crosshair_yaxis(), secondary_y=False, row=row_idx, col=1)
            
            r_min, r_max = float(ratio_s.min()), float(ratio_s.max())
            r_range = max(r_max - r_min, 1)
            fig_breadth.update_yaxes(range=[r_min - r_range*0.05, r_max + r_range*0.05], **crosshair_yaxis(), secondary_y=True, row=row_idx, col=1)
            fig_breadth.update_xaxes(type='category', **crosshair_xaxis(), row=row_idx, col=1)
        
            fig_breadth.add_shape(type='rect', xref='x domain', yref='y domain', x0=0, y0=0, x1=1, y1=1, line=dict(color='rgba(150, 150, 150, 0.4)', width=1.2), row=row_idx, col=1)
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
    
    # ── 소분류 4: 감마풋콜 ──
    with sub_tabs[2]:
        if not df.empty:
            df_gex = df.copy()
            hd_gex = [fmt_date_kor(d) for d in df_gex.index]

            # Determine X range based on active_period_days or entire range
            if active_period_days:
                target_start = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=active_period_days))
                detected_indices = [i for i, d in enumerate(df_gex.index) if d >= target_start]
                initial_x_range_gex = [detected_indices[0], len(hd_gex) - 1] if detected_indices else None
            else:
                initial_x_range_gex = None

            # QQQ Y-range calculation for better scaling
            if active_period_days and detected_indices:
                q_prices = df_gex['QQQ'].iloc[detected_indices[0]:]
                qmin, qmax = float(q_prices.min()), float(q_prices.max())
            else:
                qmin, qmax = float(df_gex['QQQ'].min()), float(df_gex['QQQ'].max())

            # ── 1. 감마풋콜 단독 저점/고점 감지 날짜 통합 표 (최근 100개) ──
            single_bottom_df = pd.DataFrame(index=df_gex[df_gex['GammaPutCall_Bottom_Signal']].index)
            single_bottom_df['type'] = '저점'
            single_top_df = pd.DataFrame(index=df_gex[df_gex['GammaPutCall_Top_Signal']].index)
            single_top_df['type'] = '고점'
            
            combined_single = pd.concat([single_bottom_df, single_top_df]).sort_index(ascending=False)[:100]
            
            TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;vertical-align:middle;"
            
            if not combined_single.empty:
                cs_dates_row = []
                cs_types_row = []
                for dt, row in combined_single.iterrows():
                    t = row['type']
                    bg = '#A9D08E' if t == '저점' else '#E06666'
                    cs_dates_row.append(f"<td style='background:{bg};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                    cs_types_row.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{t}</td>")
                    
                cs_table_html = f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 감마풋콜 단독 저점/고점 감지 날짜 (최근 100개)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>날짜</th>
                        {"".join(cs_dates_row)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>구분</th>
                        {"".join(cs_types_row)}
                    </tr>
                </table>
                </div>
                """
                st.markdown(cs_table_html, unsafe_allow_html=True)

            # ── 2. 감마풋콜 단독 차트 통합 (하나의 차트로 표시) ──
            fig_single_combined = make_subplots(specs=[[{"secondary_y": True}]])

            # 저점 신호 감지막대 배경
            fig_single_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['GammaPutCall_Bottom_Signal'], qmax * 1.5, 0),
                    name="저점 신호 감지",
                    marker_color="rgba(46, 204, 113, 0.25)",
                    marker_line_width=0, hoverinfo="skip", showlegend=False
                ),
                secondary_y=False
            )
            # 고점 신호 감지막대 배경
            fig_single_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['GammaPutCall_Top_Signal'], qmax * 1.5, 0),
                    name="고점 신호 감지",
                    marker_color="rgba(231, 76, 60, 0.25)",
                    marker_line_width=0, hoverinfo="skip", showlegend=False
                ),
                secondary_y=False
            )

            # QQQ 가격 (왼쪽 y축)
            fig_single_combined.add_trace(
                go.Scatter(
                    x=hd_gex, y=df_gex['QQQ'],
                    name="QQQ 가격", mode="lines+markers",
                    line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                    marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                    hovertemplate="QQQ: %{y:,.2f}<extra></extra>", showlegend=False
                ),
                secondary_y=False
            )

            # GEX (오른쪽 y축)
            fig_single_combined.add_trace(
                go.Scatter(
                    x=hd_gex, y=df_gex['GEX_Bil'] / 10.0,
                    name="감마익스포저 (십억)",
                    line=dict(color='rgba(255, 0, 0, 0.8)', width=1),
                    hovertemplate="GEX: %{y:.2f}B<extra></extra>", showlegend=False
                ),
                secondary_y=True
            )

            # PCR (오른쪽 y축)
            fig_single_combined.add_trace(
                go.Scatter(
                    x=hd_gex, y=df_gex['PutCallRatio'],
                    name="풋콜레이쇼",
                    line=dict(color='rgba(0, 0, 255, 0.8)', width=1),
                    hovertemplate="PCR: %{y:.2f}<extra></extra>", showlegend=False
                ),
                secondary_y=True
            )

            fig_single_combined.update_layout(
                **COMMON_LAYOUT,
                height=500,
                margin=dict(l=0, r=50, t=30, b=10),
                showlegend=False,
                barmode='overlay'
            )

            fig_single_combined.add_shape(
                type="rect", xref="x domain", yref="y domain",
                x0=0, y0=0, x1=1, y1=1,
                line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2)
            )

            fig_single_combined.update_yaxes(range=[qmin*0.95, qmax*1.05], **crosshair_yaxis(), secondary_y=False)
            fig_single_combined.update_yaxes(range=[-0.75, 2.25], **crosshair_yaxis(), secondary_y=True)
            fig_single_combined.update_xaxes(type="category", **crosshair_xaxis())

            if initial_x_range_gex:
                fig_single_combined.update_xaxes(range=initial_x_range_gex)

            fig_single_combined.add_hline(y=1.0, line_dash="dash", line_color="gray", line_width=1.0, secondary_y=True)
            st.plotly_chart(fig_single_combined, width="stretch", config=COMMON_CONFIG, key="single_combined_subplots")

            # 접기(expander) 형태로 GEX 설명 노출 (기본값: False 닫힘)
            with st.expander("💡 감마 익스포저(GEX) 및 풋콜레이쇼(PCR) 지표 설명 및 활용 가이드", expanded=False):
                st.markdown("""
                - **감마 익스포저 (Gamma Exposure, GEX)**: 옵션 마켓메이커(딜러)들의 포지션 변동으로 인한 헤지 압력을 수치화한 지표입니다.
                  - **양의 감마 (Positive Gamma, GEX > 0)**: 시장 변동성을 낮춥니다. 주가 변동 시 마켓메이커들이 반대 매매로 대처하여 주가가 박스권에 머무는 성향이 있습니다.
                  - **음의 감마 (Negative Gamma, GEX < 0)**: 시장 변동성을 폭발적으로 확장시킵니다. 하락장에서 마켓메이커들의 헤지용 매도가 쏟아지기 때문에 폭락 속도를 더 빠르게 만드는 경향이 있습니다. 역사적 통계에 따라 GEX가 **-8.0B(하위 10% 수준) 이하**로 추락하는 지점은 극단적 매도세의 정점으로, **최적의 분할 저점 매수 기회**를 의미합니다.
                - **풋콜레이쇼 (Put/Call Ratio, PCR)**: 콜옵션 거래량 대비 풋옵션 거래량 비율로, 공포 심리를 파악하는 마인드셋 지표입니다.
                  - **PCR 1.1 이상 (고공 행진)**: 시장의 하방 두려움이 극에 달해 풋옵션 매수가 넘치는 상황으로, 단기 바닥 영역(저점) 매수 조건에 충족됩니다.
                  - **PCR 0.7 이하 (바닥권)**: 극도의 낙관주의로 콜옵션이 과매수 상태이며, 주가 상승세 둔화 및 하방 변곡점(고점) 매도 조건에 충족됩니다.

                ※ 본 모니터링 화면의 GEX는 S&P 500 GEX 데이터를 QQQ의 신뢰성 높은 대용 지표로 연계하여 실시간 렌더링하고 있으며, 풋콜레이쇼(PCR)는 CBOE 옵션 시장 $CPC 데이터를 충실히 재현한 실시간 프록시 지표입니다.
                """)

            st.markdown("<hr style='margin: 1.0rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)

            # 저점/고점 검증결과 단일 표 통합 노출
            st.markdown("### 📊 감마풋콜 지표 성능 검증")
            bottom_conditions = {
                "**감마풋콜 저점**": (df_gex['GammaPutCall_Bottom_Signal'], "GEX <= -0.5B & PCR >= 1.08")
            }
            stats_bottom = calculate_indicator_stats(df_gex, 'QQQ', bottom_conditions, window=41, dd_threshold=0.05)

            top_conditions = {
                "**감마풋콜 고점**": (df_gex['GammaPutCall_Top_Signal'], "GEX >= 1.0B & PCR <= 0.72")
            }
            stats_top = calculate_top_stats(df_gex, 'QQQ', top_conditions, window=41, ru_threshold=0.10)

            rows = []
            for item in stats_bottom:
                rows.append({
                    "감지 조건": item['name'],
                    "조건 세부 내용": item['desc'],
                    "발생 횟수": item['triggered'],
                    "적중률 (Hit Rate)": item['hit_rate'],
                    "포착률 (Recall)": item['recall'],
                    "종합 점수": item['score']
                })
            for item in stats_top:
                rows.append({
                    "감지 조건": item['name'],
                    "조건 세부 내용": item['desc'],
                    "발생 횟수": item['triggered'],
                    "적중률 (Hit Rate)": item['hit_rate'],
                    "포착률 (Recall)": item['recall'],
                    "종합 점수": item['score']
                })
            combined_stats = pd.DataFrame(rows)
            render_gamma_stats_table(combined_stats, '감마풋콜 단독 지표 검증 결과')

            st.markdown("<hr style='margin: 1.5rem 0; border: 0.5px solid #333;'>", unsafe_allow_html=True)

            # ── 3. 감마풋콜기타 혼합 저점/고점 차트 통합 (x축 연동) 및 감지표 세로 배치 ──
            # ── 감마풋콜기타 혼합 저점 7단계 감지 날짜 표 ──
            hb_sig_dates = df_gex[df_gex['Score_Bottom'] >= 14.0].index.sort_values(ascending=False)[:100]
            if not hb_sig_dates.empty:
                hb_dates_row = []
                hb_levels_row = []
                for dt in hb_sig_dates:
                    cnt = df_gex.loc[dt, 'Score_Bottom']
                    bg = '#800080' if cnt >= 20.0 else '#000080' if cnt >= 19.0 else '#87CEEB' if cnt >= 18.0 else '#A9D08E' if cnt >= 17.0 else '#FFD700' if cnt >= 16.0 else '#FF8C00' if cnt >= 15.0 else '#E06666'
                    lvl = "7단계" if cnt >= 20.0 else "6단계" if cnt >= 19.0 else "5단계" if cnt >= 18.0 else "4단계" if cnt >= 17.0 else "3단계" if cnt >= 16.0 else "2단계" if cnt >= 15.0 else "1단계"

                    hb_dates_row.append(f"<td style='background:{bg};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                    hb_levels_row.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{lvl}</td>")

                hb_table_html = f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 혼합 저점 신호 감지 날짜 (최근 100개)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>날짜</th>
                        {"".join(hb_dates_row)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>단계</th>
                        {"".join(hb_levels_row)}
                    </tr>
                </table>
                </div>
                """
                st.markdown(hb_table_html, unsafe_allow_html=True)

            # ── 감마풋콜기타 혼합 고점 7단계 감지 날짜 표 ──
            ht_sig_dates = df_gex[df_gex['Score_Top'] >= 13.5].index.sort_values(ascending=False)[:100]
            if not ht_sig_dates.empty:
                ht_dates_row = []
                ht_levels_row = []
                for dt in ht_sig_dates:
                    cnt = df_gex.loc[dt, 'Score_Top']
                    bg = '#800080' if cnt >= 16.5 else '#000080' if cnt >= 16.0 else '#87CEEB' if cnt >= 15.5 else '#A9D08E' if cnt >= 15.0 else '#FFD700' if cnt >= 14.5 else '#FF8C00' if cnt >= 14.0 else '#E06666'
                    lvl = "7단계" if cnt >= 16.5 else "6단계" if cnt >= 16.0 else "5단계" if cnt >= 15.5 else "4단계" if cnt >= 15.0 else "3단계" if cnt >= 14.5 else "2단계" if cnt >= 14.0 else "1단계"

                    ht_dates_row.append(f"<td style='background:{bg};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                    ht_levels_row.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{lvl}</td>")

                ht_table_html = f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 혼합 고점 신호 감지 날짜 (최근 100개)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>날짜</th>
                        {"".join(ht_dates_row)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>단계</th>
                        {"".join(ht_levels_row)}
                    </tr>
                </table>
                </div>
                """
                st.markdown(ht_table_html, unsafe_allow_html=True)

            # 차트 통합 생성
            fig_hybrid_combined = make_subplots(
                rows=2, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.08, 
                subplot_titles=["📊 \"감마풋콜기타 혼합 저점\" 지표 및 7단계(빨주노초파남보) 감지 시각화", "📊 \"감마풋콜기타 혼합 고점\" 지표 및 7단계(빨주노초파남보) 감지 시각화"],
                specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
            )

            # Row 1 (저점 7단계)
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 14.0, qmax * 1.5, 0),
                    name="저점 1단계 (빨강)", marker_color="rgba(224, 102, 102, 0.45)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 15.0, qmax * 1.5, 0),
                    name="저점 2단계 (주황)", marker_color="rgba(255, 140, 0, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 16.0, qmax * 1.5, 0),
                    name="저점 3단계 (노랑)", marker_color="rgba(255, 255, 153, 0.45)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 17.0, qmax * 1.5, 0),
                    name="저점 4단계 (초록)", marker_color="rgba(0, 128, 0, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 18.0, qmax * 1.5, 0),
                    name="저점 5단계 (하늘)", marker_color="rgba(135, 206, 235, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 19.0, qmax * 1.5, 0),
                    name="저점 6단계 (남색)", marker_color="rgba(0, 0, 128, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Bottom'] >= 20.0, qmax * 1.5, 0),
                    name="저점 7단계 (보라)", marker_color="rgba(128, 0, 128, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=1, col=1, secondary_y=False
            )
            # QQQ 가격 (Row 1)
            fig_hybrid_combined.add_trace(
                go.Scatter(
                    x=hd_gex, y=df_gex['QQQ'],
                    name="QQQ 가격", mode="lines+markers",
                    line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                    marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                    hovertemplate="QQQ: %{y:,.2f}<extra></extra>", showlegend=False
                ), row=1, col=1, secondary_y=False
            )

            # Row 2 (고점 7단계)
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 13.5, qmax * 1.5, 0),
                    name="고점 1단계 (빨강)", marker_color="rgba(224, 102, 102, 0.45)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 14.0, qmax * 1.5, 0),
                    name="고점 2단계 (주황)", marker_color="rgba(255, 140, 0, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 14.5, qmax * 1.5, 0),
                    name="고점 3단계 (노랑)", marker_color="rgba(255, 255, 153, 0.45)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 15.0, qmax * 1.5, 0),
                    name="고점 4단계 (초록)", marker_color="rgba(0, 128, 0, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 15.5, qmax * 1.5, 0),
                    name="고점 5단계 (하늘)", marker_color="rgba(135, 206, 235, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 16.0, qmax * 1.5, 0),
                    name="고점 6단계 (남색)", marker_color="rgba(0, 0, 128, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            fig_hybrid_combined.add_trace(
                go.Bar(
                    x=hd_gex, y=np.where(df_gex['Score_Top'] >= 16.5, qmax * 1.5, 0),
                    name="고점 7단계 (보라)", marker_color="rgba(128, 0, 128, 0.3)",
                    marker_line_width=0.5, marker_line_color='white',
                    hoverinfo="skip", showlegend=False
                ), row=2, col=1, secondary_y=False
            )
            # QQQ 가격 (Row 2)
            fig_hybrid_combined.add_trace(
                go.Scatter(
                    x=hd_gex, y=df_gex['QQQ'],
                    name="QQQ 가격", mode="lines+markers",
                    line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                    marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                    hovertemplate="QQQ: %{y:,.2f}<extra></extra>", showlegend=False
                ), row=2, col=1, secondary_y=False
            )

            fig_hybrid_combined.update_layout(
                **COMMON_LAYOUT,
                height=750,
                margin=dict(l=0, r=50, t=30, b=10),
                showlegend=False,
                barmode='overlay'
            )

            fig_hybrid_combined.update_annotations(font_size=10)

            fig_hybrid_combined.add_shape(
                type="rect", xref="x domain", yref="y domain",
                x0=0, y0=0, x1=1, y1=1,
                line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2),
                row=1, col=1
            )
            fig_hybrid_combined.add_shape(
                type="rect", xref="x domain", yref="y domain",
                x0=0, y0=0, x1=1, y1=1,
                line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2),
                row=2, col=1
            )

            fig_hybrid_combined.update_yaxes(range=[qmin*0.95, qmax*1.05], **crosshair_yaxis(), row=1, col=1, secondary_y=False)
            fig_hybrid_combined.update_yaxes(**crosshair_yaxis(), row=1, col=1, secondary_y=True)
            fig_hybrid_combined.update_yaxes(range=[qmin*0.95, qmax*1.05], **crosshair_yaxis(), row=2, col=1, secondary_y=False)
            fig_hybrid_combined.update_yaxes(**crosshair_yaxis(), row=2, col=1, secondary_y=True)

            fig_hybrid_combined.update_xaxes(type="category", **crosshair_xaxis())

            if initial_x_range_gex:
                fig_hybrid_combined.update_xaxes(range=initial_x_range_gex)

            st.plotly_chart(fig_hybrid_combined, width="stretch", config=COMMON_CONFIG, key="hybrid_combined_subplots")

            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    with sub_tabs[3]:
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
                f"<table style='width:100%;border-collapse:collapse;border:none !important;margin:0 !important;text-align:center;'>"
                f"<tr style='background:transparent !important;border:none !important;'>"
                f"  <td style='border:none !important;padding:2px 4px !important;font-size:0.75rem;color:#8b93a3;'>DXI 지수</td>"
                f"  <td style='border:none !important;padding:2px 4px !important;font-size:0.85rem;font-weight:700;text-align:right;'>{int(round(dxi.get('value', 0))):,}</td>"
                f"  <td style='border:none !important;padding:2px 4px !important;font-size:0.75rem;text-align:right;'>{get_chg_badge(dxi.get('chg', 0))}</td>"
                f"</tr>"
                f"</table>"
                f"</div>", unsafe_allow_html=True
            )
    
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
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
    
            five_years_ago_kr = pd.to_datetime('2020-01-01')
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
    
            # Collect all unique dates to form a sorted category array for x-axis (starting from 2020-01-01)
            start_date_2020 = pd.to_datetime('2020-01-01')
            monthly_dates = [pd.to_datetime(m + "-01") for m in dr_m.get('m', []) if pd.to_datetime(m + "-01") >= start_date_2020]
            customs_dates = [pd.to_datetime(m + "-01") for m in dr_c.get('m', []) if pd.to_datetime(m + "-01") >= start_date_2020]
            dr_m_vals = [v for m, v in zip(dr_m.get('m', []), dr_m.get('v', [])) if pd.to_datetime(m + "-01") >= start_date_2020]
            na_m_vals = [v for m, v in zip(na_m.get('m', []), na_m.get('v', [])) if pd.to_datetime(m + "-01") >= start_date_2020]
            dr_c_vals = [v for m, v in zip(dr_c.get('m', []), dr_c.get('v', [])) if pd.to_datetime(m + "-01") >= start_date_2020]
            na_c_vals = [v for m, v in zip(na_c.get('m', []), na_c.get('v', [])) if pd.to_datetime(m + "-01") >= start_date_2020]

            all_dates = {d for d in df1_kr.index if d >= start_date_2020}
            all_dates.update(monthly_dates)
            all_dates.update(customs_dates)
    
            # Spot dates
            parsed_spot_dict = {}
            for grp in spot_groups:
                for row in grp[2]:
                    tid = row[3]
                    series_data = dram_data.get('series', {}).get(str(tid), {'d': [], 'v': []})
                    spot_d = series_data.get('d', [])
                    spot_v_raw = series_data.get('v', [])
                    parsed = []
                    parsed_v = []
                    for dt_str, val in zip(spot_d, spot_v_raw):
                        if len(dt_str) == 5:
                            d_obj = pd.to_datetime(f"{datetime.date.today().year}-{dt_str}")
                        else:
                            d_obj = pd.to_datetime(dt_str)
                        if d_obj >= start_date_2020:
                            parsed.append(d_obj)
                            parsed_v.append(val)
                            all_dates.add(d_obj)
                    parsed_spot_dict[tid] = (parsed, parsed_v)
        
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
            kospi_hd = [fmt_date_kor(d) for d in df1_kr.index if d >= start_date_2020]
            df1_kr_overview = df1_kr[df1_kr.index >= start_date_2020]
            fig_mem.add_trace(go.Scatter(
                x=kospi_hd, y=df1_kr_overview['KOSPI'], name='KOSPI 지수',
                mode='lines+markers', line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                hovertemplate='KOSPI: %{y:.2f}<extra></extra>'
            ), row=1, col=1, secondary_y=False)
    
            m_hd = [fmt_date_kor(d) for d in monthly_dates]
            fig_mem.add_trace(go.Scatter(
                x=m_hd, y=dr_m_vals, name='DRAM 현물 ($)', mode='lines', line=dict(color='rgba(255, 0, 0, 0.8)', width=1),
                hovertemplate='DRAM 현물: $%{y:.2f}<extra></extra>'
            ), row=1, col=1, secondary_y=True)
            fig_mem.add_trace(go.Scatter(
                x=m_hd, y=na_m_vals, name='NAND 웨이퍼 ($)', mode='lines', line=dict(color='rgba(255, 255, 0, 0.8)', width=1),
                hovertemplate='NAND 웨이퍼: $%{y:.2f}<extra></extra>'
            ), row=1, col=1, secondary_y=True)
    
            c_hd = [fmt_date_kor(d) for d in customs_dates]
            fig_mem.add_trace(go.Scatter(
                x=c_hd, y=dr_c_vals, name='수출 DRAM (k$/kg)', mode='lines', line=dict(color='rgba(0, 128, 0, 0.8)', width=1),
                hovertemplate='수출 DRAM: %{y:.2f}k/kg<extra></extra>'
            ), row=1, col=1, secondary_y=True)
            fig_mem.add_trace(go.Scatter(
                x=c_hd, y=na_c_vals, name='수출 NAND (k$/kg)', mode='lines', line=dict(color='rgba(0, 0, 128, 0.8)', width=1),
                hovertemplate='수출 NAND: %{y:.2f}k/kg<extra></extra>'
            ), row=1, col=1, secondary_y=True)
    
            # 2) 6 Spot Group Rows
            colors = ['#ff5b5b', '#3b82f6', '#d99a2b', '#10b981', '#8b5cf6', '#f43f5e', '#f59e0b', '#06b6d4', '#6366f1']
            for idx, grp in enumerate(spot_groups):
                row_idx = idx + 2
        
                # KOSPI on left
                fig_mem.add_trace(go.Scatter(
                    x=kospi_hd, y=df1_kr['KOSPI'], name=f'KOSPI ({grp[1]})',
                    mode='lines+markers', line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                    marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                    hovertemplate='KOSPI: %{y:.2f}<extra></extra>', showlegend=False
                ), row=row_idx, col=1, secondary_y=False)
        
                # Series items on right
                for c_idx, row in enumerate(grp[2]):
                    item_name = row[0]
                    tid = row[3]
                    parsed_dates, spot_v = parsed_spot_dict[tid]
                    s_hd = [fmt_date_kor(d) for d in parsed_dates]
                    c = colors[c_idx % len(colors)]
        
                    mem_palette = ['rgba(255, 0, 0, 0.8)', 'rgba(255, 255, 0, 0.8)', 'rgba(0, 128, 0, 0.8)', 'rgba(0, 0, 128, 0.8)', 'rgba(128, 0, 128, 0.8)', 'rgba(165, 42, 42, 0.8)', 'rgba(135, 206, 235, 0.8)']
                    fig_mem.add_trace(go.Scatter(
                        x=s_hd, y=spot_v, name=item_name, mode='lines', line=dict(color=mem_palette[c_idx % len(mem_palette)], width=1),
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
            <table style="width:100%;border-collapse:collapse;font-size:0.6rem !important;text-align:center;">
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

# ── Tab 2: 고점지표 ──
with tabs[1]:
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
            fv5_factor = 0.60
            SLOPE_FV5_HIGH_CHARTS = [
                (2, 10, 'FV5_슬로프10일합', round(6.8 * fv5_factor, 2)),
                (3, 20, 'FV5_슬로프20일합', round(9.8 * fv5_factor, 2)),
                (4, 30, 'FV5_슬로프30일합', round(10.3 * fv5_factor, 2)),
                (5, 40, 'FV5_슬로프40일합', round(11.0 * fv5_factor, 2)),
                (6, 50, 'FV5_슬로프50일합', round(10.4 * fv5_factor, 2)),
                (7, 60, 'FV5_슬로프60일합', round(11.3 * fv5_factor, 2)),
                (8, 70, 'FV5_슬로프70일합', round(12.3 * fv5_factor, 2)),
            ]
            
            # 동시 감지 갯수 계산 및 저장 (저점일 제외)
            fv5_slope_detect_count = sum(((df[sfc] >= thresh) & _not_bottom).astype(int) for _, _, sfc, thresh in SLOPE_FV5_HIGH_CHARTS)
            df['fv5_slope_detect_count'] = fv5_slope_detect_count
            
            # 상한 돌파 신호 감지표 (저점일 제외)
            all_top_fv5_sl = []
            for _, days_t, sfc, thresh in SLOPE_FV5_HIGH_CHARTS:
                _cond_sl = (df[sfc] >= thresh) & _not_bottom
                all_top_fv5_sl.extend(df[_cond_sl].index.tolist())
            dc_top_fv5_sl = Counter(all_top_fv5_sl)
            parent_dates_fv5_sl = sorted(list(set(all_top_fv5_sl)), reverse=True)
            
            if parent_dates_fv5_sl:
                r100_sl = parent_dates_fv5_sl[:100]
                dates_row_sl = []
                counts_row_sl = []
                for dt in r100_sl:
                    cnt = dc_top_fv5_sl.get(dt, 1)
                    # 1개(빨강), 2개(주황), 3개(노랑), 4개(초록), 5개(파랑), 6개(남색), 7개(보라)
                    bg = "#E06666" if cnt==1 else "#FF8C00" if cnt==2 else '#FFD700' if cnt==3 else "#A9D08E" if cnt==4 else "#87CEEB" if cnt==5 else "#000080" if cnt==6 else "#800080"
                    fg = "#FFF"
                    dates_row_sl.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    
                    detected_items = []
                    for _, days, sc_col, th in SLOPE_FV5_HIGH_CHARTS:
                        if dt in df.index and df.loc[dt, sc_col] >= th:
                            # 초과율(%) 계산: (슬로프합 - 상한선) / abs(상한선)
                            val_diff_pct = (df.loc[dt, sc_col] - th) / abs(th)
                            if 0.0 <= val_diff_pct <= 0.40:
                                color = '#A9D08E' # 초록
                            elif 0.40 < val_diff_pct <= 0.60:
                                color = '#FFD700' # 노랑
                            elif 0.60 < val_diff_pct <= 0.80:
                                color = '#E06666' # 빨강
                            else:
                                color = '#595959' # 검정
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    
                    val_str = "<br>".join(detected_items)
                    counts_row_sl.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 고점 과열 감지 날짜 (최근 100개, 저점 감지일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_sl)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>감지</th>
                        {"".join(counts_row_sl)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            hd_df = [fmt_date_kor(d) for d in df.index]
            
            bottom_slope_options = ["슬로프통합", "10일합", "20일합", "30일합", "40일합", "50일합", "60일합", "70일합"]
            selected_bottom_slopes = st.multiselect("📊 표시할 슬로프 차트 선택 (다중 선택 가능)", bottom_slope_options, default=["슬로프통합"], key="top_fv5_slope_multiselect")
            
            if not selected_bottom_slopes:
                st.info("시각화할 슬로프 지표를 다중 선택창에서 선택해 주세요 (예: 슬로프통합, 10일합 등).")
            else:
                num_charts = len(selected_bottom_slopes)
                fig_dsi = make_subplots(rows=num_charts, cols=1, shared_xaxes=True, vertical_spacing=0.03 if num_charts > 1 else 0.0,
                    subplot_titles=tuple(selected_bottom_slopes),
                    specs=[[{"secondary_y": True}]]*num_charts)
                
                chart_info_map = {
                    10: ('FV5_슬로프10일합', round(6.8 * fv5_factor, 2)),
                    20: ('FV5_슬로프20일합', round(9.8 * fv5_factor, 2)),
                    30: ('FV5_슬로프30일합', round(10.3 * fv5_factor, 2)),
                    40: ('FV5_슬로프40일합', round(11.0 * fv5_factor, 2)),
                    50: ('FV5_슬로프50일합', round(10.4 * fv5_factor, 2)),
                    60: ('FV5_슬로프60일합', round(11.3 * fv5_factor, 2)),
                    70: ('FV5_슬로프70일합', round(12.3 * fv5_factor, 2)),
                }
                
                for idx, choice in enumerate(selected_bottom_slopes):
                    row_i = idx + 1
                    sf = (idx == 0)
                    
                    if choice == "슬로프통합":
                        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=False,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        fig_dsi.add_trace(go.Scatter(x=hd_df, y=df['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'), row=row_i, col=1, secondary_y=True)
                        
                        detect_colors = {
                            1: 'rgba(224, 102, 102, 0.45)', # 빨강
                            2: 'rgba(255, 140, 0, 0.3)',   # 주황
                            3: 'rgba(255, 255, 153, 0.45)', # 노랑
                            4: 'rgba(0, 128, 0, 0.3)', # 초록
                            5: 'rgba(135, 206, 235, 0.3)', # 파랑
                            6: 'rgba(0, 0, 128, 0.3)',     # 남색
                            7: 'rgba(128, 0, 128, 0.3)'    # 보라
                        }
                        for cnt_val, bar_color in detect_colors.items():
                            cond_bar = (df['fv5_slope_detect_count'] == cnt_val)
                            fig_dsi.add_trace(go.Bar(
                                x=hd_df,
                                y=cond_bar.astype(int).values * float(df['QQQ'].max()) * 1.2,
                                marker_color=bar_color,
                                showlegend=False,
                                hoverinfo='skip',
                                marker_line_width=0.5,
                                marker_line_color='white'
                            ), row=row_i, col=1, secondary_y=False)
                            
                    else:
                        days = int(choice.replace("일합", ""))
                        sc, thresh = chart_info_map[days]
                        
                        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        fig_dsi.add_trace(go.Scatter(x=hd_df,y=df[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(255, 0, 0, 0.8)', width=1),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=row_i,col=1,secondary_y=True)
                        fig_dsi.add_trace(go.Scatter(x=hd_df, y=df['(FGI-VIX)/5'], name='(FGI-VIX)/5', line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate='(FGI-VIX)/5: %{y:.2f}<extra></extra>'), row=row_i, col=1, secondary_y=True)
                        fig_dsi.add_trace(go.Scatter(x=hd_df,y=[thresh]*len(hd_df),name='상한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='upper',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        fig_dsi.add_trace(go.Scatter(x=hd_df,y=[-thresh]*len(hd_df),name='하한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='lower',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        
                        # 초과 비율(%)에 따른 막대 그래프 렌더링 (0% 초과부터 표시)
                        diff_pct = (df[sc] - thresh) / abs(thresh)
                        bottom_cond_vals = [
                            ((diff_pct >= 0.0) & (diff_pct <= 0.40), 'rgba(0, 128, 0, 0.3)'),   # 0~40%: 초록색
                            ((diff_pct > 0.40) & (diff_pct <= 0.60), 'rgba(255, 220, 0, 0.3)'),   # 40% 초과 ~ 60% 이하: 노란색
                            ((diff_pct > 0.60) & (diff_pct <= 0.80), 'rgba(220, 30, 30, 0.3)'),   # 60% 초과 ~ 80% 이하: 빨간색
                            ((diff_pct > 0.80), 'rgba(0, 0, 0, 0.3)'),                             # 80% 초과: 검은색
                        ]
                        for tc, tfc in bottom_cond_vals:
                            fig_dsi.add_trace(go.Bar(x=hd_df, y=tc.astype(int).values * float(df['QQQ'].max()) * 1.2, marker_color=tfc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'),row=row_i,col=1,secondary_y=False)
                
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
                
                chart_height = max(400, num_charts * 300)
                layout_params = COMMON_LAYOUT.copy()
                layout_params.pop('shapes', None)
                
                shapes = []
                for idx in range(num_charts):
                    shapes.append(dict(type="rect", xref=f"x{idx+1}" if idx > 0 else "x", yref=f"y{idx+1}" if idx > 0 else "y", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2)))
                
                fig_dsi.update_layout(
                    **layout_params,
                    height=chart_height,
                    showlegend=False,
                    barmode='overlay',
                    bargap=0,
                    margin=dict(l=0, r=50, t=30, b=10),
                    shapes=shapes
                )
                
                for idx in range(num_charts):
                    x_axis_key = f"xaxis{idx+1}" if idx > 0 else "xaxis"
                    y_axis_key = f"yaxis{idx+1}" if idx > 0 else "yaxis"
                    y_axis_key_sec = f"yaxis{idx+1}2" if idx > 0 else "yaxis2"
                    
                    if initial_x_range_dsi:
                        fig_dsi.update_layout({x_axis_key: crosshair_xaxis(range=initial_x_range_dsi, type='category')})
                    else:
                        fig_dsi.update_layout({x_axis_key: crosshair_xaxis(type='category')})
                    
                    fig_dsi.update_layout({y_axis_key: crosshair_yaxis(range=[qmin_dsi*0.95, qmax_dsi*1.05], side='left')})
                    
                    choice = selected_bottom_slopes[idx]
                    if choice == "슬로프통합":
                        fig_dsi.update_layout({y_axis_key_sec: crosshair_yaxis(range=[-20, 20], side='right', overlaying=y_axis_key.replace("yaxis", "y"))})
                    else:
                        days = int(choice.replace("일합", ""))
                        sc, thresh = chart_info_map[days]
                        fig_dsi.update_layout({y_axis_key_sec: crosshair_yaxis(range=[-thresh*2.2, thresh*2.2], side='right', overlaying=y_axis_key.replace("yaxis", "y"))})
                
                st.plotly_chart(fig_dsi, width='stretch', config=COMMON_CONFIG, key="top_fv5_slope_chart")
            
            # 고점 검증결과 표
            _nb = _not_bottom
            top_fv5_conditions = {
                "**10일합 돌파**": ((df['FV5_슬로프10일합'] >= round(6.8 * fv5_factor, 2)) & _nb, f"10일슬로프합 >= {round(6.8 * fv5_factor, 2)}"),
                "**20일합 돌파**": ((df['FV5_슬로프20일합'] >= round(9.8 * fv5_factor, 2)) & _nb, f"20일슬로프합 >= {round(9.8 * fv5_factor, 2)}"),
                "**30일합 돌파**": ((df['FV5_슬로프30일합'] >= round(10.3 * fv5_factor, 2)) & _nb, f"30일슬로프합 >= {round(10.3 * fv5_factor, 2)}"),
                "**40일합 돌파**": ((df['FV5_슬로프40일합'] >= round(11.0 * fv5_factor, 2)) & _nb, f"40일슬로프합 >= {round(11.0 * fv5_factor, 2)}"),
                "**50일합 돌파**": ((df['FV5_슬로프50일합'] >= round(10.4 * fv5_factor, 2)) & _nb, f"50일슬로프합 >= {round(10.4 * fv5_factor, 2)}"),
                "**60일합 돌파**": ((df['FV5_슬로프60일합'] >= round(11.3 * fv5_factor, 2)) & _nb, f"60일슬로프합 >= {round(11.3 * fv5_factor, 2)}"),
                "**70일합 돌파**": ((df['FV5_슬로프70일합'] >= round(12.3 * fv5_factor, 2)) & _nb, f"70일슬로프합 >= {round(12.3 * fv5_factor, 2)}"),
                "**슬로프합 종합 감지**": (
                    ((df['FV5_슬로프10일합'] >= round(6.8 * fv5_factor, 2)) | (df['FV5_슬로프20일합'] >= round(9.8 * fv5_factor, 2)) | (df['FV5_슬로프30일합'] >= round(10.3 * fv5_factor, 2)) | 
                     (df['FV5_슬로프40일합'] >= round(11.0 * fv5_factor, 2)) | (df['FV5_슬로프50일합'] >= round(10.4 * fv5_factor, 2)) | (df['FV5_슬로프60일합'] >= round(11.3 * fv5_factor, 2)) | (df['FV5_슬로프70일합'] >= round(12.3 * fv5_factor, 2))) & _nb,
                    "1개 이상 지표 돌파"
                ),
                "**슬로프합 강력 돌파**": (
                    (((df['FV5_슬로프10일합'] >= round(6.8 * fv5_factor, 2)).astype(int) + 
                      (df['FV5_슬로프20일합'] >= round(9.8 * fv5_factor, 2)).astype(int) + 
                      (df['FV5_슬로프30일합'] >= round(10.3 * fv5_factor, 2)).astype(int) + 
                      (df['FV5_슬로프40일합'] >= round(11.0 * fv5_factor, 2)).astype(int) + 
                      (df['FV5_슬로프50일합'] >= round(10.4 * fv5_factor, 2)).astype(int) + 
                      (df['FV5_슬로프60일합'] >= round(11.3 * fv5_factor, 2)).astype(int) + 
                      (df['FV5_슬로프70일합'] >= round(12.3 * fv5_factor, 2)).astype(int)) >= 4) & _nb,
                    "4개 이상 지표 동시 돌파"
                )
            }
            stats_top1 = calculate_top_stats(df, 'QQQ', top_fv5_conditions)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_top_stats_table(stats_top1, "지표검증결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
        
        # ── 소분류 2: 슬로프합 고점 ──
        with top_sub_tabs[1]:
            SLOPE_TOP_CHARTS = [
                (2, 10, '슬로프10일합', 29),
                (3, 20, '슬로프20일합', 39),
                (4, 30, '슬로프30일합', 46),
                (5, 40, '슬로프40일합', 59),
                (6, 50, '슬로프50일합', 75),
                (7, 60, '슬로프60일합', 93),
                (8, 70, '슬로프70일합', 109),
            ]
            
            # 동시 감지 갯수 계산 및 저장
            slope_detect_count = sum(((df[sfc] >= thresh) & _not_bottom).astype(int) for _, _, sfc, thresh in SLOPE_TOP_CHARTS)
            df['slope_detect_count'] = slope_detect_count
            
            # 상한 돌파 신호 감지표 (저점일 제외, 초과율 0% 이상인 경우 수집)
            all_top_sl = []
            for _, days_t, sfc, thresh in SLOPE_TOP_CHARTS:
                _cond_sl = (df[sfc] >= thresh) & _not_bottom
                all_top_sl.extend(df[_cond_sl].index.tolist())
            dc_top_sl = Counter(all_top_sl)
            parent_dates_sl = sorted(list(set(all_top_sl)), reverse=True)
            
            if parent_dates_sl:
                r100_sl = parent_dates_sl[:100]
                dates_row_sl = []
                counts_row_sl = []
                for dt in r100_sl:
                    cnt = dc_top_sl.get(dt, 1)
                    bg = "#E06666" if cnt==1 else "#FF8C00" if cnt==2 else '#FFD700' if cnt==3 else "#A9D08E" if cnt==4 else "#87CEEB" if cnt==5 else "#000080" if cnt==6 else "#800080"
                    fg = "#FFF"
                    dates_row_sl.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    
                    detected_items = []
                    for _, days, sc_col, th in SLOPE_TOP_CHARTS:
                        if dt in df.index and df.loc[dt, sc_col] >= th:
                            val_diff_pct = (df.loc[dt, sc_col] - th) / th
                            if 0.0 <= val_diff_pct <= 0.40:
                                color = '#A9D08E'
                            elif 0.40 < val_diff_pct <= 0.60:
                                color = '#FFD700'
                            elif 0.60 < val_diff_pct <= 0.80:
                                color = '#E06666'
                            else:
                                color = '#595959'
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    
                    val_str = "<br>".join(detected_items)
                    counts_row_sl.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 슬로프합 상한 돌파 고점 신호 (최근 100개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_sl)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>돌파</th>
                        {"".join(counts_row_sl)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            slope_options = ["슬로프통합", "10일합", "20일합", "30일합", "40일합", "50일합", "60일합", "70일합"]
            selected_slopes = st.multiselect("📊 표시할 슬로프 차트 선택 (다중 선택 가능)", slope_options, default=["슬로프통합"], key="top_slope_multiselect")
            
            hd_top_sl = [fmt_date_kor(d) for d in df.index]
            
            if not selected_slopes:
                st.info("시각화할 슬로프 지표를 다중 선택창에서 선택해 주세요 (예: 슬로프통합, 10일합 등).")
            else:
                num_charts = len(selected_slopes)
                fig_top_sl = make_subplots(rows=num_charts, cols=1, shared_xaxes=True, vertical_spacing=0.03 if num_charts > 1 else 0.0,
                    subplot_titles=tuple(selected_slopes),
                    specs=[[{"secondary_y": True}]]*num_charts)
                
                chart_info_map = {
                    10: ('슬로프10일합', 29),
                    20: ('슬로프20일합', 39),
                    30: ('슬로프30일합', 46),
                    40: ('슬로프40일합', 59),
                    50: ('슬로프50일합', 75),
                    60: ('슬로프60일합', 93),
                    70: ('슬로프70일합', 109),
                }
                
                for idx, choice in enumerate(selected_slopes):
                    row_i = idx + 1
                    sf = (idx == 0)
                    
                    if choice == "슬로프통합":
                        fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=False,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        
                        detect_colors = {
                            1: 'rgba(224, 102, 102, 0.45)', # 빨강
                            2: 'rgba(255, 140, 0, 0.3)',   # 주황
                            3: 'rgba(255, 255, 153, 0.45)', # 노랑
                            4: 'rgba(0, 128, 0, 0.3)', # 초록
                            5: 'rgba(135, 206, 235, 0.3)', # 파랑
                            6: 'rgba(0, 0, 128, 0.3)',     # 남색
                            7: 'rgba(128, 0, 128, 0.3)'    # 보라
                        }
                        for cnt_val, bar_color in detect_colors.items():
                            cond_bar = (df['slope_detect_count'] == cnt_val)
                            fig_top_sl.add_trace(go.Bar(
                                x=hd_top_sl,
                                y=cond_bar.astype(int).values * float(df['QQQ'].max()) * 1.2,
                                marker_color=bar_color,
                                showlegend=False,
                                hoverinfo='skip',
                                marker_line_width=0.5,
                                marker_line_color='white'
                            ), row=row_i, col=1, secondary_y=False)
                            
                    else:
                        days = int(choice.replace("일합", ""))
                        sc, thresh = chart_info_map[days]
                        
                        fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=df['QQQ'],name='QQQ 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=sf,legendgroup='qqq',hovertemplate='QQQ: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=df[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(255, 0, 0, 0.8)', width=1),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=row_i,col=1,secondary_y=True)
                        fig_top_sl.add_trace(go.Scatter(x=hd_top_sl,y=[thresh]*len(hd_top_sl),name='상한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='upper_top',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        
                        diff_pct = (df[sc] - thresh) / thresh
                        top_cond_vals = [
                            (((diff_pct >= 0.0) & (diff_pct <= 0.40)) & _not_bottom, 'rgba(0, 128, 0, 0.3)'),
                            (((diff_pct > 0.40) & (diff_pct <= 0.60)) & _not_bottom, 'rgba(255, 220, 0, 0.3)'),
                            (((diff_pct > 0.60) & (diff_pct <= 0.80)) & _not_bottom, 'rgba(220, 30, 30, 0.3)'),
                            ((diff_pct > 0.80) & _not_bottom, 'rgba(0, 0, 0, 0.3)'),
                        ]
                        for tc, tfc in top_cond_vals:
                            fig_top_sl.add_trace(go.Bar(x=hd_top_sl, y=tc.astype(int).values * float(df['QQQ'].max()) * 1.2, marker_color=tfc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'),row=row_i,col=1,secondary_y=False)
                
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
                
                chart_height = max(400, num_charts * 300)
                layout_params_tsl = COMMON_LAYOUT.copy()
                layout_params_tsl.pop('shapes', None)
                
                shapes = []
                for idx in range(num_charts):
                    y_ref = "y domain" if idx == 0 else f"y{2*idx + 1} domain"
                    shapes.append(dict(type="rect", xref="paper", yref=y_ref, x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.5)))
                
                fig_top_sl.update_layout(**layout_params_tsl, height=chart_height, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=shapes)
                
                for idx, choice in enumerate(selected_slopes):
                    row_i = idx + 1
                    fig_top_sl.update_yaxes(range=[qmin_tsl*0.95,qmax_tsl*1.05],**crosshair_yaxis(),secondary_y=False,row=row_i,col=1)
                    if choice == "슬로프통합":
                        fig_top_sl.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True, row=row_i, col=1)
                    else:
                        fig_top_sl.update_yaxes(range=[-180,250],tick0=-180,dtick=30,**crosshair_yaxis(),secondary_y=True,row=row_i,col=1)
                
                if initial_x_tsl:
                    fig_top_sl.update_xaxes(range=initial_x_tsl, type='category', **crosshair_xaxis())
                else:
                    fig_top_sl.update_xaxes(type='category', **crosshair_xaxis())
                fig_top_sl.update_annotations(font_size=10)
                
                st.plotly_chart(fig_top_sl, width='stretch', config=COMMON_CONFIG, key="top_tab_slope_chart")
            
            # 슬로프합 고점 검증결과 표
            slope_top_conditions = {
                "**10일합 상한돌파**": ((df['슬로프10일합'] >= 29) & _nb, "슬로프10일합 ≥ 29"),
                "**20일합 상한돌파**": ((df['슬로프20일합'] >= 39) & _nb, "슬로프20일합 ≥ 39"),
                "**30일합 상한돌파**": ((df['슬로프30일합'] >= 46) & _nb, "슬로프30일합 ≥ 46"),
                "**40일합 상한돌파**": ((df['슬로프40일합'] >= 59) & _nb, "슬로프40일합 ≥ 59"),
                "**50일합 상한돌파**": ((df['슬로프50일합'] >= 75) & _nb, "슬로프50일합 ≥ 75"),
                "**60일합 상한돌파**": ((df['슬로프60일합'] >= 93) & _nb, "슬로프60일합 ≥ 93"),
                "**70일합 상한돌파**": ((df['슬로프70일합'] >= 109) & _nb, "슬로프70일합 ≥ 109"),
                "**슬로프합 고점 종합**": (
                    ((df['슬로프10일합'] >= 29) | (df['슬로프20일합'] >= 39) | (df['슬로프30일합'] >= 46) | (df['슬로프40일합'] >= 59) | (df['슬로프50일합'] >= 75) | (df['슬로프60일합'] >= 93) | (df['슬로프70일합'] >= 109)) & _nb,
                    "1개 이상 상한선 돌파 (저점일 제외)"
                )
            }
            stats_top_sl = calculate_top_stats(df, 'QQQ', slope_top_conditions)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_top_stats_table(stats_top_sl, "고점 지표검증결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
            
            slope_multi_conditions_us = {
                "**빨간색 (1개 감지)**": (df['slope_detect_count'] >= 1, "동시 감지 1개"),
                "**주황색 (2개 감지)**": (df['slope_detect_count'] >= 2, "동시 감지 2개"),
                "**노란색 (3개 감지)**": (df['slope_detect_count'] >= 3, "동시 감지 3개"),
                "**초록색 (4개 감지)**": (df['slope_detect_count'] >= 4, "동시 감지 4개"),
                "**파란색 (5개 감지)**": (df['slope_detect_count'] >= 5, "동시 감지 5개"),
                "**남색 (6개 감지)**":   (df['slope_detect_count'] >= 6, "동시 감지 6개"),
                "**보라색 (7개 감지)**": (df['slope_detect_count'] >= 7, "동시 감지 7개"),
            }
            stats_top_sl_multi = calculate_top_stats(df, 'QQQ', slope_multi_conditions_us)
            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
            render_slope_multi_stats_table(stats_top_sl_multi, "📊 슬로프합 최종본 다중 감지 검증 결과")
        
        # ── 소분류 3: 다중지표 고점 ──
        with top_sub_tabs[2]:
            _nb_top = _not_bottom.reindex(df_top.index).fillna(True)
            
            # QQQ_RU 백분위 추가 (저점 DD_Pct 대칭용)
            df_top['RU_Pct'] = df_top['QQQ_RU'].rolling(252, min_periods=60).rank(pct=True)
            
            factor = 0.58
            
            # 49개 고점 후보 조건들 (저점 49개 조건과 1:1 완벽히 매칭 및 반전된 조건식)
            top_multi_conditions_list = [
                # 지표개발 반전 19개
                (df_top['QQQ_%B'] * (df_top['HYG_RSI'] / 100) >= 0.75 * factor) & _nb_top,
                ((100 - df_top['FearGreedIndex']) * np.exp(-df_top['TNX_ROC'] * 2) / (df_top['VIX'] + 1e-10) >= 6.0 * factor) & _nb_top,
                (((df_top['FearGreedIndex'] - 50) / 20 + (df_top['QQQ_RSI'] - 50) / 15 + (df_top['QQQ_%B'] - 0.5) / 0.25 - df_top['VIX_Z']) >= 4.0 * factor) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.99 * factor) & (df_top['FearGreedIndex'] >= 94 * factor) & (df_top['VIX'] <= 12 / factor)) & _nb_top,
                ((df_top['QQQ_%B'] >= 1.05 * factor) & (df_top['FearGreedIndex'] >= 93 * factor)) & _nb_top,
                ((df_top['슬로프10일합'] >= 40 * factor) & (df_top['VIX'] <= 12 / factor) & (df_top['FearGreedIndex'] >= 91 * factor)) & _nb_top,
                ((df_top['슬로프40일합'] >= 70 * factor) & (df_top['FearGreedIndex'] >= 92 * factor) & (df_top['QQQ_%B'] >= 0.98 * factor)) & _nb_top,
                ((df_top['HYG_RSI'] >= 82 * factor) & (df_top['VIX'] <= 11 / factor)) & _nb_top,
                ((df_top['FearGreedIndex'] >= 92 * factor) & (df_top['VIX'] <= 13 / factor) & (df_top['HYG_RSI'] >= 78 * factor)) & _nb_top,
                ((df_top['슬로프5일합'] >= 35 * factor) & (df_top['QQQ_RSI'] >= 78 * factor) & (df_top['VIX'] <= 13 / factor)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 85 * factor) & (df_top['FearGreedIndex'] >= 85 * factor)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 82 * factor) & (df_top['FearGreedIndex'] >= 88 * factor)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 80 * factor) & (df_top['FearGreedIndex'] >= 88 * factor)) & _nb_top,
                ((df_top['QQQ_RSI7'] >= 78 * factor) & (df_top['FearGreedIndex'] >= 88 * factor)) & _nb_top,
                ((df_top['VVIX_Z'] <= -2.5 * factor) & (df_top['FearGreedIndex'] >= 85 * factor)) & _nb_top,
                ((df_top['VVIX_Z'] <= -2.0 * factor) & (df_top['FearGreedIndex'] >= 80 * factor)) & _nb_top,
                ((df_top['VVIX_Pct'] <= 0.10 * factor) & (df_top['FearGreedIndex'] >= 90 * factor)) & _nb_top,
                ((df_top['VVIX_Pct'] <= 0.10 * factor) & (df_top['QQQ_RSI7'] >= 78 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'].diff(7) >= 20 * factor) & (df_top['VIX_Pct'] <= 0.15 * factor)) & _nb_top,
                # 적중집중 반전 10개
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 72 * factor) & (df_top['VVIX_Pct'] <= 0.30 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 60 * factor) & (df_top['VVIX_Pct'] <= 0.30 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 6.5 * factor) & (df_top['FearGreedIndex'] >= 82 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                (((1000 / (df_top['VIX'] * df_top['VVIX'] + 1e-5)) >= 1.0 * factor) & (df_top['FearGreedIndex'] >= 90 * factor) & (df_top['QQQ_RU'] >= 0.25 * factor)) & _nb_top,
                (((1000 / (df_top['VIX'] * df_top['VVIX'] + 1e-5)) >= 1.0 * factor) & (df_top['FearGreedIndex'] >= 90 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 65 * factor) & (df_top['VVIX_Pct'] <= 0.30 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 50 * factor) & (df_top['VVIX_Pct'] <= 0.30 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 72 * factor) & (df_top['VVIX_Pct'] <= 0.20 * factor)) & _nb_top,
                ((np.log(np.maximum(-df_top['VVIX_Z'] + 5.0, 1e-5)) * (1 - df_top['VIX_Pct']) >= 1.0 * factor) & (df_top['FearGreedIndex'] >= 88 * factor) & (df_top['QQQ_%B'] >= 0.85 * factor)) & _nb_top,
                (((100 - df_top['FearGreedIndex']) * np.exp(-df_top['TNX_ROC'] * 3) <= 15 / factor) & (df_top['QQQ_RSI7'] >= 72 * factor) & (df_top['VIX_Pct'] <= 0.20 * factor)) & _nb_top,
                # 균형집중 반전 10개
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 5.5 * factor) & (df_top['FearGreedIndex'] >= 70 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 4.5 * factor) & (df_top['FearGreedIndex'] >= 78 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.90 * factor) & (df_top['QQQ_RSI7'] >= 60 * factor) & (df_top['FearGreedIndex'] >= 70 * factor) & (df_top['VIX_Pct'] <= 0.40 * factor) & (df_top['VVIX_Pct'] <= 0.50 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 3 >= 2.5 * factor) & (df_top['FGI_Pct'] >= 0.70 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 4 >= 3.0 * factor) & (df_top['FGI_Pct'] >= 0.70 * factor)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.85 * factor) & (df_top['QQQ_RSI7'] >= 65 * factor) & (df_top['FearGreedIndex'] >= 80 * factor) & (df_top['VIX_Pct'] <= 0.40 * factor) & (df_top['VVIX_Pct'] <= 0.50 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 60 * factor) & (df_top['VVIX_Pct'] <= 0.50 * factor) & (df_top['RU_Pct'] >= 0.70 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 70 * factor) & (df_top['VVIX_Pct'] <= 0.50 * factor) & (df_top['RU_Pct'] >= 0.40 * factor)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 0.8 * factor) & (df_top['FearGreedIndex'] >= 88 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 1.0 * factor) & (df_top['FearGreedIndex'] >= 88 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                # 포착집중 반전 10개
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 3.5 * factor) & (df_top['FearGreedIndex'] >= 60 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / (df_top['VVIX'] + 1e-5)) >= 4.0 * factor) & (df_top['FearGreedIndex'] >= 55 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.75 * factor) & (df_top['QQQ_RSI7'] >= 50 * factor) & (df_top['FearGreedIndex'] >= 60 * factor) & (df_top['VIX_Pct'] <= 0.60 * factor) & (df_top['VVIX_Pct'] <= 0.60 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 2 >= 2.0 * factor) & (df_top['FGI_Pct'] >= 0.65 * factor)) & _nb_top,
                ((df_top['QQQ_%B'] >= 0.80 * factor) & (df_top['QQQ_RSI7'] >= 50 * factor) & (df_top['FearGreedIndex'] >= 55 * factor) & (df_top['VIX_Pct'] <= 0.60 * factor) & (df_top['VVIX_Pct'] <= 0.60 * factor)) & _nb_top,
                (((df_top['QQQ_RSI7'] / 100) + df_top['RU_Pct'] * 2 >= 1.5 * factor) & (df_top['FGI_Pct'] >= 0.65 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 45 * factor) & (df_top['VVIX_Pct'] <= 0.70 * factor) & (df_top['RU_Pct'] >= 0.50 * factor)) & _nb_top,
                ((df_top['FearGreedIndex'] * df_top['QQQ_%B'] >= 50 * factor) & (df_top['VVIX_Pct'] <= 0.70 * factor) & (df_top['RU_Pct'] >= 0.50 * factor)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 0.3 * factor) & (df_top['FearGreedIndex'] >= 82 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
                ((df_top['VIX_Z'] * df_top['VVIX_Z'] >= 0.5 * factor) & (df_top['FearGreedIndex'] >= 82 * factor) & (df_top['QQQ_RU'] >= 0.30 * factor)) & _nb_top,
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
                ((df_top['top_multi_count'] >= 1) & (df_top['top_multi_count'] <= 7), 'rgba(220,30,30,0.3)', '#E06666', '1~7개 감지'), # 빨간색
                ((df_top['top_multi_count'] >= 8) & (df_top['top_multi_count'] <= 14), 'rgba(255,140,0,0.3)', '#FF8C00', '8~14개 감지'), # 주황색
                ((df_top['top_multi_count'] >= 15) & (df_top['top_multi_count'] <= 21), 'rgba(255,220,0,0.3)', '#FFD700', '15~21개 감지'), # 노란색
                ((df_top['top_multi_count'] >= 22) & (df_top['top_multi_count'] <= 28), 'rgba(0,128,0,0.3)', '#A9D08E', '22~28개 감지'), # 초록색
                ((df_top['top_multi_count'] >= 29) & (df_top['top_multi_count'] <= 35), 'rgba(135,206,235,0.3)', '#87CEEB', '29~35개 감지'), # 파란색
                ((df_top['top_multi_count'] >= 36) & (df_top['top_multi_count'] <= 42), 'rgba(0,0,128,0.3)', '#000080', '36~42개 감지'), # 남색
                ((df_top['top_multi_count'] >= 43) & (df_top['top_multi_count'] <= 49), 'rgba(128,0,128,0.3)', '#800080', '43~49개 감지'), # 보라색
            ]
            
            # 감지 신호표 (1개 이상 감지된 날 기준)
            df_sig_tm = df_top[df_top['top_multi_count'] >= 1].sort_index(ascending=False).head(100)
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
                    fg = "#FFF"
                    dates_row_tm.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    counts_row_tm.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{int(cnt)}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 고점 감지 신호 (최근 100개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_tm)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>갯수</th>
                        {"".join(counts_row_tm)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            fig_top_multi = make_subplots(specs=[[{"secondary_y": True}]])
            hd_top_multi = [fmt_date_kor(d) for d in df_top.index]
            
            fig_top_multi.add_trace(go.Scatter(x=hd_top_multi, y=df_top['QQQ'], name='QQQ 가격', mode='lines+markers',
                line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
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
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_top_stats_table(stats_top_multi, "지표검증결과 (2018.10 ~ 현재 QQQ 고점 대비, 저점 감지일 제외)")
        
        # ── 소분류 4: 통합지표 고점 ──
        with top_sub_tabs[3]:
            _nb_top2 = _not_bottom.reindex(df_top.index).fillna(True)
            
            # 후보1: 과열 에너지 공식 (포착률 10~15% 재조정)
            energy_top = (df_top['FearGreedIndex']/100) * df_top['QQQ_%B'] * (df_top['QQQ_RSI7']/100)
            c_top_1 = ((energy_top >= 0.73) & (df_top['VIX_Pct'] <= 0.08)) & _nb_top2

            # 후보2: RSI 다이버전스 + Rally-Up 복합 (포착률 10~15% 재조정)
            c_top_2 = ((df_top['RSI_Div']) & (df_top['QQQ_RU'] >= 0.50)) & _nb_top2

            # 후보3: MACD 전환 + %B 과매수 + VIX 안일 (포착률 10~15% 재조정)
            c_top_3 = ((df_top['MACD_Hist'].diff() < 0) & (df_top['MACD_Hist'] > 0) & (df_top['QQQ_%B'] >= 0.95) & (df_top['VIX_Pct'] <= 0.08)) & _nb_top2

            # 후보4: SKEW 급등 + VIX 저위 + RSI7 과매수 (포착률 10~15% 재조정)
            c_top_4 = ((df_top['SKEW'] >= 145) & (df_top['VIX'] <= 13) & (df_top['QQQ_RSI7'] >= 70)) & _nb_top2
            
            # 후보5: 통합 (OR)
            c_top_all = c_top_1 | c_top_2 | c_top_3 | c_top_4
            
            # 감지 신호표
            triggered_dates_top = df_top[c_top_all].index.sort_values(ascending=False)
            recent_100_top = triggered_dates_top[:100]
            if len(recent_100_top) > 0:
                dates_row_top = ""
                for dt in recent_100_top:
                    cnt = int(c_top_1.loc[dt]) + int(c_top_2.loc[dt]) + int(c_top_3.loc[dt]) + int(c_top_4.loc[dt])
                    bg = '#800080'
                    fg = '#FFF'
                    dates_row_top += f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 4대 통합 고점 감지 신호 (최근 100개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {dates_row_top}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            
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
                line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                hovertemplate='QQQ: %{y:.2f}<extra></extra>'
            ), secondary_y=False)
            
            fig_top_final.add_trace(go.Bar(
                x=hd_top_final, y=c_top_all.reindex(df_top_plot.index).astype(int).values * (qqq_yr_tt[1] if qqq_yr_tt else 600), name='통합 고점 감지 (OR)',
                marker_color='rgba(128, 0, 128, 0.3)',
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
        # ===== 저점 감지일 수집 (한국 KOSPI용 4개 탭 종합) =====
        # 공탐변동 저점
        _bottom_fgi_kr = (
            ((df_kr['FearGreedIndex'] <= 9) & (df_kr['VKOSPI'] >= 26)) |
            ((df_kr['FearGreedIndex'] >= 10) & (df_kr['FearGreedIndex'] <= 19) & (df_kr['VKOSPI'] >= 22)) |
            ((df_kr['FearGreedIndex'] >= 20) & (df_kr['FearGreedIndex'] <= 29) & (df_kr['VKOSPI'] >= 18)) |
            ((df_kr['FearGreedIndex'] >= 30) & (df_kr['FearGreedIndex'] <= 39) & (df_kr['VKOSPI'] >= 14))
        )
        # 슬로프합 저점
        _bottom_slope_kr = (
            (df_kr['슬로프10일합'] <= -15) | (df_kr['슬로프20일합'] <= -20) |
            (df_kr['슬로프30일합'] <= -25) | (df_kr['슬로프40일합'] <= -30) |
            (df_kr['슬로프50일합'] <= -35) | (df_kr['슬로프60일합'] <= -40) |
            (df_kr['슬로프70일합'] <= -45)
        )
        # 다중지표 저점
        _multi_conds_for_bottom_kr = [
            (df_kr['KOSPI_%B'] * (df_kr['HYG_RSI'] / 100) <= 0.010),
            (df_kr['FearGreedIndex'] * np.exp(df_kr['TNX_ROC'] * 2) / (df_kr['VKOSPI'] + 1e-10) <= 0.35),
            (((df_kr['FearGreedIndex'] - 50) / 20 + (df_kr['KOSPI_RSI'] - 50) / 15 + (df_kr['KOSPI_%B'] - 0.5) / 0.25 - df_kr['VKOSPI_Z']) <= -5.0),
            ((df_kr['KOSPI_%B'] <= 0.01) & (df_kr['FearGreedIndex'] <= 6) & (df_kr['VKOSPI'] >= 25)),
            ((df_kr['KOSPI_%B'] <= -0.05) & (df_kr['FearGreedIndex'] <= 7)),
        ]
        _multi_cnt_kr = sum(c.fillna(False).astype(int) for c in _multi_conds_for_bottom_kr)
        _bottom_multi_kr = _multi_cnt_kr >= 1
        
        # 실제 KOSPI 차트상 저점 산출
        _rolling_max_kr = df_kr['KOSPI'].rolling(252, min_periods=1).max()
        _drawdown_kr = (_rolling_max_kr - df_kr['KOSPI']) / _rolling_max_kr
        _local_min_kr = df_kr['KOSPI'].rolling(41, center=True, min_periods=1).min()
        is_actual_bottom_kr = (df_kr['KOSPI'] <= _local_min_kr * 1.03) & (_drawdown_kr >= 0.05)
        
        is_any_bottom_kr = (_bottom_fgi_kr | _bottom_slope_kr | _bottom_multi_kr | is_actual_bottom_kr).reindex(df_kr.index).fillna(False)
        
        # ===== 고점지표용 보조지표 전처리 (한국 KOSPI용) =====
        df_top_kr = df_kr.copy()
        
        df_top_kr['KOSPI_Low252'] = df_top_kr['KOSPI'].rolling(252, min_periods=1).min()
        df_top_kr['KOSPI_RU'] = (df_top_kr['KOSPI'] - df_top_kr['KOSPI_Low252']) / (df_top_kr['KOSPI_Low252'] + 1e-10)
        
        df_top_kr['KOSPI_20H'] = df_top_kr['KOSPI'].rolling(20).max()
        df_top_kr['RSI7_20H_kr'] = df_top_kr['KOSPI_RSI7'].rolling(20).max()
        df_top_kr['RSI_Div'] = (df_top_kr['KOSPI'] >= df_top_kr['KOSPI_20H'] * 0.99) & (df_top_kr['KOSPI_RSI7'] < df_top_kr['RSI7_20H_kr'] - 5)
        
        _ema12_kr = df_top_kr['KOSPI'].ewm(span=12, adjust=False).mean()
        _ema26_kr = df_top_kr['KOSPI'].ewm(span=26, adjust=False).mean()
        df_top_kr['MACD'] = _ema12_kr - _ema26_kr
        df_top_kr['MACD_Signal'] = df_top_kr['MACD'].ewm(span=9, adjust=False).mean()
        df_top_kr['MACD_Hist'] = df_top_kr['MACD'] - df_top_kr['MACD_Signal']
        
        df_top_kr['KOSPI_MA20'] = df_top_kr['KOSPI'].rolling(20).mean()
        df_top_kr['KOSPI_MA50'] = df_top_kr['KOSPI'].rolling(50).mean()
        df_top_kr['MA20_Dev'] = (df_top_kr['KOSPI'] - df_top_kr['KOSPI_MA20']) / (df_top_kr['KOSPI_MA20'] + 1e-10) * 100
        df_top_kr['MA50_Dev'] = (df_top_kr['KOSPI'] - df_top_kr['KOSPI_MA50']) / (df_top_kr['KOSPI_MA50'] + 1e-10) * 100
        
        df_top_kr['KOSPI_Vel'] = df_top_kr['KOSPI'].pct_change(5)
        df_top_kr['KOSPI_Accel'] = df_top_kr['KOSPI_Vel'].diff(3)
        df_top_kr['RU_Pct'] = df_top_kr['KOSPI_RU'].rolling(252, min_periods=60).rank(pct=True)
        
        _not_bottom_kr = ~is_any_bottom_kr.reindex(df_top_kr.index).fillna(False)
        
        # ===== 소분류 탭 구성 =====
        top_sub_tabs_kr = st.tabs(['공탐변동', '슬로프합', '다중지표', '통합지표'])
        
        # ── 소분류 1: 공탐변동 고점 ──
        with top_sub_tabs_kr[0]:
            five_years_ago_top_kr = pd.to_datetime(datetime.date.today() - datetime.timedelta(days=5*365))
            df_top1_kr = df_top_kr[df_top_kr.index >= five_years_ago_top_kr].copy()
            
            # 한국형 공탐/변동성 고점 조건
            color_cond_map_top_kr = [
                (((df_top1_kr['FearGreedIndex']>=90)&(df_top1_kr['VKOSPI']<=14)) & _not_bottom_kr, '#595959', '#FFFFFF', 'rgba(0,0,0,0.3)'),
                (((df_top1_kr['FearGreedIndex']>=80)&(df_top1_kr['FearGreedIndex']<=89)&(df_top1_kr['VKOSPI']>=13)&(df_top1_kr['VKOSPI']<=16)) & _not_bottom_kr, '#E06666', '#FFFFFF', 'rgba(220,30,30,0.3)'),
                (((df_top1_kr['FearGreedIndex']>=70)&(df_top1_kr['FearGreedIndex']<=79)&(df_top1_kr['VKOSPI']>=15)&(df_top1_kr['VKOSPI']<=18)) & _not_bottom_kr, '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
                (((df_top1_kr['FearGreedIndex']>=60)&(df_top1_kr['FearGreedIndex']<=69)&(df_top1_kr['VKOSPI']>=17)&(df_top1_kr['VKOSPI']<=20)) & _not_bottom_kr, '#A9D08E', '#000000', 'rgba(0,128,0,0.3)'),
            ]
            
            date_color_map_top_kr = {}
            for cond, bg, fg, _ in reversed(color_cond_map_top_kr):
                for d in df_top1_kr[cond].index:
                    date_color_map_top_kr[d] = (bg, fg)
            all_detected_sorted_top_kr = sorted(date_color_map_top_kr.keys(), reverse=True)[:100]
            
            TH_SIG = "border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;"
            TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
            
            date_cells_top_kr = "".join([f"<td style='background:{date_color_map_top_kr[d][0]};color:{date_color_map_top_kr[d][1]};font-weight:bold;{TD_SIG}'>{fmt_date_kor(d)}</td>" for d in all_detected_sorted_top_kr]) if all_detected_sorted_top_kr else ""
            vix_cells_top_kr = "".join([f"<td style='background:{date_color_map_top_kr[d][0]};color:{date_color_map_top_kr[d][1]};font-weight:bold;{TD_SIG}'>{df_top1_kr.loc[d, 'VKOSPI']:.2f}</td>" for d in all_detected_sorted_top_kr]) if all_detected_sorted_top_kr else ""
            fgi_cells_top_kr = "".join([f"<td style='background:{date_color_map_top_kr[d][0]};color:{date_color_map_top_kr[d][1]};font-weight:bold;{TD_SIG}'>{df_top1_kr.loc[d, 'FearGreedIndex']:.1f}</td>" for d in all_detected_sorted_top_kr]) if all_detected_sorted_top_kr else ""
            fv5_cells_top_kr = "".join([f"<td style='background:{date_color_map_top_kr[d][0]};color:{date_color_map_top_kr[d][1]};font-weight:bold;{TD_SIG}'>{df_top1_kr.loc[d, '(FGI-VIX)/5']:.2f}</td>" for d in all_detected_sorted_top_kr]) if all_detected_sorted_top_kr else ""
            
            st.markdown(
                f"<div style='margin-bottom:0.2rem;'>"
                f"<span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 100개, 저점일 제외)</span>"
                f"<div style='overflow-x:auto;margin-top:3px;'>"
                f"<table style='border-collapse:collapse;font-size:0.55rem;text-align:center;'>"
                f"<tbody>"
                f"<tr><th style='{TH_SIG}'>날짜</th>{date_cells_top_kr}</tr>"
                f"<tr><th style='{TH_SIG}'>VKOSPI</th>{vix_cells_top_kr}</tr>"
                f"<tr><th style='{TH_SIG}'>FGI</th>{fgi_cells_top_kr}</tr>"
                f"<tr><th style='{TH_SIG}'>FV5</th>{fv5_cells_top_kr}</tr>"
                f"</tbody>"
                f"</table>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True
            )
            
            fig_kr_top = make_subplots(specs=[[{"secondary_y": True}]])
            hd1_kr_top = [fmt_date_kor(d) for d in df_top1_kr.index]
            
            fig_kr_top.add_trace(go.Scatter(x=hd1_kr_top, y=df_top1_kr['KOSPI'], name='KOSPI 가격', mode='lines+markers', line=dict(color='rgba(0, 0, 0, 0.5)', width=2), marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)), hovertemplate='KOSPI: %{y:.2f}<extra></extra>'), secondary_y=False)
            fig_kr_top.add_trace(go.Scatter(x=hd1_kr_top, y=df_top1_kr['VKOSPI'], name='VKOSPI', line=dict(color='rgba(255, 0, 0, 0.8)', width=1), hovertemplate='VKOSPI: %{y:.2f}<extra></extra>'), secondary_y=True)
            fig_kr_top.add_trace(go.Scatter(x=hd1_kr_top, y=df_top1_kr['FearGreedIndex'], name='FGI', line=dict(color='rgba(255, 255, 0, 0.8)', width=1), hovertemplate='FGI: %{y:.1f}<extra></extra>'), secondary_y=True)
            fig_kr_top.add_trace(go.Scatter(x=hd1_kr_top, y=df_top1_kr['(FGI-VIX)/5'], name='(FGI-VKOSPI)/5', line=dict(color='rgba(0, 128, 0, 0.8)', width=1), hovertemplate='(FGI-VKOSPI)/5: %{y:.2f}<extra></extra>'), secondary_y=True)
            
            max_kospi_top_kr = float(df_top1_kr['KOSPI'].max()) * 1.2
            for cond, _bg, _fg, fc in color_cond_map_top_kr:
                fig_kr_top.add_trace(go.Bar(x=hd1_kr_top, y=cond.astype(int) * max_kospi_top_kr, marker_color=fc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
                
            if active_period_days:
                target_date_kr = datetime.date.today() - datetime.timedelta(days=active_period_days)
                detected_indices_kr = [i for i, d in enumerate(df_top1_kr.index) if d >= pd.to_datetime(target_date_kr)]
                initial_x_range_kr = [detected_indices_kr[0], len(hd1_kr_top) - 1] if detected_indices_kr else None
                if detected_indices_kr:
                    kospi_1y = df_top1_kr['KOSPI'].iloc[detected_indices_kr[0]:]
                    k_min, k_max = float(kospi_1y.min()), float(kospi_1y.max())
                    kospi_y_range = [k_min * 0.95, k_max * 1.05]
                else:
                    kospi_y_range = [float(df_top1_kr['KOSPI'].min()) * 0.95, float(df_top1_kr['KOSPI'].max()) * 1.05]
            else:
                initial_x_range_kr = None
                k_min, k_max = float(df_top1_kr['KOSPI'].min()), float(df_top1_kr['KOSPI'].max())
                kospi_y_range = [k_min * 0.95, k_max * 1.05]
                
            fig_kr_top.update_layout(**COMMON_LAYOUT, height=320, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
            if initial_x_range_kr:
                fig_kr_top.update_xaxes(range=initial_x_range_kr, type='category', **crosshair_xaxis())
            else:
                fig_kr_top.update_xaxes(type='category', **crosshair_xaxis())
            fig_kr_top.update_yaxes(range=kospi_y_range, **crosshair_yaxis(), secondary_y=False, title_text="")
            fig_kr_top.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
            
            st.plotly_chart(fig_kr_top, width='stretch', config=COMMON_CONFIG, key="tab4_kr_top_chart")
            
            fgi_conditions_kr_top = {
                "**검정색 (극강 과열)**": (color_cond_map_top_kr[0][0], "FGI>=90 & VKOSPI<=14"),
                "**빨간색 (강력 과열)**": (color_cond_map_top_kr[1][0], "FGI 80~89 & VKOSPI 13~16"),
                "**노란색 (주의 과열)**": (color_cond_map_top_kr[2][0], "FGI 70~79 & VKOSPI 15~18"),
                "**초록색 (초기 과열)**": (color_cond_map_top_kr[3][0], "FGI 60~69 & VKOSPI 17~20"),
            }
            stats_kr_top = calculate_top_stats(df_top1_kr, 'KOSPI', fgi_conditions_kr_top)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_top_stats_table(stats_kr_top, "지표검증결과 (2018.01 ~ 현재 KOSPI 고점 대비, 저점 감지일 제외)")
            
        # ── 소분류 2: 슬로프합 고점 ──
        with top_sub_tabs_kr[1]:
            SLOPE_TOP_CHARTS_KR = [
                (2, 10, '슬로프10일합', 384),
                (3, 20, '슬로프20일합', 702),
                (4, 30, '슬로프30일합', 1069),
                (5, 40, '슬로프40일합', 1754),
                (6, 50, '슬로프50일합', 2078),
                (7, 60, '슬로프60일합', 2574),
                (8, 70, '슬로프70일합', 2959),
            ]
            
            slope_detect_count_top_kr = sum(((df_top_kr[sfc] >= thresh)).astype(int) for _, _, sfc, thresh in SLOPE_TOP_CHARTS_KR)
            df_top_kr['slope_detect_count_top'] = slope_detect_count_top_kr
            
            all_top_sl_kr_top = []
            for _, days_t, sfc, thresh in SLOPE_TOP_CHARTS_KR:
                _cond_sl = (df_top_kr[sfc] >= thresh) & _not_bottom_kr
                all_top_sl_kr_top.extend(df_top_kr[_cond_sl].index.tolist())
            dc_top_sl_kr_top = Counter(all_top_sl_kr_top)
            parent_dates_sl_kr_top = sorted(list(set(all_top_sl_kr_top)), reverse=True)
            
            if parent_dates_sl_kr_top:
                r100_sl_kr_top = parent_dates_sl_kr_top[:100]
                dates_row_sl_kr_top = []
                counts_row_sl_kr_top = []
                for dt in r100_sl_kr_top:
                    cnt = dc_top_sl_kr_top.get(dt, 1)
                    bg = "#E06666" if cnt==1 else "#FF8C00" if cnt==2 else '#FFD700' if cnt==3 else "#A9D08E" if cnt==4 else "#87CEEB" if cnt==5 else "#000080" if cnt==6 else "#800080"
                    fg = "#FFF"
                    dates_row_sl_kr_top.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    
                    detected_items = []
                    for _, days, sc_col, th in SLOPE_TOP_CHARTS_KR:
                        if dt in df_top_kr.index and df_top_kr.loc[dt, sc_col] >= th:
                            val_diff_pct = (df_top_kr.loc[dt, sc_col] - th) / abs(th)
                            if 0.0 <= val_diff_pct <= 0.40:
                                color = '#A9D08E'
                            elif 0.40 < val_diff_pct <= 0.60:
                                color = '#FFD700'
                            elif 0.60 < val_diff_pct <= 0.80:
                                color = '#E06666'
                            else:
                                color = '#595959'
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    
                    val_str = "<br>".join(detected_items)
                    counts_row_sl_kr_top.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 100개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_sl_kr_top)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>이탈</th>
                        {"".join(counts_row_sl_kr_top)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
                
            hd_df_kr_top = [fmt_date_kor(d) for d in df_top_kr.index]
            
            bottom_slope_options_kr_top = ["슬로프통합", "10일합", "20일합", "30일합", "40일합", "50일합", "60일합", "70일합"]
            selected_bottom_slopes_kr_top = st.multiselect("📊 표시할 슬로프 차트 선택 (다중 선택 가능)", bottom_slope_options_kr_top, default=["슬로프통합"], key="bottom_slope_multiselect_kr_top")
            
            if not selected_bottom_slopes_kr_top:
                st.info("시각화할 슬로프 지표를 다중 선택창에서 선택해 주세요.")
            else:
                num_charts_kr_top = len(selected_bottom_slopes_kr_top)
                fig_dsi_kr_top = make_subplots(rows=num_charts_kr_top, cols=1, shared_xaxes=True, vertical_spacing=0.03 if num_charts_kr_top > 1 else 0.0,
                    subplot_titles=tuple(selected_bottom_slopes_kr_top),
                    specs=[[{"secondary_y": True}]]*num_charts_kr_top)
                
                chart_info_map_kr_top = {
                    10: ('슬로프10일합', 384),
                    20: ('슬로프20일합', 702),
                    30: ('슬로프30일합', 1069),
                    40: ('슬로프40일합', 1754),
                    50: ('슬로프50일합', 2078),
                    60: ('슬로프60일합', 2574),
                    70: ('슬로프70일합', 2959),
                }
                
                for idx, choice in enumerate(selected_bottom_slopes_kr_top):
                    row_i = idx + 1
                    sf = (idx == 0)
                    
                    if choice == "슬로프통합":
                        fig_dsi_kr_top.add_trace(go.Scatter(x=hd_df_kr_top,y=df_top_kr['KOSPI'],name='KOSPI 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=False,legendgroup='kospi',hovertemplate='KOSPI: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        
                        detect_colors = {
                            1: 'rgba(224, 102, 102, 0.45)',
                            2: 'rgba(255, 140, 0, 0.3)',
                            3: 'rgba(255, 255, 153, 0.45)',
                            4: 'rgba(0, 128, 0, 0.3)',
                            5: 'rgba(135, 206, 235, 0.3)',
                            6: 'rgba(0, 0, 128, 0.3)',
                            7: 'rgba(128, 0, 128, 0.3)'
                        }
                        for cnt_val, bar_color in detect_colors.items():
                            cond_bar = (df_top_kr['slope_detect_count_top'] == cnt_val) & _not_bottom_kr
                            fig_dsi_kr_top.add_trace(go.Bar(x=hd_df_kr_top, y=cond_bar.astype(int).values * float(df_top_kr['KOSPI'].max()) * 1.2, marker_color=bar_color, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'), row=row_i, col=1, secondary_y=False)
                            
                    else:
                        days = int(choice.replace("일합", ""))
                        sc, thresh = chart_info_map_kr_top[days]
                        
                        fig_dsi_kr_top.add_trace(go.Scatter(x=hd_df_kr_top,y=df_top_kr['KOSPI'],name='KOSPI 가격',mode='lines+markers',line=dict(color='rgba(0, 0, 0, 0.5)', width=2),marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),showlegend=sf,legendgroup='kospi',hovertemplate='KOSPI: %{y:.2f}<extra></extra>'),row=row_i,col=1,secondary_y=False)
                        fig_dsi_kr_top.add_trace(go.Scatter(x=hd_df_kr_top,y=df_top_kr[sc],name=f'슬로프 {days}일합계',line=dict(color='rgba(255, 0, 0, 0.8)', width=1),showlegend=True,hovertemplate=f'슬로프{days}일합: %{{y:.1f}}<extra></extra>'),row=row_i,col=1,secondary_y=True)
                        fig_dsi_kr_top.add_trace(go.Scatter(x=hd_df_kr_top,y=[-thresh]*len(hd_df_kr_top),name='하한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='lower_kr',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        fig_dsi_kr_top.add_trace(go.Scatter(x=hd_df_kr_top,y=[thresh]*len(hd_df_kr_top),name='상한선',line=dict(color='gray', width=1, dash='dash'),showlegend=sf,legendgroup='lower_kr',hoverinfo='skip'),row=row_i,col=1,secondary_y=True)
                        
                        diff_pct = (df_top_kr[sc] - thresh) / abs(thresh)
                        bottom_cond_vals = [
                            (((diff_pct >= 0.0) & (diff_pct <= 0.40) & _not_bottom_kr), 'rgba(0, 128, 0, 0.3)'),
                            (((diff_pct > 0.40) & (diff_pct <= 0.60) & _not_bottom_kr), 'rgba(255, 220, 0, 0.3)'),
                            (((diff_pct > 0.60) & (diff_pct <= 0.80) & _not_bottom_kr), 'rgba(220, 30, 30, 0.3)'),
                            (((diff_pct > 0.80) & _not_bottom_kr), 'rgba(0, 0, 0, 0.3)'),
                        ]
                        for tc, tfc in bottom_cond_vals:
                            fig_dsi_kr_top.add_trace(go.Bar(x=hd_df_kr_top, y=tc.astype(int).values * float(df_top_kr['KOSPI'].max()) * 1.2, marker_color=tfc, showlegend=False, hoverinfo='skip', marker_line_width=0.5, marker_line_color='white'),row=row_i,col=1,secondary_y=False)
                
                if active_period_days:
                    target_date_dsi_kr = datetime.date.today() - datetime.timedelta(days=active_period_days)
                    detected_indices_dsi_kr = [i for i, d in enumerate(df_top_kr.index) if d >= pd.to_datetime(target_date_dsi_kr)]
                    initial_x_range_dsi_kr = [detected_indices_dsi_kr[0], len(hd_df_kr_top) - 1] if detected_indices_dsi_kr else None
                    if detected_indices_dsi_kr:
                        kospi_1y_dsi = df_top_kr['KOSPI'].iloc[detected_indices_dsi_kr[0]:]
                        kmin_dsi, kmax_dsi = float(kospi_1y_dsi.min()), float(kospi_1y_dsi.max())
                    else:
                        kmin_dsi, kmax_dsi = float(df_top_kr['KOSPI'].min()), float(df_top_kr['KOSPI'].max())
                else:
                    initial_x_range_dsi_kr = None
                    kmin_dsi, kmax_dsi = float(df_top_kr['KOSPI'].min()), float(df_top_kr['KOSPI'].max())
                
                chart_height_kr = max(400, num_charts_kr_top * 300)
                layout_params_kr = COMMON_LAYOUT.copy()
                layout_params_kr.pop('shapes', None)
                
                shapes_kr = []
                for idx in range(num_charts_kr_top):
                    y_ref = 'y domain' if idx == 0 else f'y{2*idx + 1} domain'
                    shapes_kr.append(dict(type='rect', xref='paper', yref=y_ref, x0=0, y0=0, x1=1, y1=1, line=dict(color='rgba(150, 150, 150, 0.4)', width=1.5)))
                    
                fig_dsi_kr_top.update_layout(**layout_params_kr, height=chart_height_kr, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0, shapes=shapes_kr)
                
                for idx, choice in enumerate(selected_bottom_slopes_kr_top):
                    row_i = idx + 1
                    fig_dsi_kr_top.update_yaxes(range=[kmin_dsi*0.95,kmax_dsi*1.05],**crosshair_yaxis(),secondary_y=False,row=row_i,col=1)
                    if choice == '슬로프통합':
                        fig_dsi_kr_top.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True, row=row_i, col=1)
                    else:
                        fig_dsi_kr_top.update_yaxes(range=[-120,180],tick0=-120,dtick=20,**crosshair_yaxis(),secondary_y=True,row=row_i,col=1)
                
                if initial_x_range_dsi_kr:
                    fig_dsi_kr_top.update_xaxes(range=initial_x_range_dsi_kr, type='category', **crosshair_xaxis())
                else:
                    fig_dsi_kr_top.update_xaxes(type='category', **crosshair_xaxis())
                fig_dsi_kr_top.update_annotations(font_size=10)
                
                st.plotly_chart(fig_dsi_kr_top, width='stretch', config=COMMON_CONFIG, key='tab4_kr_slope_chart_top')
                
            slope_conditions_kr_top = {
                '**10일합 이탈**': (df_top_kr['슬로프10일합'] >= 384, '10일슬로프합 >= 384'),
                '**20일합 이탈**': (df_top_kr['슬로프20일합'] >= 702, '20일슬로프합 >= 702'),
                '**30일합 이탈**': (df_top_kr['슬로프30일합'] >= 1069, '30일슬로프합 >= 1069'),
                '**40일합 이탈**': (df_top_kr['슬로프40일합'] >= 1754, '40일슬로프합 >= 1754'),
                '**50일합 이탈**': (df_top_kr['슬로프50일합'] >= 2078, '50일슬로프합 >= 2078'),
                '**60일합 이탈**': (df_top_kr['슬로프60일합'] >= 2574, '60일슬로프합 >= 2574'),
                '**70일합 이탈**': (df_top_kr['슬로프70일합'] >= 2959, '70일슬로프합 >= 2959'),
                '**슬로프합 종합 감지**': (
                    ((df_top_kr['슬로프10일합'] >= 384) | (df_top_kr['슬로프20일합'] >= 702) | (df_top_kr['슬로프30일합'] >= 1069) | 
                     (df_top_kr['슬로프40일합'] >= 1754) | (df_top_kr['슬로프50일합'] >= 2078) | (df_top_kr['슬로프60일합'] >= 2574) | (df_top_kr['슬로프70일합'] >= 2959)) & _not_bottom_kr,
                    '1개 이상 지표 이탈'
                ),
                '**슬로프합 강력 이탈**': (
                    (((df_top_kr['슬로프10일합'] >= 384).astype(int) + 
                      (df_top_kr['슬로프20일합'] >= 702).astype(int) + 
                      (df_top_kr['슬로프30일합'] >= 1069).astype(int) + 
                      (df_top_kr['슬로프40일합'] >= 1754).astype(int) + 
                      (df_top_kr['슬로프50일합'] >= 2078).astype(int) + 
                      (df_top_kr['슬로프60일합'] >= 2574).astype(int) + 
                      (df_top_kr['슬로프70일합'] >= 2959).astype(int)) >= 4) & _not_bottom_kr,
                    '4개 이상 지표 동시 이탈'
                )
            }
            df_kr_past = df_top_kr[df_top_kr.index < pd.to_datetime(datetime.date.today())]
            stats_slope_kr_top = calculate_top_stats(df_kr_past, 'KOSPI', slope_conditions_kr_top)
            st.markdown('<br>', unsafe_allow_html=True)
            render_top_stats_table(stats_slope_kr_top, '지표검증결과 (2018.01 ~ 현재 KOSPI 고점 대비, 저점 감지일 제외 - 당일 제외)')
            
            df_kr_past = df_top_kr[df_top_kr.index < pd.to_datetime(datetime.date.today())]
            slope_multi_conditions_kr = {
                "**빨간색 (1개 감지)**": (df_kr_past['slope_detect_count_top'] >= 1, "동시 감지 1개"),
                "**주황색 (2개 감지)**": (df_kr_past['slope_detect_count_top'] >= 2, "동시 감지 2개"),
                "**노란색 (3개 감지)**": (df_kr_past['slope_detect_count_top'] >= 3, "동시 감지 3개"),
                "**초록색 (4개 감지)**": (df_kr_past['slope_detect_count_top'] >= 4, "동시 감지 4개"),
                "**파란색 (5개 감지)**": (df_kr_past['slope_detect_count_top'] >= 5, "동시 감지 5개"),
                "**남색 (6개 감지)**":   (df_kr_past['slope_detect_count_top'] >= 6, "동시 감지 6개"),
                "**보라색 (7개 감지)**": (df_kr_past['slope_detect_count_top'] >= 7, "동시 감지 7개"),
            }
            stats_top_sl_multi_kr = calculate_top_stats(df_kr_past, 'KOSPI', slope_multi_conditions_kr)
            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
            render_slope_multi_stats_table(stats_top_sl_multi_kr, "📊 슬로프합 최종본 다중 감지 검증 결과 (당일 제외)")
            
        # ── 소분류 3: 다중지표 고점 ──
        with top_sub_tabs_kr[2]:
            top_multi_conditions_list_kr = [
                # 지표개발 반전 19개
                ((df_top_kr['KOSPI_%B'] * (df_top_kr['HYG_RSI'] / 100) >= 0.85 * 1.30) & (df_top_kr['VKOSPI'] <= 14 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * np.exp(-df_top_kr['TNX_ROC'] * 2) >= 70 * 1.30) & (df_top_kr['VKOSPI'] <= 14 / 1.30)) & _not_bottom_kr,
                (((df_top_kr['FearGreedIndex'] - 50) / 20 + (df_top_kr['KOSPI_RSI'] - 50) / 15 + (df_top_kr['KOSPI_%B'] - 0.5) / 0.25 - df_top_kr['VKOSPI_Z']) >= 4.0 * 1.30) & _not_bottom_kr,
                ((df_top_kr['KOSPI_%B'] >= 0.95 * 1.30) & (df_top_kr['FearGreedIndex'] >= 85 * 1.30) & (df_top_kr['VKOSPI'] <= 13 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_%B'] >= 0.98 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['슬로프10일합'] >= 40 * 1.30) & (df_top_kr['VKOSPI'] <= 13 / 1.30) & (df_top_kr['FearGreedIndex'] >= 80 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['슬로프40일합'] >= 70 * 1.30) & (df_top_kr['FearGreedIndex'] >= 82 * 1.30) & (df_top_kr['KOSPI_%B'] >= 0.90 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['HYG_RSI'] >= 82 * 1.30) & (df_top_kr['VKOSPI'] <= 13 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] >= 88 * 1.30) & (df_top_kr['VKOSPI'] <= 14 / 1.30) & (df_top_kr['HYG_RSI'] >= 78 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['슬로프5일합'] >= 35 * 1.30) & (df_top_kr['KOSPI_RSI'] >= 78 * 1.30) & (df_top_kr['VKOSPI'] <= 13 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_RSI7'] >= 85 * 1.30) & (df_top_kr['FearGreedIndex'] >= 82 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_RSI7'] >= 82 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_RSI7'] >= 80 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_RSI7'] >= 78 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VVIX_Z'] <= -2.5 / 1.30) & (df_top_kr['FearGreedIndex'] >= 85 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VVIX_Z'] <= -2.0 / 1.30) & (df_top_kr['FearGreedIndex'] >= 80 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VVIX_Pct'] <= 0.10 / 1.30) & (df_top_kr['FearGreedIndex'] >= 90 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VVIX_Pct'] <= 0.10 / 1.30) & (df_top_kr['KOSPI_RSI7'] >= 78 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'].diff(7) >= 20 * 1.30) & (df_top_kr['VKOSPI_Pct'] <= 0.15 / 1.30)) & _not_bottom_kr,
                # 적중집중 반전 10개
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 72 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.30 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 60 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.30 / 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 6.5 * 1.30) & (df_top_kr['FearGreedIndex'] >= 82 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                (((1000 / (df_top_kr['VKOSPI'] * df_top_kr['VVIX'] + 1e-5)) >= 1.0 * 1.30) & (df_top_kr['FearGreedIndex'] >= 90 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.25 * 1.30)) & _not_bottom_kr,
                (((1000 / (df_top_kr['VKOSPI'] * df_top_kr['VVIX'] + 1e-5)) >= 1.0 * 1.30) & (df_top_kr['FearGreedIndex'] >= 90 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 65 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.30 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 50 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.30 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 72 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.20 / 1.30)) & _not_bottom_kr,
                ((np.log(np.maximum(-df_top_kr['VVIX_Z'] + 5.0, 1e-5)) * (1 - df_top_kr['VKOSPI_Pct']) >= 1.0 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30) & (df_top_kr['KOSPI_%B'] >= 0.85 * 1.30)) & _not_bottom_kr,
                (((100 - df_top_kr['FearGreedIndex']) * np.exp(-df_top_kr['TNX_ROC'] * 3) <= 15 / 1.30) & (df_top_kr['KOSPI_RSI7'] >= 72 * 1.30) & (df_top_kr['VKOSPI_Pct'] <= 0.20 / 1.30)) & _not_bottom_kr,
                # 균형집중 반전 10개
                (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 5.5 * 1.30) & (df_top_kr['FearGreedIndex'] >= 70 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 4.5 * 1.30) & (df_top_kr['FearGreedIndex'] >= 78 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_%B'] >= 0.90 * 1.30) & (df_top_kr['KOSPI_RSI7'] >= 60 * 1.30) & (df_top_kr['FearGreedIndex'] >= 70 * 1.30) & (df_top_kr['VKOSPI_Pct'] <= 0.40 / 1.30) & (df_top_kr['VVIX_Pct'] <= 0.50 / 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 3 >= 2.5 * 1.30) & (df_top_kr['FGI_Pct'] >= 0.70 * 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 4 >= 3.0 * 1.30) & (df_top_kr['FGI_Pct'] >= 0.70 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_%B'] >= 0.85 * 1.30) & (df_top_kr['KOSPI_RSI7'] >= 65 * 1.30) & (df_top_kr['FearGreedIndex'] >= 80 * 1.30) & (df_top_kr['VKOSPI_Pct'] <= 0.40 / 1.30) & (df_top_kr['VVIX_Pct'] <= 0.50 / 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 60 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.50 / 1.30) & (df_top_kr['RU_Pct'] >= 0.70 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 70 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.50 / 1.30) & (df_top_kr['RU_Pct'] >= 0.40 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 0.8 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 1.0 * 1.30) & (df_top_kr['FearGreedIndex'] >= 88 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                # 포착집중 반전 10개
                (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 3.5 * 1.30) & (df_top_kr['FearGreedIndex'] >= 60 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 4.0 * 1.30) & (df_top_kr['FearGreedIndex'] >= 55 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_%B'] >= 0.75 * 1.30) & (df_top_kr['KOSPI_RSI7'] >= 50 * 1.30) & (df_top_kr['FearGreedIndex'] >= 60 * 1.30) & (df_top_kr['VKOSPI_Pct'] <= 0.60 / 1.30) & (df_top_kr['VVIX_Pct'] <= 0.60 / 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 2 >= 2.0 * 1.30) & (df_top_kr['FGI_Pct'] >= 0.65 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['KOSPI_%B'] >= 0.80 * 1.30) & (df_top_kr['KOSPI_RSI7'] >= 50 * 1.30) & (df_top_kr['FearGreedIndex'] >= 55 * 1.30) & (df_top_kr['VKOSPI_Pct'] <= 0.60 / 1.30) & (df_top_kr['VVIX_Pct'] <= 0.60 / 1.30)) & _not_bottom_kr,
                (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 2 >= 1.5 * 1.30) & (df_top_kr['FGI_Pct'] >= 0.65 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 45 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.70 / 1.30) & (df_top_kr['RU_Pct'] >= 0.50 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 50 * 1.30) & (df_top_kr['VVIX_Pct'] <= 0.70 / 1.30) & (df_top_kr['RU_Pct'] >= 0.50 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 0.3 * 1.30) & (df_top_kr['FearGreedIndex'] >= 82 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
                ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 0.5 * 1.30) & (df_top_kr['FearGreedIndex'] >= 82 * 1.30) & (df_top_kr['KOSPI_RU'] >= 0.30 * 1.30)) & _not_bottom_kr,
            ]
            
            df_top_kr['top_multi_count'] = sum(cond.reindex(df_top_kr.index).fillna(False).astype(int) for cond in top_multi_conditions_list_kr)
            
            if active_period_days:
                target_date_tm = datetime.date.today() - datetime.timedelta(days=active_period_days)
                detected_tm = [i for i, d in enumerate(df_top_kr.index) if d >= pd.to_datetime(target_date_tm)]
                initial_x_tm = [detected_tm[0], len(df_top_kr.index) - 1] if detected_tm else None
                if detected_tm:
                    kospi_1y_tm = df_top_kr['KOSPI'].iloc[detected_tm[0]:]
                    kospi_yr_tm = [float(kospi_1y_tm.min()) * 0.95, float(kospi_1y_tm.max()) * 1.05]
                else:
                    kospi_yr_tm = [float(df_top_kr['KOSPI'].min()) * 0.95, float(df_top_kr['KOSPI'].max()) * 1.05]
            else:
                initial_x_tm = None
                kospi_yr_tm = [float(df_top_kr['KOSPI'].min()) * 0.95, float(df_top_kr['KOSPI'].max()) * 1.05]
            
            max_kospi_tm = float(df_top_kr['KOSPI'].max()) * 1.2
            
            top_cond_map_kr = [
                ((df_top_kr['top_multi_count'] >= 1) & (df_top_kr['top_multi_count'] <= 7), 'rgba(220,30,30,0.3)', '#E06666', '1~7개 감지'), 
                ((df_top_kr['top_multi_count'] >= 8) & (df_top_kr['top_multi_count'] <= 14), 'rgba(255,140,0,0.3)', '#FF8C00', '8~14개 감지'), 
                ((df_top_kr['top_multi_count'] >= 15) & (df_top_kr['top_multi_count'] <= 21), 'rgba(255,220,0,0.3)', '#FFD700', '15~21개 감지'), 
                ((df_top_kr['top_multi_count'] >= 22) & (df_top_kr['top_multi_count'] <= 28), 'rgba(0,128,0,0.3)', '#A9D08E', '22~28개 감지'), 
                ((df_top_kr['top_multi_count'] >= 29) & (df_top_kr['top_multi_count'] <= 35), 'rgba(135,206,235,0.3)', '#87CEEB', '29~35개 감지'), 
                ((df_top_kr['top_multi_count'] >= 36) & (df_top_kr['top_multi_count'] <= 42), 'rgba(0,0,128,0.3)', '#000080', '36~42개 감지'), 
                ((df_top_kr['top_multi_count'] >= 43) & (df_top_kr['top_multi_count'] <= 49), 'rgba(128,0,128,0.3)', '#800080', '43~49개 감지'), 
            ]
            
            df_sig_tm_kr = df_top_kr[df_top_kr['top_multi_count'] >= 1].sort_index(ascending=False).head(100)
            if not df_sig_tm_kr.empty:
                dates_row_tm_kr = []
                counts_row_tm_kr = []
                for dt, row in df_sig_tm_kr.iterrows():
                    cnt = row['top_multi_count']
                    bg = '#E06666'
                    for c, bar_c, tbl_c, lbl in top_cond_map_kr:
                        if c.loc[dt]:
                            bg = tbl_c
                            break
                    fg = "#FFF"
                    dates_row_tm_kr.append(f"<td style='background:{bg};color:{fg};font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>")
                    counts_row_tm_kr.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{int(cnt)}</td>")
                
                st.markdown(f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 고점 감지 신호 (최근 100개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {"".join(dates_row_tm_kr)}
                    </tr>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>갯수</th>
                        {"".join(counts_row_tm_kr)}
                    </tr>
                </table>
                </div>
                """, unsafe_allow_html=True)
            
            fig_top_multi_kr = make_subplots(specs=[[{"secondary_y": True}]])
            hd_top_multi_kr = [fmt_date_kor(d) for d in df_top_kr.index]
            
            fig_top_multi_kr.add_trace(go.Scatter(x=hd_top_multi_kr, y=df_top_kr['KOSPI'], name='KOSPI 가격', mode='lines+markers',
                line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                hovertemplate='KOSPI: %{y:.2f}<extra></extra>'), secondary_y=False)
            
            for cond, bar_color, tbl_color, label in top_cond_map_kr:
                fig_top_multi_kr.add_trace(go.Bar(x=hd_top_multi_kr, y=cond.astype(int).values * max_kospi_tm,
                    marker_color=bar_color, showlegend=False, hoverinfo='skip',
                    marker_line_width=0.5, marker_line_color='white'), secondary_y=False)
            
            fig_top_multi_kr.update_layout(**COMMON_LAYOUT, height=400, margin=dict(l=0,r=50,t=30,b=10), showlegend=False, barmode='overlay', bargap=0,
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.2))])
            if initial_x_tm:
                fig_top_multi_kr.update_xaxes(range=initial_x_tm, type='category', **crosshair_xaxis())
            else:
                fig_top_multi_kr.update_xaxes(type='category', **crosshair_xaxis())
            fig_top_multi_kr.update_yaxes(range=kospi_yr_tm, **crosshair_yaxis(), secondary_y=False, title_text="")
            fig_top_multi_kr.update_yaxes(showticklabels=False, showgrid=False, secondary_y=True)
            
            st.plotly_chart(fig_top_multi_kr, width='stretch', config=COMMON_CONFIG, key="top_tab_multi_chart_kr")
            
            top_multi_verify_kr = {
                "**빨간색**": (top_cond_map_kr[0][0], top_cond_map_kr[0][3]),
                "**주황색**": (top_cond_map_kr[1][0], top_cond_map_kr[1][3]),
                "**노란색**": (top_cond_map_kr[2][0], top_cond_map_kr[2][3]),
                "**초록색**": (top_cond_map_kr[3][0], top_cond_map_kr[3][3]),
                "**파란색**": (top_cond_map_kr[4][0], top_cond_map_kr[4][3]),
                "**남색**":   (top_cond_map_kr[5][0], top_cond_map_kr[5][3]),
                "**보라색**": (top_cond_map_kr[6][0], top_cond_map_kr[6][3]),
            }
            stats_top_multi_kr = calculate_top_stats(df_top_kr, 'KOSPI', top_multi_verify_kr)
            st.markdown("<div style='margin-top:2px;'></div>", unsafe_allow_html=True)
            render_top_stats_table(stats_top_multi_kr, "지표검증결과 (2018.01 ~ 현재 KOSPI 고점 대비, 저점 감지일 제외)")
            
        # ── 소분류 4: 통합지표 고점 ──
        with top_sub_tabs_kr[3]:
            _nb_top2_kr = _not_bottom_kr.reindex(df_top_kr.index).fillna(True)
            
            energy_top_kr = (df_top_kr['FearGreedIndex']/100) * df_top_kr['KOSPI_%B'] * (df_top_kr['KOSPI_RSI7']/100)
            c_top_1_kr = ((energy_top_kr >= 0.75) & (df_top_kr['VKOSPI_Pct'] <= 0.15)) & _nb_top2_kr
            
            c_top_2_kr = ((df_top_kr['RSI_Div']) & (df_top_kr['KOSPI_RU'] >= 0.65)) & _nb_top2_kr
            
            c_top_3_kr = ((df_top_kr['MACD_Hist'].diff() < 0) & (df_top_kr['MACD_Hist'] > 0) & (df_top_kr['KOSPI_%B'] >= 0.95) & (df_top_kr['VKOSPI_Pct'] <= 0.15)) & _nb_top2_kr
            
            c_top_4_kr = ((df_top_kr['SKEW'] >= 155) & (df_top_kr['VKOSPI'] <= 14) & (df_top_kr['KOSPI_RSI7'] >= 72)) & _nb_top2_kr
            
            c_top_all_kr = c_top_1_kr | c_top_2_kr | c_top_3_kr | c_top_4_kr
            
            triggered_dates_top_kr = df_top_kr[c_top_all_kr].index.sort_values(ascending=False)
            recent_100_top_kr = triggered_dates_top_kr[:100]
            if len(recent_100_top_kr) > 0:
                dates_row_top_kr = ""
                for dt in recent_100_top_kr:
                    dates_row_top_kr += f"<td style='background:#800080;color:white;font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
                
                table_html_top_kr = f"""
                <div style='margin-bottom:0.3rem;overflow-x:auto;'>
                <span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 통합 고점 신호 (최근 100개, 저점일 제외)</span>
                <table style='border-collapse:collapse;margin-top:3px;text-align:center;'>
                    <tr>
                        <th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>
                        {dates_row_top_kr}
                    </tr>
                </table>
                </div>
                """
                st.markdown(table_html_top_kr, unsafe_allow_html=True)
                
            if active_period_days:
                target_date_tt_kr = datetime.date.today() - datetime.timedelta(days=active_period_days)
                df_top_plot_kr = df_top_kr[df_top_kr.index >= pd.to_datetime(target_date_tt_kr)]
                if not df_top_plot_kr.empty:
                    kospi_yr_tt = [float(df_top_plot_kr['KOSPI'].min()) * 0.95, float(df_top_plot_kr['KOSPI'].max()) * 1.05]
                    initial_x_tt = [df_top_plot_kr.index[0].strftime("%Y-%m-%d"), df_top_plot_kr.index[-1].strftime("%Y-%m-%d")]
                else:
                    kospi_yr_tt = None
                    initial_x_tt = None
            else:
                df_top_plot_kr = df_top_kr.copy()
                if not df_top_plot_kr.empty:
                    kospi_yr_tt = [float(df_top_plot_kr['KOSPI'].min()) * 0.95, float(df_top_plot_kr['KOSPI'].max()) * 1.05]
                    initial_x_tt = [df_top_plot_kr.index[0].strftime("%Y-%m-%d"), df_top_plot_kr.index[-1].strftime("%Y-%m-%d")]
                else:
                    kospi_yr_tt = None
                    initial_x_tt = None
            
            fig_top_final_kr = make_subplots(specs=[[{"secondary_y": True}]])
            hd_top_final_kr = [fmt_date_kor(d) for d in df_top_plot_kr.index]
            
            fig_top_final_kr.add_trace(go.Scatter(
                x=hd_top_final_kr, y=df_top_plot_kr['KOSPI'], name='KOSPI 가격', mode='lines+markers',
                line=dict(color='rgba(0, 0, 0, 0.5)', width=2),
                marker=dict(symbol='circle', color='white', size=1.5, line=dict(color='black', width=0.25)),
                hovertemplate='KOSPI: %{y:.2f}<extra></extra>'
            ), secondary_y=False)
            
            fig_top_final_kr.add_trace(go.Bar(
                x=hd_top_final_kr, y=c_top_all_kr.reindex(df_top_plot_kr.index).astype(int).values * (kospi_yr_tt[1] if kospi_yr_tt else 3000), name='통합 고점 감지 (OR)',
                marker_color='rgba(128, 0, 128, 0.3)',
                marker_line_width=0.5, marker_line_color='white',
                hovertemplate='고점 신호 감지<extra></extra>'
            ), secondary_y=False)
            
            fig_top_final_kr.update_layout(**COMMON_LAYOUT, height=350, margin=dict(l=0,r=50,t=10,b=10), showlegend=False,
                shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color="rgba(150, 150, 150, 0.4)", width=1.0))])
            fig_top_final_kr.update_xaxes(type='category', **crosshair_xaxis())
            if initial_x_tt:
                fig_top_final_kr.update_xaxes(range=initial_x_tt)
            
            st.plotly_chart(fig_top_final_kr, width='stretch', config=COMMON_CONFIG, key="top_chart_final_or_kr")
            
            top_final_conditions_kr = {
                "**최종 4대 통합 고점지표 (OR)**": (c_top_all_kr, '과열에너지 + RSI다이버전스·RU + MACD전환 + SKEW경고'),
            }
            stats_top_final_kr = calculate_top_stats(df_top_kr, 'KOSPI', top_final_conditions_kr)
            render_top_stats_table(stats_top_final_kr, "통합 고점지표 검증 결과 (2018.01 ~ 현재 KOSPI 고점 대비, 저점 감지일 제외)")
