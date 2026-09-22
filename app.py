import streamlit as st
import yfinance as yf
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, timedelta

# 1. Page Configuration (Mobile & Desktop Responsive)
st.set_page_config(
    page_title="Holding Overview",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Database Connection (Google Sheets via Streamlit Native Connection)
conn = st.connection("gsheets", type=GSheetsConnection)

def load_holdings():
    try:
        # Read directly from Google Sheet (ttl=0 ensures immediate freshness)
        df = conn.read(ttl="0s")
        if df is None or df.empty:
            return []
        
        # Clean and format columns
        df = df.dropna(subset=['symbol'])
        df['symbol'] = df['symbol'].astype(str).str.strip()
        df['symbol'] = df['symbol'].apply(lambda x: "".join(filter(str.isdigit, x)).zfill(4))
        df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0).astype(float)
        df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0.0).astype(float)
        
        # Filter valid records
        df = df[df['shares'] > 0]
        return df.to_dict(orient="records")
    except Exception as e:
        st.error(f"讀取 Google Sheets 資料庫失敗: {e}")
        return []

def save_holdings(holdings_list):
    try:
        if not holdings_list:
            # Keep table schema even when all stocks are sold
            empty_df = pd.DataFrame(columns=["symbol", "shares", "cost"])
            conn.update(data=empty_df)
        else:
            df = pd.DataFrame(holdings_list)
            # Ensure proper string/number types
            df['symbol'] = df['symbol'].astype(str).apply(lambda x: "".join(filter(str.isdigit, x)).zfill(4))
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0)
            df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0.0)
            conn.update(data=df)
        return True
    except Exception as e:
        st.error(f"儲存資料至 Google Sheets 失敗: {e}")
        return False

def format_hk_ticker(sym):
    clean = "".join(filter(str.isdigit, str(sym))).zfill(4)
    return f"{clean}.HK"

# 3. Financial Analytics Engine (Live Price, MAs, CAGR, Dividends)
@st.cache_data(ttl=300)
def fetch_stock_analytics(sym, shares, cost):
    ticker_str = format_hk_ticker(sym)
    try:
        t = yf.Ticker(ticker_str)
        hist = t.history(period="5y", interval="1d")
        
        if hist.empty:
            return None
        
        # Crucial NaN sanitation to avoid '$nan' errors during off-market hours
        closes = hist['Close'].dropna()
        closes = closes[closes > 0]
        
        if len(closes) < 10:
            return None

        # Fetch latest closing price
        curr_price = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) > 1 else curr_price
        
        # Fast-info fallback for real-time consistency
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

        # 52-Week High (last 250 trading sessions)
        last_250 = closes.tail(250)
        high_52w = float(last_250.max())
        dist_52w_pct = ((curr_price - high_52w) / high_52w) * 100.0 if high_52w > 0 else 0.0

        # EMA Matrix (10, 20, 30, 50, 200 EMA)
        ema10 = float(closes.ewm(span=10, adjust=False).mean().iloc[-1])
        ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema30 = float(closes.ewm(span=30, adjust=False).mean().iloc[-1])
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1])

        # 30-Week Simple Moving Average (150 trading days)
        ma30w_window = closes.tail(150)
        ma30w = float(ma30w_window.mean())
        dist_30w_pct = ((curr_price - ma30w) / ma30w) * 100.0 if ma30w > 0 else 0.0

        # Stan Weinstein Stage Analysis Diagnosis
        if curr_price >= ma30w and curr_price >= ema10:
            trend_status = "🟢 Stage 2 多頭續抱"
        elif curr_price >= ma30w and curr_price < ema10:
            trend_status = "🟡 短線拉回整理"
        else:
            trend_status = "🔴 跌破 30W 線警示"

        # 5-Year Capital Appreciation & CAGR
        price_5y_ago = float(closes.iloc[0])
        price_growth_5y = ((curr_price - price_5y_ago) / price_5y_ago) * 100.0 if price_5y_ago > 0 else 0.0
        cagr_5y = (((curr_price / price_5y_ago) ** (1.0 / 5.0) - 1.0) * 100.0) if (price_5y_ago > 0 and curr_price > 0) else 0.0

        # 5-Year Dividend History & Annual Cash Flow Run-Rate
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

        stock_name = sym
        try:
            stock_name = t.fast_info.name or t.info.get('shortName') or sym
        except Exception:
            pass

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
            "ema10_pct": ((curr_price - ema10) / ema10) * 100.0 if ema10 > 0 else 0.0,
            "ema20_pct": ((curr_price - ema20) / ema20) * 100.0 if ema20 > 0 else 0.0,
            "ema30_pct": ((curr_price - ema30) / ema30) * 100.0 if ema30 > 0 else 0.0,
            "ema50_pct": ((curr_price - ema50) / ema50) * 100.0 if ema50 > 0 else 0.0,
            "ema200_pct": ((curr_price - ema200) / ema200) * 100.0 if ema200 > 0 else 0.0,
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

# Load persistent portfolio from Google Sheets
holdings = load_holdings()

# 4. Header & Top Controls
col_title, col_btn = st.columns([3, 1])
with col_title:
    st.title("💼 Holding Overview")
    st.caption("雲端資料庫同步 • 港股即時均線 • 5年股息與動能")

with col_btn:
    st.write(" ")
    if st.button("🔄 立即重新整理", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 5. Buy / Sell Trade Management Area
with st.expander("⚙️ 買入 / 沽出持股管理 (點擊展開)", expanded=(len(holdings) == 0)):
    m_col1, m_col2 = st.columns(2)
    
    # Buy / Add Form
    with m_col1:
        st.subheader("➕ 買入 / 新增持股")
        with st.form("buy_form"):
            in_sym = st.text_input("港股代號 (例: 0700, 0005, 0941)").strip()
            in_shares = st.number_input("持有股數", min_value=1, step=100, value=500)
            in_cost = st.number_input("買入成本均價 (HKD，可選填)", min_value=0.0, step=1.0, value=0.0)
            btn_buy = st.form_submit_button("確認新增持股", use_container_width=True)
            
            if btn_buy and in_sym:
                clean_sym = "".join(filter(str.isdigit, in_sym)).zfill(4)
                
                # Check if ticker already exists
                existing = next((item for item in holdings if item["symbol"] == clean_sym), None)
                if existing:
                    existing["shares"] += in_shares
                    if in_cost > 0:
                        existing["cost"] = in_cost
                else:
                    holdings.append({
                        "symbol": clean_sym,
                        "shares": in_shares,
                        "cost": in_cost
                    })
                
                if save_holdings(holdings):
                    st.cache_data.clear()
                    st.success(f"已成功買入並同步至 Google Sheets: {clean_sym}！")
                    st.rerun()

    # Sell / Delete Form
    with m_col2:
        st.subheader("➖ 沽出 / 刪除持股")
        if holdings:
            symbol_list = [h["symbol"] for h in holdings]
            del_sym = st.selectbox("選擇要沽出的股票代號", symbol_list)
            
            if st.button("確認全數沽出並自雲端刪除", type="primary", use_container_width=True):
                updated_holdings = [h for h in holdings if h["symbol"] != del_sym]
                if save_holdings(updated_holdings):
                    st.cache_data.clear()
                    st.success(f"已成功自 Google Sheets 沽出並刪除 {del_sym}！")
                    st.rerun()
        else:
            st.info("目前雲端資料庫內無任何持股。")

# 6. Fetch & Calculate Live Metrics
results = []
if holdings:
    with st.spinner("正在自港交所與雲端資料庫同步數據..."):
        for h in holdings:
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

    # KPI Banner
    kpi1, kpi2 = st.columns(2)
    kpi1.metric("總持股市值", f"${tot_val:,.2f} HKD", f"總成本: ${tot_cost:,.2f}")
    kpi2.metric("今日總損益", f"${tot_daily_pl:+,.2f}", f"{tot_daily_pct:+.2f}%")

    kpi3, kpi4 = st.columns(2)
    kpi3.metric("組合股息率", f"{tot_div_yield:.2f}%", f"年股息現金流: ${tot_annual_div:,.2f}")
    kpi4.metric("30W均線動能體質", f"{above_30w_count}/{len(results)} 檔線上", "Stage 2 續抱" if above_30w_count == len(results) else "注意破線標的")

    st.markdown("---")

    # 4 Dedicated Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📅 每日即時監控", 
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
                "漲跌幅 (%)": f"{r['daily_pct']:+.2f}%",
                "52W最高價": f"${r['high_52w']:.2f}",
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

    with tab3:
        growth_rows = []
        for r in results:
            growth_rows.append({
                "代號": r['symbol'],
                "5年前起算價": f"${r['price_5y_ago']:.2f}",
                "現價": f"${r['current_price']:.2f}",
                "5年純漲幅": f"{r['price_growth_5y']:+.2f}%",
                "5年 CAGR": f"{r['cagr_5y']:.2f}%",
                "5年每股股息總額": f"${r['total_div_5y']:.2f}",
                "含息總回報 %": f"{r['total_return_5y']:+.2f}%"
            })
        st.dataframe(pd.DataFrame(growth_rows), use_container_width=True, hide_index=True)

    with tab4:
        div_rows = []
        for r in results:
            div_rows.append({
                "代號": r['symbol'],
                "持股數": f"{r['shares']:,}",
                "5年每股累計股息": f"${r['total_div_5y']:.2f}",
                "5年實收總股息": f"${(r['total_div_5y'] * r['shares']):,.2f}",
                "預估年息收入": f"${r['annual_div_cash']:,.2f}",
                "當前股息率 (%)": f"{r['div_yield']:.2f}%",
                "成本殖利率 (YOC)": f"{r['yoc']:.2f}%"
            })
        st.dataframe(pd.DataFrame(div_rows), use_container_width=True, hide_index=True)
else:
    st.info("目前資料庫內尚無持股。請展開上方的「買入 / 沽出持股管理」輸入您的第一檔港股。")
