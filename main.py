import os
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Bot
import asyncio

# ================== AYARLAR ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ================== TELEGRAM ==================
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarları eksik")
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="HTML"))

# ================== ANALİZ MOTORU ==================
def load_data():
    """Tarihsel datayı yükler"""
    try:
        df = pd.read_csv("historical_data.csv")
        return df
    except Exception as e:
        print(f"Data yüklenemedi: {e}")
        return None

def calculate_distance(row, h, d, a, o25):
    """Euclidean mesafe hesaplar"""
    return np.sqrt(
        (row["H"] - h)**2 +
        (row["D"] - d)**2 +
        (row["A"] - a)**2 +
        (row["O25"] - o25)**2
    )

def analyze_match(df, h, d, a, o25, n30=30, n100=100):
    """Bir maç için n=30 ve n=100 analiz yapar"""
    df = df.copy()
    df["mesafe"] = df.apply(lambda x: calculate_distance(x, h, d, a, o25), axis=1)
    df = df.sort_values("mesafe")

    nearest_30 = df.head(n30)
    nearest_100 = df.head(n100)

    def get_stats(subset):
        total = len(subset)
        if total == 0:
            return 0, 0, 0, 0
        home = (subset["FTR"] == "H").sum() / total * 100
        away = (subset["FTR"] == "A").sum() / total * 100
        over = subset["Over25"].mean() * 100
        btts = subset["BTTS"].mean() * 100
        return round(home, 1), round(away, 1), round(over, 1), round(btts, 1)

    h30, a30, o30, b30 = get_stats(nearest_30)
    h100, a100, o100, b100 = get_stats(nearest_100)
    min_dist = round(df["mesafe"].iloc[0], 3)

    # En yüksek sinyali bul
    signals = {
        "Home": (h30 + h100) / 2,
        "Away": (a30 + a100) / 2,
        "Over": (o30 + o100) / 2,
        "BTTS": (b30 + b100) / 2
    }
    best_signal = max(signals, key=signals.get)
    best_value = round(signals[best_signal], 1)

    return {
        "mesafe": min_dist,
        "n30": (h30, a30, o30, b30),
        "n100": (h100, a100, o100, b100),
        "best": best_signal,
        "best_val": best_value
    }

# ================== ÖRNEK BÜLTEN (Şimdilik sabit) ==================
# Daha sonra burayı dinamik hale getireceğiz
TODAY_MATCHES = [
    {"name": "Crystal Palace - Ipswich", "H": 1.90, "D": 3.60, "A": 4.00, "O25": 1.85},
    {"name": "Bournemouth - Brentford", "H": 2.50, "D": 3.50, "A": 2.75, "O25": 1.80},
    {"name": "Southampton - Bristol City", "H": 1.70, "D": 3.80, "A": 4.50, "O25": 1.75},
    {"name": "Tottenham - Everton", "H": 2.05, "D": 3.50, "A": 3.60, "O25": 1.80},
    {"name": "Liverpool - Fulham", "H": 1.45, "D": 4.80, "A": 6.50, "O25": 1.65},
]

def create_report(df):
    today = datetime.now().strftime("%d.%m.%Y")
    results = []

    for m in TODAY_MATCHES:
        res = analyze_match(df, m["H"], m["D"], m["A"], m["O25"])
        results.append({
            "name": m["name"],
            "mesafe": res["mesafe"],
            "n30": res["n30"],
            "n100": res["n100"],
            "best": res["best"],
            "best_val": res["best_val"]
        })

    # Mesafeye göre sırala
    results = sorted(results, key=lambda x: x["mesafe"])

    # Tablo oluştur
    lines = []
    lines.append(f"<b>📊 {today} – Bahis Sinyal Raporu</b>\n")
    lines.append("<code>")
    lines.append(f"{'Maç':<28} | Mesafe | n30 BTTS | n100 BTTS | Sinyal")
    lines.append("-" * 70)

    for r in results:
        n30_btts = r["n30"][3]
        n100_btts = r["n100"][3]
        line = f"{r['name']:<28} | {r['mesafe']:<6} | %{n30_btts:<7} | %{n100_btts:<8} | {r['best']} %{r['best_val']}"
        lines.append(line)

    lines.append("</code>\n")
    lines.append("<b>En Net 3 Sinyal:</b>")

    for i, r in enumerate(results[:3], 1):
        lines.append(f"{i}. {r['name']} → <b>{r['best']} %{r['best_val']}</b>")

    return "\n".join(lines)

# ================== ANA ==================
def main():
    print("Sistem başlatıldı...")
    df = load_data()

    if df is None or df.empty:
        send_telegram("❌ historical_data.csv bulunamadı veya boş.")
        return

    try:
        message = create_report(df)
        send_telegram(message)
        print("Rapor gönderildi.")
    except Exception as e:
        send_telegram(f"❌ Hata: {str(e)}")
        print(e)

if __name__ == "__main__":
    main()
