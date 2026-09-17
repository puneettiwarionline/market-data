from datetime import datetime, timedelta
import io
import os
from zoneinfo import ZoneInfo

import pandas as pd
import requests

# GitHub Secrets से API Token रीड करेगा
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_API_TOKEN")

# अपनी Telegram Chat ID यहाँ डालें (या इसे भी os.getenv("TELEGRAM_CHAT_ID") कर सकते हैं)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

IST = ZoneInfo("Asia/Kolkata")
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_API_TOKEN or TELEGRAM_CHAT_ID is missing from environment variables."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    response = requests.post(url, json=payload, timeout=30)
    if not response.ok:
        raise RuntimeError(
            f"Telegram API returned {response.status_code}: {response.text}"
        )

    print("Telegram notification sent successfully.")


def create_nse_session():
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    session.get("https://www.nseindia.com/", timeout=30)
    return session


def get_latest_participant_data(session, lookback_days=7):
    today = datetime.now(IST).date()

    for days_ago in range(lookback_days):
        report_date = today - timedelta(days=days_ago)
        date_code = report_date.strftime("%d%m%Y")
        url = (
            "https://archives.nseindia.com/content/nsccl/"
            f"fao_participant_oi_{date_code}.csv"
        )
        response = session.get(url, timeout=30)

        if response.status_code == 404:
            continue

        response.raise_for_status()
        data = pd.read_csv(io.StringIO(response.text), skiprows=1)
        data.columns = data.columns.str.strip()
        data["Client Type"] = data["Client Type"].str.strip()
        return report_date, data

    raise RuntimeError("Participant OI report was not found in the last 7 days.")


def get_cash_activity(session):
    response = session.get(
        "https://www.nseindia.com/api/fiidiiTradeReact", timeout=30
    )
    response.raise_for_status()
    rows = response.json()
    return {row["category"]: row for row in rows}


def get_market_indices(session):
    response = session.get("https://www.nseindia.com/api/allIndices", timeout=30)
    response.raise_for_status()
    payload = response.json()
    indices = {row["index"].strip(): row for row in payload["data"]}
    return payload["timestamp"], indices


def get_position_signal(call_net, put_net):
    if call_net < 0 < put_net:
        return "🔴 Bearish"
    if put_net < 0 < call_net:
        return "🟢 Bullish"
    return "🟡 Mixed"


def get_breadth_signal(ratio):
    if ratio > 1.5:
        return "🟢 Broad Strength"
    if ratio < 0.7:
        return "🔴 Broad Weakness"
    return "🟡 Mixed Breadth"


def get_vix_signal(value, percent_change):
    if percent_change > 5 or value >= 20:
        return "🔴 High Fear"
    if value >= 17:
        return "🟠 Elevated"
    if value < 14:
        return "🟢 Low Fear"
    return "🟡 Normal"


def format_crore(value):
    sign = "+" if value >= 0 else "-"
    return f"{sign}₹{abs(value):,.2f} Cr"


def add_score(score, value, bullish_condition, bearish_condition):
    if bullish_condition(value):
        return score + 1
    if bearish_condition(value):
        return score - 1
    return score


def get_market_data():
    session = create_nse_session()
    sections = []
    data_dates = []
    score = 0

    try:
        cash = get_cash_activity(session)
        fii_cash = cash["FII/FPI"]
        dii_cash = cash["DII"]
        fii_cash_net = float(fii_cash["netValue"])
        dii_cash_net = float(dii_cash["netValue"])
        cash_date = fii_cash["date"]
        cash_icon = "🟢" if fii_cash_net >= 0 else "🔴"
        dii_icon = "🟢" if dii_cash_net >= 0 else "🔴"
        score = add_score(score, fii_cash_net, lambda value: value > 0, lambda value: value < 0)
        sections.append(
            "💰 *CASH MARKET*\n"
            f"FII/FPI Net: `{format_crore(fii_cash_net)}` {cash_icon}\n"
            f"DII Net: `{format_crore(dii_cash_net)}` {dii_icon}"
        )
        data_dates.append(f"Cash: {cash_date}")
    except Exception as error:
        print(f"Cash market data unavailable: {error}")
        sections.append("💰 *CASH MARKET*\n⚠️ Data unavailable")

    try:
        participant_date, participant_data = get_latest_participant_data(session)
        fii = participant_data[participant_data["Client Type"] == "FII"].iloc[0]
        pro = participant_data[participant_data["Client Type"] == "Pro"].iloc[0]

        long_count = int(fii["Future Index Long"])
        short_count = int(fii["Future Index Short"])
        total_count = long_count + short_count
        long_share = long_count / total_count * 100 if total_count else 0
        long_short_ratio = long_count / short_count if short_count else 0
        net_contracts = long_count - short_count
        score = add_score(score, net_contracts, lambda value: value > 0, lambda value: value < 0)

        sections.append(
            "📈 *FII INDEX FUTURES*\n"
            f"Long: `{long_count:,}` | Short: `{short_count:,}`\n"
            f"Net: `{net_contracts:+,}` {'🟢' if net_contracts >= 0 else '🔴'}\n"
            f"Long Share: `{long_share:.2f}%` | L/S: `{long_short_ratio:.2f}`"
        )

        option_lines = ["🎯 *INDEX OPTIONS POSITIONING*"]
        fii_option_signal = None
        for label, row in (("FII", fii), ("Pro", pro)):
            call_net = int(row["Option Index Call Long"] - row["Option Index Call Short"])
            put_net = int(row["Option Index Put Long"] - row["Option Index Put Short"])
            option_signal = get_position_signal(call_net, put_net)
            if label == "FII":
                fii_option_signal = option_signal
            option_lines.append(
                f"{label}: Call `{call_net:+,}` | Put `{put_net:+,}`\n"
                f"Positioning: {option_signal}"
            )
        sections.append("\n".join(option_lines))

        if fii_option_signal == "🟢 Bullish":
            score += 1
        elif fii_option_signal == "🔴 Bearish":
            score -= 1
        data_dates.append(f"F&O: {participant_date.strftime('%d-%b-%Y')}")
    except Exception as error:
        print(f"Participant data unavailable: {error}")
        sections.append("📈 *FII FUTURES & OPTIONS*\n⚠️ Data unavailable")

    try:
        index_timestamp, indices = get_market_indices(session)
        nifty_500 = indices["NIFTY 500"]
        advances = int(nifty_500["advances"])
        declines = int(nifty_500["declines"])
        breadth_ratio = advances / declines if declines else float("inf")
        breadth_signal = get_breadth_signal(breadth_ratio)
        score = add_score(
            score,
            breadth_ratio,
            lambda value: value > 1.5,
            lambda value: value < 0.7,
        )

        vix = indices["INDIA VIX"]
        vix_value = float(vix["last"])
        vix_change = float(vix["percentChange"])
        vix_signal = get_vix_signal(vix_value, vix_change)
        if vix_change > 5 or vix_value >= 20:
            score -= 1

        sections.append(
            "🌐 *MARKET BREADTH — NIFTY 500*\n"
            f"Advances: `{advances}` | Declines: `{declines}`\n"
            f"A/D Ratio: `{breadth_ratio:.2f}` {breadth_signal}"
        )
        sections.append(
            "⚡ *INDIA VIX*\n"
            f"Value: `{vix_value:.2f}` | Change: `{vix_change:+.2f}%`\n"
            f"Signal: {vix_signal}"
        )
        data_dates.append(f"Indices: {index_timestamp}")
    except Exception as error:
        print(f"Index data unavailable: {error}")
        sections.append("🌐 *BREADTH & INDIA VIX*\n⚠️ Data unavailable")

    if score >= 2:
        overall_signal = "🟢 BULLISH"
    elif score <= -2:
        overall_signal = "🔴 BEARISH"
    else:
        overall_signal = "🟡 MIXED"

    report_date = datetime.now(IST).strftime("%d %b %Y")
    message = (
        f"📊 *MARKET SETUP | {report_date}*\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(sections)
        + "\n\n━━━━━━━━━━━━━━━━━━━\n"
        f"*OVERALL: {overall_signal}*\n"
        "Signals are indicative, not trading advice."
    )
    if data_dates:
        message += "\n\n_Data: " + " | ".join(data_dates) + "_"

    send_telegram_message(message)


def main():
    try:
        get_market_data()
    except Exception as error:
        send_telegram_message(f"❌ *Market data error:* {str(error)}")



if __name__ == "__main__":
    main()
