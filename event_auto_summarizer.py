# -*- coding: utf-8 -*-
import urllib.request
import json
import xml.etree.ElementTree as ET
import re
import os
import datetime

# 주요 금융 이슈 키워드 맵 (영어/한국어 릴레이션 및 명칭 정제)
KEYWORD_MAPPING = [
    (r'iran|israel|war|middle east|conflict|military', '중동 정세 불안발'),
    (r'tariff|trade war|china|export|trade', '무역 관세 분쟁발'),
    (r'yen|carry trade|japan|boj', '엔 캐리 청산발'),
    (r'svb|bank|banking|collapse|failure|credit suisse', '은행권 파산 사태'),
    (r'rate|fed|yield|bond|powell|hawkish', '금리/채권 금리 급등발'),
    (r'inflation|cpi|ppi|cost', '인플레이션 우려'),
    (r'recession|gdp|slowdown|hard landing', '경기 침체 우려'),
    (r'tech|valuation|bubble|ai|chip|earnings', '기술주 밸류에이션 조정'),
    (r'election|policy|trump|biden|politics', '정치 불확실성 우려'),
    (r'pandemic|covid|virus', '팬데믹/바이러스 악재')
]

SUFFIX_MAPPING = [
    (r'crash|plunge|tumble|slump|sell-off', '폭락'),
    (r'correction|pullback|dip', '조정'),
    (r'bear market|downtrend', '하락장')
]

def fetch_period_news_keywords(start_ym, end_ym):
    """
    구글 뉴스 RSS 또는 관련 금융 기사에서 해당 기간의 주요 키워드를 수집합니다.
    """
    try:
        query = f"US stock market drop {start_ym}"
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml_data = resp.read()
            
        root = ET.fromstring(xml_data)
        titles = []
        for item in root.findall('.//item/title')[:15]:
            if item.text:
                titles.append(item.text.lower())
        return " ".join(titles)
    except Exception as e:
        return ""

def summarize_event_name(period_str):
    """
    period_str 예: "2026.04 ~ 2026.05" 또는 "2026.04 ~ 진행중"
    뉴스를 기반으로 15자 이내의 깔끔한 사건명을 자동 생성합니다.
    """
    try:
        parts = period_str.split(' ~ ')
        start_ym = parts[0]
        end_ym = parts[1]
        
        news_text = fetch_period_news_keywords(start_ym, end_ym)
        
        prefix = ""
        suffix = "하락조정장"
        
        if news_text:
            for pattern, kor_name in KEYWORD_MAPPING:
                if re.search(pattern, news_text, re.IGNORECASE):
                    prefix = kor_name
                    break
                    
            for pattern, kor_suffix in SUFFIX_MAPPING:
                if re.search(pattern, news_text, re.IGNORECASE):
                    suffix = kor_suffix
                    break
        
        if prefix:
            if prefix.endswith('사태') or prefix.endswith('우려'):
                title = f"{prefix} {suffix}"
            else:
                title = f"{prefix} {suffix}"
        else:
            title = "글로벌 증시 하락조정장"
            
        if len(title) > 18:
            title = title[:18]
            
        if end_ym == "진행중":
            title = f"{title} (진행중)"
            
        return title
    except Exception as e:
        if "진행중" in period_str:
            return "하락조정장 (진행중)"
        return "하락조정장"

def get_or_update_event_cache(period_str, fall_rate_str, json_filepath):
    """
    JSON 캐시 파일에서 사건을 확인하고, 없으면 요약 정제 후 JSON 파일에 새로 기록합니다.
    """
    events = []
    if os.path.exists(json_filepath):
        try:
            with open(json_filepath, 'r', encoding='utf-8') as f:
                events = json.load(f)
        except Exception:
            events = []

    # 기존 캐시에 기간이 일치하는 사건이 있는지 확인
    for ev in events:
        if ev.get('period') == period_str:
            # 진행 중인 사건이라면 하락률 업데이트
            if "진행중" in period_str:
                ev['fall_rate'] = fall_rate_str
                try:
                    with open(json_filepath, 'w', encoding='utf-8') as f:
                        json.dump(events, f, ensure_ascii=False, indent=4)
                except Exception:
                    pass
            return ev

    # 캐시에 없으면 자동 뉴스 탐색 & 정제 요약
    new_title = summarize_event_name(period_str)
    new_event = {
        "title": new_title,
        "period": period_str,
        "fall_rate": fall_rate_str
    }
    
    events.append(new_event)
    
    # JSON 파일 업데이트 저장
    try:
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(events, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"JSON Cache save failed: {e}")
        
    return new_event
