import os
import glob
import traceback
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TZ = timezone(timedelta(hours=3))


def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarlari eksik")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for i in range(0, len(message), 3900):
        chunk = message[i:i + 3900]
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
            },
            timeout=20,
        )
        print("telegram", r.status_code, r.text[:200])


def pick_col(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def normalize(df, league_code=""):
    h = pick_col(df, ["B365H", "AvgH", "PSH", "WHH", "IWH"])
    d = pick_col(df, ["B365D", "AvgD", "PSD", "WHD", "IWD"])
    a = pick_col(df, ["B365A", "AvgA", "PSA", "WHA", "IWA"])
    o = pick_col(df, ["B365>2.5", "Avg>2.5", "P>2.5"])
    if not all([h, d, a]):
        return pd.DataFrame()

    out = pd.DataFrame()
    out["H"] = pd.to_numeric(df[h], errors="coerce")
    out["D"] = pd.to_numeric(df[d], errors="coerce")
    out["A"] = pd.to_numeric(df[a], errors="coerce")
    out["O25"] = pd.to_numeric(df[o], errors="coerce") if o else np.nan
    out["FTR"] = df["FTR"] if "FTR" in df.columns else np.nan

    if "FTHG" in df.columns and "FTAG" in df.columns:
        hg = pd.to_numeric(df["FTHG"], errors="coerce")
        ag = pd.to_numeric(df["FTAG"], errors="coerce")
        out["Over25"] = ((hg + ag) > 2.5).astype(float)
        out["BTTS"] = ((hg > 0) & (ag > 0)).astype(float)
    else:
        out["Over25"] = np.nan
        out["BTTS"] = np.nan

    out["HomeTeam"] = df["HomeTeam"] if "HomeTeam" in df.columns else ""
    out["AwayTeam"] = df["AwayTeam"] if "AwayTeam" in df.columns else ""
    out["Date"] = df["Date"] if "Date" in df.columns else ""
    out["League"] = league_code
    return out


def load_local_history():
    files = glob.glob("futbol_data/*.csv") + glob.glob("futbol_data/**/*.csv", recursive=True)
    print("csv sayisi:", len(files))
    dfs = []
    for f in files:
        try:
            raw = pd.read_csv(f, low_memory=False, encoding="utf-8", on_bad_lines="skip")
            n = normalize(raw)
            if not n.empty:
                dfs.append(n)
        except Exception as e:
            print("local skip", f, e)
    if not dfs:
        return pd.DataFrame(columns=["H", "D", "A", "O25", "FTR", "Over25", "BTTS"])
    return pd.concat(dfs, ignore_index=True)


def parse_date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except Exception:
            pass
    return None


def fetch_bulletin():
    season = "2627"
    leagues = ["E0", "E1", "E2", "E3", "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "SC0", "G1"]
    today = datetime.now(TZ).date()
    tomorrow = today + timedelta(days=1)
    rows = []
    for code in leagues:
        url = f"https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200 or not r.text.strip():
                print("yok", code, r.status_code)
                continue
            raw = pd.read_csv(pd.io.common.StringIO(r.text), low_memory=False)
            n = normalize(raw, code)
            if n.empty:
                continue
            for _, row in n.iterrows():
                dt = parse_date(row.get("Date", ""))
                finished = str(row.get("FTR", "")).strip() in ["H", "D", "A"]
                if dt in (today, tomorrow) and not finished and pd.notna(row["H"]):
                    rows.append(row.to_dict())
        except Exception as e:
            print("bulletin hata", code, e)
    return rows


def analyze_match(hist, h, d, a, o25):
    work = hist.dropna(subset=["H", "D", "A", "FTR"]).copy()
    if len(work) == 0:
        return 9.99, (0, 0, 0, 0), (0, 0, 0, 0), "Yok", 0

    if o25 is not None and not (isinstance(o25, float) and np.isnan(o25)):
        tmp = work.dropna(subset=["O25"])
        if len(tmp) >= 30:
            work = tmp
            work["mesafe"] = np.sqrt(
                (work["H"] - h) ** 2
                + (work["D"] - d) ** 2
                + (work["A"] - a) ** 2
                + (work["O25"] - o25) ** 2
            )
        else:
            work["mesafe"] = np.sqrt(
                (work["H"] - h) ** 2 + (work["D"] - d) ** 2 + (work["A"] - a) ** 2
            )
    else:
        work["mesafe"] = np.sqrt(
            (work["H"] - h) ** 2 + (work["D"] - d) ** 2 + (work["A"] - a) ** 2
        )

    work = work.sort_values("mesafe")

    def stats(sub):
        if len(sub) == 0:
            return 0, 0, 0, 0
        home = (sub["FTR"] == "H").mean() * 100
        away = (sub["FTR"] == "A").mean() * 100
        over = float(sub["Over25"].mean() * 100) if "Over25" in sub else 0
        btts = float(sub["BTTS"].mean() * 100) if "BTTS" in sub else 0
        return round(home, 1), round(away, 1), round(over, 1), round(btts, 1)

    s30 = stats(work.head(30))
    s100 = stats(work.head(min(100, len(work))))
    mind = round(float(work["mesafe"].iloc[0]), 3)
    signals = {
        "Home": (s30[0] + s100[0]) / 2,
        "Away": (s30[1] + s100[1]) / 2,
        "Over": (s30[2] + s100[2]) / 2,
        "BTTS": (s30[3] + s100[3]) / 2,
    }
    best = max(signals, key=signals.get)
    return mind, s30, s100, best, round(signals[best], 1)


def main():
    hist = load_local_history()
    if "FTR" in hist.columns:
        hist = hist[hist["FTR"].isin(["H", "D", "A"])].copy()
    print("tarihsel mac:", len(hist))

    today_matches = fetch_bulletin()
    print("bulten mac:", len(today_matches))

    if hist.empty:
        send_telegram("❌ Tarihsel data okunamadı. futbol_data klasörünü kontrol et.")
        return

    if not today_matches:
        send_telegram(
            f"⚠️ Bugün/yarın için henüz oranlı oynanmamış maç yok.\n"
            f"Tarihsel data hazır: {len(hist)} maç."
        )
        return

    today = datetime.now(TZ).strftime("%d.%m.%Y")
    rows = []
    for m in today_matches:
        mind, s30, s100, best, bestv = analyze_match(
            hist, m["H"], m["D"], m["A"], m.get("O25", np.nan)
        )
        rows.append({**m, "mesafe": mind, "n30": s30, "n100": s100, "best": best, "bestv": bestv})
    rows = sorted(rows, key=lambda x: x["mesafe"])

    lines = [
        f"<b>📊 {today} Otomatik Sinyal</b>",
        f"Bülten: {len(rows)} maç",
        f"Tarihsel data: {len(hist)} maç",
        "",
        "<code>",
        f"{'Maç':<26} Mesafe n30B n100B Sinyal",
        "-" * 52,
    ]
    for r in rows[:20]:
        name = f"{r.get('HomeTeam','')} - {r.get('AwayTeam','')}"[:26]
        lines.append(
            f"{name:<26} {r['mesafe']:<6} %{r['n30'][3]:<4} %{r['n100'][3]:<5} {r['best']} %{r['bestv']}"
        )
    lines.append("</code>\n")
    lines.append("<b>En net 5 sinyal</b>")
    for i, r in enumerate(rows[:5], 1):
        lines.append(
            f"{i}. {r.get('HomeTeam','')} - {r.get('AwayTeam','')} → <b>{r['best']} %{r['bestv']}</b> (mesafe {r['mesafe']})"
        )
    send_telegram("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(err)
        send_telegram("❌ Bot hatası:\n<code>" + err[-1500:] + "</code>")
        raise
