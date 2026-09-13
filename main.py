import os
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Bot
import asyncio
import glob

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

# ================== DATA YÜKLEME ==================
def load_all_data():
    """futbol_data klasöründeki tüm CSV'leri birleştirir"""
    files = glob.glob("futbol_data/*.csv") + glob.glob("futbol_data/**/*.csv", recursive=True)
    
    if not files:
        print("Hiç CSV bulunamadı!")
        return None
    
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, low_memory=False)
            # Gerekli kolonları standartlaştır
            if 'B365H' in df.columns:
                df = df.rename(columns={
                    'B365H': 'H',
                    'B365D': 'D',
                    'B365A': 'A',
                    'B365>2.5': 'O25'
                })
            # FTR, FTHG, FTAG varsa BTTS ve Over hesapla
            if 'FTHG' in df.columns and 'FTAG' in df.columns:
                df['BTTS'] = ((df['FTHG'] > 0) & (df['FTAG'] > 0)).astype(int)
                df['Over25'] = ((df['FTHG'] + df['FTAG']) > 2.5).astype(int)
            
            # Sadece ihtiyacımız olan kolonları al
            needed = ['H', 'D', 'A', 'O25', 'FTR', 'Over25', 'BTTS']
            available = [c for c in needed if c in df.columns]
            if len(available) >= 4:
                dfs.append(df[available].dropna())
        except Exception as e:
            print(f"Hata {f}: {e}")
            continue
    
    if not dfs:
        return None
    
    full_df = pd.concat(dfs, ignore_index=True)
    print(f"Toplam {len(full_df)} maç yüklendi.")
    return full_df

# ================== ANALİZ ==================
def analyze_match(df, h, d, a, o25, n30=30, n100=100):
    df = df.copy()
    df["mesafe"] = np.sqrt(
        (df["H"] - h)**2 +
        (df["D"] - d)**2 +
        (df["A"] - a)**2 +
        (df["O25"] - o25)**2
    )
    df = df.sort_values("mesafe")
    
    def get_stats(subset):
        total = len(subset)
        if total == 0:
            return 0, 0, 0, 0
        home = (subset["FTR"] == "H").mean() * 100
        away = (subset["FTR"] == "A").mean() * 100
        over = subset["Over25"].mean() * 100 if "Over25" in subset else 0
        btts = subset["BTTS"].mean() * 100 if "BTTS" in subset else 0
        return round(home,1), round(away,1), round(over,1), round(btts,1)
    
    n30_stats = get_stats(df.head(n30))
    n100_stats = get_stats(df.head(n100))
    min_dist = round(df["mesafe"].iloc[0], 3)
    
    signals = {
        "Home": (n30_stats[0] + n100_stats[0]) / 2,
        "Away": (n30_stats[1] + n100_stats[1]) / 2,
        "Over": (n30_stats[2] + n100_stats[2]) / 2,
        "BTTS": (n30_stats[3] + n100_stats[3]) / 2
    }
    best = max(signals, key=signals.get)
    
    return {
        "mesafe": min_dist,
        "n30": n30_stats,
        "n100": n100_stats,
        "best": best,
        "best_val": round(signals[best], 1)
    }

# ================== ÖRNEK BÜLTEN (şimdilik sabit) ==================
TODAY_MATCHES = [
    {"name": "Man United - Man City", "H": 3.10, "D": 3.60, "A": 2.20, "O25": 1.70},
    {"name": "Sheffield Utd - Wolves", "H": 3.40, "D": 3.40, "A": 2.10, "O25": 1.85},
    {"name": "Coventry - Brighton", "H": 3.80, "D": 3.60, "A": 1.95, "O25": 1.80},
    {"name": "Galatasaray - Kocaelispor", "H": 1.35, "D": 5.00, "A": 8.50, "O25": 1.45},
    {"name": "Lecce - Monza", "H": 2.40, "D": 3.20, "A": 3.00, "O25": 1.90},
]

def create_report(df):
    today = datetime.now().strftime("%d.%m.%Y")
    results = []
    
    for m in TODAY_MATCHES:
        res = analyze_match(df, m["H"], m["D"], m["A"], m["O25"])
        results.append({
            "name": m["name"],
            **res
        })
    
    results = sorted(results, key=lambda x: x["mesafe"])
    
    lines = [f"<b>📊 {today} – Bahis Sinyal Raporu</b>\n"]
    lines.append("<code>")
    lines.append(f"{'Maç':<28} | Mesafe | n30 BTTS | n100 BTTS | Sinyal")
    lines.append("-"*70)
    
    for r in results:
        line = f"{r['name']:<28} | {r['mesafe']:<6} | %{r['n30'][3]:<7} | %{r['n100'][3]:<8} | {r['best']} %{r['best_val']}"
        lines.append(line)
    
    lines.append("</code>\n")
    lines.append("<b>En Net 3 Sinyal:</b>")
    for i, r in enumerate(results[:3], 1):
        lines.append(f"{i}. {r['name']} → <b>{r['best']} %{r['best_val']}</b>")
    
    return "\n".join(lines)

# ================== ANA ==================
def main():
    print("Sistem başlatıldı...")
    df = load_all_data()
    
    if df is None or len(df) < 100:
        send_telegram("❌ Yeterli data yüklenemedi. futbol_data klasörünü kontrol et.")
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
