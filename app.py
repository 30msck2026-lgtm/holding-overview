import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import re
from datetime import datetime, timedelta

# 1. 頁面配置
st.set_page_config(
    page_title="Holding Overview",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 注入自訂 CSS：
# 1. 縮小頂部 KPI 數字與間距
# 2. 緊湊型金融表格：精簡第一欄寬度（約 62px），各欄位緊湊不浪費空間
# 3. 完整的 30W 破線警示條，不再被截斷
st.markdown("""
<style>
/* 縮小 st.metric 數值字體 */
[data-testid="stMetricValue"] {
    font-size: 1.35rem !important;
    font-weight: 600 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.85rem !important;
    color: #a0aec0 !important;
}
[data-testid="stMetricDelta"] {
    font-size: 0.8rem !important;
}
div[data-testid="metric-container"] {
    padding: 6px 8px !important;
}

/* 30W MA 專屬動能與完整警示條樣式 (自動換行，杜絕省略截斷) */
.ma30w-alert-box {
    background-color: #1c1917;
    border: 1px solid #78350f;
    border-radius: 6px;
    padding: 8px 12px;
    margin-top: 4px;
    margin-bottom: 12px;
    font-size: 0.85rem;
    line-height: 1.4;
    color: #fef08a;
    word-break: break-word;
}
.ma30w-alert-box.green {
    background-color: #064e3b;
    border-color: #047857;
    color: #a7f3d0;
}

/* 自訂專業金融表格容器 (只允許橫向滑動，高度完全展開，解決上下滾動衝突) */
.table-responsive-container {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin-bottom: 1.5rem;
    border-radius: 8px;
    border: 1px solid #2d3748;
}

.custom-stock-table {
    width: max-content;
    min-width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.82rem;
    color: #e2e8f0;
    background-color: #0e1117;
}

.custom-stock-table th, .custom-stock-table td {
    padding: 8px 8px;
    white-space: nowrap;
    border-bottom: 1px solid #1a202c;
    text-align: right;
}

.custom-stock-table th {
    background-color: #1a202c;
    color: #a0aec0;
    font-weight: 600;
}

/* 核心優化：鎖定左側第一欄「代號」，並將寬度大幅收窄至剛好容納 4 碼代號 */
.custom-stock-table th:first-child,
.custom-stock-table td:first-child {
    position: sticky;
    left: 0;
    z-index: 2;
    text-align: center;
    width: 62px !important;
    min-width: 62px !important;
    max-width: 65px !important;
    background-color: #161b22 !important;
    border-right: 2px solid #2d3748;
    font-weight: bold;
    padding: 8px 4px !important;
}

.custom-stock-table th:first-child {
    z-index: 3;
    background-color: #21262d !important;
}

/* 總和列 (TOTAL) 強調樣式 */
.custom-stock-table tr.total-row td {
    font-weight: bold;
    background-color: #1a202c !important;
    border-top: 2px solid #4a5568;
    color: #edf2f7;
}

.custom-stock-table tr.total-row td:first-child {
    background-color: #21262d !important;
}
</style>
""", unsafe_allow_html=True)

# 2. Google Sheets 核心讀寫模組
def get_sheet_id():
    url = st.secrets.get("SHEET_URL", "")
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else None

def load_holdings_from_gsheet():
    sheet_id = get_sheet_id()
    if not sheet_id:
        return []
    try:
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&id={sheet_id}&gid=0"
        df = pd.read_csv(csv_url, encoding="utf-8")
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        if 'symbol' in df.columns:
            df = df.dropna(subset=['symbol'])
            df['symbol'] = df['symbol'].astype(str).str.strip()
            df['symbol'] = df['symbol'].apply(lambda x: "".join(filter(str.isdigit, x)).zfill(4))
            
            if 'shares' not in df.columns:
                df['shares'] = 0.0
            if 'cost' not in df.columns:
                df['cost'] = 0.0
            
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0).astype(float)
            df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0.0).astype(float)
            df = df[df['shares'] > 0]
            
            return df[['symbol', 'shares', 'cost']].to_dict(orient="records")
    except Exception as e:
        st.warning(f"讀取 Google Sheet 提示: {e}")
    return []

def save_holdings_to_gsheet(holdings_list):
    api_url = st.secrets.get("WRITE_API", "")
    if not api_url:
        st.error("請先在 Streamlit Secrets 設定 WRITE_API！")
        return False
    try:
        payload = {
            "action": "sync_all",
            "holdings": holdings_list
        }
        res = requests.post(api_url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        st.error(f"同步至 Google Sheet 失敗: {e}")
        return False

def format_hk_ticker(sym):
    clean = "".join(filter(str.isdigit, str(sym))).zfill(4)
    return f"{clean}.HK"

# 3. 港股即時數據與均線計算引擎
@st.cache_data(ttl=300)
def fetch_stock_analytics(sym, shares, cost):
    ticker_str = format_hk_ticker(sym)
    try:
        t = yf.Ticker(ticker_str)
        hist = t.history(period="5y", interval="1d")
        
        if hist.empty:
            return None
        
        closes = hist['Close'].dropna()
        closes = closes[closes > 0]
        if len(closes) < 160:
            return None

        curr_price = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) > 1 else curr_price
        
        try:
            fast_p = t.fast_info.last_price
            if fast_p and not pd.isna(fast_p) and fast_p > 0:
                curr_price = float(fast_p)
                prev_p = t.fast_info.previous_close
                if prev_p and not pd.isna(prev_p) and prev_p > 0:
                    prev_close = float(prev_p)
        except Exception:
            pass

        daily_chg = curr_price - prev_close
        daily_pct = (daily_chg / prev_close) * 100.0 if prev_close > 0 else 0.0

        last_250 = closes.tail(250)
        high_52w = float(last_250.max())
        dist_52w_pct = ((curr_price - high_52w) / high_52w) * 100.0 if high_52w > 0 else 0.0

        ema10 = float(closes.ewm(span=10, adjust=False).mean().iloc[-1])
        ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema30 = float(closes.ewm(span=30, adjust=False).mean().iloc[-1])
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1])

        ma30w_window = closes.tail(150)
        ma30w = float(ma30w_window.mean())
        dist_30w_pct = ((curr_price - ma30w) / ma30w) * 100.0 if ma30w > 0 else 0.0

        past_closes = closes.iloc[:-10]
        past_ma30w = float(past_closes.tail(150).mean())
        past_price = float(past_closes.iloc[-1])
        past_dist_30w_pct = ((past_price - past_ma30w) / past_ma30w) * 100.0

        gap_diff = abs(dist_30w_pct) - abs(past_dist_30w_pct)
        
        if abs(gap_diff) <= 2.5:
            ma30w_trend = "⏸️ 貼線平穩"
        elif curr_price >= ma30w:
            if gap_diff > 2.5:
                ma30w_trend = "🚀 擴大遠離"
            else:
                ma30w_trend = "🧲 回踩走近"
        else:
            if gap_diff > 2.5:
                ma30w_trend = "📉 破線下殺"
            else:
                ma30w_trend = "⤴️ 跌深反彈"

        if curr_price >= ma30w and curr_price >= ema10:
            trend_status = "🟢 Stage 2 多頭續抱"
        elif curr_price >= ma30w and curr_price < ema10:
            trend_status = "🟡 短線拉回整理"
        else:
            trend_status = "🔴 跌破 30W 線警示"

        price_5y_ago = float(closes.iloc[0])
        price_growth_5y = ((curr_price - price_5y_ago) / price_5y_ago) * 100.0 if price_5y_ago > 0 else 0.0
        cagr_5y = (((curr_price / price_5y_ago) ** (1.0 / 5.0) - 1.0) * 100.0) if (price_5y_ago > 0 and curr_price > 0) else 0.0

        divs = t.dividends
        total_div_5y = 0.0
        latest_annual_div = 0.0
        
        if divs is not None and not divs.empty:
            div_df = divs.dropna().reset_index()
            div_df['Date'] = pd.to_datetime(div_df['Date']).dt.tz_localize(None)
            cutoff_5y = datetime.now() - timedelta(days=5*365)
            cutoff_1y = datetime.now() - timedelta(days=365)
            
            div_5y = div_df[div_df['Date'] >= cutoff_5y]
            if not div_5y.empty:
                total_div_5y = float(div_5y['Dividends'].sum())
            
            div_1y = div_df[div_df['Date'] >= cutoff_1y]
            if not div_1y.empty:
                latest_annual_div = float(div_1y['Dividends'].sum())

        total_return_5y = ((curr_price - price_5y_ago + total_div_5y) / price_5y_ago) * 100.0 if price_5y_ago > 0 else 0.0
        annual_div_cash = latest_annual_div * shares
        div_yield = (latest_annual_div / curr_price * 100.0) if curr_price > 0 else 0.0
        yoc = (latest_annual_div / cost * 100.0) if cost > 0 else div_yield
        market_val = curr_price * shares
        total_cost = cost * shares
        holding_pl = market_val - total_cost
        holding_pl_pct = (holding_pl / total_cost * 100.0) if total_cost > 0 else 0.0

        return {
            "symbol": sym,
            "shares": shares,
            "cost": cost,
            "current_price": curr_price,
            "daily_chg": daily_chg,
            "daily_pct": daily_pct,
            "market_val": market_val,
            "total_cost": total_cost,
            "holding_pl": holding_pl,
            "holding_pl_pct": holding_pl_pct,
            "high_52w": high_52w,
            "dist_52w_pct": dist_52w_pct,
            "ema10_pct": ((curr_price - ema10) / ema10) * 100.0 if ema10 > 0 else 0.0,
            "ema20_pct": ((curr_price - ema20) / ema20) * 100.0 if ema20 > 0 else 0.0,
            "ema30_pct": ((curr_price - ema30) / ema30) * 100.0 if ema30 > 0 else 0.0,
            "ema50_pct": ((curr_price - ema50) / ema50) * 100.0 if ema50 > 0 else 0.0,
            "ema200_pct": ((curr_price - ema200) / ema200) * 100.0 if ema200 > 0 else 0.0,
            "ma30w": ma30w,
            "dist_30w_pct": dist_30w_pct,
            "ma30w_trend": ma30w_trend,
            "trend_status": trend_status,
            "price_5y_ago": price_5y_ago,
            "price_growth_5y": price_growth_5y,
            "cagr_5y": cagr_5y,
            "total_div_5y": total_div_5y,
            "total_return_5y": total_return_5y,
            "annual_div_cash": annual_div_cash,
            "div_yield": div_yield,
            "yoc": yoc
        }
    except Exception:
        return None

# 初始化載入 Google Sheets
if "holdings" not in st.session_state:
    st.session_state.holdings = load_holdings_from_gsheet()

# 4. 頂部標題與控制欄
col_title, col_btn = st.columns([3, 1])
with col_title:
    st.title("💼 Holding Overview")
    st.caption("Google Sheets 雲端即時同步 • 港股動能矩陣 • 5年股息")

with col_btn:
    st.write(" ")
    if st.button("🔄 立即重新整理", use_container_width=True):
        st.cache_data.clear()
        st.session_state.holdings = load_holdings_from_gsheet()
        st.rerun()

# 5. 買入 / 沽出管理區
with st.expander("⚙️ 買入 / 沽出持股管理 (點擊展開)", expanded=(len(st.session_state.holdings) == 0)):
    top_col_left, top_col_right = st.columns(2)
    
    with top_col_left:
        st.subheader("➕ 買入 / 新增持股")
        with st.form("buy_form"):
            in_sym = st.text_input("港股代號 (例: 0700, 0005, 0941)").strip()
            in_shares = st.number_input("持有股數", min_value=1.0, step=100.0, value=500.0)
            in_cost = st.number_input("買入成本均價 (HKD，可填至小數後三位)", min_value=0.0, step=0.001, format="%.3f", value=0.0)
            btn_buy = st.form_submit_button("確認新增並存入雲端", use_container_width=True)
            
            if btn_buy and in_sym:
                clean_sym = "".join(filter(str.isdigit, in_sym)).zfill(4)
                existing = next((item for item in st.session_state.holdings if item["symbol"] == clean_sym), None)
                if existing:
                    existing["shares"] += in_shares
                    if in_cost > 0:
                        existing["cost"] = in_cost
                else:
                    st.session_state.holdings.append({
                        "symbol": clean_sym,
                        "shares": in_shares,
                        "cost": in_cost
                    })
                
                with st.spinner("正在永久存入 Google Sheets..."):
                    if save_holdings_to_gsheet(st.session_state.holdings):
                        st.cache_data.clear()
                        st.success(f"已成功買入並同步至 Google Sheet: {clean_sym}！")
                        st.rerun()

    with top_col_right:
        st.subheader("➖ 沽出 / 刪除持股")
        if st.session_state.holdings:
            del_sym = st.selectbox("選擇要沽出的股票代號", [h["symbol"] for h in st.session_state.holdings])
            if st.button("確認全數沽出並自雲端移除", type="primary", use_container_width=True):
                st.session_state.holdings = [h for h in st.session_state.holdings if h["symbol"] != del_sym]
                with st.spinner("正在從 Google Sheets 刪除..."):
                    if save_holdings_to_gsheet(st.session_state.holdings):
                        st.cache_data.clear()
                        st.success(f"已成功自 Google Sheet 沽出: {del_sym}！")
                        st.rerun()
        else:
            st.info("目前 Google Sheet 內無持股。")

# 輔助函數：渲染緊湊型 Sticky 表格（第一欄僅 62px 寬，節省空間）
def render_sticky_table(data_rows, columns):
    html = ['<div class="table-responsive-container"><table class="custom-stock-table">']
    
    html.append("<thead><tr>")
    for col in columns:
        html.append(f"<th>{col}</th>")
    html.append("</tr></thead><tbody>")
    
    for row in data_rows:
        is_total = "TOTAL" in str(row.get("代號", ""))
        tr_class = ' class="total-row"' if is_total else ''
        html.append(f"<tr{tr_class}>")
        for col in columns:
            val = str(row.get(col, "-"))
            html.append(f"<td>{val}</td>")
        html.append("</tr>")
        
    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)

# 6. 計算與展示數據
results = []
if st.session_state.holdings:
    with st.spinner("正在自動更新即時行情與均線..."):
        for h in st.session_state.holdings:
            res = fetch_stock_analytics(h['symbol'], h['shares'], h.get('cost', 0))
            if res:
                results.append(res)

if results:
    tot_val = sum(r['market_val'] for r in results)
    tot_cost = sum(r['total_cost'] for r in results)
    tot_overall_pl = tot_val - tot_cost
    tot_overall_pct = (tot_overall_pl / tot_cost * 100.0) if tot_cost > 0 else 0.0
    
    tot_daily_pl = sum(r['daily_chg'] * r['shares'] for r in results)
    tot_prev_val = tot_val - tot_daily_pl
    tot_daily_pct = (tot_daily_pl / tot_prev_val * 100.0) if tot_prev_val > 0 else 0.0
    
    tot_annual_div = sum(r['annual_div_cash'] for r in results)
    tot_div_yield = (tot_annual_div / tot_val * 100.0) if tot_val > 0 else 0.0
    
    total_count = len(results)

    # 30 週線 (30W MA) 統計清單
    above_30w_list = [r['symbol'] for r in results if r['dist_30w_pct'] >= 0]
    below_30w_list = [r['symbol'] for r in results if r['dist_30w_pct'] < 0]
    above_30w_count = len(above_30w_list)

    # 頂部 KPI 卡片
    kpi1, kpi2 = st.columns(2)
    kpi1.metric("總持股市值", f"${tot_val:,.2f} HKD", f"總成本: ${tot_cost:,.2f}")
    kpi2.metric("全倉總盈虧", f"${tot_overall_pl:+,.2f} HKD", f"{tot_overall_pct:+.2f}%")

    kpi3, kpi4 = st.columns(2)
    kpi3.metric("今日總損益", f"${tot_daily_pl:+,.2f}", f"{tot_daily_pct:+.2f}%")
    kpi4.metric("組合年股息", f"${tot_annual_div:,.2f} /年", f"股息率: {tot_div_yield:.2f}%")

    # 30 週線動能卡片與「完整不截斷」的提示條
    st.metric("30週線 (30W MA) 動能", f"{above_30w_count} / {total_count} 檔線上")
    if above_30w_count == total_count:
        st.markdown('<div class="ma30w-alert-box green">🟢 <b>多頭健康：</b>目前全部持股皆處於 30 週牛市線上！</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="ma30w-alert-box">⚠️ <b>跌破30週線清單 ({len(below_30w_list)}檔)：</b><br>{", ".join(below_30w_list)}</div>', unsafe_allow_html=True)

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📅 每日即時監控", 
        "🌊 均線與週線動能", 
        "📈 5年複合成長 (CAGR)", 
        "💰 5年股息現金流"
    ])

    # ---------------- TAB 1: 每日即時監控 ----------------
    with tab1:
        daily_cols = [
            "代號", "現價", "買入成本", "今日漲跌", "漲跌幅",
            "52W最高", "距52W", "持股數", "市值",
            "持倉盈虧", "盈虧率"
        ]
        daily_rows = []
        for r in results:
            daily_rows.append({
                "代號": r['symbol'],
                "現價": f"${r['current_price']:.2f}",
                "買入成本": f"${r['cost']:.3f}",
                "今日漲跌": f"{r['daily_chg']:+.2f}",
                "漲跌幅": f"{r['daily_pct']:+.2f}%",
                "52W最高": f"${r['high_52w']:.2f}",
                "距52W": f"{r['dist_52w_pct']:.1f}%",
                "持股數": f"{int(r['shares']):,}",
                "市值": f"${r['market_val']:,.2f}",
                "持倉盈虧": f"{r['holding_pl']:+,.2f}",
                "盈虧率": f"{r['holding_pl_pct']:+.2f}%"
            })
        
        daily_rows.append({
            "代號": "📊 TOTAL",
            "現價": "-",
            "買入成本": "-",
            "今日漲跌": "-",
            "漲跌幅": "-",
            "52W最高": "-",
            "距52W": "-",
            "持股數": "-",
            "市值": f"${tot_val:,.2f}",
            "持倉盈虧": f"${tot_overall_pl:+,.2f}",
            "盈虧率": f"{tot_overall_pct:+.2f}%"
        })
        render_sticky_table(daily_rows, daily_cols)

    # ---------------- TAB 2: 週線與均線動能 ----------------
    with tab2:
        momentum_cols = [
            "代號", "現價", "10 EMA", "20 EMA", "30 EMA",
            "50 EMA", "200 EMA", "30W MA", "距 30W %",
            "動能趨勢", "趨勢狀態"
        ]
        momentum_rows = []
        for r in results:
            momentum_rows.append({
                "代號": r['symbol'],
                "現價": f"${r['current_price']:.2f}",
                "10 EMA": f"{r['ema10_pct']:+.2f}%",
                "20 EMA": f"{r['ema20_pct']:+.2f}%",
                "30 EMA": f"{r['ema30_pct']:+.2f}%",
                "50 EMA": f"{r['ema50_pct']:+.2f}%",
                "200 EMA": f"{r['ema200_pct']:+.2f}%",
                "30W MA": f"${r['ma30w']:.2f}",
                "距 30W %": f"{r['dist_30w_pct']:+.2f}%",
                "動能趨勢": r['ma30w_trend'],
                "趨勢狀態": r['trend_status']
            })
        
        momentum_rows.append({
            "代號": "📊 統計",
            "現價": "-",
            "10 EMA": "-",
            "20 EMA": "-",
            "30 EMA": "-",
            "50 EMA": "-",
            "200 EMA": "-",
            "30W MA": "-",
            "距 30W %": f"{above_30w_count}/{total_count} 線上",
            "動能趨勢": "-",
            "趨勢狀態": "Stage 2 多頭" if above_30w_count == total_count else "注意破線標的"
        })
        render_sticky_table(momentum_rows, momentum_cols)

    # ---------------- TAB 3: 5年複合成長 (CAGR) ----------------
    with tab3:
        growth_cols = [
            "代號", "5年前價", "現價", "5年純漲幅",
            "5年 CAGR", "5年總股息", "含息總回報"
        ]
        growth_rows = []
        for r in results:
            growth_rows.append({
                "代號": r['symbol'],
                "5年前價": f"${r['price_5y_ago']:.2f}",
                "現價": f"${r['current_price']:.2f}",
                "5年純漲幅": f"{r['price_growth_5y']:+.2f}%",
                "5年 CAGR": f"{r['cagr_5y']:.2f}%",
                "5年總股息": f"${r['total_div_5y']:.2f}",
                "含息總回報": f"{r['total_return_5y']:+.2f}%"
            })
        render_sticky_table(growth_rows, growth_cols)

    # ---------------- TAB 4: 5年股息現金流 ----------------
    with tab4:
        div_cols = [
            "代號", "持股數", "5年每股息", "5年實收息",
            "預估年息", "股息率", "成本殖利率 (YOC)"
        ]
        div_rows = []
        for r in results:
            div_rows.append({
                "代號": r['symbol'],
                "持股數": f"{int(r['shares']):,}",
                "5年每股息": f"${r['total_div_5y']:.2f}",
                "5年實收息": f"${(r['total_div_5y'] * r['shares']):,.2f}",
                "預估年息": f"${r['annual_div_cash']:,.2f}",
                "股息率": f"{r['div_yield']:.2f}%",
                "成本殖利率 (YOC)": f"{r['yoc']:.2f}%"
            })
        
        tot_div_5y_cash = sum(r['total_div_5y'] * r['shares'] for r in results)
        tot_yoc_overall = (tot_annual_div / tot_cost * 100.0) if tot_cost > 0 else 0.0
        
        div_rows.append({
            "代號": "📊 TOTAL",
            "持股數": "-",
            "5年每股息": "-",
            "5年實收息": f"${tot_div_5y_cash:,.2f}",
            "預估年息": f"${tot_annual_div:,.2f}",
            "股息率": f"{tot_div_yield:.2f}%",
            "成本殖利率 (YOC)": f"{tot_yoc_overall:.2f}%"
        })
        render_sticky_table(div_rows, div_cols)

    # ---------------- 7. 最底層 Footnote 指標定義按鈕 ----------------
    st.markdown("<br><hr style='border: 0.5px solid #2d3748;'>", unsafe_allow_html=True)
    
    @st.dialog("📖 指標定義與計算邏輯說明 (Footnote)")
    def show_footnotes():
        st.markdown("""
        ### 1. 均線與週線動能體質 (Momentum & Trend)
        * **30週線 (30W MA)**：
          Stan Weinstein 階段分析法（Stage Analysis）的核心牛熊分水嶺（以過去 150 個交易日簡單均線計算）。若跌破 30W MA，代表中長線轉弱，需提高警覺。
        * **10 / 20 / 30 / 50 / 200 EMA (%)**：
          指數移動平均線（Exponential Moving Average）距離百分比。
          $$\\text{EMA \\%} = \\frac{\\text{現價} - \\text{EMA}}{\\text{EMA}} \\times 100\\%$$
          正數代表股價站在該均線之上，數值愈大短期動能愈強烈。
        * **30W 線動能趨勢 (走近 / 遠離)**：
          比較**「今日乖離率」**與**「兩週前 (10 個交易日前) 乖離率」**的絕對差距變化，以 **2.5%** 作為中長線過濾雜訊的基準閾值：
          * **🚀 擴大遠離 (強勢多頭)**：股價在 30W 線上方，且兩週內加速拋離均線超過 2.5%（主升浪動能增強）。
          * **🧲 回踩走近 (尋求支撐)**：股價在 30W 線上方，但兩週內向 30W 線回調收窄超過 2.5%（回踩測試均線支撐）。
          * **⏸️ 貼線平穩運行**：兩週內距離變化在 $\\pm 2.5\\%$ 以內（貼線窄幅橫盤整理）。
          * **📉 破線下殺 (加速遠離)**：股價跌破 30W 線，且負乖離持續擴大超過 2.5%。
          * **⤴️ 跌深反彈 (逼近30W)**：股價在 30W 線下方反彈回升，向 30W 線逼近。
        * **Stage 2 多頭續抱**：現價同時高於 30W MA 與 10 EMA，屬於標準主升多頭型態。

        ---

        ### 2. 5年長期成長指標 (Growth & Returns)
        * **5年 CAGR (年化複合成長率)**：
          衡量過去 5 年純股價的年均幾何增長速度（不含股息）：
          $$\\text{CAGR} = \\left( \\frac{\\text{現價}}{\\text{5年前股價}} \\right)^{\\frac{1}{5}} - 1$$
        * **5年含息總回報率 (%)**：
          將過去 5 年累計派發的所有現金股利加回目前股價，計算真實的整體投資回報：
          $$\\text{含息總回報} = \\frac{\\text{現價} - \\text{5年前股價} + \\text{5年每股股息總額}}{\\text{5年前股價}} \\times 100\\%$$

        ---

        ### 3. 現金流與股利收益率 (Dividends & Cashflow)
        * **5年實收總股息**：該股票過去 5 年派發的每股現金股息總和 $\\times$ 當前持股數量。
        * **預估年息收入**：依據近 1 年（365天內）該股票的官方派息總額 $\\times$ 持股數推算。
        * **當前股息率 (%)**：以當前市場現價計算的前瞻現金流收益率：
          $$\\text{當前股息率} = \\frac{\\text{全倉預估年股息總和}}{\\text{全倉總市值}} \\times 100\\%$$
        * **成本殖利率 (Yield on Cost, YOC)**：
          以你的**買入成本價**為基準計算的真實分紅收益率：
          $$\\text{YOC} = \\frac{\\text{全倉預估年股息總和}}{\\text{全倉總成本}} \\times 100\\%$$
        """)

    foot_col1, foot_col2, foot_col3 = st.columns([1, 2, 1])
    with foot_col2:
        if st.button("📖 查看指標定義與計算說明 (Footnote)", use_container_width=True):
            show_footnotes()

else:
    st.info("目前 Google Sheet 資料庫內無持股。請展開上方「買入 / 沽出持股管理」輸入您的第一檔港股。")
