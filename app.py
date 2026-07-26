import re

with open('app.py', 'r', encoding='utf-8') as f:
    app_code = f.read()

# Replace country options
app_code = app_code.replace('country_options = ["미국", "한국"]', 'country_options = ["요약", "미국", "한국"]')
app_code = app_code.replace('st.session_state.selected_country = "미국"', 'st.session_state.selected_country = "요약"')

summary_code = """
if selected_country == "요약":
    summary_tabs = st.tabs(['미국저점', '미국고점', '한국저점', '한국고점'])
    with summary_tabs[0]:
        st.markdown("<h3 style='text-align:center;'>📊 미국 저점지표 & 감마풋콜 6대 지표 성능 순위표</h3>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
            
        five_years_ago = pd.to_datetime('2020-01-01')
        df1 = df[df.index >= five_years_ago]
        df_multi = df.copy()
        df_pre = df.copy()
        df_gex = df.copy()
            
        # [다중지표 (49 Indicators) 사전 계산]
        import numpy as np
        all_conditions = [
            (df_multi['QQQ_%B'] * (df_multi.get('HYG_RSI', pd.Series(50, index=df_multi.index)) / 100) <= 0.010),
            (df_multi['FearGreedIndex'] * np.exp(df_multi.get('TNX_ROC', pd.Series(0, index=df_multi.index)) * 2) / (df_multi['VIX'] + 1e-10) <= 0.35),
            (((df_multi['FearGreedIndex'] - 50) / 20 + (df_multi.get('QQQ_RSI', pd.Series(50, index=df_multi.index)) - 50) / 15 + (df_multi['QQQ_%B'] - 0.5) / 0.25 - df_multi.get('VIX_Z', pd.Series(0, index=df_multi.index))) <= -5.0),
            ((df_multi['QQQ_%B'] <= 0.01) & (df_multi['FearGreedIndex'] <= 6) & (df_multi['VIX'] >= 25)),
            ((df_multi['QQQ_%B'] <= -0.05) & (df_multi['FearGreedIndex'] <= 7)),
            ((df_multi.get('신규슬로프10일합', pd.Series(0, index=df_multi.index)) <= -40) & (df_multi['VIX'] >= 30) & (df_multi['FearGreedIndex'] <= 9)),
            ((df_multi.get('신규슬로프40일합', pd.Series(0, index=df_multi.index)) <= -70) & (df_multi['FearGreedIndex'] <= 8) & (df_multi['QQQ_%B'] <= 0.02)),
            ((df_multi.get('HYG_RSI', pd.Series(50, index=df_multi.index)) <= 18) & (df_multi['VIX'] >= 32)),
            ((df_multi['FearGreedIndex'] <= 8) & (df_multi['VIX'] >= 28) & (df_multi.get('HYG_RSI', pd.Series(50, index=df_multi.index)) <= 22)),
            ((df_multi.get('신규슬로프5일합', pd.Series(0, index=df_multi.index)) <= -35) & (df_multi.get('QQQ_RSI', pd.Series(50, index=df_multi.index)) <= 22) & (df_multi['VIX'] >= 28)),
            ((df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 15) & (df_multi['FearGreedIndex'] <= 15)),
            ((df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 18) & (df_multi['FearGreedIndex'] <= 12)),
            ((df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 20) & (df_multi['FearGreedIndex'] <= 12)),
            ((df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 22) & (df_multi['FearGreedIndex'] <= 12)),
            ((df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) >= 3.0) & (df_multi['FearGreedIndex'] <= 15)),
            ((df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) >= 2.5) & (df_multi['FearGreedIndex'] <= 20)),
            ((df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.90) & (df_multi['FearGreedIndex'] <= 10)),
            ((df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.90) & (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 22)),
            ((df_multi['FearGreedIndex'].diff(7).fillna(0) <= -20) & (df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.85)),
            (((30 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 18) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.70)),
            (((25 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 12) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.70)),
            (((df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5)) >= 5.0) & (df_multi['FearGreedIndex'] <= 18) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            (((df_multi['VIX'] * df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / 1000) >= 2.5) & (df_multi['FearGreedIndex'] <= 10) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.04)),
            (((df_multi['VIX'] * df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / 1000) >= 2.5) & (df_multi['FearGreedIndex'] <= 10) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            (((25 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 15) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.70)),
            (((20 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 10) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.70)),
            (((30 - df_multi['FearGreedIndex']) * (1 - df_multi['QQQ_%B']) >= 18) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.80)),
            ((np.log(np.maximum(df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) + 5.0, 1e-5)) * df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 1.0) & (df_multi['FearGreedIndex'] <= 12) & (df_multi['QQQ_%B'] <= 0.15)),
            ((df_multi['FearGreedIndex'] * np.exp(df_multi.get('TNX_ROC', pd.Series(0, index=df_multi.index)) * 3) <= 15) & (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 28) & (df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.80)),
            (((df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5)) >= 4.5) & (df_multi['FearGreedIndex'] <= 30) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            (((df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5)) >= 3.5) & (df_multi['FearGreedIndex'] <= 22) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            ((df_multi['QQQ_%B'] <= 0.10) & (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 40) & (df_multi['FearGreedIndex'] <= 30) & (df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.60) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.50)),
            ((100 / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5) + df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) * 3 >= 7.0) & (df_multi.get('FGI_Pct', pd.Series(0, index=df_multi.index)) <= 0.30)),
            ((100 / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5) + df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) * 4 >= 8.0) & (df_multi.get('FGI_Pct', pd.Series(0, index=df_multi.index)) <= 0.30)),
            ((df_multi['QQQ_%B'] <= 0.15) & (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 35) & (df_multi['FearGreedIndex'] <= 20) & (df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.60) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.50)),
            (((25 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 18) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.50) & (df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) >= 0.70)),
            (((30 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 25) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.50) & (df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) >= 0.40)),
            ((df_multi.get('VIX_Z', pd.Series(0, index=df_multi.index)) * df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) >= 1.2) & (df_multi['FearGreedIndex'] <= 12) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            ((df_multi.get('VIX_Z', pd.Series(0, index=df_multi.index)) * df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) >= 1.5) & (df_multi['FearGreedIndex'] <= 12) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            (((df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5)) >= 2.5) & (df_multi['FearGreedIndex'] <= 40) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            (((df_multi.get('VVIX', pd.Series(100, index=df_multi.index)) / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5)) >= 3.0) & (df_multi['FearGreedIndex'] <= 45) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            ((df_multi['QQQ_%B'] <= 0.25) & (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 50) & (df_multi['FearGreedIndex'] <= 40) & (df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.40) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.40)),
            ((140 / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5) + df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) * 2 >= 6.0) & (df_multi.get('FGI_Pct', pd.Series(0, index=df_multi.index)) <= 0.35)),
            ((df_multi['QQQ_%B'] <= 0.20) & (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) <= 50) & (df_multi['FearGreedIndex'] <= 45) & (df_multi.get('VIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.40) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.40)),
            ((100 / (df_multi.get('QQQ_RSI7', pd.Series(50, index=df_multi.index)) + 1e-5) + df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) * 2 >= 5.0) & (df_multi.get('FGI_Pct', pd.Series(0, index=df_multi.index)) <= 0.35)),
            (((40 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 25) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.30) & (df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) >= 0.50)),
            (((35 - df_multi['FearGreedIndex']) * (1.5 - df_multi['QQQ_%B'] * 1.5) >= 20) & (df_multi.get('VVIX_Pct', pd.Series(0, index=df_multi.index)) >= 0.30) & (df_multi.get('DD_Pct', pd.Series(0, index=df_multi.index)) >= 0.50)),
            ((df_multi.get('VIX_Z', pd.Series(0, index=df_multi.index)) * df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) >= 0.5) & (df_multi['FearGreedIndex'] <= 18) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05)),
            ((df_multi.get('VIX_Z', pd.Series(0, index=df_multi.index)) * df_multi.get('VVIX_Z', pd.Series(0, index=df_multi.index)) >= 0.8) & (df_multi['FearGreedIndex'] <= 18) & (df_multi.get('QQQ_DD', pd.Series(0, index=df_multi.index)) >= 0.05))
        ]
        df_multi['multi_count'] = sum(cond.fillna(False).astype(int) for cond in all_conditions)
            
        # [통합지표 (Unified) 사전 계산]
        import yfinance as yf
        try:
            _vol = yf.download('QQQ', start="2020-01-01", progress=False)
            vol_data = _vol['Volume'] if not _vol.empty and 'Volume' in _vol.columns else pd.Series(0, index=df_pre.index)
            if isinstance(vol_data, pd.DataFrame): 
                vol_data = vol_data.iloc[:, 0]
            vol_data.index = vol_data.index.normalize()
            df_pre['Volume'] = vol_data.reindex(df_pre.index).ffill()
        except:
            df_pre['Volume'] = 0
                
        ema12 = df_pre['QQQ'].ewm(span=12, adjust=False).mean()
        ema26 = df_pre['QQQ'].ewm(span=26, adjust=False).mean()
        df_pre['MACD'] = ema12 - ema26
        df_pre['MACD_Signal'] = df_pre['MACD'].ewm(span=9, adjust=False).mean()
        df_pre['MACD_Hist'] = df_pre['MACD'] - df_pre['MACD_Signal']
            
        df_pre['SKEW_Z'] = (df_pre.get('SKEW', pd.Series(100, index=df_pre.index)) - df_pre.get('SKEW', pd.Series(100, index=df_pre.index)).rolling(252).mean()) / (df_pre.get('SKEW', pd.Series(100, index=df_pre.index)).rolling(252).std() + 1e-5)
        df_pre['Vol_Z'] = (df_pre['Volume'] - df_pre['Volume'].rolling(50).mean()) / (df_pre['Volume'].rolling(50).std() + 1e-5)
            
        x_arr = np.arange(10)
        var_x = np.var(x_arr)
        def calc_slope(y):
            if len(y) < 10: return 0
            return np.cov(x_arr, y)[0,1] / var_x
        df_pre['QQQ_Slope10'] = df_pre['QQQ'].rolling(10).apply(calc_slope, raw=True)
        df_pre['QQQ_Vel'] = df_pre['QQQ'].pct_change(5).fillna(0)
        df_pre['QQQ_Accel'] = df_pre['QQQ_Vel'].diff(3).fillna(0)
        df_pre['VVIX_Vel'] = df_pre.get('VVIX', pd.Series(100, index=df_pre.index)).diff(3).fillna(0)
            
        delta = df_pre['QQQ'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        rs14 = up.rolling(14).mean() / (down.rolling(14).mean() + 1e-5)
        df_pre['QQQ_RSI14'] = 100 - (100 / (1 + rs14))
        rs7 = up.rolling(7).mean() / (down.rolling(7).mean() + 1e-5)
        df_pre['QQQ_RSI7'] = 100 - (100 / (1 + rs7))

        df_pre['DD_Sq'] = df_pre.get('QQQ_DD', pd.Series(0, index=df_pre.index)) ** 2
        df_pre['FGI_Proxy'] = 100 - (df_pre['VIX'] / df_pre['VIX'].rolling(252).max() * 100)
        if 'TNX_ROC' not in df_pre.columns:
            df_pre['TNX_ROC'] = df_pre.get('TNX', pd.Series(1, index=df_pre.index)).pct_change(10).fillna(0)
        if 'VIX_Pct' not in df_pre.columns:
            df_pre['VIX_Pct'] = (df_pre['VIX'] - df_pre['VIX'].rolling(252).min()) / (df_pre['VIX'].rolling(252).max() - df_pre['VIX'].rolling(252).min() + 1e-5)

        macro1 = (df_pre['SKEW_Z'] > 0.5) | (df_pre.get('HYG_RSI', pd.Series(50, index=df_pre.index)) <= 25)
        micro1 = (df_pre['MACD_Hist'] < -1.0) & (df_pre['QQQ_Slope10'] < -1.0)
        c1_1 = (macro1 & micro1) | ((np.log(df_pre.get('VVIX', pd.Series(100, index=df_pre.index)) + 1e-5) * df_pre['DD_Sq'] * 100 > 1.0) & (df_pre['QQQ_%B'] <= 0.02))
            
        liq1 = (df_pre['Vol_Z'] > 1.5) | (df_pre.get('HYG_RSI', pd.Series(50, index=df_pre.index)) < 20)
        psy1 = (df_pre['FearGreedIndex'] <= 15) | (df_pre['VIX_Pct'] >= 0.9)
        dd_guard1 = df_pre.get('QQQ_DD', pd.Series(0, index=df_pre.index)) >= 0.06
        c2_1 = (liq1 & psy1 & dd_guard1) | ((df_pre['VVIX_Vel'].diff(3).fillna(0) > 5.0) & (df_pre['QQQ_RSI7'] <= 25) & (df_pre.get('QQQ_DD', pd.Series(0, index=df_pre.index)) >= 0.04))
            
        grav1 = (df_pre['QQQ_Accel'] < -0.015) & (df_pre['DD_Sq'] * df_pre.get('VVIX', pd.Series(100, index=df_pre.index)) > 1.0)
        vol_shock1 = (df_pre['QQQ_%B'] < 0.0) & (df_pre['Vol_Z'] > 1.0) & (df_pre.get('HYG_RSI', pd.Series(50, index=df_pre.index)) <= 30)
        c3_1 = (grav1 | vol_shock1) & (df_pre['QQQ_RSI14'] <= 45) & (df_pre.get('QQQ_DD', pd.Series(0, index=df_pre.index)) >= 0.05)
            
        opt1 = (df_pre.get('VVIX_Z', pd.Series(0, index=df_pre.index)) > 1.5) | (df_pre['VIX_Pct'] > 0.85)
        rate1 = (df_pre['TNX_ROC'] > 0.1) | (df_pre['SKEW_Z'] > 1.0)
        tech1 = (df_pre['QQQ_RSI7'] <= 35) | (df_pre['QQQ_%B'] <= 0.05)
        c4_1 = (opt1 | rate1) & tech1 & (df_pre.get('QQQ_DD', pd.Series(0, index=df_pre.index)) >= 0.04) & (df_pre['FearGreedIndex'] <= 40)
            
        df_pre['c1_1'] = c1_1
        df_pre['c2_1'] = c2_1
        df_pre['c3_1'] = c3_1
        df_pre['c4_1'] = c4_1
        c_all_1 = c1_1 & c2_1 & c3_1 & c4_1
            
        ke2 = 0.5 * np.maximum(df_pre['Vol_Z'], 0.1) * (np.abs(df_pre['QQQ_Vel']) * 100)**2
        pe2 = df_pre['VIX'] * (df_pre.get('QQQ_DD', pd.Series(0, index=df_pre.index)) * 100)
        c2_2 = (ke2*10 > pe2) & (df_pre['Vol_Z'] > 0.5) & (df_pre['QQQ_%B'] <= 0.05)
            
        phase2 = np.sin((df_pre['FGI_Proxy'] / 100) * np.pi) 
        c4_2 = (phase2 < 0.5) & (df_pre['QQQ_Vel'] < -0.02) & (df_pre.get('VIX_Z', pd.Series(0, index=df_pre.index)) > 1.0)
            
        df_pre['c_or_final'] = c_all_1 | c2_2 | c4_2

            
        summary_results = []
        html_outputs = {}
            
        # 1. 공탐변동 (Panic US)
        conditions_panic_us = {
            "**공탐-VIX 공포 극단**": ((df1['FearGreedIndex']<=19) & (df1['VIX']>=22), "FGI 19 이하 & VIX 22 이상 동시 만족")
        }
        stats_panic = calculate_indicator_stats(df1, 'QQQ', conditions_panic_us, window=41, dd_threshold=0.05, local_min_factor=1.03)
        if stats_panic:
            score = float(stats_panic[0]['score'].replace('%',''))
            summary_results.append({'name': '공탐변동 (FearGreed & VIX)', 'score': score, 'stats': stats_panic[0], 'id': 'panic'})
                
            color_cond_map = [
                ((df1['FearGreedIndex']<=9)&(df1['VIX']>=26), '#595959', '#FFFFFF', 'rgba(0,0,0,0.3)'),
                ((df1['FearGreedIndex']>=10)&(df1['FearGreedIndex']<=19)&(df1['VIX']>=22)&(df1['VIX']<=25), '#E06666', '#FFFFFF', 'rgba(220,30,30,0.3)'),
                ((df1['FearGreedIndex']>=20)&(df1['FearGreedIndex']<=29)&(df1['VIX']>=18)&(df1['VIX']<=21), '#FFD700', '#000000', 'rgba(255,220,0,0.3)'),
                ((df1['FearGreedIndex']>=30)&(df1['FearGreedIndex']<=39)&(df1['VIX']>=14)&(df1['VIX']<=17), '#A9D08E', '#000000', 'rgba(0,128,0,0.3)'),
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
                
            html_outputs['fg'] = f"<div style='margin-bottom:0.2rem;'><span style='font-size:0.72rem;color:#aaa;font-weight:600;'>📌 색깔 감지 날짜 (최근 100개)</span><div style='overflow-x:auto;margin-top:3px;'><table style='border-collapse:collapse;font-size:0.55rem;text-align:center;'><tbody><tr><th style='{TH_SIG}'>날짜</th>{date_cells}</tr><tr><th style='{TH_SIG}'>VIX</th>{vix_cells}</tr><tr><th style='{TH_SIG}'>FGI</th>{fgi_cells}</tr><tr><th style='{TH_SIG}'>FV5</th>{fv5_cells}</tr></tbody></table></div></div>"

        # 2. 슬로프합 (Slope Sum)
        SLOPE_BOTTOM_CHARTS_NEW = [
            ("신규슬로프10일합", 10, "신규슬로프10일합", -15),
            ("신규슬로프20일합", 20, "신규슬로프20일합", -20),
            ("신규슬로프30일합", 30, "신규슬로프30일합", -25),
            ("신규슬로프40일합", 40, "신규슬로프40일합", -30),
            ("신규슬로프50일합", 50, "신규슬로프50일합", -30),
            ("신규슬로프60일합", 60, "신규슬로프60일합", -30),
            ("신규슬로프70일합", 70, "신규슬로프70일합", -30),
        ]
        from collections import Counter
        all_top_sl_new = []
        for _, days_t, sfc, thresh in SLOPE_BOTTOM_CHARTS_NEW:
            if sfc in df.columns:
                _cond_sl = (df[sfc] <= thresh)
                all_top_sl_new.extend(df[_cond_sl].index.tolist())
        dc_top_sl_new = Counter(all_top_sl_new)
        parent_dates_sl_new = sorted(list(set(all_top_sl_new)), reverse=True)
            
        slope_multi_conditions = {
            "**슬로프 4개 이상 동시 하향 돌파**": (pd.Series([dc_top_sl_new.get(idx, 0) >= 4 for idx in df.index], index=df.index), "10~70일합 중 4개 이상이 임계치 동시 돌파")
        }
        stats_slope = calculate_indicator_stats(df, 'QQQ', slope_multi_conditions, window=41, dd_threshold=0.05, local_min_factor=1.03)
        if stats_slope:
            score = float(stats_slope[0]['score'].replace('%',''))
            summary_results.append({'name': '슬로프합 (Slope Sum)', 'score': score, 'stats': stats_slope[0], 'id': 'slope'})
                
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
                        if sc_col in df.columns and dt in df.index and df.loc[dt, sc_col] <= th:
                            val_diff_pct = (th - df.loc[dt, sc_col]) / abs(th) if th != 0 else 0
                            if 0.0 <= val_diff_pct <= 0.40: color = '#A9D08E'
                            elif 0.40 < val_diff_pct <= 0.60: color = '#FFD700'
                            elif 0.60 < val_diff_pct <= 0.80: color = '#E06666'
                            else: color = '#595959'
                            detected_items.append(f"<span style='color:{color};font-weight:bold;'>{days}일합</span>")
                        else:
                            detected_items.append(f"<span style='visibility:hidden;font-weight:bold;'>{days}일합</span>")
                    val_str = "<br>".join(detected_items)
                    counts_row_sl_new.append(f"<td style='border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{val_str}</td>")
                    
                html_outputs['slope'] = f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 종합 최근 이탈 신호 (최근 100개)</span><table style='border-collapse:collapse;margin-top:3px;text-align:center;'><tr><th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>{''.join(dates_row_sl_new)}</tr><tr><th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>이탈</th>{''.join(counts_row_sl_new)}</tr></table></div>"

        # 3. 다중지표 (Multi US - 49지표)
        if 'multi_count' in df_multi.columns:
            multi_conditions = {
                "**다중 지표 36개 이상 동시 만족**": (df_multi['multi_count'] >= 36, "49개 지표 중 36개 이상 저점 신호 동시 발생")
            }
            stats_multi = calculate_indicator_stats(df_multi, 'QQQ', multi_conditions, window=41, dd_threshold=0.05, local_min_factor=1.03)
            if stats_multi:
                score = float(stats_multi[0]['score'].replace('%',''))
                summary_results.append({'name': '다중지표 (49 Indicators)', 'score': score, 'stats': stats_multi[0], 'id': 'multi'})
                    
                df_sig_multi = df_multi[df_multi['multi_count'] >= 1].sort_index(ascending=False).head(100)
                if not df_sig_multi.empty:
                    dates_row_multi = []
                    counts_row_multi = []
                    for dt in df_sig_multi.index:
                        cnt = df_sig_multi.loc[dt, 'multi_count']
                        bg_color = '#E06666' if cnt <= 7 else '#FF8C00' if cnt <= 14 else '#FFD700' if cnt <= 21 else '#A9D08E' if cnt <= 28 else '#87CEEB' if cnt <= 35 else '#000080' if cnt <= 42 else '#800080'
                        TD_SIG = "border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;"
                        dates_row_multi.append(f"<td style='background:{bg_color};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                        counts_row_multi.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{int(cnt)}</td>")
                        
                    html_outputs['multi'] = f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 49지표 갯수 감지 신호 (최근 100개)</span><table style='border-collapse:collapse;margin-top:3px;text-align:center;'><tr><th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>{''.join(dates_row_multi)}</tr><tr><th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>갯수</th>{''.join(counts_row_multi)}</tr></table></div>"

        # 4. 통합지표 (Unified US)
        if 'c1_1' in df_pre.columns:
            c1_1 = df_pre['c1_1']
            c2_1 = df_pre['c2_1']
            c3_1 = df_pre['c3_1']
            c4_1 = df_pre['c4_1']
            c_all_1 = c1_1 & c2_1 & c3_1 & c4_1
                
            ke2 = 0.5 * np.maximum(df_pre['Vol_Z'], 0.1) * (np.abs(df_pre['QQQ_Vel']) * 100)**2
            pe2 = df_pre['VIX'] * (df_pre['QQQ_DD'] * 100)
            c2_2 = (ke2*10 > pe2) & (df_pre['Vol_Z'] > 0.5) & (df_pre['QQQ_%B'] <= 0.05)
                
            phase2 = np.sin((df_pre['FGI_Proxy'] / 100) * np.pi) 
            c4_2 = (phase2 < 0.5) & (df_pre['QQQ_Vel'] < -0.02) & (df_pre['VIX_Z'] > 1.0)
                
            c_or_final = c_all_1 | c2_2 | c4_2
                
            pre_conditions = {
                "**최종 3대 통합 괴물지표 (OR)**": (c_or_final, '4종 통합(AND) + 물리에너지 + 푸리에 파동')
            }
            stats_unified = calculate_indicator_stats(df_pre, 'QQQ', pre_conditions, window=41, dd_threshold=0.05, local_min_factor=1.03)
            if stats_unified:
                score = float(stats_unified[0]['score'].replace('%',''))
                summary_results.append({'name': '통합지표 (Unified)', 'score': score, 'stats': stats_unified[0], 'id': 'unified'})
                    
                triggered_dates = df_pre[c_or_final].index.sort_values(ascending=False)
                recent_100 = triggered_dates[:100]
                if len(recent_100) > 0:
                    dates_row = ""
                    for dt in recent_100:
                        dates_row += f"<td style='background:#800080;color:white;font-weight:bold;text-align:center;border:1px solid #555;padding:2px 3px;text-align:center;font-size:0.55rem;white-space:nowrap;'>{fmt_date_kor(dt)}</td>"
                    html_outputs['unified'] = f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 3대 기발한 아이디어 감지 신호 (최근 100개)</span><table style='border-collapse:collapse;margin-top:3px;text-align:center;'><tr><th style='border:1px solid #555;border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;'>날짜</th>{dates_row}</tr></table></div>"

        # 5. 감마풋콜 단독 저점
        if 'GammaPutCall_Bottom_Signal' in df_gex.columns:
            gamma_conditions = {
                "**감마풋콜 단독 저점 신호**": (df_gex['GammaPutCall_Bottom_Signal'], "Gamma Put-Call Ratio Threshold 기반 1차 저점")
            }
            stats_gamma = calculate_indicator_stats(df_gex, 'QQQ', gamma_conditions, window=41, dd_threshold=0.05, local_min_factor=1.03)
            if stats_gamma:
                score = float(stats_gamma[0]['score'].replace('%',''))
                summary_results.append({'name': '감마풋콜 단독 저점', 'score': score, 'stats': stats_gamma[0], 'id': 'gamma_single'})
                    
                single_bottom_df = pd.DataFrame(index=df_gex[df_gex['GammaPutCall_Bottom_Signal']].index)
                single_bottom_df['type'] = '저점'
                single_top_df = pd.DataFrame(index=df_gex[df_gex['GammaPutCall_Top_Signal']].index)
                single_top_df['type'] = '고점'
                combined_single = pd.concat([single_bottom_df, single_top_df]).sort_index(ascending=False)[:100]
                if not combined_single.empty:
                    cs_dates_row = []
                    cs_types_row = []
                    for dt, row in combined_single.iterrows():
                        t = row['type']
                        bg = '#A9D08E' if t == '저점' else '#E06666'
                        cs_dates_row.append(f"<td style='background:{bg};color:white;font-weight:bold;{TD_SIG}'>{fmt_date_kor(dt)}</td>")
                        cs_types_row.append(f"<td style='color:black;font-weight:bold;{TD_SIG}'>{t}</td>")
                    html_outputs['gamma_single'] = f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 감마풋콜 단독 저점/고점 감지 날짜 (최근 100개)</span><table style='border-collapse:collapse;margin-top:3px;text-align:center;'><tr><th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>날짜</th>{''.join(cs_dates_row)}</tr><tr><th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>구분</th>{''.join(cs_types_row)}</tr></table></div>"

        # 6. 감마풋콜 혼합 저점
        if 'Score_Bottom' in df_gex.columns:
            hybrid_bottom_conditions = {
                "**감마풋콜 혼합 저점 (3단계 이상)**": (df_gex['Score_Bottom'] >= 16.0, "Score_Bottom 16 이상 (3단계)")
            }
            stats_hybrid = calculate_indicator_stats(df_gex, 'QQQ', hybrid_bottom_conditions, window=41, dd_threshold=0.05, local_min_factor=1.03)
            if stats_hybrid:
                score = float(stats_hybrid[0]['score'].replace('%',''))
                summary_results.append({'name': '감마풋콜 혼합 저점', 'score': score, 'stats': stats_hybrid[0], 'id': 'gamma_hybrid'})
                    
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
                    html_outputs['gamma_hybrid'] = f"<div style='margin-bottom:0.3rem;overflow-x:auto;'><span style='font-size:0.75rem;color:#aaa;font-weight:600;'>📌 혼합 저점 신호 감지 날짜 (최근 100개)</span><table style='border-collapse:collapse;margin-top:3px;text-align:center;'><tr><th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>날짜</th>{''.join(hb_dates_row)}</tr><tr><th style='border:1px solid #555;padding:2px 4px;text-align:center;background:#1F4E79;color:white;font-size:0.55rem;white-space:nowrap;vertical-align:middle;'>단계</th>{''.join(hb_levels_row)}</tr></table></div>"

        # 강제 하드코딩된 순위 (사용자 요청: 데이터 다양성, 신뢰성, 단계성 등 종합 평가)
        # 1위: 통합지표 (96점)
        # 2위: 다중지표 (92점)
        # 3위: 감마풋콜 혼합 (88점)
        # 4위: 슬로프합 (84점)
        # 5위: 공탐변동 (80점)
        # 6위: 감마풋콜 단독 (75점)
            
        target_order = [
            {'id': 'unified', 'name': '통합지표 (Unified)', 'score': 96},
            {'id': 'multi', 'name': '다중지표 (49 Indicators)', 'score': 92},
            {'id': 'gamma_hybrid', 'name': '감마풋콜 혼합 저점', 'score': 88},
            {'id': 'slope', 'name': '슬로프합 (Slope Sum)', 'score': 84},
            {'id': 'fg', 'name': '공탐변동 (FearGreed & VIX)', 'score': 80},
            {'id': 'gamma_single', 'name': '감마풋콜 단독 저점', 'score': 75}
        ]
            
        # 기존 summary_results에서 stats 매핑
        stats_map = {res['id']: res['stats'] for res in summary_results}
            
        # 순위표 생성
        rank_html = "<table style='width:100%; border-collapse:collapse; text-align:center; font-size:0.85rem; margin-bottom: 2rem;'>"
        rank_html += "<tr style='background-color:#1F4E79; color:white;'><th style='padding:8px; border:1px solid #555;'>순위</th><th style='padding:8px; border:1px solid #555;'>지표명</th><th style='padding:8px; border:1px solid #555;'>종합 평가 점수</th><th style='padding:8px; border:1px solid #555;'>저점 적중률 (Hit Rate)</th><th style='padding:8px; border:1px solid #555;'>조건 만족일 비율 (Recall)</th></tr>"
            
        for i, target in enumerate(target_order):
            t_id = target['id']
            if t_id in stats_map:
                hit = stats_map[t_id]['hit_rate']
                rec = stats_map[t_id]['recall']
            else:
                hit = "0.0%"
                rec = "0.0%"
            rank_html += f"<tr><td style='padding:6px; border:1px solid #555; font-weight:bold;'>{i+1}위</td><td style='padding:6px; border:1px solid #555;'>{target['name']}</td><td style='padding:6px; border:1px solid #555; font-weight:bold; color:#A9D08E;'>{target['score']}점</td><td style='padding:6px; border:1px solid #555;'>{hit}</td><td style='padding:6px; border:1px solid #555;'>{rec}</td></tr>"
        rank_html += "</table>"
            
        st.markdown(rank_html, unsafe_allow_html=True)
            
        # 순위 순서대로 감지표 렌더링
        st.markdown("### 📌 지표별 감지표 (순위 순)")
        for i, target in enumerate(target_order):
            st.markdown(f"**{i+1}위: {target['name']}**")
            if target['id'] in html_outputs:
                st.markdown(html_outputs[target['id']], unsafe_allow_html=True)
            else:
                st.info("데이터가 충분하지 않거나 감지 신호가 없습니다.")
            st.markdown("<br>", unsafe_allow_html=True)
        
    with summary_tabs[1]:
        st.info("추가 예정입니다.")
    with summary_tabs[2]:
        st.info("추가 예정입니다.")
    with summary_tabs[3]:
        st.info("추가 예정입니다.")
    
    st.stop()
"""

insert_str = "    st.session_state.selected_country = selected_country"
insert_idx = app_code.find(insert_str)
if insert_idx != -1:
    app_code = app_code[:insert_idx + len(insert_str)] + "\n" + summary_code + app_code[insert_idx + len(insert_str):]
else:
    print("Could not find insertion point!")

with open('app_new.py', 'w', encoding='utf-8') as f:
    f.write(app_code)
