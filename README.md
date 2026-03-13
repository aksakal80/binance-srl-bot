# Binance SRL Sinyal Botu v3.0

Kurulum ve kullanım bilgileri yakında eklenecektir.#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance SRL Sinyal Botu v4.0
Gate.io tarzı Destek/Direnç Zone sistemi:
- ATR bazlı zone genişliği
- Dokunma sayısı (touch count)
- Kırılma tespiti (breakout detection)
- Timeframe konfluence skoru
- Bounce gücü analizi
- Son dokunma zamanı
"""

import os
import sys
import time
import logging
import argparse
import asyncio
import traceback
import multiprocessing
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe

# ═══════════════════════════════════════════════
# BÖLÜM 0 — YAPILANDIRMA SABİTLERİ
# ═══════════════════════════════════════════════

# ─── Telegram ───
TELEGRAM_TOKEN     = "8576023339:AAFoHQ5YfNyvZEUTW9qW9zs5D-PndwkpW38"
TELEGRAM_CHAT_ID   = "-1003880760948"
TELEGRAM_THREAD_ID = ""

# ─── Timeframe ───
ACTIVE_TIMEFRAME  = "1h"
CANDLE_LIMIT      = 500          # Daha uzun geçmiş → daha iyi dokunma sayısı
SCAN_INTERVAL_SEC = 900

# ─── Sinyal Eşikleri ───
NEAR_PCT          = 1.0
APPROACH_PCT      = 3.0
MIN_CONFIDENCE    = 2

# ─── İndikatör Parametreleri ───
RSI_PERIOD        = 14
RSI_SUPPORT_MAX   = 45
RSI_RESIST_MIN    = 55
VOL_SPIKE_MULT    = 1.5
VOL_LOOKBACK      = 20
WR_PERIOD         = 10
EMA_SHORT         = 20
EMA_LONG          = 50
ATR_PERIOD        = 14
MACD_FAST         = 12
MACD_SLOW         = 26
MACD_SIGNAL       = 9
BB_PERIOD         = 20
BB_STD            = 2.0

# ─── Destek/Direnç (Gate.io tarzı) ───
SWING_WINDOW      = 3            # Daha geniş swing penceresi
CLUSTER_TOL_PCT   = 0.5          # ATR bazlı zone genişliği için baz
MIN_TOUCH_COUNT   = 2            # Bir zone'un geçerli sayılması için min dokunma
BOUNCE_MIN_PCT    = 0.3          # Min bounce gücü (ATR'nin %30'u)
BREAK_CONFIRM_PCT = 0.5          # Kırılma onayı: zone'un bu kadar ötesine geçince kırılmış sayılır
ZONE_ATR_MULT     = 0.5          # Zone genişliği = ATR * bu çarpan

# ─── Konfluence ───
CONFLUENCE_TF_LIST = ["1h", "4h", "1d"]   # Konfluence kontrolü için timeframe'ler

# ─── Best 20 ───
BEST_N            = 20

# ─── Grafik ───
CHART_CANDLES     = 100
CHART_BG_COLOR    = "#0d1117"
CHART_UP_COLOR    = "#00c896"
CHART_DOWN_COLOR  = "#ff4560"
CHART_ZONE_ALPHA  = 0.15
CHART_TEMP_DIR    = "tmp_charts"

# ─── Binance API ───
BINANCE_API_KEY    = "nCNQe7GcuSqMhNbMOGlfeMZOIw5RCeJYoqHPPm3Ea5ACMmUx3JU00n8Elklg94aW"
BINANCE_API_SECRET = "rwBWrQybI6TlzVzGYTDvyJmMEYftFDFcTodsurgoc0vKqnqG6G6ZkgYxbXyNjgrp"
BINANCE_BASE_URL  = "https://api.binance.com"
API_RETRY_COUNT   = 3
API_RETRY_DELAY   = 5
SYMBOL_DELAY      = 0.12
RATE_LIMIT_WEIGHT = 1100
MIN_VOLUME_USDT   = 500_000


# ═══════════════════════════════════════════════
# BÖLÜM YARDIMCI — LOGLAMA
# ═══════════════════════════════════════════════

def loglama_kur(timeframe: str) -> logging.Logger:
    logger = logging.getLogger("binance_srl_bot")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt_konsol = logging.Formatter(
        f"%(asctime)s [{timeframe.upper()}] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fmt_dosya = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(logging.INFO)
    konsol.setFormatter(fmt_konsol)
    logger.addHandler(konsol)
    try:
        tf_dosya = logging.FileHandler(f"bot_{timeframe.upper()}.log", encoding="utf-8")
        tf_dosya.setLevel(logging.DEBUG)
        tf_dosya.setFormatter(fmt_dosya)
        logger.addHandler(tf_dosya)
    except Exception:
        pass
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

def _api_get(url: str, params: dict = None, timeout: int = 15):
    for deneme in range(1, API_RETRY_COUNT + 1):
        try:
            headers = {}
            if BINANCE_API_KEY:
                headers["X-MBX-APIKEY"] = BINANCE_API_KEY
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            kullanilan = int(resp.headers.get("X-MBX-USED-WEIGHT-1M", 0))
            if kullanilan >= RATE_LIMIT_WEIGHT:
                log.warning("Rate limit %d, 60s bekleniyor...", kullanilan)
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
    log.info("Toplam %d USDT sembolü filtrelendi", len(semboller))
    return semboller


def mum_verisi_getir(sembol: str, timeframe: str, limit: int = CANDLE_LIMIT) -> pd.DataFrame | None:
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": sembol, "interval": timeframe, "limit": limit}
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
# BÖLÜM B — İNDİKATÖRLER
# ═══════════════════════════════════════════════

def atr_hesapla(df: pd.DataFrame, periyot: int = ATR_PERIOD) -> float:
    """Average True Range hesaplar."""
    yuksek = df["yuksek"]
    dusuk = df["dusuk"]
    kapanis = df["kapanis"]
    tr1 = yuksek - dusuk
    tr2 = (yuksek - kapanis.shift()).abs()
    tr3 = (dusuk - kapanis.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=periyot, adjust=False).mean()
    return float(atr.iloc[-1])


def rsi_hesapla(df: pd.DataFrame, periyot: int = RSI_PERIOD) -> float:
    kapanis = df["kapanis"]
    delta = kapanis.diff()
    kazanc = delta.clip(lower=0)
    kayip = (-delta).clip(lower=0)
    ort_kazanc = kazanc.ewm(com=periyot - 1, min_periods=periyot).mean()
    ort_kayip = kayip.ewm(com=periyot - 1, min_periods=periyot).mean()
    rs = ort_kazanc / ort_kayip.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def rsi_serisi_hesapla(df: pd.DataFrame, periyot: int = RSI_PERIOD) -> np.ndarray:
    kapanis = df["kapanis"]
    delta = kapanis.diff()
    kazanc = delta.clip(lower=0)
    kayip = (-delta).clip(lower=0)
    ort_k = kazanc.ewm(com=periyot - 1, min_periods=periyot).mean()
    ort_l = kayip.ewm(com=periyot - 1, min_periods=periyot).mean()
    rs = ort_k / ort_l.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).values


def macd_hesapla(df: pd.DataFrame) -> tuple[float, float, float]:
    """MACD, Signal ve Histogram döndürür."""
    kapanis = df["kapanis"]
    ema_fast = kapanis.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = kapanis.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


def bollinger_hesapla(df: pd.DataFrame) -> tuple[float, float, float]:
    """Bollinger Bands üst, orta, alt döndürür."""
    kapanis = df["kapanis"]
    orta = kapanis.rolling(BB_PERIOD).mean()
    std = kapanis.rolling(BB_PERIOD).std()
    ust = orta + BB_STD * std
    alt = orta - BB_STD * std
    return float(ust.iloc[-1]), float(orta.iloc[-1]), float(alt.iloc[-1])


def williams_r_hesapla(df: pd.DataFrame, periyot: int = WR_PERIOD) -> float:
    son_n = df.tail(periyot)
    en_yuksek = son_n["yuksek"].max()
    en_dusuk = son_n["dusuk"].min()
    kapanis = df["kapanis"].iloc[-1]
    if en_yuksek == en_dusuk:
        return -50.0
    return float((en_yuksek - kapanis) / (en_yuksek - en_dusuk) * -100)


def ema_hesapla(df: pd.DataFrame, periyot: int) -> float:
    return float(df["kapanis"].ewm(span=periyot, adjust=False).mean().iloc[-1])


def hacim_spike_hesapla(df: pd.DataFrame) -> tuple[bool, float]:
    son_hacim = df["hacim"].iloc[-1]
    ort_hacim = df["hacim"].iloc[-(VOL_LOOKBACK + 1):-1].mean()
    if ort_hacim <= 0:
        return False, 0.0
    oran = son_hacim / ort_hacim
    return oran >= VOL_SPIKE_MULT, round(oran, 2)


def obv_hesapla(df: pd.DataFrame) -> float:
    """On Balance Volume — son değer döndürür (trend için işareti önemli)."""
    kapanis = df["kapanis"]
    hacim = df["hacim"]
    yon = np.sign(kapanis.diff().fillna(0))
    obv = (yon * hacim).cumsum()
    # OBV eğimi: son 5 bar pozitifse yükseliş trendi
    son5 = obv.iloc[-5:]
    egim = (son5.iloc[-1] - son5.iloc[0]) / max(abs(son5.iloc[0]), 1)
    return float(egim)


def mum_formasyonu_tespit(df: pd.DataFrame) -> str:
    """
    Son mumun formasyonunu tespit eder.
    Dönen değerler: 'hammer', 'engulfing_bull', 'engulfing_bear',
                    'doji', 'shooting_star', ''
    """
    if len(df) < 2:
        return ""
    son = df.iloc[-1]
    onceki = df.iloc[-2]
    acilis = son["acilis"]
    kapanis = son["kapanis"]
    yuksek = son["yuksek"]
    dusuk = son["dusuk"]
    govde = abs(kapanis - acilis)
    alt_fitil = min(acilis, kapanis) - dusuk
    ust_fitil = yuksek - max(acilis, kapanis)
    toplam = yuksek - dusuk

    if toplam == 0:
        return ""

    # Doji
    if govde / toplam < 0.1:
        return "doji"

    # Hammer (yükseliş - destek bölgesinde)
    if alt_fitil > 2 * govde and ust_fitil < govde * 0.5:
        return "hammer 🔨"

    # Shooting Star (düşüş - direnç bölgesinde)
    if ust_fitil > 2 * govde and alt_fitil < govde * 0.5:
        return "shooting_star 🌠"

    # Bullish Engulfing
    if (kapanis > acilis and onceki["kapanis"] < onceki["acilis"]
            and kapanis > onceki["acilis"] and acilis < onceki["kapanis"]):
        return "engulfing_bull 📈"

    # Bearish Engulfing
    if (kapanis < acilis and onceki["kapanis"] > onceki["acilis"]
            and kapanis < onceki["acilis"] and acilis > onceki["kapanis"]):
        return "engulfing_bear 📉"

    return ""


# ═══════════════════════════════════════════════
# BÖLÜM C — GATE.IO TARZI ZONE SİSTEMİ
# ═══════════════════════════════════════════════

def swing_noktalarini_bul_detayli(df: pd.DataFrame, pencere: int = SWING_WINDOW) -> list[dict]:
    """
    Swing High/Low noktalarını zaman damgası, fiyat ve indeks ile döndürür.
    """
    yuksekler = df["yuksek"].values
    dusukler = df["dusuk"].values
    zamanlar = df.index
    n = len(df)
    noktalar = []

    for i in range(pencere, n - pencere):
        if all(yuksekler[i] > yuksekler[i - j] for j in range(1, pencere + 1)) and \
           all(yuksekler[i] > yuksekler[i + j] for j in range(1, pencere + 1)):
            noktalar.append({
                "tur": "HIGH",
                "fiyat": float(yuksekler[i]),
                "indeks": i,
                "zaman": zamanlar[i]
            })
        if all(dusukler[i] < dusukler[i - j] for j in range(1, pencere + 1)) and \
           all(dusukler[i] < dusukler[i + j] for j in range(1, pencere + 1)):
            noktalar.append({
                "tur": "LOW",
                "fiyat": float(dusukler[i]),
                "indeks": i,
                "zaman": zamanlar[i]
            })

    return noktalar


def dokunma_sayisi_hesapla(df: pd.DataFrame, zone_alt: float, zone_ust: float) -> tuple[int, datetime | None, float]:
    """
    Fiyatın bir zone'a kaç kez dokunduğunu, son dokunma zamanını
    ve ortalama bounce gücünü hesaplar.
    """
    dokunmalar = 0
    son_dokunma = None
    bounce_gucleri = []

    yuksekler = df["yuksek"].values
    dusukler = df["dusuk"].values
    kapanis = df["kapanis"].values
    zamanlar = df.index
    n = len(df)

    for i in range(n):
        # Fitil veya gövde zone'a girdi mi?
        if dusukler[i] <= zone_ust and yuksekler[i] >= zone_alt:
            dokunmalar += 1
            son_dokunma = zamanlar[i]

            # Bounce gücü: sonraki 3 mumun hareketi
            if i + 3 < n:
                mevcut = kapanis[i]
                sonraki_maks = max(kapanis[i:i+4])
                sonraki_min = min(kapanis[i:i+4])
                zone_ort = (zone_alt + zone_ust) / 2
                if mevcut < zone_ort:  # Destek bölgesi
                    bounce = (sonraki_maks - mevcut) / max(mevcut, 1) * 100
                else:  # Direnç bölgesi
                    bounce = (mevcut - sonraki_min) / max(mevcut, 1) * 100
                bounce_gucleri.append(max(bounce, 0))

    ort_bounce = float(np.mean(bounce_gucleri)) if bounce_gucleri else 0.0
    return dokunmalar, son_dokunma, round(ort_bounce, 2)


def zone_kirildi_mi(df: pd.DataFrame, zone_alt: float, zone_ust: float, tur: str) -> bool:
    """
    Zone kırılma tespiti:
    - Destek zone: Fiyat zone'un altına kapanış yaptıysa kırılmış
    - Direnç zone: Fiyat zone'un üstüne kapanış yaptıysa kırılmış
    """
    son_5_kapanis = df["kapanis"].iloc[-5:].values
    break_margin = (zone_ust - zone_alt) * BREAK_CONFIRM_PCT

    if tur == "DESTEK":
        # Son 5 mumdan 2'si altına kapandıysa kırılmış
        kirilanlar = sum(1 for k in son_5_kapanis if k < zone_alt - break_margin)
        return kirilanlar >= 2
    else:
        kirilanlar = sum(1 for k in son_5_kapanis if k > zone_ust + break_margin)
        return kirilanlar >= 2


def hacim_profili_seviyeleri(df: pd.DataFrame, bolgeler: int = 24) -> list[float]:
    toplam_min = df["dusuk"].min()
    toplam_max = df["yuksek"].max()
    if toplam_max <= toplam_min:
        return []
    bolge_boyutu = (toplam_max - toplam_min) / bolgeler
    hacim_dagilimi = np.zeros(bolgeler)
    for _, mum in df.iterrows():
        mum_aralik = mum["yuksek"] - mum["dusuk"]
        if mum_aralik <= 0:
            continue
        for b in range(bolgeler):
            bolge_alt = toplam_min + b * bolge_boyutu
            bolge_ust = bolge_alt + bolge_boyutu
            ortu = min(mum["yuksek"], bolge_ust) - max(mum["dusuk"], bolge_alt)
            if ortu > 0:
                hacim_dagilimi[b] += mum["hacim"] * (ortu / mum_aralik)
    esik = np.percentile(hacim_dagilimi, 75)
    return [
        toplam_min + (b + 0.5) * bolge_boyutu
        for b in range(bolgeler)
        if hacim_dagilimi[b] >= esik
    ]


def zone_guc_skoru(dokunma: int, bounce_pct: float, kirilmadi: bool,
                   hacim_onay: bool, atr: float, seviye: float) -> tuple[int, str, str]:
    """
    Gate.io tarzı zone güç skoru:
    - Dokunma sayısı
    - Bounce gücü
    - Kırılma durumu
    - Hacim onayı
    Döner: (skor 1-5, yıldız str, renk kodu)
    """
    skor = 0
    if dokunma >= 5:
        skor += 2
    elif dokunma >= 3:
        skor += 1

    bounce_esik = (bounce_pct / (atr / seviye * 100)) if atr > 0 and seviye > 0 else bounce_pct
    if bounce_pct >= 1.5:
        skor += 2
    elif bounce_pct >= 0.5:
        skor += 1

    if kirilmadi:
        skor += 1

    if hacim_onay:
        skor += 1

    skor = min(skor, 5)

    if skor >= 4:
        yildiz = "★★★★★" if skor == 5 else "★★★★"
        renk = "#00c896"
    elif skor == 3:
        yildiz = "★★★"
        renk = "#f59e0b"
    elif skor == 2:
        yildiz = "★★"
        renk = "#f97316"
    else:
        yildiz = "★"
        renk = "#ef4444"

    return skor, yildiz, renk


def destek_direnc_zone_hesapla(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """
    Gate.io tarzı zone hesaplama:
    - ATR bazlı zone genişliği
    - Dokunma sayısı
    - Kırılma tespiti
    - Son dokunma zamanı
    - Bounce gücü
    - Güç skoru (1-5 yıldız)
    """
    mevcut_fiyat = float(df["kapanis"].iloc[-1])
    atr = atr_hesapla(df)

    # Swing noktaları
    swing_noktalari = swing_noktalarini_bul_detayli(df)

    # Hacim profili
    hacim_seviyeleri = hacim_profili_seviyeleri(df)

    # Zone genişliği = ATR * çarpan
    zone_yaricap = atr * ZONE_ATR_MULT

    # Tüm seviyeleri topla
    tum_seviyeler = []
    for n in swing_noktalari:
        tum_seviyeler.append(n["fiyat"])
    tum_seviyeler.extend(hacim_seviyeleri)

    # Kümeleme (ATR bazlı tolerans)
    tolerans = CLUSTER_TOL_PCT / 100 * mevcut_fiyat
    if not tum_seviyeler:
        return [], []

    sirali = sorted(tum_seviyeler)
    kumeler = []
    mevcut = [sirali[0]]
    for s in sirali[1:]:
        if abs(s - np.mean(mevcut)) <= tolerans:
            mevcut.append(s)
        else:
            kumeler.append(float(np.mean(mevcut)))
            mevcut = [s]
    kumeler.append(float(np.mean(mevcut)))

    destekler = []
    direncleri = []

    for kume_ort in kumeler:
        zone_alt = kume_ort - zone_yaricap
        zone_ust = kume_ort + zone_yaricap

        # Dokunma sayısı ve bounce analizi
        dokunma, son_dokunma, bounce_pct = dokunma_sayisi_hesapla(df, zone_alt, zone_ust)

        if dokunma < MIN_TOUCH_COUNT:
            continue

        # Hacim onayı (yüksek hacim bölgesinde mi?)
        hacim_onay = any(abs(s - kume_ort) / max(kume_ort, 1) * 100 < 1.0 for s in hacim_seviyeleri)

        if kume_ort < mevcut_fiyat:
            # Destek adayı
            kirildi = zone_kirildi_mi(df, zone_alt, zone_ust, "DESTEK")
            if kirildi:
                continue
            skor, yildiz, renk = zone_guc_skoru(dokunma, bounce_pct, True, hacim_onay, atr, kume_ort)
            destekler.append({
                "seviye": kume_ort,
                "zone_alt": zone_alt,
                "zone_ust": zone_ust,
                "dokunma": dokunma,
                "son_dokunma": son_dokunma,
                "bounce_pct": bounce_pct,
                "hacim_onay": hacim_onay,
                "skor": skor,
                "yildiz": yildiz,
                "renk": renk,
                "atr": atr,
            })
        else:
            # Direnç adayı
            kirildi = zone_kirildi_mi(df, zone_alt, zone_ust, "DİRENÇ")
            if kirildi:
                continue
            skor, yildiz, renk = zone_guc_skoru(dokunma, bounce_pct, True, hacim_onay, atr, kume_ort)
            direncleri.append({
                "seviye": kume_ort,
                "zone_alt": zone_alt,
                "zone_ust": zone_ust,
                "dokunma": dokunma,
                "son_dokunma": son_dokunma,
                "bounce_pct": bounce_pct,
                "hacim_onay": hacim_onay,
                "skor": skor,
                "yildiz": yildiz,
                "renk": renk,
                "atr": atr,
            })

    # Fiyata mesafeye göre sırala
    destekler.sort(key=lambda x: abs(mevcut_fiyat - x["seviye"]))
    direncleri.sort(key=lambda x: abs(mevcut_fiyat - x["seviye"]))

    return destekler, direncleri


# ═══════════════════════════════════════════════
# BÖLÜM D — SİNYAL MOTORU
# ═══════════════════════════════════════════════

def sinyal_olustur(sembol: str, df: pd.DataFrame, timeframe: str) -> list[dict]:
    """
    Gate.io tarzı gelişmiş sinyal motoru.

    Güven Skoru (maks 8/8):
    +1  RSI onayı
    +1  Volume Spike
    +1  Williams %R
    +1  EMA trend
    +1  MACD yönü
    +1  Bollinger Band konumu
    +1  Zone gücü (skor >= 3)
    +1  OBV trend uyumu
    """
    if df is None or len(df) < max(RSI_PERIOD, MACD_SLOW, BB_PERIOD) + 10:
        return []

    mevcut_fiyat = float(df["kapanis"].iloc[-1])
    son_zaman = df.index[-1]

    # İndikatörler
    rsi = rsi_hesapla(df)
    wr = williams_r_hesapla(df)
    vol_spike, vol_oran = hacim_spike_hesapla(df)
    ema_kisa = ema_hesapla(df, EMA_SHORT)
    ema_uzun = ema_hesapla(df, EMA_LONG)
    macd_line, macd_signal, macd_hist = macd_hesapla(df)
    bb_ust, bb_orta, bb_alt = bollinger_hesapla(df)
    obv_egim = obv_hesapla(df)
    formasyon = mum_formasyonu_tespit(df)

    destekler, direncleri = destek_direnc_zone_hesapla(df)

    sinyaller = []

    def sinyal_olustur_ic(zone: dict, tur: str) -> dict | None:
        seviye = zone["seviye"]
        mesafe_pct = abs(mevcut_fiyat - seviye) / mevcut_fiyat * 100

        if mesafe_pct > APPROACH_PCT:
            return None

        yakinlik = "YAKIN" if mesafe_pct <= NEAR_PCT else "YAKLAŞIYOR"

        # ── Güven skoru (8 kriter) ──
        guven = 0
        rsi_onay = wr_onay = ema_onay = macd_onay = bb_onay = obv_onay = False

        if tur == "DESTEK":
            if rsi < RSI_SUPPORT_MAX:
                guven += 1; rsi_onay = True
            if wr < -75:
                guven += 1; wr_onay = True
            if mevcut_fiyat > ema_uzun:
                guven += 1; ema_onay = True
            if macd_hist > 0 or (macd_line > macd_signal):
                guven += 1; macd_onay = True
            if mevcut_fiyat <= bb_orta:  # Alt BB bölgesi
                guven += 1; bb_onay = True
            if obv_egim > 0:
                guven += 1; obv_onay = True
        else:
            if rsi > RSI_RESIST_MIN:
                guven += 1; rsi_onay = True
            if wr > -25:
                guven += 1; wr_onay = True
            if mevcut_fiyat < ema_uzun:
                guven += 1; ema_onay = True
            if macd_hist < 0 or (macd_line < macd_signal):
                guven += 1; macd_onay = True
            if mevcut_fiyat >= bb_orta:  # Üst BB bölgesi
                guven += 1; bb_onay = True
            if obv_egim < 0:
                guven += 1; obv_onay = True

        if vol_spike:
            guven += 1
        if zone["skor"] >= 3:
            guven += 1

        if guven < MIN_CONFIDENCE:
            return None

        return {
            "sembol": sembol,
            "timeframe": timeframe,
            "tur": tur,
            "fiyat": mevcut_fiyat,
            "seviye": seviye,
            "zone_alt": zone["zone_alt"],
            "zone_ust": zone["zone_ust"],
            "mesafe_pct": round(mesafe_pct, 2),
            "yakinlik": yakinlik,
            "zone_skor": zone["skor"],
            "zone_yildiz": zone["yildiz"],
            "zone_renk": zone["renk"],
            "dokunma": zone["dokunma"],
            "son_dokunma": zone["son_dokunma"],
            "bounce_pct": zone["bounce_pct"],
            "hacim_onay": zone["hacim_onay"],
            "atr": round(zone["atr"], 8),
            "guven": guven,
            "rsi": round(rsi, 1),
            "rsi_onay": rsi_onay,
            "wr": round(wr, 1),
            "wr_onay": wr_onay,
            "vol_spike": vol_spike,
            "vol_oran": vol_oran,
            "ema_onay": ema_onay,
            "ema_kisa": round(ema_kisa, 8),
            "ema_uzun": round(ema_uzun, 8),
            "macd_onay": macd_onay,
            "macd_hist": round(macd_hist, 8),
            "bb_onay": bb_onay,
            "bb_ust": round(bb_ust, 8),
            "bb_alt": round(bb_alt, 8),
            "obv_onay": obv_onay,
            "formasyon": formasyon,
            "destekler": destekler[:3],
            "direncleri": direncleri[:3],
            "zaman": son_zaman,
            "df": df,
        }

    for sev in destekler[:5]:
        s = sinyal_olustur_ic(sev, "DESTEK")
        if s:
            sinyaller.append(s)

    for sev in direncleri[:5]:
        s = sinyal_olustur_ic(sev, "DİRENÇ")
        if s:
            sinyaller.append(s)

    if sinyaller:
        sinyaller.sort(key=lambda x: (-x["guven"], -x["zone_skor"], x["mesafe_pct"]))
        return [sinyaller[0]]

    return []


# ═══════════════════════════════════════════════
# BÖLÜM E — GRAFİK ÜRETİCİ (Gate.io tarzı)
# ═══════════════════════════════════════════════

def grafik_olustur(sinyal: dict) -> str | None:
    try:
        df = sinyal["df"]
        sembol = sinyal["sembol"]
        timeframe = sinyal["timeframe"]
        tur = sinyal["tur"]
        guven = sinyal["guven"]

        grafik_df = df.tail(CHART_CANDLES).copy()
        Path(CHART_TEMP_DIR).mkdir(exist_ok=True)
        dosya_adi = os.path.join(CHART_TEMP_DIR, f"{sembol}_{timeframe}_{int(time.time())}.png")

        fig = plt.figure(figsize=(16, 12), facecolor=CHART_BG_COLOR)
        gs = fig.add_gridspec(4, 1, height_ratios=[4, 1, 1, 1], hspace=0.05)

        ax_mum = fig.add_subplot(gs[0])
        ax_rsi = fig.add_subplot(gs[1], sharex=ax_mum)
        ax_macd = fig.add_subplot(gs[2], sharex=ax_mum)
        ax_vol = fig.add_subplot(gs[3], sharex=ax_mum)

        for ax in [ax_mum, ax_rsi, ax_macd, ax_vol]:
            ax.set_facecolor(CHART_BG_COLOR)
            ax.tick_params(colors="#8b9ab1", labelsize=7)
            for spine in ax.spines.values():
                spine.set_color("#2d3748")
            ax.grid(axis="y", color="#1e2736", linewidth=0.5, alpha=0.8)

        x = np.arange(len(grafik_df))
        tarihler = [t.strftime("%d/%m %H:%M") for t in grafik_df.index]

        # ─── Mum Grafik ───
        for i, (_, mum) in enumerate(grafik_df.iterrows()):
            renk = CHART_UP_COLOR if mum["kapanis"] >= mum["acilis"] else CHART_DOWN_COLOR
            alt = min(mum["acilis"], mum["kapanis"])
            ust = max(mum["acilis"], mum["kapanis"])
            yukseklik = max(ust - alt, mum["kapanis"] * 0.0001)
            ax_mum.bar(i, yukseklik, bottom=alt, color=renk, width=0.7, alpha=0.9)
            ax_mum.plot([i, i], [mum["dusuk"], mum["yuksek"]], color=renk, linewidth=0.8)

        # EMA çizgileri
        kapanis = grafik_df["kapanis"].values
        if len(kapanis) >= EMA_SHORT:
            ema_k = pd.Series(kapanis).ewm(span=EMA_SHORT, adjust=False).mean().values
            ax_mum.plot(x, ema_k, color="#3b82f6", linewidth=1.0, label=f"EMA{EMA_SHORT}", alpha=0.9)
        if len(kapanis) >= EMA_LONG:
            ema_u = pd.Series(kapanis).ewm(span=EMA_LONG, adjust=False).mean().values
            ax_mum.plot(x, ema_u, color="#f97316", linewidth=1.0, label=f"EMA{EMA_LONG}", alpha=0.9)

        # Bollinger Bands
        bb_s = pd.Series(kapanis)
        bb_orta_s = bb_s.rolling(BB_PERIOD).mean().values
        bb_std_s = bb_s.rolling(BB_PERIOD).std().values
        bb_ust_s = bb_orta_s + BB_STD * bb_std_s
        bb_alt_s = bb_orta_s - BB_STD * bb_std_s
        ax_mum.plot(x, bb_ust_s, color="#a78bfa", linewidth=0.7, alpha=0.6, linestyle="--")
        ax_mum.plot(x, bb_alt_s, color="#a78bfa", linewidth=0.7, alpha=0.6, linestyle="--")
        ax_mum.fill_between(x, bb_alt_s, bb_ust_s, alpha=0.04, color="#a78bfa")

        # ── Gate.io tarzı ZONE bölgeleri (dolgu + çizgi) ──
        for idx, sev in enumerate(sinyal["destekler"][:3], 1):
            ax_mum.axhspan(
                sev["zone_alt"], sev["zone_ust"],
                color=CHART_UP_COLOR, alpha=CHART_ZONE_ALPHA
            )
            ax_mum.axhline(y=sev["seviye"], color=CHART_UP_COLOR, linestyle="--", linewidth=0.9, alpha=0.8)
            ax_mum.text(
                len(x) - 1, sev["seviye"],
                f" S{idx} [{sev['yildiz']} #{sev['dokunma']}x]",
                color=CHART_UP_COLOR, fontsize=7, va="bottom",
                path_effects=[pe.withStroke(linewidth=2, foreground=CHART_BG_COLOR)]
            )

        for idx, sev in enumerate(sinyal["direncleri"][:3], 1):
            ax_mum.axhspan(
                sev["zone_alt"], sev["zone_ust"],
                color=CHART_DOWN_COLOR, alpha=CHART_ZONE_ALPHA
            )
            ax_mum.axhline(y=sev["seviye"], color=CHART_DOWN_COLOR, linestyle="--", linewidth=0.9, alpha=0.8)
            ax_mum.text(
                len(x) - 1, sev["seviye"],
                f" R{idx} [{sev['yildiz']} #{sev['dokunma']}x]",
                color=CHART_DOWN_COLOR, fontsize=7, va="top",
                path_effects=[pe.withStroke(linewidth=2, foreground=CHART_BG_COLOR)]
            )

        # Sinyal oku
        son_fiyat = grafik_df["kapanis"].iloc[-1]
        son_x = len(x) - 1
        ok = "▲" if tur == "DESTEK" else "▼"
        ok_renk = CHART_UP_COLOR if tur == "DESTEK" else CHART_DOWN_COLOR
        ax_mum.annotate(ok, xy=(son_x, son_fiyat), color=ok_renk, fontsize=18,
                        ha="center", va="top" if tur == "DESTEK" else "bottom",
                        path_effects=[pe.withStroke(linewidth=3, foreground=CHART_BG_COLOR)])

        ax_mum.set_xlim(-1, len(x))
        ax_mum.legend(loc="upper left", framealpha=0.2, fontsize=7,
                      labelcolor="white", facecolor=CHART_BG_COLOR)
        ax_mum.set_title(
            f"{sembol}  ·  {timeframe.upper()}  ·  {tur}  ·  GÜVEN: {guven}/8  ·  Zone {sinyal['zone_yildiz']}  ·  #{sinyal['dokunma']}x Dokunma",
            color="white", fontsize=10, fontweight="bold", pad=10
        )
        adim = max(1, len(x) // 8)
        ax_mum.set_xticks(x[::adim])
        ax_mum.set_xticklabels([tarihler[i] for i in range(0, len(x), adim)],
                               rotation=30, fontsize=6, color="#8b9ab1")

        # ─── RSI Paneli ───
        rsi_seri = rsi_serisi_hesapla(grafik_df)
        ax_rsi.plot(x, rsi_seri, color="#a78bfa", linewidth=1.0)
        ax_rsi.axhline(y=RSI_SUPPORT_MAX, color="#ff4560", linestyle="--", linewidth=0.7, alpha=0.6)
        ax_rsi.axhline(y=RSI_RESIST_MIN, color="#ff4560", linestyle="--", linewidth=0.7, alpha=0.6)
        ax_rsi.fill_between(x, rsi_seri, 30, where=(rsi_seri < 30), alpha=0.25, color=CHART_UP_COLOR)
        ax_rsi.fill_between(x, rsi_seri, 70, where=(rsi_seri > 70), alpha=0.25, color=CHART_DOWN_COLOR)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI", color="#8b9ab1", fontsize=7)
        ax_rsi.set_xlim(-1, len(x))
        plt.setp(ax_rsi.get_xticklabels(), visible=False)

        # ─── MACD Paneli ───
        kap_s = pd.Series(grafik_df["kapanis"].values)
        macd_l = kap_s.ewm(span=MACD_FAST, adjust=False).mean() - kap_s.ewm(span=MACD_SLOW, adjust=False).mean()
        macd_sig = macd_l.ewm(span=MACD_SIGNAL, adjust=False).mean()
        macd_h = (macd_l - macd_sig).values
        ax_macd.plot(x, macd_l.values, color="#3b82f6", linewidth=0.9, label="MACD")
        ax_macd.plot(x, macd_sig.values, color="#f97316", linewidth=0.9, label="Signal")
        renkler_macd = [CHART_UP_COLOR if h >= 0 else CHART_DOWN_COLOR for h in macd_h]
        ax_macd.bar(x, macd_h, color=renkler_macd, width=0.7, alpha=0.7)
        ax_macd.axhline(y=0, color="#4a5568", linewidth=0.5)
        ax_macd.set_ylabel("MACD", color="#8b9ab1", fontsize=7)
        ax_macd.set_xlim(-1, len(x))
        ax_macd.legend(loc="upper left", framealpha=0.2, fontsize=6,
                       labelcolor="white", facecolor=CHART_BG_COLOR)
        plt.setp(ax_macd.get_xticklabels(), visible=False)

        # ─── Hacim Paneli ───
        for i, (_, mum) in enumerate(grafik_df.iterrows()):
            renk = CHART_UP_COLOR if mum["kapanis"] >= mum["acilis"] else CHART_DOWN_COLOR
            ax_vol.bar(i, mum["hacim"], color=renk, width=0.7, alpha=0.8)
        ax_vol.set_ylabel("Hacim", color="#8b9ab1", fontsize=7)
        ax_vol.set_xlim(-1, len(x))
        plt.setp(ax_vol.get_xticklabels(), visible=False)

        plt.tight_layout(pad=1.2)
        plt.savefig(dosya_adi, dpi=130, bbox_inches="tight",
                    facecolor=CHART_BG_COLOR, edgecolor="none")
        plt.close(fig)
        return dosya_adi

    except Exception as e:
        log.error("Grafik hatası (%s): %s", sinyal.get("sembol"), e)
        log.debug(traceback.format_exc())
        return None


# ═══════════════════════════════════════════════
# BÖLÜM F — TELEGRAM GÖNDERİCİ
# ═══════════════════════════════════════════════

def _yildiz_goster(skor: int, maks: int = 8) -> str:
    return "★" * skor + "☆" * (maks - skor)


def fmt_fiyat(f: float) -> str:
    if f >= 100:
        return f"{f:.2f}"
    elif f >= 1:
        return f"{f:.4f}"
    elif f >= 0.01:
        return f"{f:.6f}"
    else:
        return f"{f:.8f}"


def sinyal_mesaji_olustur(sinyal: dict) -> str:
    s = sinyal
    emoji = "🟢" if s["tur"] == "DESTEK" else "🔴"
    zaman: datetime = s["zaman"]
    if hasattr(zaman, "to_pydatetime"):
        zaman = zaman.to_pydatetime()
    tarih_str = zaman.strftime("%d.%m.%Y")
    saat_str = zaman.strftime("%H:%M")

    # Son dokunma zamanı
    son_dok = s["son_dokunma"]
    if son_dok is not None:
        if hasattr(son_dok, "to_pydatetime"):
            son_dok = son_dok.to_pydatetime()
        son_dok_str = son_dok.strftime("%d.%m %H:%M") if son_dok else "—"
    else:
        son_dok_str = "—"

    # RSI
    rsi_val = s["rsi"]
    if s["tur"] == "DESTEK":
        rsi_durum = "⚡ Aşırı Satım" if rsi_val < 30 else ("🔥 Güçlü" if s["rsi_onay"] else "— Onaysız")
    else:
        rsi_durum = "🔥 Aşırı Alım" if rsi_val > 70 else ("🔥 Güçlü" if s["rsi_onay"] else "— Onaysız")

    vol_durum = f"✅ ×{s['vol_oran']}" if s["vol_spike"] else "❌"
    wr_durum = "✅" if s["wr_onay"] else "❌"
    ema_durum = "✅" if s["ema_onay"] else "❌"
    macd_durum = "✅" if s["macd_onay"] else "❌"
    bb_durum = "✅" if s["bb_onay"] else "❌"
    obv_durum = "✅" if s["obv_onay"] else "❌"
    hacim_zone_durum = "✅" if s["hacim_onay"] else "❌"
    formasyon_str = f"\n🕯 Formasyon: {s['formasyon']}" if s["formasyon"] else ""

    # Destek seviyeleri
    destekler_str = ""
    for idx, sev in enumerate(s["destekler"][:3], 1):
        destekler_str += (
            f"  S{idx}: {fmt_fiyat(sev['seviye'])}  "
            f"[Zone: {fmt_fiyat(sev['zone_alt'])} – {fmt_fiyat(sev['zone_ust'])}]  "
            f"{sev['yildiz']}  #{sev['dokunma']}x\n"
        )
    if not destekler_str:
        destekler_str = "  —\n"

    # Direnç seviyeleri
    direncleri_str = ""
    for idx, sev in enumerate(s["direncleri"][:3], 1):
        direncleri_str += (
            f"  R{idx}: {fmt_fiyat(sev['seviye'])}  "
            f"[Zone: {fmt_fiyat(sev['zone_alt'])} – {fmt_fiyat(sev['zone_ust'])}]  "
            f"{sev['yildiz']}  #{sev['dokunma']}x\n"
        )
    if not direncleri_str:
        direncleri_str = "  —\n"

    mesaj = (
        f"📊 *{s['sembol']}* · {s['timeframe'].upper()}\n"
        f"💲 Fiyat: `{fmt_fiyat(s['fiyat'])}` USDT\n"
        f"🕐 {tarih_str} · {saat_str} UTC\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} *{s['tur']} {s['yakinlik']}* · %{s['mesafe_pct']}\n"
        f"📍 Zone: `{fmt_fiyat(s['zone_alt'])}` – `{fmt_fiyat(s['zone_ust'])}`\n"
        f"🎯 Merkez: `{fmt_fiyat(s['seviye'])}`\n"
        f"👆 Dokunma: *{s['dokunma']}x*  |  Son: {son_dok_str}\n"
        f"💥 Bounce: %{s['bounce_pct']}  |  ATR: `{fmt_fiyat(s['atr'])}`\n"
        f"📦 Hacim Zone: {hacim_zone_durum}\n"
        f"{formasyon_str}"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 *DESTEK ZONEları*\n"
        f"{destekler_str}"
        f"🔴 *DİRENÇ ZONEları*\n"
        f"{direncleri_str}"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 RSI(14): `{rsi_val}`  {rsi_durum}\n"
        f"📊 W%R: `{s['wr']}`  {wr_durum}\n"
        f"📈 Vol Spike: {vol_durum}\n"
        f"📈 EMA Trend: {ema_durum}\n"
        f"〽️ MACD: {macd_durum}  |  BB: {bb_durum}  |  OBV: {obv_durum}\n"
        f"⭐ Güven: *{s['guven']}/8*  {_yildiz_goster(s['guven'])}\n"
        f"🏆 Zone Gücü: {s['zone_yildiz']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Binance SRL Bot · v4.0_"
    )
    return mesaj


def best20_mesaji_olustur(sinyaller: list[dict], tur: str, timeframe: str) -> str:
    simdi = datetime.now(timezone.utc)
    tarih_str = simdi.strftime("%d.%m.%Y")
    saat_str = simdi.strftime("%H:%M")

    if tur == "DESTEK":
        baslik = f"🟢 BEST 20 DESTEK — {timeframe.upper()}"
        emoji = "🟢"
    else:
        baslik = f"🔴 BEST 20 DİRENÇ — {timeframe.upper()}"
        emoji = "🔴"

    def sira_emojisi(n):
        return {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, f"#{n} ")

    satirlar = [
        f"{baslik}",
        f"🕐 {tarih_str} · {saat_str} UTC",
        "────────────────────────────",
        "",
    ]

    for i, s in enumerate(sinyaller[:BEST_N], 1):
        onaylar = (
            f"RSI:{'✅' if s['rsi_onay'] else '❌'} "
            f"Vol:{'✅' if s['vol_spike'] else '❌'} "
            f"MACD:{'✅' if s['macd_onay'] else '❌'} "
            f"BB:{'✅' if s['bb_onay'] else '❌'} "
            f"OBV:{'✅' if s['obv_onay'] else '❌'}"
        )
        satirlar.append(
            f"{sira_emojisi(i)} #{i}  {s['sembol']} · {s['timeframe'].upper()}\n"
            f"   {emoji} {s['tur']} {s['yakinlik']} · %{s['mesafe_pct']}\n"
            f"   Zone: {fmt_fiyat(s['zone_alt'])} – {fmt_fiyat(s['zone_ust'])} {s['zone_yildiz']}\n"
            f"   #{s['dokunma']}x Dokunma · Bounce: %{s['bounce_pct']}\n"
            f"   {onaylar}\n"
            f"   ⭐ Güven: {s['guven']}/8  {_yildiz_goster(s['guven'])}"
        )

    satirlar.extend([
        "",
        "────────────────────────────",
        f"Toplam {tur.lower()} sinyali: {len(sinyaller)}",
        "_Binance SRL Bot · v4.0_"
    ])
    return "\n".join(satirlar)


async def telegram_mesaj_gonder(token: str, chat_id: str, metin: str, thread_id: str = "") -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": metin, "parse_mode": "Markdown"}
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            pass
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram mesaj hatası: %s", e)
        return False


async def telegram_foto_gonder(token: str, chat_id: str, foto_yolu: str, caption: str = "", thread_id: str = "") -> bool:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        form_data = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "Markdown"}
        if thread_id:
            try:
                form_data["message_thread_id"] = int(thread_id)
            except ValueError:
                pass
        with open(foto_yolu, "rb") as f:
            resp = requests.post(url, data=form_data, files={"photo": f}, timeout=60)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram foto hatası: %s", e)
        return False


async def sinyal_gonder(token: str, chat_id: str, sinyal: dict, thread_id: str = ""):
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
# BÖLÜM G — ANA DÖNGÜ
# ═══════════════════════════════════════════════

async def tarama_yap(token: str, chat_id: str, timeframe: str, thread_id: str = ""):
    baslangic = time.time()
    log.info("Tarama başlıyor... Timeframe: %s", timeframe.upper())

    try:
        semboller = hacimli_sembolleri_getir()
    except Exception as e:
        log.error("Sembol listesi alınamadı: %s", e)
        return

    toplam = len(semboller)
    tum_sinyaller = []

    for i, sembol in enumerate(semboller, 1):
        if i % 50 == 0:
            log.info("İlerleme: %d/%d", i, toplam)
        try:
            df = mum_verisi_getir(sembol, timeframe)
            if df is not None:
                sinyaller = sinyal_olustur(sembol, df, timeframe)
                tum_sinyaller.extend(sinyaller)
        except Exception as e:
            log.debug("Sembol hatası %s: %s", sembol, e)
        time.sleep(SYMBOL_DELAY)

    destek_s = [s for s in tum_sinyaller if s["tur"] == "DESTEK"]
    direnc_s  = [s for s in tum_sinyaller if s["tur"] == "DİRENÇ"]

    destek_s.sort(key=lambda x: (-x["guven"], -x["zone_skor"], x["mesafe_pct"]))
    direnc_s.sort(key=lambda x:  (-x["guven"], -x["zone_skor"], x["mesafe_pct"]))

    log.info("Tamamlandı: %d destek, %d direnç", len(destek_s), len(direnc_s))

    for sinyal in destek_s:
        try:
            await sinyal_gonder(token, chat_id, sinyal, thread_id=thread_id)
            await asyncio.sleep(1)
        except Exception as e:
            log.error("Destek sinyal gönderme hatası: %s", e)

    for sinyal in direnc_s:
        try:
            await sinyal_gonder(token, chat_id, sinyal, thread_id=thread_id)
            await asyncio.sleep(1)
        except Exception as e:
            log.error("Direnç sinyal gönderme hatası: %s", e)

    if destek_s:
        try:
            await telegram_mesaj_gonder(token, chat_id, best20_mesaji_olustur(destek_s, "DESTEK", timeframe), thread_id=thread_id)
        except Exception as e:
            log.error("Best20 Destek hatası: %s", e)

    if direnc_s:
        try:
            await telegram_mesaj_gonder(token, chat_id, best20_mesaji_olustur(direnc_s, "DİRENÇ", timeframe), thread_id=thread_id)
        except Exception as e:
            log.error("Best20 Direnç hatası: %s", e)

    sure = round(time.time() - baslangic, 1)
    log.info("Süre: %ss | Sonraki: %d dk sonra", sure, SCAN_INTERVAL_SEC // 60)


async def ana_dongu(token: str, chat_id: str, timeframe: str, thread_id: str = ""):
    log.info("Binance SRL Bot v4.0 başlatıldı — %s", timeframe.upper())
    Path(CHART_TEMP_DIR).mkdir(exist_ok=True)
    while True:
        try:
            await tarama_yap(token, chat_id, timeframe, thread_id=thread_id)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("Döngü hatası: %s", e)
            log.debug(traceback.format_exc())
        log.info("%d saniye bekleniyor...", SCAN_INTERVAL_SEC)
        await asyncio.sleep(SCAN_INTERVAL_SEC)


def process_calistir(token, chat_id, timeframe, api_key, api_secret, thread_id=""):
    global BINANCE_API_KEY, BINANCE_API_SECRET
    if api_key:
        BINANCE_API_KEY = api_key
    if api_secret:
        BINANCE_API_SECRET = api_secret
    loglama_kur(timeframe)
    log.info("Process başlatıldı: %s (PID: %d)", timeframe.upper(), multiprocessing.current_process().pid)
    try:
        asyncio.run(ana_dongu(token=token, chat_id=chat_id, timeframe=timeframe, thread_id=thread_id))
    except KeyboardInterrupt:
        log.info("Process durduruldu: %s", timeframe.upper())


def main():
    global BINANCE_API_KEY, BINANCE_API_SECRET
    parser = argparse.ArgumentParser(description="Binance SRL Sinyal Botu v4.0")
    parser.add_argument("--token",      type=str, default=TELEGRAM_TOKEN)
    parser.add_argument("--chat-id",    type=str, default=TELEGRAM_CHAT_ID)
    parser.add_argument("--thread-id",  type=str, default=TELEGRAM_THREAD_ID)
    parser.add_argument("--timeframe",  type=str, default=ACTIVE_TIMEFRAME,
                        choices=["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w"])
    parser.add_argument("--multi",      action="store_true")
    parser.add_argument("--tf",         action="append", metavar="TIMEFRAME:CHAT_ID[:THREAD_ID]")
    parser.add_argument("--api-key",    type=str, default=BINANCE_API_KEY)
    parser.add_argument("--api-secret", type=str, default=BINANCE_API_SECRET)

    args = parser.parse_args()
    token = args.token
    api_key = args.api_key
    api_secret = args.api_secret

    if not token:
        print("HATA: Telegram token gerekli.")
        sys.exit(1)

    if args.multi:
        if not args.tf:
            print("HATA: --multi için en az bir --tf gerekli.")
            sys.exit(1)
        loglama_kur("MULTI")
        processler = []
        for tf_deger in args.tf:
            parcalar = tf_deger.split(":")
            if len(parcalar) < 2:
                print(f"HATA: Geçersiz --tf: '{tf_deger}'")
                sys.exit(1)
            timeframe = parcalar[0].lower()
            chat_id = parcalar[1]
            thread_id = parcalar[2] if len(parcalar) >= 3 else ""
            p = multiprocessing.Process(
                target=process_calistir,
                args=(token, chat_id, timeframe, api_key, api_secret, thread_id),
                name=f"Bot-{timeframe.upper()}"
            )
            processler.append(p)
            p.start()
            log.info("Process: %s PID=%d", p.name, p.pid)
        try:
            for p in processler:
                p.join()
        except KeyboardInterrupt:
            for p in processler:
                p.terminate()
            for p in processler:
                p.join()
    else:
        chat_id = args.chat_id
        timeframe = args.timeframe
        thread_id = args.thread_id
        if not chat_id:
            print("HATA: --chat-id gerekli.")
            sys.exit(1)
        if api_key:
            BINANCE_API_KEY = api_key
        if api_secret:
            BINANCE_API_SECRET = api_secret
        loglama_kur(timeframe)
        try:
            asyncio.run(ana_dongu(token, chat_id, timeframe, thread_id=thread_id))
        except KeyboardInterrupt:
            log.info("Bot kapatıldı.")


if __name__ == "__main__":
    main()
