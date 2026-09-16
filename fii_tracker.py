from datetime import datetime
import io
import os
import pandas as pd
import requests

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = "fii_position_history.csv"

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/",
}


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_API_TOKEN or TELEGRAM_CHAT_ID is missing."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30
    )

    if not response.ok:
        raise RuntimeError(
            f"Telegram API returned {response.status_code}: {response.text}"
        )

    print("Telegram notification sent successfully.")


# ============================================================
# GET FII DATA FROM NSE
# ============================================================

def get_fii_data_from_nse():
    today = datetime.now().strftime("%d%m%Y")

    url = (
        f"https://archives.nseindia.com/content/"
        f"nsccl/fao_participant_oi_{today}.csv"
    )

    try:
        response = requests.get(
            url,
            headers=NSE_HEADERS,
            timeout=30
        )

        if response.status_code != 200:
            print("NSE FII file not available.")
            return None

        df = pd.read_csv(
            io.StringIO(response.text),
            skiprows=1
        )

        df.columns = df.columns.str.strip()

        if "Client Type" not in df.columns:
            print("Unexpected NSE file format.")
            return None

        df["Client Type"] = (
            df["Client Type"]
            .astype(str)
            .str.strip()
        )

        fii_rows = df[df["Client Type"] == "FII"]

        if fii_rows.empty:
            print("FII row not found.")
            return None

        fii = fii_rows.iloc[0]

        long_cnt = float(fii["Future Index Long"])
        short_cnt = float(fii["Future Index Short"])

        total = long_cnt + short_cnt

        long_pct = (
            long_cnt / total * 100
            if total > 0
            else 0
        )

        short_pct = (
            short_cnt / total * 100
            if total > 0
            else 0
        )

        long_short_ratio = (
            long_cnt / short_cnt
            if short_cnt > 0
            else 0
        )

        net_contracts = long_cnt - short_cnt

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "fii_long": int(long_cnt),
            "fii_short": int(short_cnt),
            "long_pct": long_pct,
            "short_pct": short_pct,
            "long_short_ratio": long_short_ratio,
            "net_contracts": int(net_contracts),
        }

    except Exception as e:
        print(f"Error fetching NSE FII data: {e}")
        return None


# ============================================================
# GET NIFTY DATA
# ============================================================

def get_nifty_data():
    """
    Uses Yahoo Finance chart API for NIFTY 50 (^NSEI).

    This is only used for price/history.
    """

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        "^NSEI?range=3mo&interval=1d"
    )

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
            timeout=30
        )

        if response.status_code != 200:
            print("Unable to fetch Nifty data.")
            return None

        data = response.json()

        result = data["chart"]["result"][0]

        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]

        rows = []

        for timestamp, close in zip(timestamps, closes):

            if close is None:
                continue

            date = datetime.fromtimestamp(timestamp).strftime(
                "%Y-%m-%d"
            )

            rows.append({
                "date": date,
                "nifty_close": float(close)
            })

        nifty_df = pd.DataFrame(rows)

        if nifty_df.empty:
            return None

        nifty_df = nifty_df.drop_duplicates(
            subset=["date"]
        )

        nifty_df = nifty_df.sort_values("date")

        return nifty_df

    except Exception as e:
        print(f"Error fetching Nifty data: {e}")
        return None


# ============================================================
# LOAD HISTORY
# ============================================================

def load_history():

    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame()

    try:
        df = pd.read_csv(HISTORY_FILE)

        if df.empty:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(
            df["date"]
        )

        return df.sort_values("date")

    except Exception as e:
        print(f"Error loading history: {e}")
        return pd.DataFrame()


# ============================================================
# SAVE HISTORY
# ============================================================

def save_history(df):

    df = df.copy()

    df["date"] = pd.to_datetime(df["date"])

    df = df.sort_values("date")

    # One record per date
    df = df.drop_duplicates(
        subset=["date"],
        keep="last"
    )

    df.to_csv(
        HISTORY_FILE,
        index=False
    )

    print(f"History saved: {HISTORY_FILE}")


# ============================================================
# CALCULATE CHANGES
# ============================================================

def calculate_changes(df):

    if df.empty:
        return None

    df = df.sort_values("date").reset_index(drop=True)

    latest = df.iloc[-1]

    result = {
        "current": latest
    }

    # --------------------------------------------------------
    # 1 Trading Day
    # --------------------------------------------------------

    if len(df) >= 2:

        previous = df.iloc[-2]

        result["1d"] = {
            "net": latest["net_contracts"] - previous["net_contracts"],
            "long": latest["fii_long"] - previous["fii_long"],
            "short": latest["fii_short"] - previous["fii_short"],
            "long_pct": latest["long_pct"] - previous["long_pct"],
        }

    # --------------------------------------------------------
    # 5 Trading Days
    # --------------------------------------------------------

    if len(df) >= 6:

        previous = df.iloc[-6]

        result["5d"] = {
            "net": latest["net_contracts"] - previous["net_contracts"],
            "long": latest["fii_long"] - previous["fii_long"],
            "short": latest["fii_short"] - previous["fii_short"],
            "long_pct": latest["long_pct"] - previous["long_pct"],
        }

    # --------------------------------------------------------
    # 20 Trading Days
    # --------------------------------------------------------

    if len(df) >= 21:

        previous = df.iloc[-21]

        result["20d"] = {
            "net": latest["net_contracts"] - previous["net_contracts"],
            "long": latest["fii_long"] - previous["fii_long"],
            "short": latest["fii_short"] - previous["fii_short"],
            "long_pct": latest["long_pct"] - previous["long_pct"],
        }

    return result


# ============================================================
# NIFTY PERFORMANCE
# ============================================================

def calculate_nifty_changes(nifty_df):

    if nifty_df is None or nifty_df.empty:
        return None

    nifty_df = nifty_df.sort_values("date").reset_index(drop=True)

    latest = nifty_df.iloc[-1]

    result = {
        "price": latest["nifty_close"]
    }

    # 1 trading day
    if len(nifty_df) >= 2:

        previous = nifty_df.iloc[-2]

        result["1d"] = (
            latest["nifty_close"] /
            previous["nifty_close"] - 1
        ) * 100

    # 5 trading days
    if len(nifty_df) >= 6:

        previous = nifty_df.iloc[-6]

        result["5d"] = (
            latest["nifty_close"] /
            previous["nifty_close"] - 1
        ) * 100

    # 20 trading days
    if len(nifty_df) >= 21:

        previous = nifty_df.iloc[-21]

        result["20d"] = (
            latest["nifty_close"] /
            previous["nifty_close"] - 1
        ) * 100

    return result


# ============================================================
# FORMAT NUMBER
# ============================================================

def fmt_number(value):

    if pd.isna(value):
        return "N/A"

    return f"{int(value):,}"


def fmt_change(value):

    if value is None:
        return "N/A"

    if value > 0:
        return f"+{value:,.0f}"

    return f"{value:,.0f}"


def fmt_pct(value):

    if value is None:
        return "N/A"

    if value > 0:
        return f"+{value:.2f}%"

    return f"{value:.2f}%"


# ============================================================
# POSITIONING INTERPRETATION
# ============================================================

def get_positioning_signal(changes):

    if not changes:
        return "⚪ Insufficient history"

    current = changes["current"]

    net = current["net_contracts"]

    # Current net positioning
    if net > 0:
        base = "🟢 Net Long"
    elif net < 0:
        base = "🔴 Net Short"
    else:
        base = "⚪ Neutral"

    # Look at 5-day change if available
    if "5d" in changes:

        net_change = changes["5d"]["net"]

        if net_change > 0:
            trend = "FII positioning improving"
        elif net_change < 0:
            trend = "FII positioning weakening"
        else:
            trend = "FII positioning stable"

        return f"{base}\n{trend}"

    return base


# ============================================================
# CREATE TELEGRAM MESSAGE
# ============================================================

def create_message(fii_df, nifty_df):

    changes = calculate_changes(fii_df)

    if not changes:
        return None

    current = changes["current"]

    nifty = calculate_nifty_changes(nifty_df)

    date_display = pd.to_datetime(
        current["date"]
    ).strftime("%d-%b-%Y")

    # --------------------------------------------------------
    # FII
    # --------------------------------------------------------

    message = (
        f"📊 *FII POSITIONING DASHBOARD*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🗓 *Date:* {date_display}\n\n"

        f"🔥 *INDEX FUTURES*\n"
        f"Long: `{fmt_number(current['fii_long'])}`\n"
        f"Short: `{fmt_number(current['fii_short'])}`\n"
        f"Long %: `{current['long_pct']:.2f}%`\n"
        f"Short %: `{current['short_pct']:.2f}%`\n"
        f"L/S Ratio: `{current['long_short_ratio']:.2f}`\n"
        f"Net Contracts: `{fmt_number(current['net_contracts'])}`\n\n"
    )

    # --------------------------------------------------------
    # Changes
    # --------------------------------------------------------

    message += "📈 *POSITION CHANGES*\n"

    if "1d" in changes:
        message += (
            f"*1D Net:* `{fmt_change(changes['1d']['net'])}`\n"
            f"*1D Long %:* `{fmt_pct(changes['1d']['long_pct'])}`\n"
        )
    else:
        message += "*1D:* `Not enough history`\n"

    if "5d" in changes:
        message += (
            f"*5D Net:* `{fmt_change(changes['5d']['net'])}`\n"
            f"*5D Long %:* `{fmt_pct(changes['5d']['long_pct'])}`\n"
        )
    else:
        message += "*5D:* `Not enough history`\n"

    if "20d" in changes:
        message += (
            f"*20D Net:* `{fmt_change(changes['20d']['net'])}`\n"
            f"*20D Long %:* `{fmt_pct(changes['20d']['long_pct'])}`\n"
        )
    else:
        message += "*20D:* `Not enough history`\n"

    # --------------------------------------------------------
    # NIFTY
    # --------------------------------------------------------

    if nifty:

        message += (
            f"\n📉 *NIFTY 50*\n"
            f"Price: `{nifty['price']:,.2f}`\n"
        )

        if "1d" in nifty:
            message += f"1D: `{fmt_pct(nifty['1d'])}`\n"

        if "5d" in nifty:
            message += f"5D: `{fmt_pct(nifty['5d'])}`\n"

        if "20d" in nifty:
            message += f"20D: `{fmt_pct(nifty['20d'])}`\n"

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    signal = get_positioning_signal(changes)

    message += (
        f"\n🧭 *POSITIONING STATUS*\n"
        f"{signal}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *For analysis only — not a trading signal.*"
    )

    return message


# ============================================================
# MAIN
# ============================================================

def get_fii_data():

    print("Fetching FII data...")

    fii_today = get_fii_data_from_nse()

    if fii_today is None:

        send_telegram_message(
            f"⚠️ *FII Data Alert*\n\n"
            f"NSE FII participant-OI data is not available "
            f"for {datetime.now().strftime('%d-%b-%Y')}."
        )

        return

    # --------------------------------------------------------
    # Load old FII history
    # --------------------------------------------------------

    history = load_history()

    today_df = pd.DataFrame([fii_today])

    if not history.empty:

        combined = pd.concat(
            [history, today_df],
            ignore_index=True
        )

    else:

        combined = today_df

    # --------------------------------------------------------
    # Nifty
    # --------------------------------------------------------

    nifty_df = get_nifty_data()

    if nifty_df is not None:

        combined["date"] = pd.to_datetime(
            combined["date"]
        )

        nifty_df["date"] = pd.to_datetime(
            nifty_df["date"]
        )

        combined = combined.merge(
            nifty_df,
            on="date",
            how="left"
        )

    # --------------------------------------------------------
    # Save history
    # --------------------------------------------------------

    save_history(combined)

    # --------------------------------------------------------
    # Create Telegram message
    # --------------------------------------------------------

    message = create_message(
        combined,
        nifty_df
    )

    if message:
        send_telegram_message(message)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    get_fii_data()
