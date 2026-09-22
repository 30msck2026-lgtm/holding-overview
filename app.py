import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, timedelta

# 頁面配置
st.set_page_config(
    page_title="Holding Overview",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DATA_FILE = "portfolio_data.json"

DEFAULT_HOLDINGS = [
    {"symbol": "0700", "shares": 100, "cost": 380.0},
    {"symbol": "0005", "shares": 400, "cost": 65.0},
    {"symbol": "0941", "shares": 500, "cost": 70.0}
]

def load_holdings():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data:
                    return data
        except Exception:
            pass
    return DEFAULT_HOLDINGS

def save_holdings(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def format_hk_ticker(sym):
    clean = "".join(filter(str.isdigit, str(sym)))
    while len(clean) < 4:
        clean = "0" + clean
    return f"{clean}.HK"

@st.cache_data(ttl=300)
def fetch_stock_analytics(sym, shares, cost):
    ticker_str = format_hk_ticker(sym)
    try:
        t = yf.Ticker(ticker_str)
        hist = t.history(period="5y", interval="1d")
        if hist.empty or len(hist) < 10:
            return None
        
        closes = hist['Close']
        curr_price = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) > 1 else curr_price
        daily_chg = curr_price - prev_close
        daily_pct = (daily_chg / prev_close) * 100.0

        last_250 = closes.tail(250)
        high_52w = float(last_250.max())
        dist_52w_pct = ((curr_price - high_52w) / high_52w) * 100.0

        ema10 = float(closes.ewm(span=10, adjust=False).mean().iloc[-1])
        ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema30 = float(closes.ewm(span=30, adjust=False).mean().iloc[-1])
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1])

        ma30w_window = closes.tail(150)
        ma30w = float(ma30w_window.mean())
        dist_30w_pct = ((curr_price - ma30w) / ma30w) * 100.0

        if curr_price >= ma30w and curr_price >= ema10:
            trend_status = "🟢 Stage 2 多頭續抱"
        elif curr_price >= ma30w and curr_price < ema10:
            trend_status = "🟡 短線拉回整理"
        else:
            trend_status = "🔴 跌破 30W 線警示"

        price_5y_ago = float(closes.iloc[0])
        price_growth_5y = ((curr_price - price_5y_ago) / price_5y_ago) * 100.0
        cagr_5y = ((curr_price / price_5y_ago) ** (1.0 / 5.0) - 1.0) * 100.0

        divs = t.dividends
        total_div_5y = 0.0
        latest_annual_div = 0.0
        
        if not divs.empty:
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
    except Exception:
        return None

if "holdings" not in st.session_state:
    st.session_state.holdings = load_holdings()

# 頁面標題與重整按鈕
col_title, col_btn = st.columns([3, 1])
with col_title:
    st.title("💼 Holding Overview")
    st.caption("港股自動追蹤 • 均線動能體質 • 5年股息與成長")

with col_btn:
    st.write(" ")
    if st.button("🔄 立即重新整理", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 買入與沽出管理區（常駐於上方折疊選單中）
with st.expander("⚙️ 買入 / 沽出持股管理 (點擊展開)", expanded=(len(st.session_state.holdings) == 0)):
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        st.subheader("➕ 買入 / 新增持股")
        with st.form("add_form"):
            in_sym = st.text_input("港股代號 (例: 0700, 0005, 0941)").strip()
            in_shares = st.number_input("持有股數", min_value=1, step=100, value=100)
            in_cost = st.number_input("買入成本均價 (HKD，可留空)", min_value=0.0, step=1.0, value=0.0)
            btn_submit = st.form_submit_button("確認新增持股", use_container_width=True)
            
            if btn_submit and in_sym:
                clean_sym = "".join(filter(str.isdigit, in_sym))
                while len(clean_sym) < 4:
                    clean_sym = "0" + clean_sym
                
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
                st.success(f"已加入 {clean_sym}！")
                st.rerun()

    with m_col2:
        st.subheader("➖ 沽出 / 刪除持股")
        if st.session_state.holdings:
            del_sym = st.selectbox("選擇要沽出的代號", [h["symbol"] for h in st.session_state.holdings])
            if st.button("確認全數沽出並刪除", type="primary", use_container_width=True):
                st.session_state.holdings = [h for h in st.session_state.holdings if h["symbol"] != del_sym]
                save_holdings(st.session_state.holdings)
                st.cache_data.clear()
                st.success(f"已沽出 {del_sym}！")
                st.rerun()
        else:
            st.info("暫無可沽出標的")

# 抓取並運算數據
results = []
with st.spinner("正在自動連線更新行情..."):
    for h in st.session_state.holdings:
        res = fetch_stock_analytics(h['symbol'], h['shares'], h.get('cost', 0))
        if res:
            results.append(res)

if results:
    tot_val = sum(r['market_val'] for r in results)
    tot_cost = sum(r['cost'] * r['shares'] for r in results)
    tot_daily_pl = sum(r['daily_chg'] * r['shares'] for r in results)
    tot_prev_val = tot_val - tot_daily_pl
    tot_daily_pct = (tot_daily_pl / tot_prev_val * 100.0) if tot_prev_val > 0 else 0.0
    tot_annual_div = sum(r['annual_div_cash'] for r in results)
    tot_div_yield = (tot_annual_div / tot_val * 100.0) if tot_val > 0 else 0.0
    above_30w_count = sum(1 for r in results if r['dist_30w_pct'] >= 0)

    kpi1, kpi2 = st.columns(2)
    kpi1.metric("總持股市值", f"${tot_val:,.2f} HKD", f"總成本: ${tot_cost:,.2f}")
    kpi2.metric("今日總損益", f"${tot_daily_pl:+,.2f}", f"{tot_daily_pct:+.2f}%")

    kpi3, kpi4 = st.columns(2)
    kpi3.metric("組合股息率", f"{tot_div_yield:.2f}%", f"年股息: ${tot_annual_div:,.2f}")
    kpi4.metric("30W均線動能", f"{above_30w_count}/{len(results)} 檔線上", "Stage 2 續抱" if above_30w_count == len(results) else "注意破線標的")

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📅 每日監控", 
        "🌊 均線與週線動能", 
        "📈 5年複合成長 (CAGR)", 
        "💰 5年股息現金流"
    ])

    with tab1:
        daily_rows = []
        for r in results:
            daily_rows.append({
                "代號": r['symbol'],
                "名稱": r['name'],
                "現價": f"${r['current_price']:.2f}",
                "今日漲跌": f"{r['daily_chg']:+.2f}",
                "漲跌幅": f"{r['daily_pct']:+.2f}%",
                "52W最高": f"${r['high_52w']:.2f}",
                "距52W高點": f"{r['dist_52w_pct']:.1f}%",
                "持股數": f"{r['shares']:,}",
                "市值 (HKD)": f"${r['market_val']:,.2f}"
            })
        st.dataframe(pd.DataFrame(daily_rows), use_container_width=True, hide_index=True)

    with tab2:
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
                "距30W %": f"{r['dist_30w_pct']:+.2f}%",
                "趨勢狀態": r['trend_status']
            })
        st.dataframe(pd.DataFrame(momentum_rows), use_container_width=True, hide_index=True)

    with tab3:
        growth_rows = []
        for r in results:
            growth_rows.append({
                "代號": r['symbol'],
                "5年前起算價": f"${r['price_5y_ago']:.2f}",
                "現價": f"${r['current_price']:.2f}",
                "5年純漲幅": f"{r['price_growth_5y']:+.2f}%",
                "5年 CAGR": f"{r['cagr_5y']:.2f}%",
                "5年每股股息": f"${r['total_div_5y']:.2f}",
                "含息總回報": f"{r['total_return_5y']:+.2f}%"
            })
        st.dataframe(pd.DataFrame(growth_rows), use_container_width=True, hide_index=True)

    with tab4:
        div_rows = []
        for r in results:
            div_rows.append({
                "代號": r['symbol'],
                "持股數": f"{r['shares']:,}",
                "5年每股股息": f"${r['total_div_5y']:.2f}",
                "5年實收股息": f"${(r['total_div_5y'] * r['shares']):,.2f}",
                "預估年息": f"${r['annual_div_cash']:,.2f}",
                "當前股息率": f"{r['div_yield']:.2f}%",
                "成本殖利率(YOC)": f"{r['yoc']:.2f}%"
            })
        st.dataframe(pd.DataFrame(div_rows), use_container_width=True, hide_index=True)
else:
    st.info("請點擊上方的「⚙️ 買入 / 沽出持股管理」輸入你的第一檔港股。")
