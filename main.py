import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from telegram import Bot
import asyncio

# ================== AYARLAR ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ================== YARDIMCI FONKSİYONLAR ==================
def send_telegram(message: str):
    """Telegram'a mesaj gönder"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarları eksik")
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="HTML"))

def create_dummy_analysis():
    """
    Şu anlık örnek sinyal tablosu üretir.
    Gerçek veri çekme ve mesafe hesabı sonraki adımda eklenecek.
    """
    today = datetime.now().strftime("%d.%m.%Y")
    
    message = f"""<b>📊 {today} – Bahis Sinyal Raporu</b>

<code>
Maç                      | Mesafe | n30 BTTS | n100 BTTS | Sinyal
-------------------------|--------|----------|-----------|--------
Crystal Palace - Ipswich | 0.031  | %67      | %64       | BTTS
Bournemouth - Brentford  | 0.000  | %63      | %61       | BTTS
Southampton - Bristol    | 0.018  | %57      | %55       | Home
Tottenham - Everton      | 0.000  | %60      | %59       | BTTS
</code>

<b>En Net 3 Sinyal:</b>
1. Crystal Palace – Ipswich → <b>BTTS %64</b>
2. Bournemouth – Brentford → <b>BTTS %61</b>
3. Southampton – Bristol City → <b>Home %61</b>

Sistem çalışıyor. Gerçek veri çekme yakında eklenecek.
"""
    return message

# ================== ANA FONKSİYON ==================
def main():
    print("Sistem başlatıldı...")
    
    try:
        message = create_dummy_analysis()
        send_telegram(message)
        print("Telegram mesajı gönderildi.")
    except Exception as e:
        print(f"Hata oluştu: {e}")
        send_telegram(f"❌ Sistem hatası: {str(e)}")

if __name__ == "__main__":
    main()
