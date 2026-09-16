from datetime import datetime
import io
import pandas as pd
import requests

# अपनी Bot Details यहाँ डालें
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    requests.post(url, json=payload)


def get_fii_data():
    today = datetime.now().strftime("%d%m%Y")
    url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{today}.csv"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            send_telegram_message(
                f"⚠️ *FII Data Alert ({datetime.now().strftime('%d-%b-%Y')})*\n\nआज का डेटा अभी तक NSE पर उपलब्ध नहीं है या आज मार्केट बंद (Holiday) था।"
            )
            return

        df = pd.read_csv(io.StringIO(response.text), skiprows=1)
        df.columns = df.columns.str.strip()

        fii_data = df[df["Client Type"].str.strip() == "FII"].iloc[0]

        long_cnt = float(fii_data["Future Index Long"])
        short_cnt = float(fii_data["Future Index Short"])
        total = long_cnt + short_cnt

        long_ratio = (long_cnt / total * 100) if total > 0 else 0
        net_contracts = int(long_cnt - short_cnt)

        # टीवी स्क्रीन जैसा मैसेज फॉर्मेट
        message = (
            f"📊 *बाजार में आज कैसा है ट्रेड सेटअप*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 *FIIs का इंडेक्स फ्यूचर्स में एक्सपोजर ट्रेंड*\n"
            f"🗓 *तारीख:* {datetime.now().strftime('%d %B')}\n\n"
            f"🔹 *लॉन्ग/शॉर्ट रेश्यो:* `{long_ratio:.2f}%`\n"
            f"🔹 *नेट कॉन्ट्रैक्ट्स:* `{net_contracts:,}`\n\n"
            f"📌 *लॉन्ग कॉन्ट्रैक्ट्स:* `{int(long_cnt):,}`\n"
            f"📌 *शॉर्ट कॉन्ट्रैक्ट्स:* `{int(short_cnt):,}`\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )

        send_telegram_message(message)

    except Exception as e:
        send_telegram_message(f"❌ *Error fetching FII data:* {str(e)}")


if __name__ == "__main__":
    get_fii_data()
