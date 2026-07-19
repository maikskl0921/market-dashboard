import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime

def slope_sum_lagged(arr, window):
    if len(arr) == 0: return np.zeros(0)
    res = np.zeros(len(arr))
    for i in range(len(arr)):
        val = 0.0
        for w in range(window):
            idx = i - w
            if idx >= 0:
                val += arr[idx]
        res[i] = val
    return res

def fetch_and_process_data():
    start_date_str = "2018-01-01"
    qqq = yf.download('QQQ', start=start_date_str, progress=False)
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq_df = qqq[['Close']].rename(columns={'Close': 'QQQ'}) if not qqq.empty and 'Close' in qqq.columns else pd.DataFrame(columns=['QQQ'])
    vix = yf.download('^VIX', start=start_date_str, progress=False)
    if isinstance(vix.columns, pd.MultiIndex): vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[['Close']].rename(columns={'Close': 'VIX'}) if not vix.empty and 'Close' in vix.columns else pd.DataFrame(columns=['VIX'])

    tnx = yf.download('^TNX', start=start_date_str, progress=False)
    if isinstance(tnx.columns, pd.MultiIndex): tnx.columns = tnx.columns.get_level_values(0)
    tnx_df = tnx[['Close']].rename(columns={'Close': 'TNX'}) if not tnx.empty and 'Close' in tnx.columns else pd.DataFrame(columns=['TNX'])

    hyg = yf.download('HYG', start=start_date_str, progress=False)
    if isinstance(hyg.columns, pd.MultiIndex): hyg.columns = hyg.columns.get_level_values(0)
    hyg_df = hyg[['Close']].rename(columns={'Close': 'HYG'}) if not hyg.empty and 'Close' in hyg.columns else pd.DataFrame(columns=['HYG'])

    skew = yf.download('^SKEW', start=start_date_str, progress=False)
    if isinstance(skew.columns, pd.MultiIndex): skew.columns = skew.columns.get_level_values(0)
    skew_df = skew[['Close']].rename(columns={'Close': 'SKEW'}) if not skew.empty and 'Close' in skew.columns else pd.DataFrame(columns=['SKEW'])

    vvix = yf.download('^VVIX', start=start_date_str, progress=False)
    if isinstance(vvix.columns, pd.MultiIndex): vvix.columns = vvix.columns.get_level_values(0)
    vvix_df = vvix[['Close']].rename(columns={'Close': 'VVIX'}) if not vvix.empty and 'Close' in vvix.columns else pd.DataFrame(columns=['VVIX'])

    tlt = yf.download('TLT', start=start_date_str, progress=False)
    if isinstance(tlt.columns, pd.MultiIndex): tlt.columns = tlt.columns.get_level_values(0)
    tlt_df = tlt[['Close']].rename(columns={'Close': 'TLT'}) if not tlt.empty and 'Close' in tlt.columns else pd.DataFrame(columns=['TLT'])

    df = qqq_df.join([vix_df, tnx_df, hyg_df, skew_df, vvix_df, tlt_df], how='outer')
    df.ffill(inplace=True)
    df.bfill(inplace=True)

    # Fear and Greed Index
    fgi_data = {}
    try:
        fgi_url = "https://feargree-api.vercel.app/api"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(fgi_url, headers=headers, timeout=10)
        if res.status_code == 200:
            api_data = res.json()
            for h in api_data.get('history', []):
                try:
                    h_date = pd.to_datetime(h['date']).normalize()
                    fgi_data[h_date] = float(h['score'])
                except:
                    pass
    except Exception:
        pass

    fgi_series = pd.Series(fgi_data, name='FearGreedIndex')
    df = df.join(fgi_series, how='left')
    df['FearGreedIndex'] = df['FearGreedIndex'].ffill().fillna(50)

    df['VIX_Pct'] = df['VIX'].rolling(252, min_periods=60).rank(pct=True)
    df['VIX_Z'] = (df['VIX'] - df['VIX'].rolling(252).mean()) / (df['VIX'].rolling(252).std() + 1e-5)
    df['FGI_Pct'] = df['FearGreedIndex'].rolling(252, min_periods=60).rank(pct=True)
    df['TNX_ROC'] = df['TNX'].pct_change(10)

    delta_hyg = df['HYG'].diff()
    gain_hyg = (delta_hyg.where(delta_hyg > 0, 0)).rolling(window=14).mean()
    loss_hyg = (-delta_hyg.where(delta_hyg < 0, 0)).rolling(window=14).mean()
    rs_hyg = gain_hyg / (loss_hyg + 1e-10)
    df['HYG_RSI'] = 100 - (100 / (1 + rs_hyg))

    vvix_ma = df['VVIX'].rolling(60).mean()
    vvix_std = df['VVIX'].rolling(60).std()
    df['VVIX_Z'] = (df['VVIX'] - vvix_ma) / (vvix_std + 1e-10)
    df['VVIX_Pct'] = df['VVIX'].rolling(252, min_periods=60).rank(pct=True)

    return df

def fetch_korean_market_data_v2(df_us=None):
    kospi = yf.download('^KS11', start="2018-01-01", progress=False)
    if isinstance(kospi.columns, pd.MultiIndex): kospi.columns = kospi.columns.get_level_values(0)
    kospi_df = kospi[['Close']].rename(columns={'Close': 'KOSPI'}) if not kospi.empty and 'Close' in kospi.columns else pd.DataFrame(columns=['KOSPI'])
    kospi_df['Volume'] = kospi['Volume']

    # FGI & VKOSPI
    headers = {'User-Agent': 'Mozilla/5.0'}
    realtime_score = 50
    realtime_vkospi = 20.0
    history_records = {}

    try:
        res = requests.get('https://feargree-api.vercel.app/api', headers=headers, timeout=8)
        if res.status_code == 200:
            api_data = res.json()
            realtime_score = int(api_data['kr']['score'])
            realtime_vkospi = float(api_data['kr']['vkospi'])
            for h in api_data.get('history', []):
                try:
                    h_date = pd.to_datetime(h['date']).normalize()
                    history_records[h_date] = float(h['kr'])
                except:
                    pass
    except Exception:
        pass

    kospi_df.index = kospi_df.index.normalize()
    today_norm = pd.to_datetime(datetime.date.today()).normalize()
    history_records[today_norm] = float(realtime_score)

    union_index = kospi_df.index.union(pd.DatetimeIndex(list(history_records.keys()))).sort_values()

    kospi_close = kospi_df['KOSPI']
    returns = kospi_close.pct_change()
    rolling_vol = returns.rolling(30).std() * np.sqrt(252) * 100
    rolling_vol = rolling_vol.ffill().bfill()

    fg_series = pd.Series(np.nan, index=union_index, dtype=float)
    for dt_norm, val in history_records.items():
        if dt_norm in fg_series.index:
            fg_series[dt_norm] = val

    first_valid = fg_series.first_valid_index()
    if first_valid is not None:
        fg_series.loc[:first_valid] = fg_series.loc[:first_valid].fillna(50.0)
    fg_series = fg_series.ffill().fillna(50.0)

    df_kr = pd.DataFrame(index=union_index)
    df_kr['KOSPI'] = kospi_close.reindex(union_index).ffill().bfill()
    df_kr['FearGreedIndex'] = fg_series
    df_kr['VKOSPI'] = rolling_vol.reindex(union_index).ffill().bfill()
    df_kr['Volume'] = kospi_df['Volume'].reindex(union_index).ffill().bfill()

    df_kr = df_kr.reindex(kospi_df.index).ffill().bfill()

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

    df_kr_s.set_index('Date', inplace=True)
    df_kr_s = df_kr_s[~df_kr_s.index.duplicated(keep='first')]

    delta_k = df_kr_s['KOSPI'].diff()
    gain_k = (delta_k.where(delta_k > 0, 0)).rolling(window=14).mean()
    loss_k = (-delta_k.where(delta_k < 0, 0)).rolling(window=14).mean()
    rs_k = gain_k / (loss_k + 1e-10)
    df_kr_s['KOSPI_RSI'] = 100 - (100 / (1 + rs_k))

    gain7_k = (delta_k.where(delta_k > 0, 0)).rolling(window=7).mean()
    loss7_k = (-delta_k.where(delta_k < 0, 0)).rolling(window=7).mean()
    rs7_k = gain7_k / (loss7_k + 1e-10)
    df_kr_s['KOSPI_RSI7'] = 100 - (100 / (1 + rs7_k))

    ma20_k = df_kr_s['KOSPI'].rolling(20).mean()
    std20_k = df_kr_s['KOSPI'].rolling(20).std()
    df_kr_s['KOSPI_%B'] = (df_kr_s['KOSPI'] - (ma20_k - 2 * std20_k)) / (4 * std20_k + 1e-10)

    vkospi_ma200 = df_kr_s['VKOSPI'].rolling(200).mean()
    vkospi_std200 = df_kr_s['VKOSPI'].rolling(200).std()
    df_kr_s['VKOSPI_Z'] = (df_kr_s['VKOSPI'] - vkospi_ma200) / (vkospi_std200 + 1e-10)
    df_kr_s['VKOSPI_Pct'] = df_kr_s['VKOSPI'].rolling(252, min_periods=60).rank(pct=True)

    df_kr_s['KOSPI_Peak'] = df_kr_s['KOSPI'].rolling(252, min_periods=1).max()
    df_kr_s['KOSPI_DD'] = (df_kr_s['KOSPI_Peak'] - df_kr_s['KOSPI']) / df_kr_s['KOSPI_Peak']
    df_kr_s['K_DD_Pct'] = df_kr_s['KOSPI_DD'].rolling(252, min_periods=60).rank(pct=True)

    if df_us is not None:
        global_cols = ['SKEW', 'VVIX', 'VVIX_Z', 'VVIX_Pct', 'HYG_RSI', 'TNX_ROC', 'FGI_Pct', 'VIX_Z']
        df_us_filtered = df_us[[c for c in global_cols if c in df_us.columns]].copy()
        df_kr_s = df_kr_s.join(df_us_filtered, how='left')
        df_kr_s = df_kr_s.ffill().bfill()

    return df_kr_s

# Load Data
df_us = fetch_and_process_data()
df_kr = fetch_korean_market_data_v2(df_us)

# is_any_bottom_kr definition in app.py (for _not_bottom_kr)
_bottom_fgi_kr = (
    ((df_kr['FearGreedIndex'] <= 9) & (df_kr['VKOSPI'] >= 26)) |
    ((df_kr['FearGreedIndex'] >= 10) & (df_kr['FearGreedIndex'] <= 19) & (df_kr['VKOSPI'] >= 22)) |
    ((df_kr['FearGreedIndex'] >= 20) & (df_kr['FearGreedIndex'] <= 29) & (df_kr['VKOSPI'] >= 18)) |
    ((df_kr['FearGreedIndex'] >= 30) & (df_kr['FearGreedIndex'] <= 39) & (df_kr['VKOSPI'] >= 14))
)
_bottom_slope_kr = (
    (df_kr['슬로프10일합'] <= -15) | (df_kr['슬로프20일합'] <= -20) |
    (df_kr['슬로프30일합'] <= -25) | (df_kr['슬로프40일합'] <= -30) |
    (df_kr['슬로프50일합'] <= -35) | (df_kr['슬로프60일합'] <= -40) |
    (df_kr['슬로프70일합'] <= -45)
)
_multi_conds_for_bottom_kr = [
    (df_kr['KOSPI_%B'] * (df_kr['HYG_RSI'] / 100) <= 0.010),
    (df_kr['FearGreedIndex'] * np.exp(df_kr['TNX_ROC'] * 2) / (df_kr['VKOSPI'] + 1e-10) <= 0.35),
    (((df_kr['FearGreedIndex'] - 50) / 20 + (df_kr['KOSPI_RSI'] - 50) / 15 + (df_kr['KOSPI_%B'] - 0.5) / 0.25 - df_kr['VKOSPI_Z']) <= -5.0),
    ((df_kr['KOSPI_%B'] <= 0.01) & (df_kr['FearGreedIndex'] <= 6) & (df_kr['VKOSPI'] >= 25)),
    ((df_kr['KOSPI_%B'] <= -0.05) & (df_kr['FearGreedIndex'] <= 7)),
]
_multi_cnt_kr = sum(c.fillna(False).astype(int) for c in _multi_conds_for_bottom_kr)
_bottom_multi_kr = _multi_cnt_kr >= 1

_rolling_max_kr = df_kr['KOSPI'].rolling(252, min_periods=1).max()
_drawdown_kr = (_rolling_max_kr - df_kr['KOSPI']) / _rolling_max_kr
_local_min_kr = df_kr['KOSPI'].rolling(41, center=True, min_periods=1).min()
is_actual_bottom_kr = (df_kr['KOSPI'] <= _local_min_kr * 1.03) & (_drawdown_kr >= 0.05)

is_any_bottom_kr = (_bottom_fgi_kr | _bottom_slope_kr | _bottom_multi_kr | is_actual_bottom_kr).reindex(df_kr.index).fillna(False)

df_top_kr = df_kr.copy()
df_top_kr['KOSPI_Low252'] = df_top_kr['KOSPI'].rolling(252, min_periods=1).min()
df_top_kr['KOSPI_RU'] = (df_top_kr['KOSPI'] - df_top_kr['KOSPI_Low252']) / (df_top_kr['KOSPI_Low252'] + 1e-10)

df_top_kr['KOSPI_20H'] = df_top_kr['KOSPI'].rolling(20).max()
df_top_kr['RSI7_20H_kr'] = df_top_kr['KOSPI_RSI7'].rolling(20).max()
df_top_kr['RSI_Div'] = (df_top_kr['KOSPI'] >= df_top_kr['KOSPI_20H'] * 0.99) & (df_top_kr['KOSPI_RSI7'] < df_top_kr['RSI7_20H_kr'] - 5)

ema12_kr = df_top_kr['KOSPI'].ewm(span=12, adjust=False).mean()
ema26_kr = df_top_kr['KOSPI'].ewm(span=26, adjust=False).mean()
df_top_kr['MACD'] = ema12_kr - ema26_kr
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

# Define actual tops (KOSPI)
price_col = 'KOSPI'
window = 41
ru_threshold = 0.10
local_max_factor = 0.97

rolling_min_v = df_top_kr[price_col].rolling(252, min_periods=1).min()
rally_up_v = (df_top_kr[price_col] - rolling_min_v) / (rolling_min_v + 1e-10)
local_max_v = df_top_kr[price_col].rolling(window, center=True, min_periods=1).max()
is_top_v = (df_top_kr[price_col] >= local_max_v * local_max_factor) & (rally_up_v >= ru_threshold)
total_tops = is_top_v.sum()

def get_top_recall_and_hr(cond):
    cond_bool = cond.reindex(df_top_kr.index).fillna(False).astype(bool)
    total_triggered = int(cond_bool.sum())
    hit_triggered = int((cond_bool & is_top_v).sum())
    hit_rate = (hit_triggered / total_triggered * 100) if total_triggered > 0 else 0.0
    recall = (hit_triggered / total_tops * 100) if total_tops > 0 else 0.0
    return recall, hit_rate, total_triggered

# Scan group scales (f1: group1, f2: group2, f3: group3, f4: group4)
# Let's search a combination of scales where L1 (1~7개) is within 3% ~ 7% (e.g. 5.5%)
# and L2 (8~14개) is within 3% ~ 7% (e.g. 3.5%), and L3~L7 are <= L2.
# This gives a nice smooth down-staircase where L1, L2 are in the target range, and L3~L7 drop down!
best_comb = []
for f1 in np.linspace(1.10, 1.60, 11):
    for f2 in np.linspace(0.80, 1.40, 13):
        for f3 in np.linspace(0.80, 1.40, 13):
            for f4 in np.linspace(0.80, 1.40, 13):
                temp_multi_conditions = [
                    # Group 1: 19 conds
                    ((df_top_kr['KOSPI_%B'] * (df_top_kr['HYG_RSI'] / 100) >= 0.85 * f1) & (df_top_kr['VKOSPI'] <= 14 / f1)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * np.exp(-df_top_kr['TNX_ROC'] * 2) >= 70 * f1) & (df_top_kr['VKOSPI'] <= 14 / f1)) & _not_bottom_kr,
                    (((df_top_kr['FearGreedIndex'] - 50) / 20 + (df_top_kr['KOSPI_RSI'] - 50) / 15 + (df_top_kr['KOSPI_%B'] - 0.5) / 0.25 - df_top_kr['VKOSPI_Z']) >= 4.0 * f1) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_%B'] >= 0.95 * f1) & (df_top_kr['FearGreedIndex'] >= 85 * f1) & (df_top_kr['VKOSPI'] <= 13 / f1)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_%B'] >= 0.98 * f1) & (df_top_kr['FearGreedIndex'] >= 88 * f1)) & _not_bottom_kr,
                    ((df_top_kr['슬로프10일합'] >= 40 * f1) & (df_top_kr['VKOSPI'] <= 13 / f1) & (df_top_kr['FearGreedIndex'] >= 80 * f1)) & _not_bottom_kr,
                    ((df_top_kr['슬로프40일합'] >= 70 * f1) & (df_top_kr['FearGreedIndex'] >= 82 * f1) & (df_top_kr['KOSPI_%B'] >= 0.90 * f1)) & _not_bottom_kr,
                    ((df_top_kr['HYG_RSI'] >= 82 * f1) & (df_top_kr['VKOSPI'] <= 13 / f1)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] >= 88 * f1) & (df_top_kr['VKOSPI'] <= 14 / f1) & (df_top_kr['HYG_RSI'] >= 78 * f1)) & _not_bottom_kr,
                    ((df_top_kr['슬로프5일합'] >= 35 * f1) & (df_top_kr['KOSPI_RSI'] >= 78 * f1) & (df_top_kr['VKOSPI'] <= 13 / f1)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_RSI7'] >= 85 * f1) & (df_top_kr['FearGreedIndex'] >= 82 * f1)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_RSI7'] >= 82 * f1) & (df_top_kr['FearGreedIndex'] >= 88 * f1)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_RSI7'] >= 80 * f1) & (df_top_kr['FearGreedIndex'] >= 88 * f1)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_RSI7'] >= 78 * f1) & (df_top_kr['FearGreedIndex'] >= 88 * f1)) & _not_bottom_kr,
                    ((df_top_kr['VVIX_Z'] <= -2.5 / f1) & (df_top_kr['FearGreedIndex'] >= 85 * f1)) & _not_bottom_kr,
                    ((df_top_kr['VVIX_Z'] <= -2.0 / f1) & (df_top_kr['FearGreedIndex'] >= 80 * f1)) & _not_bottom_kr,
                    ((df_top_kr['VVIX_Pct'] <= 0.10 / f1) & (df_top_kr['FearGreedIndex'] >= 90 * f1)) & _not_bottom_kr,
                    ((df_top_kr['VVIX_Pct'] <= 0.10 / f1) & (df_top_kr['KOSPI_RSI7'] >= 78 * 0.75)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'].diff(7) >= 20 * f1) & (df_top_kr['VKOSPI_Pct'] <= 0.15 / f1)) & _not_bottom_kr,
                    # Group 2: 10 conds
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 72 * f2) & (df_top_kr['VVIX_Pct'] <= 0.30 / f2)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 60 * f2) & (df_top_kr['VVIX_Pct'] <= 0.30 / f2)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 6.5 * f2) & (df_top_kr['FearGreedIndex'] >= 82 * f2) & (df_top_kr['KOSPI_RU'] >= 0.30 * f2)) & _not_bottom_kr,
                    (((1000 / (df_top_kr['VKOSPI'] * df_top_kr['VVIX'] + 1e-5)) >= 1.0 * f2) & (df_top_kr['FearGreedIndex'] >= 90 * f2) & (df_top_kr['KOSPI_RU'] >= 0.25 * f2)) & _not_bottom_kr,
                    (((1000 / (df_top_kr['VKOSPI'] * df_top_kr['VVIX'] + 1e-5)) >= 1.0 * f2) & (df_top_kr['FearGreedIndex'] >= 90 * f2) & (df_top_kr['KOSPI_RU'] >= 0.30 * f2)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 65 * f2) & (df_top_kr['VVIX_Pct'] <= 0.30 / f2)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 50 * f2) & (df_top_kr['VVIX_Pct'] <= 0.30 / f2)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 72 * f2) & (df_top_kr['VVIX_Pct'] <= 0.20 / f2)) & _not_bottom_kr,
                    ((np.log(np.maximum(-df_top_kr['VVIX_Z'] + 5.0, 1e-5)) * (1 - df_top_kr['VKOSPI_Pct']) >= 1.0 * f2) & (df_top_kr['FearGreedIndex'] >= 88 * f2) & (df_top_kr['KOSPI_%B'] >= 0.85 * f2)) & _not_bottom_kr,
                    (((100 - df_top_kr['FearGreedIndex']) * np.exp(-df_top_kr['TNX_ROC'] * 3) <= 15 / f2) & (df_top_kr['KOSPI_RSI7'] >= 72 * f2) & (df_top_kr['VKOSPI_Pct'] <= 0.20 / f2)) & _not_bottom_kr,
                    # Group 3: 10 conds
                    (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 5.5 * f3) & (df_top_kr['FearGreedIndex'] >= 70 * f3) & (df_top_kr['KOSPI_RU'] >= 0.30 * f3)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 4.5 * f3) & (df_top_kr['FearGreedIndex'] >= 78 * f3) & (df_top_kr['KOSPI_RU'] >= 0.30 * f3)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_%B'] >= 0.90 * f3) & (df_top_kr['KOSPI_RSI7'] >= 60 * 0.75) & (df_top_kr['FearGreedIndex'] >= 70 * f3) & (df_top_kr['VKOSPI_Pct'] <= 0.40 / f3) & (df_top_kr['VVIX_Pct'] <= 0.50 / f3)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 3 >= 2.5 * f3) & (df_top_kr['FGI_Pct'] >= 0.70 * f3)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 4 >= 3.0 * f3) & (df_top_kr['FGI_Pct'] >= 0.70 * f3)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_%B'] >= 0.85 * f3) & (df_top_kr['KOSPI_RSI7'] >= 65 * 0.75) & (df_top_kr['FearGreedIndex'] >= 80 * f3) & (df_top_kr['VKOSPI_Pct'] <= 0.40 / f3) & (df_top_kr['VVIX_Pct'] <= 0.50 / f3)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 60 * f3) & (df_top_kr['VVIX_Pct'] <= 0.50 / f3) & (df_top_kr['RU_Pct'] >= 0.70 * f3)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 70 * f3) & (df_top_kr['VVIX_Pct'] <= 0.50 / f3) & (df_top_kr['RU_Pct'] >= 0.40 * f3)) & _not_bottom_kr,
                    ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 0.8 * f3) & (df_top_kr['FearGreedIndex'] >= 88 * f3) & (df_top_kr['KOSPI_RU'] >= 0.30 * f3)) & _not_bottom_kr,
                    ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 1.0 * f3) & (df_top_kr['FearGreedIndex'] >= 88 * f3) & (df_top_kr['KOSPI_RU'] >= 0.30 * f3)) & _not_bottom_kr,
                    # Group 4: 10 conds
                    (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 3.5 * f4) & (df_top_kr['FearGreedIndex'] >= 60 * f4) & (df_top_kr['KOSPI_RU'] >= 0.30 * f4)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / (df_top_kr['VVIX'] + 1e-5)) >= 4.0 * f4) & (df_top_kr['FearGreedIndex'] >= 55 * f4) & (df_top_kr['KOSPI_RU'] >= 0.30 * f4)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_%B'] >= 0.75 * f4) & (df_top_kr['KOSPI_RSI7'] >= 50 * 0.75) & (df_top_kr['FearGreedIndex'] >= 60 * f4) & (df_top_kr['VKOSPI_Pct'] <= 0.60 / f4) & (df_top_kr['VVIX_Pct'] <= 0.60 / f4)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 2 >= 2.0 * f4) & (df_top_kr['FGI_Pct'] >= 0.65 * f4)) & _not_bottom_kr,
                    ((df_top_kr['KOSPI_%B'] >= 0.80 * f4) & (df_top_kr['KOSPI_RSI7'] >= 50 * 0.75) & (df_top_kr['FearGreedIndex'] >= 55 * f4) & (df_top_kr['VKOSPI_Pct'] <= 0.60 / f4) & (df_top_kr['VVIX_Pct'] <= 0.60 / f4)) & _not_bottom_kr,
                    (((df_top_kr['KOSPI_RSI7'] / 100) + df_top_kr['RU_Pct'] * 2 >= 1.5 * f4) & (df_top_kr['FGI_Pct'] >= 0.65 * f4)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 45 * f4) & (df_top_kr['VVIX_Pct'] <= 0.70 / f4) & (df_top_kr['RU_Pct'] >= 0.50 * f4)) & _not_bottom_kr,
                    ((df_top_kr['FearGreedIndex'] * df_top_kr['KOSPI_%B'] >= 50 * f4) & (df_top_kr['VVIX_Pct'] <= 0.70 / f4) & (df_top_kr['RU_Pct'] >= 0.50 * f4)) & _not_bottom_kr,
                    ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 0.3 * f4) & (df_top_kr['FearGreedIndex'] >= 82 * f4) & (df_top_kr['KOSPI_RU'] >= 0.30 * f4)) & _not_bottom_kr,
                    ((df_top_kr['VKOSPI_Z'] * df_top_kr['VVIX_Z'] >= 0.5 * f4) & (df_top_kr['FearGreedIndex'] >= 82 * f4) & (df_top_kr['KOSPI_RU'] >= 0.30 * 0.75)) & _not_bottom_kr,
                ]
                cnt_series = sum(cond.reindex(df_top_kr.index).fillna(False).astype(int) for cond in temp_multi_conditions)
                
                # exclusive ranges
                ranges = [(1, 7), (8, 14), (15, 21), (22, 28), (29, 35), (36, 42), (43, 49)]
                recs = []
                for r_min, r_max in ranges:
                    cond = (cnt_series >= r_min) & (cnt_series <= r_max) & _not_bottom_kr
                    rec, _, _ = get_top_recall_and_hr(cond)
                    recs.append(rec)
                
                # Check target: L1 (1~7개) in 3.0 ~ 7.0
                is_decreasing = all(recs[i] >= recs[i+1] for i in range(len(recs)-1))
                if 3.0 <= recs[0] <= 7.0 and is_decreasing:
                    best_comb.append(((f1, f2, f3, f4), recs))

best_comb.sort(key=lambda x: x[1][0], reverse=True)
print("--- Exclusive Multi Group Tuning (Target: 3% ~ 7%) ---")
for idx, (factors, recs) in enumerate(best_comb[:20]):
    recs_str = ", ".join([f"L{i+1}={val:.2f}%" for i, val in enumerate(recs)])
    print(f"[{idx}] Factors={factors} => {recs_str}")
