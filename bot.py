"""
Binance SRL Sinyal Botu v3.0
Tüm modüller tek dosyada: veri çekici, destek/direnç hesaplayıcı,
sinyal motoru, grafik üretici, Telegram gönderici ve ana döngü.
"""

import argparse
import asyncio
import logging
import os
import time

import matplotlib
matplotlib.use("Agg")  # GUI olmayan ortamlar için arka uç
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests
import ta

from telegram import Bot
from telegram.error import TelegramError

import config

# ─── Loglama ───
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Sabitler ───
BINANCE_BASE_URL = "https://api.binance.com"

# ════════════════════════════════════════════════════════════════════════════
# BÖLÜM A — VERİ ÇEKİCİ
# ════════════════════════════════════════════════════════════════════════════

# Binance timeframe eşlemesi
TIMEFRAME_MAP = {
    "1M": "1m",
    "3M": "3m",
    "5M": "5m",
    "15M": "15m",
    "30M": "30m",
    "1H": "1h",
    "2H": "2h",
    "4H": "4h",
    "6H": "6h",
    "8H": "8h",
    "12H": "12h",
    "1D": "1d",
    "3D": "3d",
    "1W": "1w",
    "1MO": "1M",
}

# Kullanılan API ağırlık sayacı
_used_weight = 0


def _binance_get(endpoint: str, params: dict | None = None, max_retries: int = 3) -> dict | list:
    """Binance REST API'sine GET isteği atar; rate-limit ve retry yönetimi yapar."""
    global _used_weight
    url = BINANCE_BASE_URL + endpoint
    for deneme in range(1, max_retries + 1):
        try:
            yanit = requests.get(url, params=params, timeout=10)
            # Kullanılan ağırlığı takip et
            agirlik = yanit.headers.get("X-MBX-USED-WEIGHT-1M") or yanit.headers.get("X-MBX-USED-WEIGHT")
            if agirlik:
                _used_weight = int(agirlik)
            # Limit aşımına yaklaşırsa bekle (1200 ağırlık sınırı)
            if _used_weight >= 1100:
                logger.warning("API ağırlık limiti yaklaşıyor (%d/1200). 60s bekleniyor...", _used_weight)
                time.sleep(60)
            if yanit.status_code == 429:
                bekleme = int(yanit.headers.get("Retry-After", 60))
                logger.warning("Rate limit aşıldı. %ds bekleniyor...", bekleme)
                time.sleep(bekleme)
                continue
            yanit.raise_for_status()
            return yanit.json()
        except requests.RequestException as hata:
            logger.error("İstek hatası (%d/%d): %s", deneme, max_retries, hata)
            if deneme < max_retries:
                time.sleep(5)
    return {}


def hacimli_usdt_sembolleri_getir() -> list[str]:
    """Son 24 saatte hacmi MIN_VOLUME_USDT üzeri olan USDT spot sembollerini döner."""
    logger.info("Yüksek hacimli USDT sembolleri alınıyor...")
    veri = _binance_get("/api/v3/ticker/24hr")
    if not veri:
        return []
    semboller = []
    for kayit in veri:
        sembol = kayit.get("symbol", "")
        if not sembol.endswith("USDT"):
            continue
        try:
            hacim = float(kayit.get("quoteVolume", 0))
        except (ValueError, TypeError):
            continue
        if hacim >= config.MIN_VOLUME_USDT:
            semboller.append((sembol, hacim))
    # Hacme göre büyükten küçüğe sırala; en iyi BEST_N kadar al
    semboller.sort(key=lambda x: x[1], reverse=True)
    sonuc = [s[0] for s in semboller[: config.BEST_N]]
    logger.info("%d sembol seçildi (top %d)", len(sonuc), config.BEST_N)
    return sonuc


def mum_verisi_getir(sembol: str, timeframe: str) -> pd.DataFrame:
    """Verilen sembol ve timeframe için OHLCV mum verisini çeker."""
    tf_binance = TIMEFRAME_MAP.get(timeframe.upper(), "1h")
    params = {
        "symbol": sembol,
        "interval": tf_binance,
        "limit": config.CANDLE_LIMIT,
    }
    ham = _binance_get("/api/v3/klines", params=params)
    if not ham:
        return pd.DataFrame()
    sutunlar = ["timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(ham, columns=sutunlar)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    for sutun in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[sutun] = pd.to_numeric(df[sutun], errors="coerce")
    df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)
    return df


def tum_verileri_getir(timeframe: str) -> dict[str, pd.DataFrame]:
    """Tüm seçili semboller için OHLCV verisi çeker ve sözlük döner."""
    semboller = hacimli_usdt_sembolleri_getir()
    veriler: dict[str, pd.DataFrame] = {}
    for i, sembol in enumerate(semboller, 1):
        logger.info("[%d/%d] %s verisi çekiliyor...", i, len(semboller), sembol)
        df = mum_verisi_getir(sembol, timeframe)
        if not df.empty:
            veriler[sembol] = df
        time.sleep(0.1)  # Rate limit koruması
    return veriler


# ════════════════════════════════════════════════════════════════════════════
# BÖLÜM B — DESTEK/DİRENÇ HESAPLAYICI
# ════════════════════════════════════════════════════════════════════════════

def swing_noktalari_bul(df: pd.DataFrame, pencere: int = config.SWING_WINDOW) -> tuple[list[float], list[float]]:
    """Swing High ve Swing Low noktalarını tespit eder."""
    swing_high: list[float] = []
    swing_low: list[float] = []
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    for i in range(pencere, n - pencere):
        # Swing High: çevresindeki pencere kadar mumdan yüksek
        if highs[i] == max(highs[i - pencere: i + pencere + 1]):
            swing_high.append(float(highs[i]))
        # Swing Low: çevresindeki pencere kadar mumdan düşük
        if lows[i] == min(lows[i - pencere: i + pencere + 1]):
            swing_low.append(float(lows[i]))
    return swing_high, swing_low


def cluster_analizi(seviyeler: list[float], tolerans_pct: float = config.CLUSTER_TOL_PCT) -> list[tuple[float, int]]:
    """Yakın fiyat seviyelerini gruplar; (ortalama_fiyat, guç_skoru) listesi döner."""
    if not seviyeler:
        return []
    sirali = sorted(seviyeler)
    kümeler: list[list[float]] = []
    mevcut_kume: list[float] = [sirali[0]]
    for fiyat in sirali[1:]:
        referans = np.mean(mevcut_kume)
        if abs(fiyat - referans) / referans * 100 <= tolerans_pct:
            mevcut_kume.append(fiyat)
        else:
            kümeler.append(mevcut_kume)
            mevcut_kume = [fiyat]
    kümeler.append(mevcut_kume)
    sonuc = [(float(np.mean(k)), len(k)) for k in kümeler]
    return sonuc


def hacim_profili_seviyeleri(df: pd.DataFrame, aralik_sayisi: int = 50) -> list[tuple[float, float]]:
    """Her low–high bandına hacim dağıtarak yoğunluk seviyeleri üretir."""
    fiyat_min = df["low"].min()
    fiyat_max = df["high"].max()
    if fiyat_max == fiyat_min:
        return []
    araliklar = np.linspace(fiyat_min, fiyat_max, aralik_sayisi + 1)
    hacim_bins = np.zeros(aralik_sayisi)
    for _, satir in df.iterrows():
        mum_dusuk = satir["low"]
        mum_yuksek = satir["high"]
        mum_hacim = satir["volume"]
        mum_aralik = mum_yuksek - mum_dusuk
        if mum_aralik == 0:
            continue
        for j in range(aralik_sayisi):
            kesisim_alt = max(araliklar[j], mum_dusuk)
            kesisim_ust = min(araliklar[j + 1], mum_yuksek)
            if kesisim_ust > kesisim_alt:
                oran = (kesisim_ust - kesisim_alt) / mum_aralik
                hacim_bins[j] += mum_hacim * oran
    sonuc = []
    for j in range(aralik_sayisi):
        orta_fiyat = (araliklar[j] + araliklar[j + 1]) / 2
        sonuc.append((float(orta_fiyat), float(hacim_bins[j])))
    return sonuc


def zone_siniflandir(guc_skoru: int) -> str:
    """Güç skoruna göre zone etiketi döner."""
    if guc_skoru >= 3:
        return "★★★"
    if guc_skoru == 2:
        return "★★"
    return "⚠️"


def sr_seviyeleri_hesapla(df: pd.DataFrame) -> dict:
    """
    Tüm destek/direnç adımlarını çalıştırır; S1–S3 ve R1–R3 seviyelerini döner.
    Her seviye: {'fiyat': float, 'guc': int, 'zone': str}
    """
    guncel_fiyat = float(df["close"].iloc[-1])

    # Adım 1: Swing noktaları
    swing_high, swing_low = swing_noktalari_bul(df)

    # Adım 2: Cluster analizi
    yuksek_kümeler = cluster_analizi(swing_high)
    dusuk_kümeler = cluster_analizi(swing_low)

    # Adım 3: Hacim profili
    hacim_seviyeleri = hacim_profili_seviyeleri(df)
    if hacim_seviyeleri:
        max_hacim = max(h for _, h in hacim_seviyeleri)
        ort_hacim = np.mean([h for _, h in hacim_seviyeleri])
        # Ortalamanın üzerindeki hacim seviyeleri güçlü aday
        hacim_adaylari = [
            (f, int(1 + (h / max_hacim * 2)))
            for f, h in hacim_seviyeleri
            if h > ort_hacim
        ]
    else:
        hacim_adaylari = []

    # Tüm adayları birleştir
    tum_adaylar: list[tuple[float, int]] = yuksek_kümeler + dusuk_kümeler + hacim_adaylari

    # Fiyatın altı → Destek adayları; üstü → Direnç adayları
    destek_adaylari = [(f, g) for f, g in tum_adaylar if f < guncel_fiyat]
    direnc_adaylari = [(f, g) for f, g in tum_adaylar if f > guncel_fiyat]

    # Mesafeye göre sırala (fiyata en yakın önce)
    destek_adaylari.sort(key=lambda x: abs(guncel_fiyat - x[0]))
    direnc_adaylari.sort(key=lambda x: abs(x[0] - guncel_fiyat))

    def seviye_olustur(adaylar: list[tuple[float, int]], etiketler: list[str]) -> dict:
        sonuc = {}
        for idx, etiket in enumerate(etiketler):
            if idx < len(adaylar):
                fiyat, guc = adaylar[idx]
                sonuc[etiket] = {
                    "fiyat": fiyat,
                    "guc": guc,
                    "zone": zone_siniflandir(guc),
                }
        return sonuc

    destekler = seviye_olustur(destek_adaylari, ["S1", "S2", "S3"])
    direncler = seviye_olustur(direnc_adaylari, ["R1", "R2", "R3"])
    return {"destek": destekler, "direnc": direncler, "fiyat": guncel_fiyat}


# ════════════════════════════════════════════════════════════════════════════
# BÖLÜM C — SİNYAL MOTORU
# ════════════════════════════════════════════════════════════════════════════

def rsi_hesapla(df: pd.DataFrame) -> float:
    """RSI (14) hesaplar; son değeri döner."""
    rsi_serisi = ta.momentum.RSIIndicator(close=df["close"], window=config.RSI_PERIOD).rsi()
    return float(rsi_serisi.iloc[-1]) if not rsi_serisi.empty else 50.0


def williams_r_hesapla(df: pd.DataFrame) -> float:
    """Williams %R (10) hesaplar; son değeri döner."""
    wr_serisi = ta.momentum.WilliamsRIndicator(
        high=df["high"], low=df["low"], close=df["close"], lbp=config.WR_PERIOD
    ).williams_r()
    return float(wr_serisi.iloc[-1]) if not wr_serisi.empty else -50.0


def ema_hesapla(df: pd.DataFrame) -> tuple[float, float]:
    """EMA20 ve EMA50 son değerlerini döner."""
    ema_kisa = ta.trend.EMAIndicator(close=df["close"], window=config.EMA_SHORT).ema_indicator()
    ema_uzun = ta.trend.EMAIndicator(close=df["close"], window=config.EMA_LONG).ema_indicator()
    return float(ema_kisa.iloc[-1]), float(ema_uzun.iloc[-1])


def hacim_spike_var_mi(df: pd.DataFrame) -> bool:
    """Son mumun hacmi ortalamanın VOL_SPIKE_MULT katından büyük mü?"""
    if len(df) < config.VOL_LOOKBACK:
        return False
    ort_hacim = df["volume"].iloc[-config.VOL_LOOKBACK - 1: -1].mean()
    son_hacim = float(df["volume"].iloc[-1])
    return son_hacim > ort_hacim * config.VOL_SPIKE_MULT


def yakinlik_hesapla(guncel_fiyat: float, seviye_fiyati: float) -> float:
    """Güncel fiyat ile seviye arasındaki mesafeyi % cinsinden döner."""
    return abs(guncel_fiyat - seviye_fiyati) / guncel_fiyat * 100


def sinyal_uret(sembol: str, df: pd.DataFrame, sr_sonuc: dict) -> list[dict]:
    """
    Verilen sembol ve S/R seviyeleri için sinyal listesi üretir.
    Her sinyal: sembol, yön, seviye_etiketi, fiyat, mesafe_pct,
                yakinlik_etiketi, güven_skoru, indikatörler içerir.
    """
    if df.empty:
        return []
    guncel_fiyat = sr_sonuc["fiyat"]
    # İndikatörleri hesapla
    rsi = rsi_hesapla(df)
    wr = williams_r_hesapla(df)
    ema_kisa, ema_uzun = ema_hesapla(df)
    hacim_spike = hacim_spike_var_mi(df)

    sinyaller = []

    # Destek seviyelerini kontrol et
    for etiket, bilgi in sr_sonuc["destek"].items():
        seviye_fiyati = bilgi["fiyat"]
        mesafe_pct = yakinlik_hesapla(guncel_fiyat, seviye_fiyati)
        if mesafe_pct > config.APPROACH_PCT:
            continue
        yakinlik_etiketi = "YAKIN 🎯" if mesafe_pct <= config.NEAR_PCT else "YAKLAŞIYOR 📡"

        # Güven skoru (destek için boğa sinyalleri)
        guven = 0
        indikatörler = []
        if rsi < config.RSI_SUPPORT_MAX:
            guven += 1
            indikatörler.append(f"RSI {rsi:.1f} (aşırı satım)")
        if hacim_spike:
            guven += 1
            indikatörler.append("Hacim Artışı 📊")
        if wr < -80:
            guven += 1
            indikatörler.append(f"W%R {wr:.1f} (aşırı satım)")
        if guncel_fiyat > ema_uzun:
            guven += 1
            indikatörler.append(f"Fiyat > EMA{config.EMA_LONG} ✅")

        if guven < config.MIN_CONFIDENCE:
            continue

        sinyaller.append({
            "sembol": sembol,
            "yon": "DESTEK",
            "etiket": etiket,
            "seviye_fiyati": seviye_fiyati,
            "guncel_fiyat": guncel_fiyat,
            "mesafe_pct": mesafe_pct,
            "yakinlik": yakinlik_etiketi,
            "zone": bilgi["zone"],
            "guven": guven,
            "indikatörler": indikatörler,
            "rsi": rsi,
            "wr": wr,
            "ema_kisa": ema_kisa,
            "ema_uzun": ema_uzun,
            "hacim_spike": hacim_spike,
        })

    # Direnç seviyelerini kontrol et
    for etiket, bilgi in sr_sonuc["direnc"].items():
        seviye_fiyati = bilgi["fiyat"]
        mesafe_pct = yakinlik_hesapla(guncel_fiyat, seviye_fiyati)
        if mesafe_pct > config.APPROACH_PCT:
            continue
        yakinlik_etiketi = "YAKIN 🎯" if mesafe_pct <= config.NEAR_PCT else "YAKLAŞIYOR 📡"

        # Güven skoru (direnç için ayı sinyalleri)
        guven = 0
        indikatörler = []
        if rsi > config.RSI_RESIST_MIN:
            guven += 1
            indikatörler.append(f"RSI {rsi:.1f} (aşırı alım)")
        if hacim_spike:
            guven += 1
            indikatörler.append("Hacim Artışı 📊")
        if wr > -20:
            guven += 1
            indikatörler.append(f"W%R {wr:.1f} (aşırı alım)")
        if guncel_fiyat < ema_uzun:
            guven += 1
            indikatörler.append(f"Fiyat < EMA{config.EMA_LONG} ⚠️")

        if guven < config.MIN_CONFIDENCE:
            continue

        sinyaller.append({
            "sembol": sembol,
            "yon": "DİRENÇ",
            "etiket": etiket,
            "seviye_fiyati": seviye_fiyati,
            "guncel_fiyat": guncel_fiyat,
            "mesafe_pct": mesafe_pct,
            "yakinlik": yakinlik_etiketi,
            "zone": bilgi["zone"],
            "guven": guven,
            "indikatörler": indikatörler,
            "rsi": rsi,
            "wr": wr,
            "ema_kisa": ema_kisa,
            "ema_uzun": ema_uzun,
            "hacim_spike": hacim_spike,
        })

    return sinyaller


# ════════════════════════════════════════════════════════════════════════════
# BÖLÜM D — GRAFİK ÜRETİCİ
# ════════════════════════════════════════════════════════════════════════════

def grafik_olustur(sembol: str, df: pd.DataFrame, sr_sonuc: dict, timeframe: str) -> str | None:
    """
    Mum grafik + S/R seviyeleri içeren PNG dosyası oluşturur; dosya yolunu döner.
    """
    os.makedirs(config.CHART_TEMP_DIR, exist_ok=True)
    dosya_yolu = os.path.join(config.CHART_TEMP_DIR, f"{sembol}_{timeframe}.png")

    # Son CHART_CANDLES mumu al
    grafik_df = df.tail(config.CHART_CANDLES).copy()
    grafik_df.index = grafik_df.index.tz_localize(None) if grafik_df.index.tz is not None else grafik_df.index

    try:
        # mplfinance stil ayarları
        mc = mpf.make_marketcolors(
            up=config.CHART_UP_COLOR,
            down=config.CHART_DOWN_COLOR,
            wick={"up": config.CHART_UP_COLOR, "down": config.CHART_DOWN_COLOR},
            volume={"up": config.CHART_UP_COLOR, "down": config.CHART_DOWN_COLOR},
            edge="inherit",
        )
        stil = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            facecolor=config.CHART_BG_COLOR,
            figcolor=config.CHART_BG_COLOR,
            gridcolor="#1e2a3a",
        )

        # EMA çizgileri için ek grafikler
        ema_kisa_serisi = ta.trend.EMAIndicator(
            close=df["close"], window=config.EMA_SHORT
        ).ema_indicator().tail(config.CHART_CANDLES)
        ema_uzun_serisi = ta.trend.EMAIndicator(
            close=df["close"], window=config.EMA_LONG
        ).ema_indicator().tail(config.CHART_CANDLES)
        ema_kisa_serisi.index = grafik_df.index
        ema_uzun_serisi.index = grafik_df.index

        ap_ema = [
            mpf.make_addplot(ema_kisa_serisi, color="#f0c040", width=1.2, label=f"EMA{config.EMA_SHORT}"),
            mpf.make_addplot(ema_uzun_serisi, color="#a060f0", width=1.2, label=f"EMA{config.EMA_LONG}"),
        ]

        # Grafik çizimi
        fig, axlar = mpf.plot(
            grafik_df,
            type="candle",
            style=stil,
            volume=True,
            addplot=ap_ema,
            returnfig=True,
            figsize=(14, 8),
            title=f"\n{sembol} — {timeframe}",
        )
        ax_fiyat = axlar[0]

        # S/R seviyelerini çiz
        for etiket, bilgi in sr_sonuc["destek"].items():
            ax_fiyat.axhline(
                y=bilgi["fiyat"], color="#00c896", linestyle="--", linewidth=0.9, alpha=0.8
            )
            ax_fiyat.text(
                0.01, bilgi["fiyat"],
                f"{etiket} {bilgi['zone']} {bilgi['fiyat']:.4f}",
                transform=ax_fiyat.get_yaxis_transform(),
                color="#00c896", fontsize=7, va="bottom",
            )
        for etiket, bilgi in sr_sonuc["direnc"].items():
            ax_fiyat.axhline(
                y=bilgi["fiyat"], color="#ff4560", linestyle="--", linewidth=0.9, alpha=0.8
            )
            ax_fiyat.text(
                0.01, bilgi["fiyat"],
                f"{etiket} {bilgi['zone']} {bilgi['fiyat']:.4f}",
                transform=ax_fiyat.get_yaxis_transform(),
                color="#ff4560", fontsize=7, va="bottom",
            )

        fig.savefig(dosya_yolu, dpi=130, bbox_inches="tight", facecolor=config.CHART_BG_COLOR)
        plt.close(fig)
        return dosya_yolu
    except Exception as hata:
        logger.error("Grafik oluşturma hatası (%s): %s", sembol, hata)
        return None


# ════════════════════════════════════════════════════════════════════════════
# BÖLÜM E — TELEGRAM GÖNDERICI
# ════════════════════════════════════════════════════════════════════════════

def sinyal_mesaji_olustur(sinyal: dict, timeframe: str) -> str:
    """Telegram için Markdown biçimli sinyal mesajı oluşturur."""
    yon_emoji = "🟢" if sinyal["yon"] == "DESTEK" else "🔴"
    guven_yildiz = "⭐" * sinyal["guven"]
    indikatörler_metni = "\n".join(f"  • {ind}" for ind in sinyal["indikatörler"])
    mesaj = (
        f"{yon_emoji} *{sinyal['sembol']}* — {sinyal['yon']} {sinyal['etiket']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Durum: *{sinyal['yakinlik']}*\n"
        f"🏷 Zone: {sinyal['zone']}\n"
        f"💰 Güncel Fiyat: `{sinyal['guncel_fiyat']:.6g}`\n"
        f"📌 Seviye: `{sinyal['seviye_fiyati']:.6g}`\n"
        f"📏 Mesafe: `%{sinyal['mesafe_pct']:.2f}`\n"
        f"⏱ Timeframe: {timeframe}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *İndikatörler:*\n{indikatörler_metni}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Güven: {guven_yildiz} ({sinyal['guven']}/4)"
    )
    return mesaj


async def telegram_mesaj_gonder(bot: Bot, chat_id: str, metin: str, gorsel_yolu: str | None = None) -> None:
    """Telegram'a mesaj (ve varsa görsel) gönderir."""
    try:
        if gorsel_yolu and os.path.exists(gorsel_yolu):
            with open(gorsel_yolu, "rb") as gorsel:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=gorsel,
                    caption=metin,
                    parse_mode="Markdown",
                )
        else:
            await bot.send_message(chat_id=chat_id, text=metin, parse_mode="Markdown")
    except TelegramError as hata:
        logger.error("Telegram gönderim hatası: %s", hata)


# ════════════════════════════════════════════════════════════════════════════
# BÖLÜM F — ANA DÖNGÜ
# ════════════════════════════════════════════════════════════════════════════

async def tarama_yap(bot: Bot, chat_id: str, timeframe: str) -> None:
    """Tek bir tarama döngüsü; tüm sembolleri analiz eder ve sinyalleri gönderir."""
    logger.info("=== Tarama başlıyor | Timeframe: %s ===", timeframe)
    veriler = tum_verileri_getir(timeframe)
    toplam_sinyal = 0
    for sembol, df in veriler.items():
        try:
            sr_sonuc = sr_seviyeleri_hesapla(df)
            sinyaller = sinyal_uret(sembol, df, sr_sonuc)
            for sinyal in sinyaller:
                mesaj = sinyal_mesaji_olustur(sinyal, timeframe)
                gorsel_yolu = grafik_olustur(sembol, df, sr_sonuc, timeframe)
                await telegram_mesaj_gonder(bot, chat_id, mesaj, gorsel_yolu)
                # Geçici grafik dosyasını sil
                if gorsel_yolu and os.path.exists(gorsel_yolu):
                    os.remove(gorsel_yolu)
                toplam_sinyal += 1
                await asyncio.sleep(0.5)  # Telegram flood koruması
        except Exception as hata:
            logger.error("Sembol işleme hatası (%s): %s", sembol, hata)
    logger.info("=== Tarama tamamlandı | %d sinyal gönderildi ===", toplam_sinyal)


async def ana_dongu(token: str, chat_id: str, timeframe: str) -> None:
    """Periyodik tarama döngüsü."""
    bot = Bot(token=token)
    logger.info("Bot başlatıldı. Token doğruluyor...")
    try:
        ben = await bot.get_me()
        logger.info("Bot: @%s (%s)", ben.username, ben.full_name)
    except TelegramError as hata:
        logger.error("Bot doğrulama hatası: %s", hata)
        return

    while True:
        baslangic = time.time()
        try:
            await tarama_yap(bot, chat_id, timeframe)
        except Exception as hata:
            logger.error("Tarama sırasında beklenmedik hata: %s", hata)
        gecen = time.time() - baslangic
        bekleme = max(0, config.SCAN_INTERVAL_SEC - gecen)
        logger.info("Sonraki tarama %.0fs sonra.", bekleme)
        await asyncio.sleep(bekleme)


def argumanlari_isle() -> argparse.Namespace:
    """Komut satırı argümanlarını ayrıştırır."""
    parser = argparse.ArgumentParser(
        description="Binance SRL Sinyal Botu v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--timeframe",
        default=config.ACTIVE_TIMEFRAME,
        help=f"Tarama zaman çerçevesi (varsayılan: {config.ACTIVE_TIMEFRAME}). "
             f"Örnekler: 1M, 5M, 15M, 1H, 4H, 1D",
    )
    parser.add_argument(
        "--chat-id",
        required=True,
        help="Telegram kanal/grup chat ID. Her timeframe için farklı kanal kullanılabilir.",
    )
    parser.add_argument(
        "--token",
        default=config.TELEGRAM_TOKEN or None,
        help="Telegram bot token (config.py'deki TELEGRAM_TOKEN override edilir).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = argumanlari_isle()
    token = args.token
    if not token:
        raise SystemExit(
            "Telegram bot token belirtilmedi. "
            "config.py dosyasındaki TELEGRAM_TOKEN alanını doldurun "
            "veya --token argümanını kullanın."
        )
    config.ACTIVE_TIMEFRAME = args.timeframe.upper()
    asyncio.run(ana_dongu(token=token, chat_id=args.chat_id, timeframe=config.ACTIVE_TIMEFRAME))
