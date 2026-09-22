import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta

# 頁面基本配置 (手機與電腦自適應)
st.set_page_config(
    page_title="Holding Overview",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DATA_FILE = "portfolio_data.json"

# 預設示範持股
DEFAULT_HOLDINGS = [
    {"symbol": "0700", "shares": 100, "cost": 380.0},
    {"symbol": "0005", "shares": 400, "cost": 65.0},
    {"symbol": "0941", "shares": 500, "cost": 70.0}
]

# 讀取本地持股資料
def load_holdings():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_HOLDINGS
    return DEFAULT_HOLDINGS

# 儲存持股資料
def save_holdings(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 格式化港股代號 (例: 700 -> 0700.HK)
def format_hk_ticker(sym):
    clean = "".join(filter(str.isdigit, str(sym)))
    while len(clean) < 4:
        clean = "0" + clean
    return f"{clean}.HK"

# 抓取單檔股票完整數據與計算技術指標 (快取 10 分鐘，加快手機載入速度)
@st.cache_data(ttl=600)
def fetch_stock_analytics(sym, shares, cost):
    ticker_str = format_hk_ticker(sym)
    t = yf.Ticker(ticker_str)
    
    # 抓取 5 年歷史日 K 線
    hist = t.history(period="5y", interval="1d")
    if hist.empty or len(hist) < 30:
        return None
    
    closes = hist['Close']
    curr_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) > 1 else curr_price
    daily_chg = curr_price - prev_close
    daily_pct = (daily_chg / prev_close) * 100.0

    # 52 週 (250 個交易日) 最高點
    last_250 = closes.tail(250)
    high_52w = float(last_250.max())
    dist_52w_pct = ((curr_price - high_52w) / high_52w) * 100.0

    # EMA 均線矩陣
    ema10 = float(closes.ewm(span=10, adjust=False).mean().iloc[-1])
    ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
    ema30 = float(closes.ewm(span=30, adjust=False).mean().iloc[-1])
    ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1])

    # 30 週簡單移動平均線 (150 個交易日)
    ma30w_window = closes.tail(150)
    ma30w = float(ma30w_window.mean())
    dist_30w_pct = ((curr_price - ma30w) / ma30w) * 100.0

    # 趨勢動能狀態 (Stan Weinstein Stage 2)
    if curr_price >= ma30w and curr_price >= ema10:
        trend_status = "🟢 Stage 2 多頭續抱"
    elif curr_price >= ma30w and curr_price < ema10:
        trend_status = "🟡 短線拉回整理"
    else:
        trend_status = "🔴 跌破 30W 線警示"

    # 5 年複合增長 (CAGR)
    price_5y_ago = float(closes.iloc[0])
    price_growth_5y = ((curr_price - price_5y_ago) / price_5y_ago) * 100.0
    cagr_5y = ((curr_price / price_5y_ago) ** (1.0 / 5.0) - 1.0) * 100.0

    # 股息歷史與預估年現金流
    divs = t.dividends
    total_div_5y = 0.0
    latest_annual_div = 0.0
    
    if not divs.empty:
        # 去除時區以利日期比較
        div_df = divs.reset_index()
        div_df['Date'] = pd.to_datetime(div_df['Date']).dt.tz_localize(None)
        cutoff_5y = datetime.now() - timedelta(days=5*365)
        cutoff_1y = datetime.now() - timedelta(days=365)
        
        div_5y = div_df[div_df['Date'] >= cutoff_5y]
        total_div_5y = float(div_5y['Dividends'].sum())
        
        div_1y = div_df[div_df['Date'] >= cutoff_1y]
        latest_annual_div = float(div_1y['Dividends'].sum())

    total_return_5y = ((curr_price - price_5y_ago + total_div_5y) / price_5y_ago) * 100.0
    annual_div_cash = latest_annual_div * shares
    div_yield = (latest_annual_div / curr_price * 100.0) if curr_price > 0 else 0.0
    yoc = (latest_annual_div / cost * 100.0) if cost > 0 else div_yield
    market_val = curr_price * shares

    stock_name = t.info.get('shortName') or sym

    return {
        "symbol": sym,
        "name": stock_name,
        "shares": shares,
        "cost": cost,
        "current_price": curr_price,
        "daily_chg": daily_chg,
        "daily_pct": daily_pct,
        "market_val": market_val,
        "high_52w": high_52w,
        "dist_52w_pct": dist_52w_pct,
        "ema10_pct": ((curr_price - ema10) / ema10) * 100.0,
        "ema20_pct": ((curr_price - ema20) / ema20) * 100.0,
        "ema30_pct": ((curr_price - ema30) / ema30) * 100.0,
        "ema50_pct": ((curr_price - ema50) / ema50) * 100.0,
        "ema200_pct": ((curr_price - ema200) / ema200) * 100.0,
        "ma30w": ma30w,
        "dist_30w_pct": dist_30w_pct,
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

# 初始化狀態
if "holdings" not in st.session_state:
    st.session_state.holdings = load_holdings()

# 頂部控制欄
header_col1, header_col2 = st.columns([3, 1])
with header_col1:
    st.title("💼 Holding Overview")
    st.caption("港股自動追蹤 • 均線動能體質 • 5年股息與成長")

with header_col2:
    st.write(" ")
    if st.button("🔄 立即重新整理", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 載入所有數據
results = []
with st.spinner("正在自動更新港股現價、均線矩陣與歷史派息..."):
    for h in st.session_state.holdings:
        res = fetch_stock_analytics(h['symbol'], h['shares'], h.get('cost', 0))
        if res:
            results.append(res)

if not results:
    st.warning("目前尚無持股數據，請於下方新增持股。")
    st.stop()

# 頂部 KPI 數據統計
tot_val = sum(r['market_val'] for r in results)
tot_cost = sum(r['cost'] * r['shares'] for r in results)
tot_daily_pl = sum(r['daily_chg'] * r['shares'] for r in results)
tot_prev_val = tot_val - tot_daily_pl
tot_daily_pct = (tot_daily_pl / tot_prev_val * 100.0) if tot_prev_val > 0 else 0.0
tot_annual_div = sum(r['annual_div_cash'] for r in results)
tot_div_yield = (tot_annual_div / tot_val * 100.0) if tot_val > 0 else 0.0
above_30w_count = sum(1 for r in results if r['dist_30w_pct'] >= 0)

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("總持股市值", f"${tot_val:,.2f} HKD", f"總成本: ${tot_cost:,.2f}")
kpi2.metric("今日總損益", f"${tot_daily_pl:+,.2f}", f"{tot_daily_pct:+.2f}%")
kpi3.metric("組合股息率", f"{tot_div_yield:.2f}%", f"年股息: ${tot_annual_div:,.2f}")
kpi4.metric("30W均線動能", f"{above_30w_count} / {len(results)} 檔線上", "Stage 2 續抱" if above_30w_count == len(results) else "注意破線標的")

st.markdown("---")

# 四大功能分頁
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📅 每日即時監控", 
    "🌊 週線與均線動能", 
    "📈 5年複合成長 (CAGR)", 
    "💰 股利現金流庫",
    "⚙️ 買入 / 沽出管理"
])

# ----------------- TAB 1: 每日即時 -----------------
with tab1:
    daily_rows = []
    for r in results:
        daily_rows.append({
            "代號": r['symbol'],
            "名稱": r['name'],
            "現價 (HKD)": f"${r['current_price']:.2f}",
            "今日漲跌": f"{r['daily_chg']:+.2f}",
            "漲跌幅 (%)": f"{r['daily_pct']:+.2f}%",
            "52W最高價": f"${r['high_52w']:.2f}",
            "距52W高點 (%)": f"{r['dist_52w_pct']:.1f}%",
            "持股數": f"{r['shares']:,}",
            "當前市值": f"${r['market_val']:,.2f}"
        })
    st.dataframe(pd.DataFrame(daily_rows), use_container_width=True, hide_index=True)

# ----------------- TAB 2: 週線與均線動能 -----------------
with tab2:
    st.caption("基準：10/20/30/50/200 日 EMA 與 30 週線 (Stan Weinstein 系統)")
    momentum_rows = []
    for r in results:
        momentum_rows.append({
            "代號": r['symbol'],
            "現價": f"${r['current_price']:.2f}",
            "10 EMA %": f"{r['ema10_pct']:+.2f}%",
            "20 EMA %": f"{r['ema20_pct']:+.2f}%",
            "30 EMA %": f"{r['ema30_pct']:+.2f}%",
            "50 EMA %": f"{r['ema50_pct']:+.2f}%",
            "200 EMA %": f"{r['ema200_pct']:+.2f}%",
            "30W MA": f"${r['ma30w']:.2f}",
            "距 30W MA %": f"{r['dist_30w_pct']:+.2f}%",
            "趨勢狀態": r['trend_status']
        })
    st.dataframe(pd.DataFrame(momentum_rows), use_container_width=True, hide_index=True)

# ----------------- TAB 3: 5年成長與總報酬 -----------------
with tab3:
    growth_rows = []
    for r in results:
        growth_rows.append({
            "代號": r['symbol'],
            "5年前起算價": f"${r['price_5y_ago']:.2f}",
            "當前現價": f"${r['current_price']:.2f}",
            "5年純股價漲幅": f"{r['price_growth_5y']:+.2f}%",
            "5年 CAGR (年化)": f"{r['cagr_5y']:.2f}%",
            "5年每股股息總額": f"${r['total_div_5y']:.2f}",
            "含息總報酬率 %": f"{r['total_return_5y']:+.2f}%"
        })
    st.dataframe(pd.DataFrame(growth_rows), use_container_width=True, hide_index=True)

# ----------------- TAB 4: 5年股息現金流 -----------------
with tab4:
    div_rows = []
    for r in results:
        div_rows.append({
            "代號": r['symbol'],
            "持股數": f"{r['shares']:,}",
            "5年每股累計股息": f"${r['total_div_5y']:.2f}",
            "5年實收總股息": f"${(r['total_div_5y'] * r['shares']):,.2f}",
            "預估年股息收入": f"${r['annual_div_cash']:,.2f}",
            "當前股息率 (%)": f"{r['div_yield']:.2f}%",
            "成本殖利率 (YOC)": f"{r['yoc']:.2f}%"
        })
    st.dataframe(pd.DataFrame(div_rows), use_container_width=True, hide_index=True)

# ----------------- TAB 5: 買入與沽出管理 -----------------
with tab5:
    col_add, col_del = st.columns(2)
    
    with col_add:
        st.subheader("➕ 買入 / 新增持股")
        with st.form("add_stock_form"):
            in_sym = st.text_input("港股代號 (例: 0700, 0005, 0941)", "").strip()
            in_shares = st.number_input("持有股數", min_value=1, step=100, value=100)
            in_cost = st.number_input("買入成本均價 (HKD，可選)", min_value=0.0, step=1.0, value=0.0)
            btn_add = st.form_submit_button("確認新增 / 買入")
            
            if btn_add and in_sym:
                clean_sym = "".join(filter(str.isdigit, in_sym))
                # 檢查是否已存在
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
                save_holdings(st.session_state.holdings)
                st.cache_data.clear()
                st.success(f"已成功加入 {clean_sym}！")
                st.rerun()

    with col_del:
        st.subheader("➖ 沽出 / 刪除持股")
        if st.session_state.holdings:
            del_sym = st.selectbox("選擇要沽出的持股代號", [h["symbol"] for h in st.session_state.holdings])
            if st.button("確認全數沽出並刪除", type="primary"):
                st.session_state.holdings = [h for h in st.session_state.holdings if h["symbol"] != del_sym]
                save_holdings(st.session_state.holdings)
                st.cache_data.clear()
                st.success(f"已沽出並刪除 {del_sym}！")
                st.rerun()
