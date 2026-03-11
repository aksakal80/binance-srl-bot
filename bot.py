#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance SRL Sinyal Botu v3.0
Destek/Direnç seviyelerine yaklaşan coinleri tespit eder ve Telegram'a bildirir.
"""

import os
import sys
import time
import logging
import argparse
import asyncio
import traceback
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ═══════════════════════════════════════════════
# BÖLÜM 0 — YAPILANDIRMA SABİTLERİ
# ═══════════════════════════════════════════════
# ╔══════════════════════════════════════════════╗
# ║  BURAYA KENDİ BİLGİLERİNİZİ GİRİN           ║
# ╚══════════════════════════════════════════════╝

# ─── Telegram ───
TELEGRAM_TOKEN     = ""   # ← BotFather'dan aldığınız token (örn: "123456:ABC-DEF...")
TELEGRAM_CHAT_ID   = ""   # ← Grubun ID'si (örn: "-1001234567890")
TELEGRAM_THREAD_ID = ""   # ← Forum alt konu ID — tek timeframe modunda (yoksa boş bırakın)

# ─── Çoklu Timeframe Yapılandırması ───────────────────────────────────────────
# python bot.py --multi  komutuyla çalıştırıldığında bu liste kullanılır.
# Her satır: ("TIMEFRAME", "CHAT_ID", "THREAD_ID")
#   CHAT_ID   → Telegram grubunuzun ID'si (hepsinde aynı olabilir)
#   THREAD_ID → Her alt konunun (topic) ID'si — nasıl bulunur: web.telegram.org'da
#               ilgili alt konuyu açın, adres çubuğundaki son sayıdır (örn: _12345)
#               Forum grubu değilse THREAD_ID'yi "" (boş) bırakın.
# Satır başındaki # işaretini kaldırarak aktif edin:
TIMEFRAME_CONFIGS = [
    # ("1H",  "-1003880760948", "2"),    # ← THREAD_ID = alt konunun ID'si
    # ("4H",  "-1003880760948", "4"),
    # ("8H",  "-1003880760948", "7"),
    # ("12H", "-1003880760948", "13"),
    # ("1D",  "-1003880760948", "9"),
]

# ─── Timeframe ───
ACTIVE_TIMEFRAME  = "1h"        # --timeframe ile override edilir
CANDLE_LIMIT      = 300
SCAN_INTERVAL_SEC = 900          # 15 dakika

# ─── Sinyal Eşikleri ───
NEAR_PCT          = 1.0          # %1 → YAKIN
APPROACH_PCT      = 3.0          # %3 → YAKLAŞIYOR
MIN_CONFIDENCE    = 3            # Minimum güven skoru (yükseltildi: daha kaliteli sinyal)

# ─── İndikatör Parametreleri ───
RSI_PERIOD        = 14
RSI_SUPPORT_MAX   = 45           # Destek: RSI < 45 (biraz genişletildi)
RSI_RESIST_MIN    = 55           # Direnç: RSI > 55
VOL_SPIKE_MULT    = 1.5
VOL_LOOKBACK      = 20
EMA_SHORT         = 20
EMA_LONG          = 50

# ─── Destek/Direnç ───
SWING_WINDOW      = 5            # 5 mum her yanda → daha anlamlı pivot noktaları
CLUSTER_TOL_PCT   = 0.8          # %0.8 tolerans → seviyeleri düzgün kümeliyor
TOUCH_TOL_PCT     = 0.5          # %0.5 içine gelen kapanış "dokunuş" sayılır
MIN_VOLUME_USDT   = 500_000

# ─── Best 20 ───
BEST_N            = 20

# ─── Grafik ───
CHART_CANDLES     = 80
CHART_BG_COLOR    = "#0d1117"
CHART_UP_COLOR    = "#00c896"
CHART_DOWN_COLOR  = "#ff4560"
CHART_TEMP_DIR    = "tmp_charts"

# ─── Binance API ───
BINANCE_API_KEY    = ""   # ← Binance API anahtarınız (opsiyonel, boş bırakılabilir)
BINANCE_API_SECRET = ""   # ← Binance gizli anahtarınız (opsiyonel, boş bırakılabilir)

# ─── API ───
BINANCE_BASE_URL  = "https://api.binance.com"
API_RETRY_COUNT   = 3
API_RETRY_DELAY   = 5
SYMBOL_DELAY      = 0.1
RATE_LIMIT_WEIGHT = 1100


# ═══════════════════════════════════════════════
# BÖLÜM YARDIMCI — LOGLAMA KURULUMU
# ═══════════════════════════════════════════════

def loglama_kur(timeframe: str) -> logging.Logger:
    """Konsol INFO, bot_TF.log DEBUG, errors.log ERROR loglaması kurar.
    Multiprocessing kullanımı için mevcut handler'ları temizler ve yeniden kurar."""
    logger = logging.getLogger("binance_srl_bot")
    logger.setLevel(logging.DEBUG)

    # Her process kendi handler'larını kursun (multiprocessing desteği için temizle)
    logger.handlers.clear()

    fmt_konsol = logging.Formatter(
        f"%(asctime)s [{timeframe.upper()}] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fmt_dosya = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Konsol — INFO
    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(logging.INFO)
    konsol.setFormatter(fmt_konsol)
    logger.addHandler(konsol)

    # bot_TF.log — DEBUG (her timeframe ayrı dosyaya yazar)
    try:
        tf_dosya = logging.FileHandler(f"bot_{timeframe.upper()}.log", encoding="utf-8")
        tf_dosya.setLevel(logging.DEBUG)
        tf_dosya.setFormatter(fmt_dosya)
        logger.addHandler(tf_dosya)
    except Exception:
        pass

    # errors.log — ERROR
    try:
        hata_dosya = logging.FileHandler("errors.log", encoding="utf-8")
        hata_dosya.setLevel(logging.ERROR)
        hata_dosya.setFormatter(fmt_dosya)
        logger.addHandler(hata_dosya)
    except Exception:
        pass

    return logger


log = logging.getLogger("binance_srl_bot")


# ═══════════════════════════════════════════════
# BÖLÜM A — VERİ ÇEKİCİ
# ═══════════════════════════════════════════════

def _api_get(url: str, params: dict = None, timeout: int = 15) -> dict | list:
    """Binance API GET isteği; 3 deneme, 5s aralıkla retry.
    BINANCE_API_KEY tanımlıysa X-MBX-APIKEY header'ı eklenir (rate limit 1200 → 6000)."""
    for deneme in range(1, API_RETRY_COUNT + 1):
        try:
            # API key varsa header'a ekle (rate limit artışı için)
            headers = {}
            if BINANCE_API_KEY:
                headers["X-MBX-APIKEY"] = BINANCE_API_KEY
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            # Rate limit ağırlığını takip et
            kullanilan = int(resp.headers.get("X-MBX-USED-WEIGHT-1M", 0))
            if kullanilan >= RATE_LIMIT_WEIGHT:
                log.warning("Rate limit %d'e ulaştı, 60s bekleniyor...", kullanilan)
                time.sleep(60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.warning("API hatası (deneme %d/%d): %s", deneme, API_RETRY_COUNT, e)
            if deneme < API_RETRY_COUNT:
                time.sleep(API_RETRY_DELAY)
            else:
                raise


def hacimli_sembolleri_getir() -> list[str]:
    """
    Binance USDT spot paritelerinden son 24 saatte hacmi
    MIN_VOLUME_USDT (500K) USDT üzerinde olan TÜM sembolleri döndürür.
    """
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/24hr"
    veriler = _api_get(url)

    semboller = []
    for v in veriler:
        sembol = v.get("symbol", "")
        if not sembol.endswith("USDT"):
            continue
        try:
            hacim = float(v.get("quoteVolume", 0))
        except (ValueError, TypeError):
            continue
        if hacim >= MIN_VOLUME_USDT:
            semboller.append(sembol)

    log.info("Toplam %d USDT sembolü filtrelendi (hacim > %s USDT)",
             len(semboller), f"{MIN_VOLUME_USDT:,.0f}")
    return semboller


def mum_verisi_getir(sembol: str, timeframe: str, limit: int = CANDLE_LIMIT) -> pd.DataFrame | None:
    """
    Belirtilen sembol ve timeframe için OHLCV mumlarını çeker.
    Başarısız olursa None döndürür.
    """
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": sembol,
        "interval": timeframe,
        "limit": limit,
    }
    try:
        veriler = _api_get(url, params=params)
    except Exception as e:
        log.error("Mum verisi alınamadı %s: %s", sembol, e)
        return None

    if not veriler:
        return None

    df = pd.DataFrame(veriler, columns=[
        "acilis_zamani", "acilis", "yuksek", "dusuk", "kapanis",
        "hacim", "kapanis_zamani", "teklif_hacmi", "islem_sayisi",
        "alis_hacmi", "alis_teklif_hacmi", "yoksay"
    ])
    df["acilis_zamani"] = pd.to_datetime(df["acilis_zamani"], unit="ms", utc=True)
    for sutun in ["acilis", "yuksek", "dusuk", "kapanis", "hacim"]:
        df[sutun] = df[sutun].astype(float)
    df = df.set_index("acilis_zamani").sort_index()
    return df


# ═══════════════════════════════════════════════
# BÖLÜM B — DESTEK/DİRENÇ HESAPLAYICI
# ═══════════════════════════════════════════════

def zone_bilgisi(dokunuslar: int) -> tuple[int, str]:
    """Dokunuş sayısına göre zone numarası ve yıldız döndürür.
    Zone 1 (güçlü): 3+ dokunuş, Zone 2 (orta): 2 dokunuş, Zone 3 (zayıf): 1 dokunuş"""
    if dokunuslar >= 3:
        return 1, "★★★"
    elif dokunuslar == 2:
        return 2, "★★"
    else:
        return 3, "★"


def swing_noktalarini_bul(df: pd.DataFrame, pencere: int = SWING_WINDOW) -> tuple[list, list]:
    """
    Swing High ve Swing Low noktalarını bulur.
    Her iki yanda 'pencere' kadar mum bakılır; daha sağlam pivotlar elde edilir.
    """
    yuksekler = df["yuksek"].values
    dusukler = df["dusuk"].values
    n = len(df)

    swing_highs = []
    swing_lows = []

    for i in range(pencere, n - pencere):
        if all(yuksekler[i] >= yuksekler[i - j] for j in range(1, pencere + 1)) and \
           all(yuksekler[i] >= yuksekler[i + j] for j in range(1, pencere + 1)):
            swing_highs.append(yuksekler[i])

        if all(dusukler[i] <= dusukler[i - j] for j in range(1, pencere + 1)) and \
           all(dusukler[i] <= dusukler[i + j] for j in range(1, pencere + 1)):
            swing_lows.append(dusukler[i])

    return swing_highs, swing_lows


def dokunuslari_say(df: pd.DataFrame, seviye: float, tolerans_pct: float = TOUCH_TOL_PCT) -> int:
    """Fiyatın belirli bir seviyeye kaç kez yaklaştığını sayar.
    Her kapanış fiyatı seviyenin tolerans_pct yüzdesi içine girerse 'dokunuş' sayılır."""
    kapanis = df["kapanis"].values
    tol = seviye * tolerans_pct / 100
    dokunuslar = 0
    onceki_dokundu = False
    for k in kapanis:
        if abs(k - seviye) <= tol:
            if not onceki_dokundu:
                dokunuslar += 1
            onceki_dokundu = True
        else:
            onceki_dokundu = False
    return max(1, dokunuslar)


def kumeleme_yap(seviyeler: list, tolerans_pct: float = CLUSTER_TOL_PCT) -> list[dict]:
    """
    Birbirine yakın seviyeleri kümeleyerek ortalama seviye ve küme büyüklüğü döndürür.
    """
    if not seviyeler:
        return []

    sirali = sorted(seviyeler)
    kumeler = []
    mevcut_kume = [sirali[0]]

    for seviye in sirali[1:]:
        kume_ort = np.mean(mevcut_kume)
        if abs(seviye - kume_ort) / kume_ort * 100 <= tolerans_pct:
            mevcut_kume.append(seviye)
        else:
            kumeler.append({"seviye": float(np.mean(mevcut_kume)), "kume_byt": len(mevcut_kume)})
            mevcut_kume = [seviye]

    kumeler.append({"seviye": float(np.mean(mevcut_kume)), "kume_byt": len(mevcut_kume)})
    return kumeler


def destek_direnc_hesapla(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """
    Swing pivot noktaları + dokunuş sayısı kullanarak Destek ve Direnç seviyelerini hesaplar.
    Gate.io stili: anlamlı pivot + dokunuş sayısına göre güç.
    """
    mevcut_fiyat = df["kapanis"].iloc[-1]

    swing_highs, swing_lows = swing_noktalarini_bul(df)

    # Kümeleme
    direnc_ham = [s for s in swing_highs if s > mevcut_fiyat]
    destek_ham = [s for s in swing_lows if s < mevcut_fiyat]

    direnc_kumeleri = kumeleme_yap(direnc_ham)
    destek_kumeleri = kumeleme_yap(destek_ham)

    def zone_ekle(kumeler: list[dict]) -> list[dict]:
        sonuc = []
        for k in kumeler:
            dokunusu = dokunuslari_say(df, k["seviye"])
            zone_no, zone_yildiz = zone_bilgisi(dokunusu)
            sonuc.append({
                "seviye": k["seviye"],
                "guc": dokunusu,
                "zone_no": zone_no,
                "zone_yildiz": zone_yildiz,
            })
        return sonuc

    destekler = zone_ekle(destek_kumeleri)
    direncleri = zone_ekle(direnc_kumeleri)

    # En yakın seviyeler önce
    destekler.sort(key=lambda x: abs(mevcut_fiyat - x["seviye"]))
    direncleri.sort(key=lambda x: abs(mevcut_fiyat - x["seviye"]))

    return destekler, direncleri


# ═══════════════════════════════════════════════
# BÖLÜM C — SİNYAL MOTORU
# ═══════════════════════════════════════════════

def rsi_hesapla(df: pd.DataFrame, periyot: int = RSI_PERIOD) -> float:
    """Son mumun RSI değerini hesaplar."""
    kapanis = df["kapanis"]
    delta = kapanis.diff()
    kazanc = delta.clip(lower=0)
    kayip = (-delta).clip(lower=0)
    ort_kazanc = kazanc.ewm(com=periyot - 1, min_periods=periyot).mean()
    ort_kayip = kayip.ewm(com=periyot - 1, min_periods=periyot).mean()
    rs = ort_kazanc / ort_kayip.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def ema_hesapla(df: pd.DataFrame, periyot: int) -> float:
    """Son mumun EMA değerini hesaplar."""
    return float(df["kapanis"].ewm(span=periyot, adjust=False).mean().iloc[-1])


def hacim_spike_hesapla(df: pd.DataFrame) -> tuple[bool, float]:
    """Volume Spike kontrolü — son hacim ortalamadan VOL_SPIKE_MULT kat fazlaysa True."""
    son_hacim = df["hacim"].iloc[-1]
    ort_hacim = df["hacim"].iloc[-(VOL_LOOKBACK + 1):-1].mean()
    if ort_hacim <= 0:
        return False, 0.0
    oran = son_hacim / ort_hacim
    return oran >= VOL_SPIKE_MULT, round(oran, 2)


def sinyal_olustur(sembol: str, df: pd.DataFrame, timeframe: str) -> list[dict]:
    """
    Bir sembol için tüm destek/direnç seviyelerini kontrol eder,
    yakın olanlar için sinyal üretir.

    Güven Skoru (maks 5/5):
    +1 RSI onayı (destek: RSI<45, direnç: RSI>55)
    +1 Volume Spike
    +1 EMA Trend uyumu (destek: fiyat > EMA20, direnç: fiyat < EMA20)
    +1 Zone 1 seviyesi (3+ dokunuş)
    +1 Zone 1 ve RSI ikisi birden onay
    """
    if df is None or len(df) < RSI_PERIOD + SWING_WINDOW + 5:
        return []

    mevcut_fiyat = df["kapanis"].iloc[-1]
    son_zaman = df.index[-1]

    # İndikatörler
    rsi = rsi_hesapla(df)
    vol_spike, vol_oran = hacim_spike_hesapla(df)
    ema_kisa = ema_hesapla(df, EMA_SHORT)
    ema_uzun = ema_hesapla(df, EMA_LONG)

    destekler, direncleri = destek_direnc_hesapla(df)

    sinyaller = []

    def sinyal_olustur_ic(seviye_dict: dict, tur: str) -> dict | None:
        seviye = seviye_dict["seviye"]
        mesafe_pct = abs(mevcut_fiyat - seviye) / mevcut_fiyat * 100

        if mesafe_pct > APPROACH_PCT:
            return None

        yakinlik = "YAKIN" if mesafe_pct <= NEAR_PCT else "YAKLAŞIYOR"

        # Güven skoru
        guven = 0
        rsi_onay = False
        ema_onay = False
        zone1_onay = seviye_dict["zone_no"] == 1

        if tur == "DESTEK":
            if rsi < RSI_SUPPORT_MAX:
                guven += 1
                rsi_onay = True
            if mevcut_fiyat > ema_kisa:
                guven += 1
                ema_onay = True
        else:  # DİRENÇ
            if rsi > RSI_RESIST_MIN:
                guven += 1
                rsi_onay = True
            if mevcut_fiyat < ema_kisa:
                guven += 1
                ema_onay = True

        if vol_spike:
            guven += 1
        if zone1_onay:
            guven += 1
        if zone1_onay and rsi_onay:
            guven += 1  # bonus: güçlü seviye + RSI onayı

        if guven < MIN_CONFIDENCE:
            return None

        return {
            "sembol": sembol,
            "timeframe": timeframe,
            "tur": tur,
            "fiyat": mevcut_fiyat,
            "seviye": seviye,
            "mesafe_pct": round(mesafe_pct, 2),
            "yakinlik": yakinlik,
            "zone_no": seviye_dict["zone_no"],
            "zone_yildiz": seviye_dict["zone_yildiz"],
            "guc": seviye_dict["guc"],
            "guven": guven,
            "rsi": round(rsi, 1),
            "rsi_onay": rsi_onay,
            "vol_spike": vol_spike,
            "vol_oran": vol_oran,
            "ema_onay": ema_onay,
            "ema_kisa": round(ema_kisa, 8),
            "ema_uzun": round(ema_uzun, 8),
            "destekler": destekler[:3],
            "direncleri": direncleri[:3],
            "zaman": son_zaman,
            "df": df,
        }

    for sev in destekler[:5]:
        sinyal = sinyal_olustur_ic(sev, "DESTEK")
        if sinyal:
            sinyaller.append(sinyal)

    for sev in direncleri[:5]:
        sinyal = sinyal_olustur_ic(sev, "DİRENÇ")
        if sinyal:
            sinyaller.append(sinyal)

    # En güçlü sinyali döndür (en düşük zone → en yakın mesafe)
    if sinyaller:
        sinyaller.sort(key=lambda x: (x["zone_no"], x["mesafe_pct"]))
        return [sinyaller[0]]

    return []


# ═══════════════════════════════════════════════
# BÖLÜM D — GRAFİK ÜRETİCİ (3 PANEL)
# ═══════════════════════════════════════════════

def grafik_olustur(sinyal: dict) -> str | None:
    """
    3 panelli grafik oluşturur:
    - Üst: Mum + SR çizgileri + EMA
    - Orta: RSI (40/60 referans çizgileri)
    - Alt: Volume barları

    Geçici dosyaya kaydedip dosya yolunu döndürür.
    """
    try:
        df = sinyal["df"]
        sembol = sinyal["sembol"]
        timeframe = sinyal["timeframe"]
        tur = sinyal["tur"]
        guven = sinyal["guven"]

        # Son CHART_CANDLES mumu al
        grafik_df = df.tail(CHART_CANDLES).copy()

        Path(CHART_TEMP_DIR).mkdir(exist_ok=True)
        dosya_adi = os.path.join(CHART_TEMP_DIR, f"{sembol}_{timeframe}_{int(time.time())}.png")

        # Figure oluştur — 3 panel, oranlar: 3:1:1
        fig, (ax_mum, ax_rsi, ax_vol) = plt.subplots(
            3, 1,
            figsize=(14, 10),
            gridspec_kw={"height_ratios": [3, 1, 1]},
            facecolor=CHART_BG_COLOR
        )

        for ax in [ax_mum, ax_rsi, ax_vol]:
            ax.set_facecolor(CHART_BG_COLOR)
            ax.tick_params(colors="#8b9ab1", labelsize=8)
            ax.spines["bottom"].set_color("#2d3748")
            ax.spines["top"].set_color("#2d3748")
            ax.spines["left"].set_color("#2d3748")
            ax.spines["right"].set_color("#2d3748")

        # X ekseni indeks (sayısal)
        x = np.arange(len(grafik_df))
        tarihler = [t.strftime("%d/%m %H:%M") for t in grafik_df.index]

        # ─── Üst Panel: Mum Grafik ───
        for i, (_, mum) in enumerate(grafik_df.iterrows()):
            renk = CHART_UP_COLOR if mum["kapanis"] >= mum["acilis"] else CHART_DOWN_COLOR
            # Gövde
            alt = min(mum["acilis"], mum["kapanis"])
            ust = max(mum["acilis"], mum["kapanis"])
            yukseklik = max(ust - alt, mum["kapanis"] * 0.0001)
            ax_mum.bar(i, yukseklik, bottom=alt, color=renk, width=0.7, alpha=0.9)
            # Fitil
            ax_mum.plot([i, i], [mum["dusuk"], mum["yuksek"]], color=renk, linewidth=0.8)

        # EMA çizgileri
        kapanis = grafik_df["kapanis"].values
        if len(kapanis) >= EMA_SHORT:
            ema_k = pd.Series(kapanis).ewm(span=EMA_SHORT, adjust=False).mean().values
            ax_mum.plot(x, ema_k, color="#3b82f6", linewidth=1.2, label=f"EMA{EMA_SHORT}", alpha=0.8)
        if len(kapanis) >= EMA_LONG:
            ema_u = pd.Series(kapanis).ewm(span=EMA_LONG, adjust=False).mean().values
            ax_mum.plot(x, ema_u, color="#f97316", linewidth=1.2, label=f"EMA{EMA_LONG}", alpha=0.8)

        # Destek çizgileri
        for idx, sev in enumerate(sinyal["destekler"][:3], 1):
            ax_mum.axhline(
                y=sev["seviye"], color=CHART_UP_COLOR,
                linestyle="--", linewidth=1.0, alpha=0.7
            )
            ax_mum.text(
                len(x) - 1, sev["seviye"],
                f" S{idx} [Z{sev['zone_no']} {sev['zone_yildiz']}]",
                color=CHART_UP_COLOR, fontsize=7, va="bottom"
            )

        # Direnç çizgileri
        for idx, sev in enumerate(sinyal["direncleri"][:3], 1):
            ax_mum.axhline(
                y=sev["seviye"], color=CHART_DOWN_COLOR,
                linestyle="--", linewidth=1.0, alpha=0.7
            )
            ax_mum.text(
                len(x) - 1, sev["seviye"],
                f" R{idx} [Z{sev['zone_no']} {sev['zone_yildiz']}]",
                color=CHART_DOWN_COLOR, fontsize=7, va="top"
            )

        # Sinyal oku (son mumda)
        son_fiyat = grafik_df["kapanis"].iloc[-1]
        son_x = len(x) - 1
        if tur == "DESTEK":
            ax_mum.annotate(
                "▲", xy=(son_x, son_fiyat),
                color=CHART_UP_COLOR, fontsize=16, ha="center", va="top"
            )
        else:
            ax_mum.annotate(
                "▼", xy=(son_x, son_fiyat),
                color=CHART_DOWN_COLOR, fontsize=16, ha="center", va="bottom"
            )

        ax_mum.set_xlim(-1, len(x))
        ax_mum.legend(loc="upper left", framealpha=0.3, fontsize=8,
                      labelcolor="white", facecolor=CHART_BG_COLOR)
        ax_mum.set_title(
            f"{sembol} · {timeframe.upper()} · {tur} · Zone {sinyal['zone_no']} {sinyal['zone_yildiz']} · Güven {guven}/5",
            color="white", fontsize=11, fontweight="bold", pad=8
        )

        # X ekseni etiketleri için (sadece mum panelinde)
        adim = max(1, len(x) // 8)
        ax_mum.set_xticks(x[::adim])
        ax_mum.set_xticklabels([tarihler[i] for i in range(0, len(x), adim)],
                               rotation=30, fontsize=7, color="#8b9ab1")

        # ─── Orta Panel: RSI ───
        # RSI serisi hesapla
        delta = grafik_df["kapanis"].diff()
        kazanc = delta.clip(lower=0)
        kayip = (-delta).clip(lower=0)
        ort_k = kazanc.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
        ort_l = kayip.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
        rs = ort_k / ort_l.replace(0, np.nan)
        rsi_seri = (100 - (100 / (1 + rs))).values

        ax_rsi.plot(x, rsi_seri, color="#a78bfa", linewidth=1.2)
        ax_rsi.axhline(y=40, color="#ff4560", linestyle="--", linewidth=0.8, alpha=0.6)
        ax_rsi.axhline(y=60, color="#ff4560", linestyle="--", linewidth=0.8, alpha=0.6)
        # Aşırı bölgeleri vurgula
        ax_rsi.fill_between(x, rsi_seri, 30,
                            where=(rsi_seri < 30), alpha=0.2, color=CHART_UP_COLOR)
        ax_rsi.fill_between(x, rsi_seri, 70,
                            where=(rsi_seri > 70), alpha=0.2, color=CHART_DOWN_COLOR)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI", color="#8b9ab1", fontsize=8)
        ax_rsi.set_xlim(-1, len(x))
        ax_rsi.set_xticks([])

        # ─── Alt Panel: Volume ───
        for i, (_, mum) in enumerate(grafik_df.iterrows()):
            renk = CHART_UP_COLOR if mum["kapanis"] >= mum["acilis"] else CHART_DOWN_COLOR
            ax_vol.bar(i, mum["hacim"], color=renk, width=0.7, alpha=0.8)

        ax_vol.set_ylabel("Hacim", color="#8b9ab1", fontsize=8)
        ax_vol.set_xlim(-1, len(x))
        ax_vol.set_xticks([])

        plt.tight_layout(pad=1.5)
        plt.savefig(dosya_adi, dpi=120, bbox_inches="tight",
                    facecolor=CHART_BG_COLOR, edgecolor="none")
        plt.close(fig)

        return dosya_adi

    except Exception as e:
        log.error("Grafik oluşturma hatası (%s): %s", sinyal.get("sembol"), e)
        log.debug(traceback.format_exc())
        return None


# ═══════════════════════════════════════════════
# BÖLÜM E — TELEGRAM GÖNDERİCİ
# ═══════════════════════════════════════════════

TELEGRAM_MAX_MESAJ_LEN = 4096  # Telegram API mesaj karakter sınırı


def _mesaj_bolum(metin: str, maks: int = TELEGRAM_MAX_MESAJ_LEN) -> list[str]:
    """Uzun bir mesajı satır kırma noktalarından bölüp parçalar hâlinde döndürür.
    Her parça en fazla 'maks' karakter uzunluğundadır."""
    satirlar = metin.split("\n")
    parcalar: list[str] = []
    current: list[str] = []
    current_len = 0
    for satir in satirlar:
        satir_len = len(satir) + 1  # +1 → \n
        if current_len + satir_len > maks and current:
            parcalar.append("\n".join(current))
            current = [satir]
            current_len = satir_len
        else:
            current.append(satir)
            current_len += satir_len
    if current:
        parcalar.append("\n".join(current))
    return parcalar

def _yildiz_goster(skor: int, maks: int = 5) -> str:
    """Güven skorunu yıldız sembollerine çevirir."""
    return "★" * skor + "☆" * (maks - skor)


def sinyal_mesaji_olustur(sinyal: dict) -> str:
    """Gate.io stili, sade bireysel sinyal mesajı oluşturur."""
    s = sinyal
    emoji = "🟢" if s["tur"] == "DESTEK" else "🔴"
    zaman: datetime = s["zaman"]
    if hasattr(zaman, "to_pydatetime"):
        zaman = zaman.to_pydatetime()
    saat_str = zaman.strftime("%d.%m %H:%M")

    def fmt_fiyat(f):
        if f >= 100:
            return f"{f:.2f}"
        elif f >= 1:
            return f"{f:.4f}"
        elif f >= 0.01:
            return f"{f:.6f}"
        else:
            return f"{f:.8f}"

    # Destek/Direnç seviye satırları
    destek_satirlari = ""
    for idx, sev in enumerate(s["destekler"][:3], 1):
        destek_satirlari += f"  S{idx}: `{fmt_fiyat(sev['seviye'])}` {sev['zone_yildiz']}\n"
    if not destek_satirlari:
        destek_satirlari = "  —\n"

    direnc_satirlari = ""
    for idx, sev in enumerate(s["direncleri"][:3], 1):
        direnc_satirlari += f"  R{idx}: `{fmt_fiyat(sev['seviye'])}` {sev['zone_yildiz']}\n"
    if not direnc_satirlari:
        direnc_satirlari = "  —\n"

    # RSI durumu
    rsi = s["rsi"]
    if s["tur"] == "DESTEK":
        rsi_tag = "⚡ Aşırı Satım" if rsi < 30 else ("🔥 Onaylı" if s["rsi_onay"] else "—")
    else:
        rsi_tag = "🔥 Aşırı Alım" if rsi > 70 else ("🔥 Onaylı" if s["rsi_onay"] else "—")

    vol_tag = f"⚡ ×{s['vol_oran']}" if s["vol_spike"] else "—"
    ema_tag = "✅" if s["ema_onay"] else "—"
    zone3_uyari = "⚠️ Zayıf seviye\n" if s["zone_no"] == 3 else ""

    mesaj = (
        f"{emoji} *{s['sembol']}* · {s['timeframe'].upper()} · {saat_str} UTC\n"
        f"💲 Fiyat: `{fmt_fiyat(s['fiyat'])}`  →  {s['tur']} {s['yakinlik']} `%{s['mesafe_pct']}`\n"
        f"📍 Seviye: `{fmt_fiyat(s['seviye'])}` · Zone {s['zone_no']} {s['zone_yildiz']} · {s['guc']}× dokunuş\n"
        f"─────────────────────\n"
        f"🟢 Destek:\n{destek_satirlari}"
        f"🔴 Direnç:\n{direnc_satirlari}"
        f"─────────────────────\n"
        f"📉 RSI: {rsi}  {rsi_tag}  |  Hacim: {vol_tag}  |  EMA: {ema_tag}\n"
        f"⭐ Güven: {s['guven']}/5  {_yildiz_goster(s['guven'])}\n"
        f"{zone3_uyari}"
        f"_Binance SRL Bot_"
    )
    return mesaj


def best20_mesaji_olustur(sinyaller: list[dict], tur: str, timeframe: str) -> str:
    """Gate.io stili sıkıştırılmış Best 20 listesi — her coin tek satır."""
    simdi = datetime.now(timezone.utc)
    saat_str = simdi.strftime("%d.%m %H:%M")

    if tur == "DESTEK":
        baslik = f"🟢 TOP {min(len(sinyaller), BEST_N)} DESTEK · {timeframe.upper()} · {saat_str} UTC"
    else:
        baslik = f"🔴 TOP {min(len(sinyaller), BEST_N)} DİRENÇ · {timeframe.upper()} · {saat_str} UTC"

    def fmt_fiyat(f):
        if f >= 100:
            return f"{f:.2f}"
        elif f >= 1:
            return f"{f:.4f}"
        elif f >= 0.01:
            return f"{f:.6f}"
        else:
            return f"{f:.8f}"

    satirlar = [baslik, "─" * 28]

    for i, s in enumerate(sinyaller[:BEST_N], 1):
        rsi_tag = "⚡" if (s["tur"] == "DESTEK" and s["rsi"] < 30) or (s["tur"] == "DİRENÇ" and s["rsi"] > 70) else ""
        vol_tag = f"⚡×{s['vol_oran']}" if s["vol_spike"] else ""
        etiket = " ".join(t for t in [rsi_tag, vol_tag] if t)

        satirlar.append(
            f"{i:>2}. *{s['sembol']}* `{fmt_fiyat(s['seviye'])}` "
            f"%{s['mesafe_pct']} {s['zone_yildiz']} {_yildiz_goster(s['guven'])} {etiket}"
        )

    satirlar.extend(["─" * 28, f"_Binance SRL Bot_"])
    return "\n".join(satirlar)


async def telegram_mesaj_gonder(token: str, chat_id: str, metin: str, thread_id: str = "") -> bool:
    """Telegram'a metin mesajı gönderir.
    4096 karakter sınırı aşılırsa mesaj otomatik olarak parçalara bölünür.
    thread_id verilirse mesaj ilgili forum konusuna (alt konuya) gönderilir."""
    # Uzun mesajları parçala
    if len(metin) > TELEGRAM_MAX_MESAJ_LEN:
        parcalar = _mesaj_bolum(metin)
        basarili = True
        for parca in parcalar:
            if parca.strip():
                ok = await telegram_mesaj_gonder(token, chat_id, parca, thread_id=thread_id)
                if not ok:
                    basarili = False
        return basarili

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": metin,
        "parse_mode": "Markdown",
    }
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            log.warning("Geçersiz thread_id değeri '%s', forum konusu olmadan gönderiliyor.", thread_id)
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if not resp.ok:
            log.warning(
                "Telegram mesaj hatası (Markdown): status=%s, yanıt=%s — düz metin ile tekrar deneniyor.",
                resp.status_code, resp.text[:200]
            )
            # Markdown parse hatası olabilir — parse_mode olmadan tekrar dene
            payload.pop("parse_mode", None)
            resp2 = requests.post(url, json=payload, timeout=30)
            resp2.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram mesaj gönderme hatası: %s", e)
        return False


async def telegram_foto_gonder(token: str, chat_id: str, foto_yolu: str, caption: str = "", thread_id: str = "") -> bool:
    """Telegram'a fotoğraf gönderir.
    thread_id verilirse fotoğraf ilgili forum konusuna (alt konuya) gönderilir."""
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        form_data = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "Markdown"}
        if thread_id:
            try:
                form_data["message_thread_id"] = int(thread_id)
            except ValueError:
                log.warning("Geçersiz thread_id değeri '%s', forum konusu olmadan gönderiliyor.", thread_id)
        with open(foto_yolu, "rb") as f:
            resp = requests.post(
                url,
                data=form_data,
                files={"photo": f},
                timeout=60
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram fotoğraf gönderme hatası: %s", e)
        return False


async def sinyal_gonder(token: str, chat_id: str, sinyal: dict, thread_id: str = ""):
    """Tek sinyali grafik + mesaj olarak gönderir."""
    mesaj = sinyal_mesaji_olustur(sinyal)
    grafik_yolu = grafik_olustur(sinyal)

    if grafik_yolu and os.path.exists(grafik_yolu):
        basarili = await telegram_foto_gonder(token, chat_id, grafik_yolu, caption=mesaj, thread_id=thread_id)
        try:
            os.remove(grafik_yolu)
        except Exception:
            pass
        if not basarili:
            await telegram_mesaj_gonder(token, chat_id, mesaj, thread_id=thread_id)
    else:
        await telegram_mesaj_gonder(token, chat_id, mesaj, thread_id=thread_id)


# ═══════════════════════════════════════════════
# BÖLÜM F — ANA DÖNGÜ
# ═══════════════════════════════════════════════

async def tarama_yap(token: str, chat_id: str, timeframe: str, thread_id: str = ""):
    """
    Tüm sembolleri tarar, sinyalleri tespit eder ve Telegram'a gönderir.
    thread_id verilirse mesajlar ilgili forum konusuna (alt konuya) gönderilir.
    Gönderim sırası:
    1. Destek sinyalleri (grafik ile)
    2. Direnç sinyalleri (grafik ile)
    3. Best 20 Destek listesi
    4. Best 20 Direnç listesi
    """
    baslangic = time.time()
    log.info("Tarama başlıyor... Timeframe: %s", timeframe.upper())

    # Sembolleri getir
    try:
        semboller = hacimli_sembolleri_getir()
    except Exception as e:
        log.error("Sembol listesi alınamadı: %s", e)
        return

    toplam = len(semboller)
    tum_sinyaller = []

    # Her sembol için veri çek ve sinyal üret
    for i, sembol in enumerate(semboller, 1):
        if i % 50 == 0:
            log.info("İlerleme: %d/%d sembol işlendi", i, toplam)

        try:
            df = mum_verisi_getir(sembol, timeframe)
            if df is not None:
                sinyaller = sinyal_olustur(sembol, df, timeframe)
                tum_sinyaller.extend(sinyaller)
        except Exception as e:
            log.debug("Sembol işleme hatası %s: %s", sembol, e)

        time.sleep(SYMBOL_DELAY)

    # Sinyalleri türe göre ayır
    destek_sinyalleri = [s for s in tum_sinyaller if s["tur"] == "DESTEK"]
    direnc_sinyalleri = [s for s in tum_sinyaller if s["tur"] == "DİRENÇ"]

    # Güven skoruna ve zone'a göre sırala (yüksek güven önce)
    destek_sinyalleri.sort(key=lambda x: (-x["guven"], x["zone_no"], x["mesafe_pct"]))
    direnc_sinyalleri.sort(key=lambda x: (-x["guven"], x["zone_no"], x["mesafe_pct"]))

    log.info("Tarama tamamlandı: %d destek, %d direnç sinyali bulundu",
             len(destek_sinyalleri), len(direnc_sinyalleri))

    # 1. Destek sinyalleri gönder
    for sinyal in destek_sinyalleri:
        try:
            await sinyal_gonder(token, chat_id, sinyal, thread_id=thread_id)
            await asyncio.sleep(1)
        except Exception as e:
            log.error("Destek sinyali gönderme hatası (%s): %s", sinyal.get("sembol"), e)

    # 2. Direnç sinyalleri gönder
    for sinyal in direnc_sinyalleri:
        try:
            await sinyal_gonder(token, chat_id, sinyal, thread_id=thread_id)
            await asyncio.sleep(1)
        except Exception as e:
            log.error("Direnç sinyali gönderme hatası (%s): %s", sinyal.get("sembol"), e)

    # 3. Best 20 Destek listesi gönder
    if destek_sinyalleri:
        best20_destek = best20_mesaji_olustur(destek_sinyalleri, "DESTEK", timeframe)
        try:
            await telegram_mesaj_gonder(token, chat_id, best20_destek, thread_id=thread_id)
        except Exception as e:
            log.error("Best 20 Destek gönderme hatası: %s", e)

    # 4. Best 20 Direnç listesi gönder
    if direnc_sinyalleri:
        best20_direnc = best20_mesaji_olustur(direnc_sinyalleri, "DİRENÇ", timeframe)
        try:
            await telegram_mesaj_gonder(token, chat_id, best20_direnc, thread_id=thread_id)
        except Exception as e:
            log.error("Best 20 Direnç gönderme hatası: %s", e)

    sure = round(time.time() - baslangic, 1)
    sonraki = datetime.now(timezone.utc).strftime("%H:%M:%S")
    log.info(
        "Tarama süresi: %ss | Destek: %d | Direnç: %d | Sonraki tarama: ~%s dk sonra",
        sure, len(destek_sinyalleri), len(direnc_sinyalleri),
        SCAN_INTERVAL_SEC // 60
    )


async def ana_dongu(token: str, chat_id: str, timeframe: str, thread_id: str = ""):
    """Ana tarama döngüsü — her SCAN_INTERVAL_SEC saniyede bir çalışır."""
    log.info("Binance SRL Sinyal Botu v3.0 başlatıldı")
    log.info("Timeframe: %s | Tarama aralığı: %d saniye", timeframe.upper(), SCAN_INTERVAL_SEC)
    if thread_id:
        log.info("Forum konu ID (thread_id): %s", thread_id)

    # Geçici grafik klasörü oluştur
    Path(CHART_TEMP_DIR).mkdir(exist_ok=True)

    while True:
        try:
            await tarama_yap(token, chat_id, timeframe, thread_id=thread_id)
        except KeyboardInterrupt:
            log.info("Bot durduruldu (Ctrl+C)")
            break
        except Exception as e:
            log.error("Tarama döngüsü hatası: %s", e)
            log.debug(traceback.format_exc())

        log.info("%d saniye bekleniyor...", SCAN_INTERVAL_SEC)
        await asyncio.sleep(SCAN_INTERVAL_SEC)


def process_calistir(token: str, chat_id: str, timeframe: str, api_key: str, api_secret: str, thread_id: str = ""):
    """Multiprocessing modunda her timeframe için ayrı process'te çalışan fonksiyon."""
    global BINANCE_API_KEY, BINANCE_API_SECRET
    # Argparse'tan gelen değerlerle global sabitleri güncelle
    if api_key:
        BINANCE_API_KEY = api_key
    if api_secret:
        BINANCE_API_SECRET = api_secret

    # Her process kendi log dosyasına yazar
    loglama_kur(timeframe)
    log.info("Process başlatıldı: Timeframe=%s, Chat ID=%s%s (PID: %d)",
             timeframe.upper(), chat_id,
             f", Thread ID={thread_id}" if thread_id else "",
             multiprocessing.current_process().pid)
    try:
        asyncio.run(ana_dongu(token=token, chat_id=chat_id, timeframe=timeframe, thread_id=thread_id))
    except KeyboardInterrupt:
        log.info("Process durduruldu (Ctrl+C): Timeframe=%s", timeframe.upper())


def main():
    """Komut satırı argümanlarını işler ve botu başlatır."""
    global BINANCE_API_KEY, BINANCE_API_SECRET
    parser = argparse.ArgumentParser(
        description="Binance SRL Sinyal Botu v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnek kullanım:
  # Tek timeframe — forum konusuz:
  python bot.py --token BOT_TOKEN --chat-id -100GRUBID --timeframe 1h

  # Tek timeframe — forum konusu ile (alt konu):
  python bot.py --token BOT_TOKEN --chat-id -100GRUBID --thread-id 12345 --timeframe 1h

  # Çoklu timeframe — her biri farklı forum konusuna (multiprocessing):
  python bot.py --token BOT_TOKEN --multi \\
      --tf 1H:-100GRUBID:11111 \\
      --tf 4H:-100GRUBID:22222 \\
      --tf 8H:-100GRUBID:33333 \\
      --tf 12H:-100GRUBID:44444 \\
      --tf 1D:-100GRUBID:55555

  # Forum konusuz (eski davranış, THREAD_ID opsiyonel):
  python bot.py --token BOT_TOKEN --multi \\
      --tf 1H:-100111 \\
      --tf 4H:-100222
        """
    )
    parser.add_argument(
        "--token", type=str, default=TELEGRAM_TOKEN,
        help="Telegram bot token (varsayılan: bot.py içindeki TELEGRAM_TOKEN)"
    )
    parser.add_argument(
        "--chat-id", type=str, default=TELEGRAM_CHAT_ID,
        help="Telegram grup chat ID — örnek: -1001234567890"
    )
    parser.add_argument(
        "--thread-id", type=str, default=TELEGRAM_THREAD_ID,
        help="Telegram forum konu (topic) ID — alt konuya göndermek için (tek timeframe modunda)"
    )
    parser.add_argument(
        "--timeframe", type=str, default=ACTIVE_TIMEFRAME,
        choices=["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"],
        help="Mum timeframe (varsayılan: 1h)"
    )
    parser.add_argument(
        "--multi", action="store_true",
        help="Çoklu timeframe modu — tüm --tf çiftleri paralel process olarak başlatılır"
    )
    parser.add_argument(
        "--tf", action="append", metavar="TIMEFRAME:CHAT_ID[:THREAD_ID]",
        help=(
            "Timeframe:ChatID veya Timeframe:ChatID:ThreadID çifti/üçlüsü. "
            "Örnek: --tf 1H:-100GRUBID:12345 --tf 4H:-100GRUBID:67890"
        )
    )
    parser.add_argument(
        "--api-key", type=str, default=BINANCE_API_KEY,
        help="Binance API anahtarı (bot.py içindeki BINANCE_API_KEY değerini override eder)"
    )
    parser.add_argument(
        "--api-secret", type=str, default=BINANCE_API_SECRET,
        help="Binance gizli anahtarı (bot.py içindeki BINANCE_API_SECRET değerini override eder)"
    )

    args = parser.parse_args()

    token = args.token
    api_key = args.api_key
    api_secret = args.api_secret

    if not token:
        print("HATA: Telegram bot token gereklidir. --token parametresi ile belirtin.")
        print("       veya bot.py içindeki TELEGRAM_TOKEN sabitini doldurun.")
        sys.exit(1)

    if args.multi:
        # ─── Çoklu timeframe modu ───
        # --tf argümanı yoksa bot.py içindeki TIMEFRAME_CONFIGS listesini kullan
        tf_listesi = args.tf
        if not tf_listesi:
            if not TIMEFRAME_CONFIGS:
                print("HATA: --multi modunda ya --tf argümanı ya da bot.py içindeki TIMEFRAME_CONFIGS listesi dolu olmalıdır.")
                print("bot.py dosyasını açıp TIMEFRAME_CONFIGS listesindeki satır başı # işaretlerini kaldırın.")
                sys.exit(1)
            # TIMEFRAME_CONFIGS'ten ("1H", "-100xxx", "12345") → "1H:-100xxx:12345" formatına çevir
            tf_listesi = [
                f"{tf}:{cid}:{tid}" if tid else f"{tf}:{cid}"
                for tf, cid, tid in TIMEFRAME_CONFIGS
            ]

        # Ana process loglama (genel bilgiler için)
        loglama_kur("MULTI")
        log.info("Çoklu timeframe modu başlatılıyor: %d timeframe", len(tf_listesi))

        processler = []
        for tf_deger in tf_listesi:
            parcalar = tf_deger.split(":", 2)
            # Desteklenen formatlar:
            #   TIMEFRAME:CHAT_ID            → parcalar = [tf, chat_id]
            #   TIMEFRAME:CHAT_ID:THREAD_ID  → parcalar = [tf, chat_id, thread_id]
            # split(":", 2) → en fazla 3 parçaya böler; THREAD_ID içinde ":" olsa sorun olmaz
            if len(parcalar) < 2:
                print(f"HATA: Geçersiz --tf formatı: '{tf_deger}'. Beklenen: TIMEFRAME:CHAT_ID[:THREAD_ID]")
                sys.exit(1)
            timeframe = parcalar[0].upper()
            chat_id = parcalar[1]
            thread_id = parcalar[2] if len(parcalar) >= 3 else ""
            p = multiprocessing.Process(
                target=process_calistir,
                args=(token, chat_id, timeframe, api_key, api_secret, thread_id),
                name=f"Bot-{timeframe}"
            )
            processler.append(p)
            p.start()
            log.info("Process başlatıldı: %s (PID: %d)%s",
                     p.name, p.pid, f" → Konu ID: {thread_id}" if thread_id else "")

        # Tüm process'lerin bitmesini bekle
        try:
            for p in processler:
                p.join()
        except KeyboardInterrupt:
            log.info("Tüm process'ler durduruluyor...")
            for p in processler:
                p.terminate()
            for p in processler:
                p.join()
            log.info("Bot kapatıldı.")
    else:
        # ─── Tek timeframe modu (eski davranış) ───
        chat_id = args.chat_id
        timeframe = args.timeframe
        thread_id = args.thread_id

        if not chat_id:
            print("HATA: Telegram chat ID gereklidir. --chat-id parametresi ile belirtin.")
            sys.exit(1)

        # Global API anahtarlarını güncelle
        if api_key:
            BINANCE_API_KEY = api_key
        if api_secret:
            BINANCE_API_SECRET = api_secret

        # Loglama kur
        loglama_kur(timeframe)
        log.info("Bot başlatılıyor: Timeframe=%s, Chat ID=%s%s",
                 timeframe.upper(), chat_id,
                 f", Konu ID={thread_id}" if thread_id else "")

        try:
            asyncio.run(ana_dongu(token, chat_id, timeframe, thread_id=thread_id))
        except KeyboardInterrupt:
            log.info("Bot kapatıldı.")


if __name__ == "__main__":
    main()
