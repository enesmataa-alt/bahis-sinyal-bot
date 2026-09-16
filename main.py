import os
import glob
import zipfile
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
MODE = os.getenv("MODE", "scan").strip().lower()

SEASON = "2627"
LEAGUES = [
    "E0", "E1", "E2", "E3", "EC",
    "D1", "D2", "I1", "I2", "SP1", "SP2",
    "F1", "F2", "N1", "B1", "P1", "T1",
    "SC0", "SC1", "SC2", "G1",
]

DATA_DIR = "futbol_data"
SIGNALS_FILE = os.path.join(DATA_DIR, "son_sinyaller.csv")
LIVE_FILE = os.path.join(DATA_DIR, "canli_eklenen.csv")
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
SOCCERBETS_URL = "https://api.soccerbets.com/exports/matches-odds-export.csv"
TR = ZoneInfo("Europe/Istanbul")

SPORTS_CORE = [
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_uefa_champs_league",
    "soccer_england_efl_cup",
    "soccer_epl",
    "soccer_efl_champ",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_turkey_super_league",
    "soccer_spl",
    "soccer_spain_segunda_division",
    "soccer_switzerland_superleague",
]


def today_str():
    return datetime.now(TR).strftime("%d/%m/%Y")


def today_date():
    return datetime.now(TR).date()


def norm_name(x):
    s = str(x or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    for w in ("fc", "cf", "afc", "sc", "cd", "ud", "ac", "as", "the"):
        s = re.sub(rf"\b{w}\b", " ", s)
    return " ".join(s.split())


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for i in range(0, len(text), 3500):
        requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text[i:i + 3500], "parse_mode": "HTML"},
            timeout=30,
        )


def pick_col(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def read_csv_flex(path):
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception:
            continue
    return None


def standardize(df):
    out = df.copy()
    h = pick_col(out, ["B365H", "AvgH", "PSH", "BbAvH", "H", "Pinnacle Home"])
    d = pick_col(out, ["B365D", "AvgD", "PSD", "BbAvD", "D", "Pinnacle Draw"])
    a = pick_col(out, ["B365A", "AvgA", "PSA", "BbAvA", "A", "Pinnacle Away"])
    o = pick_col(out, ["B365>2.5", "Avg>2.5", "P>2.5", "BbAv>2.5", "O25"])
    out["H"] = pd.to_numeric(out[h], errors="coerce") if h else np.nan
    out["D"] = pd.to_numeric(out[d], errors="coerce") if d else np.nan
    out["A"] = pd.to_numeric(out[a], errors="coerce") if a else np.nan
    out["O25"] = pd.to_numeric(out[o], errors="coerce") if o else np.nan
    if "FTHG" in out.columns and "FTAG" in out.columns:
        out["FTHG"] = pd.to_numeric(out["FTHG"], errors="coerce")
        out["FTAG"] = pd.to_numeric(out["FTAG"], errors="coerce")
        out["Over25"] = ((out["FTHG"] + out["FTAG"]) > 2.5).astype(float)
        out["BTTS"] = ((out["FTHG"] > 0) & (out["FTAG"] > 0)).astype(float)
        out["FTR"] = np.where(
            out["FTHG"] > out["FTAG"], "H",
            np.where(out["FTHG"] < out["FTAG"], "A",
                     np.where(out["FTHG"].notna(), "D", np.nan)),
        )
    if "HomeTeam" not in out.columns and "Home" in out.columns:
        out["HomeTeam"] = out["Home"]
    if "AwayTeam" not in out.columns and "Away" in out.columns:
        out["AwayTeam"] = out["Away"]
    return out


def load_local_history():
    os.makedirs(DATA_DIR, exist_ok=True)
    frames = []
    search_roots = [DATA_DIR]
    unzip_dir = os.path.join(DATA_DIR, "_unzipped")
    os.makedirs(unzip_dir, exist_ok=True)
    for zpath in glob.glob(os.path.join(DATA_DIR, "**", "*.zip"), recursive=True):
        if "/_unzipped/" in zpath.replace("\\", "/"):
            continue
        try:
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(unzip_dir)
            search_roots.append(unzip_dir)
        except Exception as e:
            print("zip hata", zpath, e)
    csv_paths = []
    for root in search_roots:
        csv_paths.extend(glob.glob(os.path.join(root, "**", "*.csv"), recursive=True))
    for path in csv_paths:
        name = os.path.basename(path).lower()
        if name in ("son_sinyaller.csv", "canli_eklenen.csv"):
            continue
        df = read_csv_flex(path)
        if df is None or len(df) == 0:
            continue
        std = standardize(df)
        if "FTR" not in std.columns:
            continue
        frames.append(std)
    if not frames:
        return pd.DataFrame()
    hist = pd.concat(frames, ignore_index=True)
    hist = hist.dropna(subset=["H", "D", "A", "FTR"])
    hist = hist[hist["FTR"].isin(["H", "D", "A"])]
    cols = [c for c in ["Date", "HomeTeam", "AwayTeam"] if c in hist.columns]
    if len(cols) == 3:
        hist = hist.drop_duplicates(subset=cols, keep="last")
    print("hist", len(hist))
    return hist.reset_index(drop=True)


def parse_event(ev, sport):
    try:
        ct = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(TR).date()
    except Exception:
        return None
    if ct != today_date():
        return None
    home = ev.get("home_team")
    away = ev.get("away_team")
    h = d = a = o25 = None
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") == "h2h" and h is None:
                for oc in mk.get("outcomes", []):
                    name = oc.get("name", "")
                    if name == home:
                        h = oc.get("price")
                    elif name == away:
                        a = oc.get("price")
                    elif str(name).lower() in ("draw", "the draw"):
                        d = oc.get("price")
            if mk.get("key") == "totals" and o25 is None:
                for oc in mk.get("outcomes", []):
                    pt = oc.get("point")
                    if pt is None:
                        continue
                    if abs(float(pt) - 2.5) < 0.01 and str(oc.get("name", "")).lower() == "over":
                        o25 = oc.get("price")
    if not (h and d and a):
        return None
    return {
        "Date": today_str(),
        "HomeTeam": home,
        "AwayTeam": away,
        "H": float(h),
        "D": float(d),
        "A": float(a),
        "O25": float(o25) if o25 else np.nan,
        "Div": sport,
        "kaynak": "odds_api",
    }


def fetch_bulletin_odds_api():
    if not ODDS_API_KEY:
        print("ODDS_API_KEY yok")
        return pd.DataFrame()
    rows = []
    for sport in SPORTS_CORE:
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "uk",
                    "markets": "h2h,totals",
                    "oddsFormat": "decimal",
                },
                timeout=25,
            )
            print("odds api", sport, r.status_code, "left", r.headers.get("x-requests-remaining"))
            if r.status_code != 200:
                continue
            for ev in r.json():
                parsed = parse_event(ev, sport)
                if parsed:
                    rows.append(parsed)
            left = r.headers.get("x-requests-remaining")
            if left is not None and int(left) < 40:
                break
        except Exception as e:
            print("odds sport hata", sport, e)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates(subset=["HomeTeam", "AwayTeam"])


def parse_any_date(val):
    s = str(val)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except Exception:
            continue
    return None


def fetch_bulletin_soccerbets(only_today=True):
    try:
        r = requests.get(SOCCERBETS_URL, timeout=30)
        if r.status_code != 200 or len(r.content) < 80:
            print("soccerbets bos", r.status_code, len(r.content))
            return pd.DataFrame()
        df = pd.read_csv(pd.io.common.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        home_c = pick_col(df, ["Home Team", "HomeTeam", "Home"])
        away_c = pick_col(df, ["Away Team", "AwayTeam", "Away"])
        h_c = pick_col(df, ["Pinnacle Home", "Home Odds", "H"])
        d_c = pick_col(df, ["Pinnacle Draw", "Draw Odds", "D"])
        a_c = pick_col(df, ["Pinnacle Away", "Away Odds", "A"])
        date_c = pick_col(df, ["Date"])
        if not all([home_c, away_c, h_c, d_c, a_c]):
            print("soccerbets kolon yok", list(df.columns))
            return pd.DataFrame()
        out = pd.DataFrame({
            "Date": df[date_c] if date_c else today_str(),
            "HomeTeam": df[home_c],
            "AwayTeam": df[away_c],
            "H": pd.to_numeric(df[h_c], errors="coerce"),
            "D": pd.to_numeric(df[d_c], errors="coerce"),
            "A": pd.to_numeric(df[a_c], errors="coerce"),
            "O25": np.nan,
            "Div": df[pick_col(df, ["League", "Div"])] if pick_col(df, ["League", "Div"]) else "SB",
            "kaynak": "soccerbets",
        })
        hg = pick_col(df, ["Home Score", "FTHG"])
        ag = pick_col(df, ["Away Score", "FTAG"])
        if hg and ag:
            out["FTHG"] = pd.to_numeric(df[hg], errors="coerce")
            out["FTAG"] = pd.to_numeric(df[ag], errors="coerce")
        if only_today and date_c:
            out = out[out["Date"].map(parse_any_date) == today_date()]
        out = out.dropna(subset=["H", "D", "A", "HomeTeam", "AwayTeam"])
        print("soccerbets maç", len(out))
        return out.reset_index(drop=True)
    except Exception as e:
        print("soccerbets hata", e)
        return pd.DataFrame()


def fetch_bulletin_fixtures():
    try:
        r = requests.get(FIXTURES_URL, timeout=30)
        r.raise_for_status()
        fx = pd.read_csv(pd.io.common.StringIO(r.text))
        fx = standardize(fx)
        fx = fx.dropna(subset=["H", "D", "A", "HomeTeam", "AwayTeam"])
        fx = fx[fx["Date"].astype(str) == today_str()].copy()
        fx["kaynak"] = "fixtures_csv"
        print("fixtures maç", len(fx))
        return fx.reset_index(drop=True)
    except Exception as e:
        print("fixtures hata", e)
        return pd.DataFrame()


def merge_matches(*frames, how="bulletin"):
    parts = [f.copy() for f in frames if f is not None and len(f)]
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["home_n"] = out["HomeTeam"].map(norm_name)
    out["away_n"] = out["AwayTeam"].map(norm_name)
    out["_o25"] = out["O25"].notna().astype(int) if "O25" in out.columns else 0
    rank = {"odds_api": 0, "fixtures_csv": 1, "soccerbets": 2}
    src = out["kaynak"] if "kaynak" in out.columns else pd.Series(["z"] * len(out))
    out["_src"] = src.map(lambda s: rank.get(s, 9))
    if how == "result":
        out["_ok"] = out["FTR"].isin(["H", "D", "A"]).astype(int) if "FTR" in out.columns else 0
        out = out.sort_values(["_ok", "_src"], ascending=[False, True])
    else:
        out = out.sort_values(["_o25", "_src"], ascending=[False, True])
    out = out.drop_duplicates(subset=["home_n", "away_n"], keep="first")
    drop_cols = [c for c in ["_o25", "_src", "_ok"] if c in out.columns]
    return out.drop(columns=drop_cols).reset_index(drop=True)


def fetch_bulletin():
    fx = merge_matches(
        fetch_bulletin_odds_api(),
        fetch_bulletin_soccerbets(only_today=True),
        fetch_bulletin_fixtures(),
        how="bulletin",
    )
    print("birlesik bulten", 0 if fx is None else len(fx))
    return fx


def neighbor_stats(hist, row):
    work = hist.dropna(subset=["H", "D", "A", "FTR", "Over25", "BTTS"]).copy()
    if len(work) < 30:
        return None
    if pd.notna(row.get("O25")):
        work2 = work.dropna(subset=["O25"])
        if len(work2) >= 30:
            dist = np.sqrt(
                (work2["H"] - row["H"]) ** 2
                + (work2["D"] - row["D"]) ** 2
                + (work2["A"] - row["A"]) ** 2
                + (work2["O25"] - row["O25"]) ** 2
            )
            work = work2.assign(mesafe=dist).sort_values("mesafe")
        else:
            dist = np.sqrt(
                (work["H"] - row["H"]) ** 2
                + (work["D"] - row["D"]) ** 2
                + (work["A"] - row["A"]) ** 2
            )
            work = work.assign(mesafe=dist).sort_values("mesafe")
    else:
        dist = np.sqrt(
            (work["H"] - row["H"]) ** 2
            + (work["D"] - row["D"]) ** 2
            + (work["A"] - row["A"]) ** 2
        )
        work = work.assign(mesafe=dist).sort_values("mesafe")

    def pack(n):
        sub = work.head(n)
        return {
            "H": round((sub["FTR"] == "H").mean() * 100, 1),
            "A": round((sub["FTR"] == "A").mean() * 100, 1),
            "O": round(sub["Over25"].mean() * 100, 1),
            "B": round(sub["BTTS"].mean() * 100, 1),
        }

    n30 = pack(30)
    n100 = pack(min(100, len(work)))
    scores = {
        "Home": (n30["H"] + n100["H"]) / 2,
        "Away": (n30["A"] + n100["A"]) / 2,
        "Over": (n30["O"] + n100["O"]) / 2,
        "BTTS": (n30["B"] + n100["B"]) / 2,
    }
    best = max(scores, key=scores.get)
    return {
        "mesafe": round(float(work["mesafe"].iloc[0]), 3),
        "n30": n30,
        "n100": n100,
        "sinyal": best,
        "sinyal_pct": round(scores[best], 1),
    }


def fmt_match(row, st):
    n30, n100 = st["n30"], st["n100"]
    o25 = row.get("O25")
    o_txt = f"{float(o25):.2f}" if pd.notna(o25) else "-"
    return (
        f"<b>{row['HomeTeam']} - {row['AwayTeam']}</b>\n"
        f"1/X/2: {row['H']:.2f} / {row['D']:.2f} / {row['A']:.2f}   O2.5: {o_txt}\n"
        f"Mesafe: {st['mesafe']}\n"
        f"n30   H %{n30['H']:.1f} | A %{n30['A']:.1f} | O %{n30['O']:.1f} | BTTS %{n30['B']:.1f}\n"
        f"n100  H %{n100['H']:.1f} | A %{n100['A']:.1f} | O %{n100['O']:.1f} | BTTS %{n100['B']:.1f}\n"
        f"Sinyal: {st['sinyal']} %{st['sinyal_pct']:.1f}"
    )


def scan_signals(hist):
    try:
        fx = fetch_bulletin()
    except Exception as e:
        send_telegram(f"❌ Bülten okunamadı: {e}")
        return
    if hist is None or len(hist) == 0:
        send_telegram("❌ Tarihsel data okunamadı.")
        return
    if fx is None or len(fx) == 0:
        send_telegram(f"⚠️ {today_str()} için oranlı maç yok.")
        return

    rows, blocks = [], []
    for _, m in fx.iterrows():
        st = neighbor_stats(hist, m)
        if not st:
            continue
        rows.append({
            "Date": today_str(),
            "HomeTeam": m["HomeTeam"],
            "AwayTeam": m["AwayTeam"],
            "home_n": norm_name(m["HomeTeam"]),
            "away_n": norm_name(m["AwayTeam"]),
            "H": m["H"], "D": m["D"], "A": m["A"], "O25": m.get("O25"),
            "mesafe": st["mesafe"],
            "sinyal": st["sinyal"],
            "sinyal_pct": st["sinyal_pct"],
            "kaynak": m.get("kaynak", ""),
        })
        blocks.append((st["mesafe"], fmt_match(m, st), st))

    if not blocks:
        send_telegram("⚠️ Analiz edilecek maç yok.")
        return

    blocks.sort(key=lambda x: x[0])
    top = blocks[:20]
    srcs = sorted({str(r.get("kaynak", "?")) for r in rows})
    lines = [
        f"📊 {today_str()} Otomatik Sinyal",
        f"Bülten: {len(blocks)} maç | kaynak: {', '.join(srcs)}",
        f"Tarihsel data: {len(hist)} maç",
        "",
    ]
    for _, txt, _ in top:
        lines.append(txt)
        lines.append("")
    lines.append("En net 5 sinyal")
    for i, (dist, txt, st) in enumerate(top[:5], 1):
        name = txt.split("\n")[0].replace("<b>", "").replace("</b>", "")
        lines.append(f"{i}. {name} → {st['sinyal']} %{st['sinyal_pct']} (mesafe {dist})")
    send_telegram("\n".join(lines))
    os.makedirs(DATA_DIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(SIGNALS_FILE, index=False)


def results_from_soccerbets():
    df = fetch_bulletin_soccerbets(only_today=False)
    if df is None or len(df) == 0 or "FTHG" not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=["FTHG", "FTAG"]).copy()
    df["home_n"] = df["HomeTeam"].map(norm_name)
    df["away_n"] = df["AwayTeam"].map(norm_name)
    df["FTR"] = np.where(df["FTHG"] > df["FTAG"], "H", np.where(df["FTHG"] < df["FTAG"], "A", "D"))
    df["Over25"] = ((df["FTHG"] + df["FTAG"]) > 2.5).astype(float)
    df["BTTS"] = ((df["FTHG"] > 0) & (df["FTAG"] > 0)).astype(float)
    df["kaynak"] = "soccerbets"
    return df


def results_from_football_data():
    frames = []
    for code in LEAGUES:
        url = f"https://www.football-data.co.uk/mmz4281/{SEASON}/{code}.csv"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200 or len(r.content) < 400:
                continue
            df = standardize(pd.read_csv(pd.io.common.StringIO(r.text), low_memory=False))
            if "FTR" in df.columns:
                df = df[df["FTR"].isin(["H", "D", "A"])]
            if len(df):
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["home_n"] = out["HomeTeam"].map(norm_name)
    out["away_n"] = out["AwayTeam"].map(norm_name)
    out["kaynak"] = "football_data"
    return out


def results_from_odds_scores():
    if not ODDS_API_KEY:
        return pd.DataFrame()
    rows = []
    for sport in SPORTS_CORE:
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/scores",
                params={"apiKey": ODDS_API_KEY, "daysFrom": 1},
                timeout=25,
            )
            if r.status_code != 200:
                continue
            for ev in r.json():
                if not ev.get("completed"):
                    continue
                scores = {s.get("name"): s.get("score") for s in ev.get("scores") or []}
                hg = pd.to_numeric(scores.get(ev.get("home_team")), errors="coerce")
                ag = pd.to_numeric(scores.get(ev.get("away_team")), errors="coerce")
                if pd.isna(hg) or pd.isna(ag):
                    continue
                rows.append({
                    "HomeTeam": ev.get("home_team"),
                    "AwayTeam": ev.get("away_team"),
                    "home_n": norm_name(ev.get("home_team")),
                    "away_n": norm_name(ev.get("away_team")),
                    "FTHG": float(hg),
                    "FTAG": float(ag),
                    "FTR": "H" if hg > ag else ("A" if hg < ag else "D"),
                    "Over25": float((hg + ag) > 2.5),
                    "BTTS": float((hg > 0) and (ag > 0)),
                    "kaynak": "odds_api",
                })
            left = r.headers.get("x-requests-remaining")
            if left is not None and int(left) < 30:
                break
        except Exception as e:
            print("scores hata", sport, e)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def collect_results():
    out = merge_matches(
        results_from_soccerbets(),
        results_from_football_data(),
        results_from_odds_scores(),
        how="result",
    )
    if out is None or len(out) == 0:
        return pd.DataFrame()
    os.makedirs(DATA_DIR, exist_ok=True)
    out.to_csv(LIVE_FILE, index=False)
    return out


def signal_hit(sig, row):
    if sig == "Home":
        return row.get("FTR") == "H"
    if sig == "Away":
        return row.get("FTR") == "A"
    if sig == "Over":
        return float(row.get("Over25", 0) or 0) == 1
    if sig == "BTTS":
        return float(row.get("BTTS", 0) or 0) == 1
    return False


def update_and_review(hist):
    finished = collect_results()
    n_all = 0 if finished is None else len(finished)
    lines = [
        f"📌 {today_str()} Gün Sonu Raporu",
        f"Skor havuzu: {n_all}",
        "",
    ]
    if not os.path.exists(SIGNALS_FILE):
        lines.append("Sabah sinyal dosyası yok.")
        send_telegram("\n".join(lines))
        return
    sig = read_csv_flex(SIGNALS_FILE)
    if sig is None or len(sig) == 0:
        lines.append("Sabah sinyal dosyası boş.")
        send_telegram("\n".join(lines))
        return
    if "home_n" not in sig.columns:
        sig["home_n"] = sig["HomeTeam"].map(norm_name)
        sig["away_n"] = sig["AwayTeam"].map(norm_name)
    if finished is None or len(finished) == 0:
        lines.append("Hiçbir kaynakta skor yok.")
        send_telegram("\n".join(lines))
        return
    merged = sig.merge(finished, on=["home_n", "away_n"], how="left", suffixes=("", "_res"))
    ok = wait = miss = 0
    lines.append("Sabah sinyalleri vs sonuç")
    for _, r in merged.iterrows():
        name = f"{r['HomeTeam']} - {r['AwayTeam']}"
        sig_name = str(r.get("sinyal", ""))
        if pd.isna(r.get("FTR")):
            wait += 1
            lines.append(f"⏳ {name} → {sig_name} henüz sonuç yok")
            continue
        hit = signal_hit(sig_name, r)
        skor = ""
        if pd.notna(r.get("FTHG")):
            skor = f" ({int(r['FTHG'])}-{int(r['FTAG'])})"
        if hit:
            ok += 1
            lines.append(f"✅ {name}{skor} → {sig_name} tuttu")
        else:
            miss += 1
            lines.append(f"❌ {name}{skor} → {sig_name} tutmadı")
    lines.append("")
    lines.append(f"Tuttu: {ok} | Tutmadı: {miss} | Bekleyen: {wait}")
    send_telegram("\n".join(lines))


def main():
    hist = load_local_history()
    if MODE == "update":
        update_and_review(hist)
    else:
        scan_signals(hist)


if __name__ == "__main__":
    main()
