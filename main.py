#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sinyal kapısı — son kural seti (21.09.2026)

Lig kesilmez. Günlük tavan yok. BTTS/Over adet limiti yok.
Derbi kuralı yok. Beraberlik 3.40 kuralı yok. Away 2.10 tavanı yok.

Kesiciler:
  - Home oranı < 1.33
  - Mesafe >= 0.20
  - Over/BTTS için O2.5 yoksa veya 1.40–1.85 dışıysa
  - |n30-n100| >= 15
  - Home/Away sinyal < 70 veya iki pencere < 68
  - Over sinyal < 72
  - BTTS sinyal < 72 veya n30_btts < 70 veya n100_btts < 65
  - Home 1.33–1.45 ise n100 Home < 70 veya mesafe >= 0.12
  - Aynı maç ikinci satır
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# SABİTLER
# ---------------------------------------------------------------------------

HOME_ODDS_MIN = 1.33
DIST_MAX = 0.20
SPLIT_MAX = 15.0

MIN_HOME_AWAY = 70.0
MIN_WINDOW_1X2 = 68.0
MIN_OVER = 72.0
MIN_BTTS = 72.0
MIN_BTTS_N30 = 70.0
MIN_BTTS_N100 = 65.0

O25_MIN = 1.40
O25_MAX = 1.85

HOME_SHORT_BAND_MAX = 1.45
HOME_SHORT_N100 = 70.0
HOME_SHORT_DIST = 0.12


def _f(x: Any, default: Optional[float] = None) -> Optional[float]:
    if x is None:
        return default
    if isinstance(x, str):
        s = x.strip().replace(",", ".")
        if s in ("", "-", "None", "null"):
            return default
        try:
            return float(s)
        except ValueError:
            return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _norm_type(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s.startswith("home") or s.startswith("ev"):
        return "Home"
    if s.startswith("away") or s.startswith("dep"):
        return "Away"
    if s.startswith("over") or s.startswith("üst"):
        return "Over"
    if "btts" in s or "kg" in s:
        return "BTTS"
    return ""


def match_key(row: Dict[str, Any]) -> str:
    h = str(row.get("home") or row.get("home_team") or "").strip().lower()
    a = str(row.get("away") or row.get("away_team") or "").strip().lower()
    h = re.sub(r"\s+", " ", h)
    a = re.sub(r"\s+", " ", a)
    return f"{h}||{a}"


def pass_signal(row: Dict[str, Any]) -> Tuple[bool, str]:
    typ = _norm_type(row.get("signal_type") or row.get("sinyal") or row.get("tip"))
    pct = _f(row.get("signal_pct") or row.get("pct") or row.get("sinyal_pct"))
    dist = _f(row.get("mesafe") or row.get("distance") or row.get("dist"), 0.0) or 0.0
    h_odd = _f(row.get("home_odds") or row.get("odd_1") or row.get("h"))
    a_odd = _f(row.get("away_odds") or row.get("odd_2") or row.get("a"))
    o25 = _f(row.get("o25") or row.get("O2.5") or row.get("over25"))

    n30_h = _f(row.get("n30_h"), 0.0) or 0.0
    n30_a = _f(row.get("n30_a"), 0.0) or 0.0
    n30_o = _f(row.get("n30_o"), 0.0) or 0.0
    n30_b = _f(row.get("n30_btts"), 0.0) or 0.0
    n100_h = _f(row.get("n100_h"), 0.0) or 0.0
    n100_a = _f(row.get("n100_a"), 0.0) or 0.0
    n100_o = _f(row.get("n100_o"), 0.0) or 0.0
    n100_b = _f(row.get("n100_btts"), 0.0) or 0.0

    if typ not in ("Home", "Away", "Over", "BTTS"):
        return False, "DROP_TYPE"

    if dist >= DIST_MAX:
        return False, "DROP_DIST"

    if typ == "Home":
        if pct is None or pct < MIN_HOME_AWAY:
            return False, "DROP_PCT"
        if n30_h < MIN_WINDOW_1X2 or n100_h < MIN_WINDOW_1X2:
            return False, "DROP_WINDOW"
        if abs(n30_h - n100_h) >= SPLIT_MAX:
            return False, "DROP_SPLIT"
        if h_odd is None or h_odd < HOME_ODDS_MIN:
            return False, "DROP_SHORT"
        if h_odd <= HOME_SHORT_BAND_MAX:
            if n100_h < HOME_SHORT_N100 or dist >= HOME_SHORT_DIST:
                return False, "DROP_SHORT_BAND"
        return True, "PASS"

    if typ == "Away":
        if pct is None or pct < MIN_HOME_AWAY:
            return False, "DROP_PCT"
        if n30_a < MIN_WINDOW_1X2 or n100_a < MIN_WINDOW_1X2:
            return False, "DROP_WINDOW"
        if abs(n30_a - n100_a) >= SPLIT_MAX:
            return False, "DROP_SPLIT"
        return True, "PASS"

    if typ == "Over":
        if o25 is None:
            return False, "DROP_NO_O25"
        if o25 < O25_MIN or o25 > O25_MAX:
            return False, "DROP_O25_PRICE"
        if pct is None or pct < MIN_OVER:
            return False, "DROP_PCT"
        if abs(n30_o - n100_o) >= SPLIT_MAX:
            return False, "DROP_SPLIT"
        return True, "PASS"

    # BTTS
    if o25 is None:
        return False, "DROP_NO_O25"
    if o25 < O25_MIN or o25 > O25_MAX:
        return False, "DROP_O25_PRICE"
    if pct is None or pct < MIN_BTTS:
        return False, "DROP_PCT"
    if n30_b < MIN_BTTS_N30 or n100_b < MIN_BTTS_N100:
        return False, "DROP_BTTS_N"
    if abs(n30_b - n100_b) >= SPLIT_MAX:
        return False, "DROP_SPLIT"
    return True, "PASS"


def dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aynı ev-dep çifti: en yüksek sinyal_pct kalsın."""
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = match_key(r)
        prev = best.get(k)
        if prev is None:
            best[k] = r
            continue
        if (_f(r.get("signal_pct"), 0) or 0) > (_f(prev.get("signal_pct"), 0) or 0):
            best[k] = r
    return list(best.values())


def filter_signals(raw: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept, dropped = [], []
    for row in raw:
        ok, why = pass_signal(row)
        row = dict(row)
        row["gate"] = why
        row["signal_type"] = _norm_type(row.get("signal_type") or row.get("sinyal") or row.get("tip"))
        (kept if ok else dropped).append(row)
    kept = dedupe(kept)
    kept.sort(key=lambda r: _f(r.get("signal_pct"), 0) or 0, reverse=True)
    return kept, dropped


def fmt_odd(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{x:.2f}"


def format_row(row: Dict[str, Any]) -> str:
    home = row.get("home") or row.get("home_team") or "?"
    away = row.get("away") or row.get("away_team") or "?"
    h = _f(row.get("home_odds") or row.get("odd_1"))
    d = _f(row.get("draw_odds") or row.get("odd_x"))
    a = _f(row.get("away_odds") or row.get("odd_2"))
    o25 = _f(row.get("o25") or row.get("O2.5"))
    dist = _f(row.get("mesafe") or row.get("distance"), 0) or 0
    typ = row.get("signal_type") or ""
    pct = _f(row.get("signal_pct"), 0) or 0
    n30_h = _f(row.get("n30_h"), 0) or 0
    n30_a = _f(row.get("n30_a"), 0) or 0
    n30_o = _f(row.get("n30_o"), 0) or 0
    n30_b = _f(row.get("n30_btts"), 0) or 0
    n100_h = _f(row.get("n100_h"), 0) or 0
    n100_a = _f(row.get("n100_a"), 0) or 0
    n100_o = _f(row.get("n100_o"), 0) or 0
    n100_b = _f(row.get("n100_btts"), 0) or 0

    lines = [
        f"{home} - {away}",
        f"1/X/2: {fmt_odd(h)} / {fmt_odd(d)} / {fmt_odd(a)}   O2.5: {fmt_odd(o25) if o25 is not None else '-'}",
        f"Mesafe: {dist:.3f}".replace(".", ".") ,
        f"n30   H %{n30_h:.1f} | A %{n30_a:.1f} | O %{n30_o:.1f} | BTTS %{n30_b:.1f}",
        f"n100  H %{n100_h:.1f} | A %{n100_a:.1f} | O %{n100_o:.1f} | BTTS %{n100_b:.1f}",
        f"Sinyal: {typ} %{pct:.1f}",
    ]
    return "\n".join(lines)


def format_report(kept: List[Dict[str, Any]], scanned: int, raw_n: int) -> str:
    day = datetime.now().strftime("%d/%m/%Y")
    head = (
        f"📊 {day} Otomatik Sinyal\n"
        f"Taranan: {scanned} maç | ham sinyal: {raw_n} | gönderilen: {len(kept)}\n"
        f"kaynak: fixtures_csv, soccerbets\n"
    )
    if not kept:
        return head + "\n(bugün kapıdan geçen sinyal yok)\n"
    body = "\n\n".join(format_row(r) for r in kept)
    return head + "\n" + body + "\n"


# ---------------------------------------------------------------------------
# BAĞLAMA
# Eski main.py'deki tarama fonksiyonun varsa buradan çağır.
# raw_signals her elemanı dict olmalı (alan adları esnek, pass_signal okur).
# ---------------------------------------------------------------------------

def collect_raw_signals() -> Tuple[List[Dict[str, Any]], int]:
    """
    Kendi taramanı buraya bağla.

    Dönüş: (ham_sinyal_listesi, taranan_mac_sayisi)

    Örnek satır:
    {
        "home": "Charleroi", "away": "Cercle Brugge",
        "home_odds": 1.70, "draw_odds": 3.70, "away_odds": 4.20, "o25": 1.57,
        "mesafe": 0.058,
        "n30_h": 33.3, "n30_a": 26.7, "n30_o": 60.0, "n30_btts": 80.0,
        "n100_h": 46.0, "n100_a": 22.0, "n100_o": 59.0, "n100_btts": 65.0,
        "signal_type": "BTTS", "signal_pct": 72.5,
    }
    """
    try:
        from collector import collect  # senin mevcut toplayıcın varsa
        return collect()
    except ImportError:
        return [], 0


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print(text)
        return
    try:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode(
            {"chat_id": chat, "text": text}
        ).encode()
        urllib.request.urlopen(url, data=data, timeout=30)
    except Exception as exc:
        print("telegram hata:", exc)
        print(text)


def main() -> None:
    raw, scanned = collect_raw_signals()
    kept, dropped = filter_signals(raw)

    reasons: Dict[str, int] = {}
    for r in dropped:
        reasons[r.get("gate", "?")] = reasons.get(r.get("gate", "?"), 0) + 1

    report = format_report(kept, scanned or len(raw), len(raw))
    report += "\n— kapı —\n"
    report += f"PASS {len(kept)} | DROP {len(dropped)}\n"
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        report += f"{k}: {v}\n"

    send_telegram(report)


if __name__ == "__main__":
    main()
