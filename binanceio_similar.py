#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
binance.io Similar Candlestick Pattern Analyzer
─────────────────────────────────────────────────
Modules:
  1. binance.io API — OHLCV data fetch
  2. DTW-based similar candlestick finder
  3. Rise/Fall probability calculation
  4. mplfinance trajectory chart drawing
  5. Telegram Bot signal + chart sending
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import numpy as np
import pandas as pd
from scipy.spatial.distance import euclidean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import mplfinance as mpf

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

# ── Coin & TF ──────────────────────────────────
COINS      = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
TIMEFRAMES = ["1h", "4h", "1d"]

# ── Analysis ───────────────────────────────────
PATTERN_LEN    = 30      # current window length (bars)
FORECAST_LEN   = 20      # forecast window (bars)
TOP_K          = 40      # best-match pattern count
MIN_SIMILARITY = 0.50    # minimum similarity threshold

# ── API ────────────────────────────────────────
DATA_LIMIT = 1000        # historical candle count
SLEEP_API  = 0.3         # sleep between API calls (sec)

# ── Chart ──────────────────────────────────────
CHART_DIR    = "charts"
CHART_DPI    = 130
SHOW_LAST_N  = 200       # show last N bars on chart

# ── Bollinger ──────────────────────────────────
BOLL_PERIOD   = 20
BOLL_STD      = 2.0
VOL_MA_PERIOD = 20

# ── Telegram ───────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
SEND_TELEGRAM      = True

# ── Color Scheme ───────────────────────────────
DARK_BG     = "#131722"
PANEL_BG    = "#1e2130"
GRID_COL    = "#2a2e39"
UP_COL      = "#26a69a"
DOWN_COL    = "#ef5350"
PATTERN_BG  = "#1565C0"
FORECAST_BG = "#1B5E20"
TRAJECTORY  = "#FFD54F"
RISE_COL    = "#00E676"
FALL_COL    = "#FF5252"
CONF_COL    = "#FFD54F"
TEXT_COL    = "#b2b5be"
TITLE_COL   = "#e0e0e0"
VOL_MA_COL  = "#FFD54F"

# ── Logging ────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# MODULE 1 — binance.io API: OHLCV Data Fetch
# ═══════════════════════════════════════════════════════════

API_BASE = "https://api.binanceio.ws/api/v4/spot/candlesticks"


def fetch_ohlcv(currency_pair: str, interval: str, limit: int = 1000) -> pd.DataFrame | None:
    """Fetch OHLCV data from binance.io API and return a DataFrame."""
    params = {
        "currency_pair": currency_pair,
        "interval": interval,
        "limit": min(limit, 1000),
    }
    for attempt in range(1, 4):
        try:
            resp = requests.get(API_BASE, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                log.warning("   ⚠️  Empty response for %s [%s]", currency_pair, interval)
                return None

            # binance.io format: [timestamp, volume, close, high, low, open, is_closed]
            rows = []
            for c in data:
                rows.append({
                    "Timestamp": int(c[0]),
                    "Volume":    float(c[1]),
                    "Close":     float(c[2]),
                    "High":      float(c[3]),
                    "Low":       float(c[4]),
                    "Open":      float(c[5]),
                })
            df = pd.DataFrame(rows)
            df["Date"] = pd.to_datetime(df["Timestamp"], unit="s", utc=True)
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            return df

        except Exception as exc:
            log.warning("   ⚠️  Attempt %d failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(SLEEP_API * attempt)

    log.error("   ❌  Could not fetch data for %s [%s]", currency_pair, interval)
    return None


# ═══════════════════════════════════════════════════════════
# MODULE 1b — Indicators (Bollinger + Volume MA)
# ═══════════════════════════════════════════════════════════

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add Bollinger Bands and Volume MA to DataFrame."""
    close = df["Close"]
    df["BB_mid"] = close.rolling(BOLL_PERIOD).mean()
    bb_std = close.rolling(BOLL_PERIOD).std()
    df["BB_upper"] = df["BB_mid"] + BOLL_STD * bb_std
    df["BB_lower"] = df["BB_mid"] - BOLL_STD * bb_std
    df["Vol_MA"] = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    return df


# ═══════════════════════════════════════════════════════════
# MODULE 2 — DTW Similar Candlestick Finder
# ═══════════════════════════════════════════════════════════

def _normalize(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize to [0, 1]."""
    mn, mx = arr.min(), arr.max()
    if mx - mn < 1e-12:
        return np.zeros_like(arr)
    return (arr - mn) / (mx - mn)


def _dtw_distance(s1: np.ndarray, s2: np.ndarray) -> float:
    """Compute DTW distance; falls back to Euclidean if dtw-python unavailable."""
    try:
        from dtw import dtw as dtw_fn
        alignment = dtw_fn(s1, s2, dist_method="euclidean")
        return alignment.distance
    except ImportError:
        return float(np.sqrt(np.sum((s1 - s2) ** 2)))


def scan_history(
    df: pd.DataFrame,
    pattern_len: int = PATTERN_LEN,
    top_k: int = TOP_K,
    min_sim: float = MIN_SIMILARITY,
    forecast_len: int = FORECAST_LEN,
) -> list[dict]:
    """Scan historical data for similar candlestick patterns using DTW."""
    closes = df["Close"].values
    n = len(closes)
    if n < pattern_len + forecast_len + 1:
        log.warning("   ⚠️  Not enough data for pattern scan")
        return []

    # Current window (last PATTERN_LEN bars)
    current_window = closes[-(pattern_len):]
    current_norm = _normalize(current_window)

    # Historical scan (sliding window, stride=1)
    candidates = []
    scan_end = n - pattern_len - forecast_len
    log.info("   🔍 %d pencere taranıyor...", max(0, scan_end))

    for i in range(0, scan_end):
        window = closes[i : i + pattern_len]
        w_norm = _normalize(window)
        dist = _dtw_distance(current_norm, w_norm)
        score = 1.0 / (1.0 + dist)
        if score >= min_sim:
            future_start = i + pattern_len
            future_end = future_start + forecast_len
            future_bars = closes[future_start:future_end].tolist()
            rose = future_bars[-1] > window[-1] if len(future_bars) == forecast_len else False
            candidates.append({
                "start_idx":  i,
                "end_idx":    i + pattern_len,
                "start_date": df.index[i],
                "end_date":   df.index[i + pattern_len - 1],
                "similarity": score,
                "distance":   dist,
                "future_bars": future_bars,
                "rose":       rose,
            })

    # Sort by similarity descending
    candidates.sort(key=lambda x: x["similarity"], reverse=True)

    # Filter overlapping windows (min gap = PATTERN_LEN // 2)
    min_gap = pattern_len // 2
    filtered: list[dict] = []
    for cand in candidates:
        overlaps = False
        for kept in filtered:
            if abs(cand["start_idx"] - kept["start_idx"]) < min_gap:
                overlaps = True
                break
        if not overlaps:
            filtered.append(cand)
        if len(filtered) >= top_k:
            break

    return filtered


# ═══════════════════════════════════════════════════════════
# MODULE 3 — Rise/Fall Probability
# ═══════════════════════════════════════════════════════════

def calc_probability(patterns: list[dict]) -> dict:
    """Calculate rise/fall probability and confidence from found patterns."""
    if not patterns:
        return {}

    rise_count = sum(1 for p in patterns if p["rose"])
    total = len(patterns)
    rise_prob = rise_count / total * 100
    fall_prob = 100 - rise_prob
    confidence = np.mean([p["similarity"] for p in patterns]) * 100

    # Best match as reference
    best = patterns[0]
    ref_start = best["start_date"].strftime("%Y-%m-%d")
    ref_end = best["end_date"].strftime("%Y-%m-%d")

    result = {
        "rise_probability": round(rise_prob, 1),
        "fall_probability": round(fall_prob, 1),
        "confidence":       round(confidence, 1),
        "similar_count":    total,
        "ref_start":        ref_start,
        "ref_end":          ref_end,
        "best_similarity":  round(best["similarity"] * 100, 1),
    }

    log.info("   ✅ %d benzer örüntü | Ort. benzerlik: %%%s", total, result["confidence"])
    log.info(
        "   📈 Rise: %%%s  |  📉 Fall: %%%s  |  🎯 Güven: %%%s",
        result["rise_probability"],
        result["fall_probability"],
        result["confidence"],
    )
    log.info("   📅 Referans: %s → %s", ref_start, ref_end)

    return result


# ═══════════════════════════════════════════════════════════
# MODULE 4 — mplfinance Trajectory Chart
# ═══════════════════════════════════════════════════════════

def _interval_to_freq(interval: str) -> str:
    """Convert interval string to pandas offset alias."""
    mapping = {"1h": "h", "4h": "4h", "1d": "D"}
    return mapping.get(interval, "h")


def draw_chart(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    patterns: list[dict],
    result: dict,
) -> str:
    """Draw candlestick chart with trajectory overlay; return file path."""
    Path(CHART_DIR).mkdir(exist_ok=True)

    # Prepare display slice
    show_df = df.tail(SHOW_LAST_N).copy()
    current_price = show_df["Close"].iloc[-1]

    # ── mplfinance style ───────────────────────
    mc = mpf.make_marketcolors(
        up=UP_COL, down=DOWN_COL,
        edge={"up": UP_COL, "down": DOWN_COL},
        wick={"up": UP_COL, "down": DOWN_COL},
        volume={"up": UP_COL, "down": DOWN_COL},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        figcolor=DARK_BG,
        facecolor=PANEL_BG,
        gridcolor=GRID_COL,
        gridstyle="--",
        gridaxis="both",
        rc={
            "axes.labelcolor": TEXT_COL,
            "xtick.color": TEXT_COL,
            "ytick.color": TEXT_COL,
        },
    )

    # ── Addplots (Bollinger + Vol MA) ──────────
    add_plots = []
    if "BB_upper" in show_df.columns:
        add_plots.append(mpf.make_addplot(
            show_df["BB_upper"], color="#90caf9", linestyle="--",
            alpha=0.6, panel=0, secondary_y=False,
        ))
        add_plots.append(mpf.make_addplot(
            show_df["BB_lower"], color="#90caf9", linestyle="--",
            alpha=0.6, panel=0, secondary_y=False,
        ))
        add_plots.append(mpf.make_addplot(
            show_df["BB_mid"], color="#4fc3f7", width=1.0,
            panel=0, secondary_y=False,
        ))
    if "Vol_MA" in show_df.columns:
        add_plots.append(mpf.make_addplot(
            show_df["Vol_MA"], color=VOL_MA_COL, width=1.0,
            panel=1, secondary_y=False,
        ))

    # ── Plot ───────────────────────────────────
    title_text = (
        f"{symbol.replace('_', '/')} [{interval.upper()}] — "
        f"Benzer Şamdan Analizi — {current_price:,.4f} USDT"
    )

    fig, axes = mpf.plot(
        show_df,
        type="candle",
        style=style,
        volume=True,
        addplot=add_plots if add_plots else None,
        figsize=(16, 9),
        returnfig=True,
        panel_ratios=(3, 1),
        title=title_text,
    )

    ax = axes[0]  # price axis

    # Apply title colour
    fig.suptitle(title_text, color=TITLE_COL, fontsize=13, fontweight="bold", y=0.98)
    ax.set_title("")  # remove duplicate

    # ── Pattern region (blue axvspan) ──────────
    n_bars = len(show_df)
    pat_start = max(0, n_bars - PATTERN_LEN)
    ax.axvspan(pat_start, n_bars - 1, alpha=0.12, color=PATTERN_BG, label="Mevcut Örüntü")

    # ── Forecast region (green axvspan) + trajectory ──
    freq = _interval_to_freq(interval)
    last_date = show_df.index[-1]
    future_dates = pd.date_range(start=last_date, periods=FORECAST_LEN + 1, freq=freq)[1:]

    # Compute average trajectory from patterns
    valid_futures = [p["future_bars"] for p in patterns if len(p["future_bars"]) == FORECAST_LEN]
    if valid_futures:
        # Normalize each future sequence relative to its starting value, then rescale
        trajectories = []
        for fb in valid_futures:
            fb_arr = np.array(fb)
            start_val = fb_arr[0]
            if start_val > 0:
                ratio = fb_arr / start_val
                trajectories.append(ratio * current_price)
        if trajectories:
            avg_traj = np.mean(trajectories, axis=0)

            # Extend x-axis for forecast
            forecast_x = np.arange(n_bars, n_bars + FORECAST_LEN)
            ax.axvspan(n_bars - 1, n_bars + FORECAST_LEN - 1,
                       alpha=0.10, color=FORECAST_BG, label="Tahmin Bölgesi")
            ax.plot(forecast_x, avg_traj, color=TRAJECTORY, linewidth=2.5,
                    linestyle="--", zorder=5, label="Beklenen Yörünge")

    # ── Info box (top-right) — colorized per-line ─
    y_offset = 0.97
    for line, color in [
        (f"Rise   %{result['rise_probability']}", RISE_COL),
        (f"Fall   %{result['fall_probability']}", FALL_COL),
        (f"Guven  %{result['confidence']}", CONF_COL),
        (f"Oruntu: {result['similar_count']}", TEXT_COL),
    ]:
        ax.text(
            0.98, y_offset, line,
            transform=ax.transAxes, va="top", ha="right",
            fontsize=10, color=color, family="monospace",
            bbox=dict(boxstyle="round,pad=0.5", fc=PANEL_BG, ec=GRID_COL, alpha=0.9),
        )
        y_offset -= 0.06

    # ── Reference label (bottom-left) ──────────
    ref_text = (
        f"Ref: {result['ref_start']} → {result['ref_end']} "
        f"| %{result['best_similarity']} benzerlik"
    )
    ax.text(
        0.02, 0.03, ref_text,
        transform=ax.transAxes, va="bottom", ha="left",
        fontsize=7.5, color=TEXT_COL,
    )

    # ── Legend ─────────────────────────────────
    ax.legend(loc="upper left", fontsize=8, facecolor=PANEL_BG,
              edgecolor=GRID_COL, labelcolor=TEXT_COL)

    # ── Save ───────────────────────────────────
    chart_path = os.path.join(CHART_DIR, f"{symbol}_{interval}_similar.png")
    fig.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight",
                facecolor=DARK_BG, edgecolor="none")
    plt.close(fig)
    log.info("   🖼  Kaydedildi: %s", chart_path)
    return chart_path


# ═══════════════════════════════════════════════════════════
# MODULE 5 — Telegram Signal Sending
# ═══════════════════════════════════════════════════════════

def _escape_md2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    out = []
    for ch in text:
        if ch in special:
            out.append(f"\\{ch}")
        else:
            out.append(ch)
    return "".join(out)


def _build_telegram_message(symbol: str, interval: str, result: dict, current_price: float) -> str:
    """Build Telegram MarkdownV2 message."""
    pair = symbol.replace("_", "/")
    raw = (
        f"📊 *{pair} — {interval.upper()} Benzer Şamdan Sinyali*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕯️ Analiz Penceresi: Son {PATTERN_LEN} mum\n"
        f"🔍 Benzer Örüntü: *{result['similar_count']} adet*\n"
        f"📐 Ort. Benzerlik: *%{result['confidence']}*\n\n"
        f"📈 Yükseliş İhtimali: *%{result['rise_probability']}*\n"
        f"📉 Düşüş İhtimali: *%{result['fall_probability']}*\n"
        f"🎯 Güven Skoru: *%{result['confidence']}*\n\n"
        f"💰 Güncel Fiyat: `{current_price:,.2f} USDT`\n"
        f"📅 Referans: `{result['ref_start']} → {result['ref_end']}`\n"
        f"⏱ Tahmin: Sonraki {FORECAST_LEN} mum\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 binance.io API · DTW Algoritması"
    )
    return _escape_md2(raw)


def send_telegram(chart_path: str, symbol: str, interval: str,
                  result: dict, current_price: float) -> bool:
    """Send chart image + caption to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("   ⚠️  Telegram credentials not set, skipping")
        return False

    caption = _build_telegram_message(symbol, interval, result, current_price)
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    # Try sendPhoto
    try:
        with open(chart_path, "rb") as photo:
            resp = requests.post(
                f"{api_url}/sendPhoto",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                },
                files={"photo": photo},
                timeout=30,
            )
        if resp.ok:
            log.info("   📨 Telegram gönderildi ✓")
            return True
        log.warning("   ⚠️  sendPhoto failed (%s), trying sendMessage", resp.status_code)
    except Exception as exc:
        log.warning("   ⚠️  sendPhoto error: %s", exc)

    # Fallback: sendMessage (text only)
    try:
        resp = requests.post(
            f"{api_url}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": caption,
                "parse_mode": "MarkdownV2",
            },
            timeout=15,
        )
        if resp.ok:
            log.info("   📨 Telegram (text only) gönderildi ✓")
            return True
        log.warning("   ⚠️  sendMessage also failed: %s", resp.text)
    except Exception as exc:
        log.warning("   ⚠️  sendMessage error: %s", exc)

    return False


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="binance.io Similar Candlestick Pattern Analyzer",
    )
    parser.add_argument(
        "--coins", nargs="+", default=COINS,
        help="Currency pairs (e.g. BTC_USDT ETH_USDT)",
    )
    parser.add_argument(
        "--timeframes", nargs="+", default=TIMEFRAMES,
        help="Timeframes (e.g. 1h 4h 1d)",
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Disable Telegram notifications",
    )
    parser.add_argument(
        "--limit", type=int, default=DATA_LIMIT,
        help="Number of historical candles to fetch",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coins = args.coins
    tfs = args.timeframes
    send_tg = SEND_TELEGRAM and not args.no_telegram
    limit = args.limit

    total = len(coins) * len(tfs)
    log.info("🚀 binance.io Similar Candlestick — %d coin × %d TF = %d analiz",
             len(coins), len(tfs), total)

    for coin in coins:
        for tf in tfs:
            log.info("")
            log.info("⏳ %s [%s] işleniyor...", coin, tf)

            # 1. Fetch data
            try:
                df = fetch_ohlcv(coin, tf, limit)
            except Exception as exc:
                log.error("   ❌ Veri çekme hatası: %s", exc)
                continue
            if df is None or df.empty:
                continue
            log.info("   📡 %d mum çekildi", len(df))

            # 2. Indicators
            try:
                df = add_indicators(df)
            except Exception as exc:
                log.error("   ❌ İndikatör hatası: %s", exc)
                continue

            # 3. DTW scan
            try:
                patterns = scan_history(df, PATTERN_LEN, TOP_K, MIN_SIMILARITY, FORECAST_LEN)
            except Exception as exc:
                log.error("   ❌ Tarama hatası: %s", exc)
                continue
            if not patterns:
                log.info("   ⚠️  Benzer örüntü bulunamadı")
                continue

            # 4. Probability
            try:
                result = calc_probability(patterns)
            except Exception as exc:
                log.error("   ❌ Olasılık hesap hatası: %s", exc)
                continue

            # 5. Chart
            try:
                chart_path = draw_chart(df, coin, tf, patterns, result)
            except Exception as exc:
                log.error("   ❌ Grafik hatası: %s", exc)
                chart_path = None

            # 6. Telegram
            if send_tg and chart_path:
                try:
                    current_price = df["Close"].iloc[-1]
                    send_telegram(chart_path, coin, tf, result, current_price)
                except Exception as exc:
                    log.error("   ❌ Telegram hatası: %s", exc)

            time.sleep(1)

    log.info("")
    log.info("✅ Tüm analizler tamamlandı.")


if __name__ == "__main__":
    main()
