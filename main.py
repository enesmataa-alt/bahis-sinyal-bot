import os
import glob
import zipfile
import tempfile
import traceback
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TZ = timezone(timedelta(hours=3))
SEASON = "2627"
LEAGUES = ["E0", "E1", "E2", "E3", "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "SC0", "G1"]
RESULTS_FILE = "futbol_data/canli_eklenen.csv"
SIGNALS_FILE = "futbol_data/son_sinyaller.csv"


def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarlari eksik")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for i in range(0, len(message), 3900):
        chunk = message[i:i + 3900]
        r = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"},
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
        out["FTHG"] = hg
        out["FTAG"] = ag
    else:
        out["Over25"] = np.nan
        out["BTTS"] = np.nan
        out["FTHG"] = np.nan
        out["FTAG"] = np.nan

    out["HomeTeam"] = df["HomeTeam"] if "HomeTeam" in df.columns else ""
    out["AwayTeam"] = df["AwayTeam"] if "AwayTeam" in df.columns else ""
    out["Date"] = df["Date"] if "Date" in df.columns else ""
    out["League"] = league_code if league_code else (df["Div"] if "Div" in df.columns else "")
    return out


def load_local_history():
    files = glob.glob("futbol_data/*.csv") + glob.glob("futbol_data/**/*.csv", recursive=True) + glob.glob("*.csv")
    zip_files = glob.glob("futbol_data/*.zip") + glob.glob("futbol_data/**/*.zip", recursive=True)
    tmpdir = tempfile.mkdtemp()
    for zpath in zip_files:
        try:
            with zipfile.ZipFile(zpath, "r") as zf:
                zf.extractall(tmpdir)
        except Exception as e:
            print("zip acilamadi", zpath, e)
    files += glob.glob(tmpdir + "/*.csv") + glob.glob(tmpdir + "/**/*.csv", recursive=True)

    dfs = []
    for f in files:
        try:
            raw = pd.read_csv(f, low_memory=False, encoding="utf-8", on_bad_lines="skip")
            n = normalize(raw)
            if n.empty:
                raw = pd.read_csv(f, low_memory=False, encoding="latin-1", on_bad_lines="skip")
                n = normalize(raw)
            if not n.empty:
                dfs.append(n)
        except Exception:
            pass
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
    today = datetime.now(TZ).date()
    tomorrow = today + timedelta(days=1)
    rows = []
    url = "https://www.football-data.co.uk/fixtures.csv"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        raw = pd.read_csv(pd.io.common.StringIO(r.text), low_memory=False)
        n = normalize(raw)
        for _, row in n.iterrows():
            dt = parse_date(row.get("Date", ""))
            if dt in (today, tomorrow) and pd.notna(row["H"]):
                rows.append(row.to_dict())
    except Exception as e:
        print("fixtures hata", e)
    return rows


def fetch_finished_current_season():
    dfs = []
    for code in LEAGUES:
        url = f"https://www.football-data.co.uk/mmz4281/{SEASON}/{code}.csv"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200 or not r.text.strip():
                continue
            raw = pd.read_csv(pd.io.common.StringIO(r.text), low_memory=False)
            n = normalize(raw, code)
            n = n[n["FTR"].isin(["H", "D", "A"])]
            if not n.empty:
                dfs.append(n)
        except Exception as e:
            print("sonuc hata", code, e)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def analyze_match(hist, h, d, a, o25):
    work = hist.dropna(subset=["H", "D", "A", "FTR"]).copy()
    if len(work) == 0:
        return 9.99, (0, 0, 0, 0), (0, 0, 0, 0), "Yok", 0
    if o25 is not None and not (isinstance(o25, float) and np.isnan(o25)):
        tmp = work.dropna(subset=["O25"])
        if len(tmp) >= 30:
            work = tmp
            work["mesafe"] = np.sqrt(
                (work["H"] - h) ** 2 + (work["D"] - d) ** 2 + (work["A"] - a) ** 2 + (work["O25"] - o25) ** 2
            )
        else:
            work["mesafe"] = np.sqrt((work["H"] - h) ** 2 + (work["D"] - d) ** 2 + (work["A"] - a) ** 2)
    else:
        work["mesafe"] = np.sqrt((work["H"] - h) ** 2 + (work["D"] - d) ** 2 + (work["A"] - a) ** 2)
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


def fmt_odd(v):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "-"
        return f"{float(v):.2f}"
    except Exception:
        return "-"


def signal_hit(best, row):
    if best == "Home":
        return str(row.get("FTR")) == "H"
    if best == "Away":
        return str(row.get("FTR")) == "A"
    if best == "Over":
        return float(row.get("Over25", 0) or 0) == 1
    if best == "BTTS":
        return float(row.get("BTTS", 0) or 0) == 1
    return False


def scan_signals(hist):
    today_matches = fetch_bulletin()
    if not today_matches:
        send_telegram(f"✅ Tarihsel data: {len(hist)} maç.\n⚠️ fixtures.csv içinde bugün/yarın maçı yok.")
        return

    today = datetime.now(TZ).strftime("%d.%m.%Y")
    rows = []
    save_rows = []
    for m in today_matches:
        mind, s30, s100, best, bestv = analyze_match(hist, m["H"], m["D"], m["A"], m.get("O25", np.nan))
        rows.append({**m, "mesafe": mind, "n30": s30, "n100": s100, "best": best, "bestv": bestv})
        save_rows.append({
            "Date": m.get("Date", ""),
            "HomeTeam": m.get("HomeTeam", ""),
            "AwayTeam": m.get("AwayTeam", ""),
            "H": m.get("H"),
            "D": m.get("D"),
            "A": m.get("A"),
            "O25": m.get("O25"),
            "best": best,
            "bestv": bestv,
            "mesafe": mind,
        })
    rows = sorted(rows, key=lambda x: x["mesafe"])

    os.makedirs("futbol_data", exist_ok=True)
    pd.DataFrame(save_rows).to_csv(SIGNALS_FILE, index=False)

    lines = [
        f"<b>📊 {today} Otomatik Sinyal</b>",
        f"Bülten: {len(rows)} maç",
        f"Tarihsel data: {len(hist)} maç",
        "",
    ]
    for r in rows[:15]:
        n30, n100 = r["n30"], r["n100"]
        lines.append(f"<b>{r.get('HomeTeam','')} - {r.get('AwayTeam','')}</b>")
        lines.append(f"1/X/2: {fmt_odd(r.get('H'))} / {fmt_odd(r.get('D'))} / {fmt_odd(r.get('A'))}   O2.5: {fmt_odd(r.get('O25'))}")
        lines.append(f"Mesafe: {r['mesafe']}")
        lines.append(f"n30   H %{n30[0]} | A %{n30[1]} | O %{n30[2]} | BTTS %{n30[3]}")
        lines.append(f"n100  H %{n100[0]} | A %{n100[1]} | O %{n100[2]} | BTTS %{n100[3]}")
        lines.append(f"Sinyal: <b>{r['best']} %{r['bestv']}</b>")
        lines.append("")
    lines.append("<b>En net 5 sinyal</b>")
    for i, r in enumerate(rows[:5], 1):
        lines.append(f"{i}. {r.get('HomeTeam','')} - {r.get('AwayTeam','')} → <b>{r['best']} %{r['bestv']}</b> (mesafe {r['mesafe']})")
    send_telegram("\n".join(lines))


def update_results(hist):
    now = datetime.now(TZ)
    hedef = now.date() - timedelta(days=1) if now.hour < 6 else now.date()
    yeni = fetch_finished_current_season()

    os.makedirs("futbol_data", exist_ok=True)
    if yeni.empty:
        send_telegram("⚠️ Gün sonu: bitmiş maç bulunamadı.")
        return

    if os.path.exists(RESULTS_FILE):
        eski = pd.read_csv(RESULTS_FILE, low_memory=False)
        hepsi = pd.concat([eski, yeni], ignore_index=True)
    else:
        hepsi = yeni
    hepsi = hepsi.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"], keep="last")
    hepsi.to_csv(RESULTS_FILE, index=False)

    gun = []
    for _, row in yeni.iterrows():
        dt = parse_date(row.get("Date", ""))
        if dt == hedef:
            gun.append(row)

    sinyaller = pd.DataFrame()
    if os.path.exists(SIGNALS_FILE):
        sinyaller = pd.read_csv(SIGNALS_FILE)

    lines = [
        f"<b>📌 {hedef.strftime('%d.%m.%Y')} Gün Sonu Raporu</b>",
        f"Dataya eklenen toplam bitmiş maç: {len(hepsi)}",
        f"Bu güne ait biten maç: {len(gun)}",
        "",
    ]

    hits = 0
    total = 0
    for row in gun:
        home = str(row.get("HomeTeam", ""))
        away = str(row.get("AwayTeam", ""))
        skor = f"{int(row.get('FTHG', 0) if pd.notna(row.get('FTHG')) else 0)}-{int(row.get('FTAG', 0) if pd.notna(row.get('FTAG')) else 0)}"
        ftr = row.get("FTR", "")
        best, bestv, mesafe = None, None, None

        if not sinyaller.empty:
            m = sinyaller[
                (sinyaller["HomeTeam"].astype(str) == home) &
                (sinyaller["AwayTeam"].astype(str) == away)
            ]
            if len(m):
                best = str(m.iloc[0]["best"])
                bestv = m.iloc[0]["bestv"]
                mesafe = m.iloc[0]["mesafe"]

        if best is None:
            mind, s30, s100, best, bestv = analyze_match(hist, row["H"], row["D"], row["A"], row.get("O25", np.nan))
            mesafe = mind

        ok = signal_hit(best, row)
        total += 1
        hits += 1 if ok else 0
        durum = "✅ Tuttu" if ok else "❌ Tutmadı"
        lines.append(f"<b>{home} - {away}</b>  {skor} ({ftr})")
        lines.append(f"Sinyal: {best} %{bestv} | Mesafe: {mesafe} | {durum}")
        lines.append("")

    if total:
        oran = round(hits / total * 100, 1)
        lines.append(f"<b>Özet:</b> {hits}/{total} sinyal tuttu (%{oran})")
    else:
        lines.append("Bu tarih için eşleşen bitmiş maç henüz yok. Kaynak gece geç güncellenebilir.")
    send_telegram("\n".join(lines))


def main():
    mode = os.getenv("MODE", "scan")
    hist = load_local_history()
    if "FTR" in hist.columns:
        hist = hist[hist["FTR"].isin(["H", "D", "A"])].copy()
    print("tarihsel mac:", len(hist), "mode:", mode)

    if hist.empty:
        send_telegram("❌ Tarihsel data okunamadı.")
        return

    if mode == "update":
        update_results(hist)
    else:
        scan_signals(hist)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(err)
        send_telegram("❌ Bot hatası:\n<code>" + err[-1500:] + "</code>")
        raise
