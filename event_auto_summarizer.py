# -*- coding: utf-8 -*-
import requests
import xml.etree.ElementTree as ET
import re
import os
import datetime
import urllib.parse

# 주요 금융 이슈 키워드 맵 (영어/한국어 릴레이션 및 명칭 정제)
KEYWORD_MAPPING = [
    (r'iran|israel|war|middle east|conflict|military|strait|hormuz', '중동 정세 불안발'),
    (r'tariff|trade war|china|export|import|sanction|duty', '무역 관세 분쟁발'),
    (r'yen|carry trade|japan|boj|ueda', '엔 캐리 청산발'),
    (r'svb|bank|banking|collapse|failure|credit suisse|liquidity', '은행권 파산 사태'),
    (r'rate|fed|yield|bond|powell|hawkish|treasury|inflationary', '금리/채권 금리 급등발'),
    (r'inflation|cpi|ppi|cost|spending|price', '인플레이션 우려'),
    (r'recession|gdp|slowdown|hard landing|jobless|unemployment', '경기 침체 우려'),
    (r'tech|valuation|bubble|ai|chip|earnings|nasdaq|semiconductor', '기술주 밸류에이션 조정'),
    (r'election|policy|trump|biden|politics|house|senate', '정치 불확실성 우려'),
    (r'pandemic|covid|virus|outbreak|variant', '팬데믹/바이러스 악재')
]

SUFFIX_MAPPING = [
    (r'crash|plunge|tumble|slump|sell-off|drop|collapse|rout', '폭락'),
    (r'correction|pullback|dip|retreat|slide', '조정'),
    (r'bear market|downtrend|decline', '하락장')
]

def fetch_period_news_keywords(start_ym, end_ym):
    """
    구글 뉴스 RSS 및 시황 뉴스에서 해당 기간의 주요 키워드를 다중 수집합니다.
    (배포 클라우드 서버 환경 차단 완화)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*'
    }
    
    titles = []
    queries = [
        f"US stock market drop {start_ym}",
        f"NASDAQ plunge {start_ym}",
        f"S&P 500 fall {start_ym}"
    ]
    
    for q in queries:
        try:
            encoded_query = urllib.parse.quote(q)
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall('.//item/title')[:10]:
                    if item.text:
                        titles.append(item.text.lower())
                if len(titles) >= 10:
                    break
        except Exception:
            continue
            
    return " ".join(titles)

def summarize_event_name(period_str):
    """
    period_str 예: "2026.04 ~ 2026.05" 또는 "2026.04 ~ 진행중"
    뉴스를 기반으로 깔끔한 사건명을 자동 생성합니다.
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
            title = f"{prefix} {suffix}"
        else:
            title = "신규 증시 하락조정장"
            
        if len(title) > 20:
            title = title[:20]
            
        if end_ym == "진행중":
            title = f"{title} (진행중)"
            
        return title
    except Exception:
        if "진행중" in period_str:
            return "신규 하락조정장 (진행중)"
        return "신규 하락조정장"

# 인메모리(서버 메모리) 캐시 보관함 (배포 환경 파일 쓰기 제한 대비)
IN_MEMORY_EVENT_CACHE = {}

def get_or_update_event_cache(period_str, fall_rate_str, json_filepath=None):
    """
    JSON 파일 및 서버 인메모리 캐시에서 사건을 확인하고,
    없으면 실시간 뉴스 수집 요약 후 리턴합니다. (배포 서버 환경 대응)
    """
    # 1. 인메모리 캐시 확인
    if period_str in IN_MEMORY_EVENT_CACHE:
        cached = IN_MEMORY_EVENT_CACHE[period_str]
        if "진행중" in period_str:
            cached['fall_rate'] = fall_rate_str
        return cached

    # 2. JSON 캐시 확인
    events = []
    if json_filepath and os.path.exists(json_filepath):
        try:
            with open(json_filepath, 'r', encoding='utf-8') as f:
                events = json.load(f)
                for ev in events:
                    if ev.get('period') == period_str:
                        if "진행중" in period_str:
                            ev['fall_rate'] = fall_rate_str
                        IN_MEMORY_EVENT_CACHE[period_str] = ev
                        return ev
        except Exception:
            pass

    # 3. 신규 뉴스 탐색 & 실시간 사건 요약 생성
    new_title = summarize_event_name(period_str)
    new_event = {
        "title": new_title,
        "period": period_str,
        "fall_rate": fall_rate_str
    }
    
    IN_MEMORY_EVENT_CACHE[period_str] = new_event
    
    # 4. JSON 파일 저장 시도 (로컬 환경 지원)
    if json_filepath:
        try:
            events.append(new_event)
            with open(json_filepath, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        
    return new_event
