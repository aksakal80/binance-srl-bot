# Binance SRL Sinyal Botu v3.0

Binance USDT spot paritelerini tarayarak destek ve direnç seviyelerine yaklaşan coinleri tespit eden ve Telegram üzerinden sinyal gönderen bir Python botu.

---

## Özellikler

- **Tam Sembol Taraması** — Son 24 saatte hacmi 500.000 USDT üzerinde olan TÜM Binance USDT paritelerini tarar (200–300 coin)
- **Swing High/Low Analizi** — Fiyat tabanlı önemli dönüm noktaları tespit edilir
- **Cluster Kümeleme** — Yakın seviyeleri birleştirerek güçlü bölgeler belirlenir
- **Volume Profile** — Yüksek hacim yoğunluğu olan fiyat bölgeleri belirlenir
- **Zone Sınıflandırması** — Her seviye Zone 1 ★★★ / Zone 2 ★★ / Zone 3 ⚠️ olarak sınıflandırılır
- **5/5 Güven Skoru** — RSI, Volume Spike, Williams %R, EMA Trend, Zone 1 bonusu
- **3 Panelli Grafik** — Mum (EMA dahil) + RSI (40/60 çizgileri) + Volume
- **Best 20 Listesi** — En güçlü 20 Destek ve 20 Direnç sinyali ayrı ayrı gönderilir
- **Çoklu Timeframe** — 1m'den 1w'ye kadar tüm Binance timeframe'leri desteklenir
- **Otomatik Loglama** — Konsol, `bot_TF.log` ve `errors.log` ayrı ayrı

---

## Gereksinimler

- Python 3.11+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather) üzerinden oluşturun)
- Telegram Chat ID

---

## Kurulum

```bash
# Repoyu klonla
git clone https://github.com/aksakal80/binance-srl-bot.git
cd binance-srl-bot

# Kütüphaneleri kur
pip install -r requirements.txt
```

---

## Başlatma

### Temel kullanım

```bash
python bot.py --token BOT_TOKEN --chat-id CHAT_ID
```

### Farklı timeframe ile

```bash
# 4 saatlik mum
python bot.py --token BOT_TOKEN --chat-id CHAT_ID --timeframe 4h

# Günlük mum
python bot.py --token BOT_TOKEN --chat-id CHAT_ID --timeframe 1d

# 15 dakikalık mum
python bot.py --token BOT_TOKEN --chat-id CHAT_ID --timeframe 15m
```

### 5 farklı terminalde (5 timeframe aynı anda)

```bash
# Terminal 1 — 15 dakika
python bot.py --token TOKEN --chat-id CHAT_ID --timeframe 15m

# Terminal 2 — 1 saat
python bot.py --token TOKEN --chat-id CHAT_ID --timeframe 1h

# Terminal 3 — 4 saat
python bot.py --token TOKEN --chat-id CHAT_ID --timeframe 4h

# Terminal 4 — 1 gün
python bot.py --token TOKEN --chat-id CHAT_ID --timeframe 1d

# Terminal 5 — 1 hafta
python bot.py --token TOKEN --chat-id CHAT_ID --timeframe 1w
```

---

## Yapılandırma (bot.py Sabitleri)

`bot.py` dosyasının başında yer alan sabitler:

| Sabit | Varsayılan | Açıklama |
|-------|-----------|----------|
| `TELEGRAM_TOKEN` | `""` | Telegram bot token (--token ile override edilebilir) |
| `TELEGRAM_CHAT_ID` | `""` | Varsayılan chat ID |
| `ACTIVE_TIMEFRAME` | `"1h"` | Varsayılan timeframe |
| `CANDLE_LIMIT` | `300` | Çekilecek mum sayısı |
| `SCAN_INTERVAL_SEC` | `900` | Tarama aralığı (saniye, varsayılan 15 dakika) |
| `NEAR_PCT` | `1.0` | YAKIN sinyal eşiği (%) |
| `APPROACH_PCT` | `3.0` | YAKLAŞIYOR sinyal eşiği (%) |
| `MIN_CONFIDENCE` | `2` | Gönderilecek minimum güven skoru |
| `RSI_PERIOD` | `14` | RSI hesaplama periyodu |
| `RSI_SUPPORT_MAX` | `40` | Destek için RSI onay eşiği (RSI < 40) |
| `RSI_RESIST_MIN` | `60` | Direnç için RSI onay eşiği (RSI > 60) |
| `VOL_SPIKE_MULT` | `1.5` | Volume Spike çarpanı (son hacim > ort × 1.5) |
| `VOL_LOOKBACK` | `20` | Volume Spike için geriye bakış periyodu |
| `WR_PERIOD` | `10` | Williams %R periyodu |
| `EMA_SHORT` | `20` | Kısa EMA periyodu |
| `EMA_LONG` | `50` | Uzun EMA periyodu |
| `SWING_WINDOW` | `2` | Swing High/Low penceresi |
| `CLUSTER_TOL_PCT` | `0.3` | Kümeleme toleransı (%) |
| `MIN_VOLUME_USDT` | `500_000` | Minimum 24s hacim filtresi (USDT) |
| `BEST_N` | `20` | Best N listesi boyutu |
| `CHART_CANDLES` | `80` | Grafikte gösterilecek son mum sayısı |

---

## Mesaj Formatı

### Bireysel Sinyal Mesajı

```
📊 COIN: BTCUSDT
⏱ Timeframe: 1H
💲 Fiyat: 65432.10 USDT
🕐 10.03.2026 · 14:00 UTC
━━━━━━━━━━━━━━━━━━━━━━━
🟢 DESTEK YAKIN (%0.72) · Zone 1 ★★★

🟢 DESTEK SEVİYELERİ (Yakından Uzağa)
  S1: 64960.00  → Güç: Zone 1 ★★★
  S2: 63500.00  → Güç: Zone 2 ★★
  S3: 62000.00  → Güç: Zone 3 ⚠️

🔴 DİRENÇ SEVİYELERİ (Yakından Uzağa)
  R1: 66000.00  → Güç: Zone 2 ★★
  R2: 67500.00  → Güç: Zone 1 ★★★
  R3: 70000.00  → Güç: Zone 3 ⚠️
━━━━━━━━━━━━━━━━━━━━━━━
📉 RSI (14): 37.4  🔥 Güçlü
📈 Volume Spike: ✅ VAR (×2.31 ort.)
📊 Williams %R: -82.5  ✅ Onaylandı
📈 EMA Trend: ✅ Uyumlu
⭐ Güven Skoru: 5/5  ★★★★★
━━━━━━━━━━━━━━━━━━━━━━━
_Binance SRL Bot · v3.0_
```

### Best 20 Listesi

```
🟢 BEST 20 DESTEK — 1H — En Yakın Destek Seviyeleri
🕐 10.03.2026 · 14:00 UTC
────────────────────────────

🥇 #1  BTCUSDT · 1H
   🟢 DESTEK YAKIN · Zone 1 ★★★ · %0.72
   Seviye: 64960.00  RSI: 37.4  ✅
   Vol Spike: ✅ ×2.31 · W%R: -82.5 ✅ · EMA: ✅
   ⭐ Güven: 5/5  ★★★★★
...
────────────────────────────
_Binance SRL Bot · v3.0_
```

---

## Grafik Açıklaması (3 Panel)

```
┌─────────────────────────────────────────────┐
│  ÜST PANEL: Mum Grafik                      │
│  • OHLC mumlar (yeşil = yükseliş, kırmızı = düşüş)  │
│  • Destek çizgileri: yeşil kesikli  ─ ─ ─   │
│  • Direnç çizgileri: kırmızı kesikli ─ ─ ─  │
│  • EMA 20: mavi çizgi                       │
│  • EMA 50: turuncu çizgi                    │
│  • Etiketler: S1 [Z1 ★★★], R1 [Z2 ★★]      │
├─────────────────────────────────────────────┤
│  ORTA PANEL: RSI                            │
│  • RSI çizgisi (mor)                        │
│  • 40 ve 60 kırmızı referans çizgileri      │
│  • Aşırı alım/satım bölgeleri vurgulı       │
├─────────────────────────────────────────────┤
│  ALT PANEL: Volume                          │
│  • Yükseliş = yeşil, Düşüş = kırmızı       │
└─────────────────────────────────────────────┘
```

---

## Önemli Notlar

### S1 ≠ Zone 1
- **S1** = Fiyata en yakın destek seviyesi (mesafeye göre sıralama)
- **Zone 1** = En güçlü seviye (güç skoruna göre sınıflandırma)
- S1 Zone 3 ⚠️ olabilir, S3 Zone 1 ★★★ olabilir — bunlar **bağımsız** sınıflandırmadır

### Güven Skoru (Maks 5/5)
| Kriter | Destek | Direnç | Puan |
|--------|--------|--------|------|
| RSI | RSI < 40 | RSI > 60 | +1 |
| Volume Spike | Hacim > ort × 1.5 | Hacim > ort × 1.5 | +1 |
| Williams %R | W%R < -80 | W%R > -20 | +1 |
| EMA Trend | Fiyat > EMA50 | Fiyat < EMA50 | +1 |
| Zone 1 Bonusu | Seviye Zone 1 ise | Seviye Zone 1 ise | +1 |

### Gönderim Sırası (Her 15 Dakika)
1. 🟢 Bireysel destek sinyalleri (grafik ile, güven yüksekten düşüğe)
2. 🔴 Bireysel direnç sinyalleri (grafik ile, güven yüksekten düşüğe)
3. 🟢 Best 20 Destek listesi (metin)
4. 🔴 Best 20 Direnç listesi (metin)

---

## Loglama

| Dosya | Seviye | İçerik |
|-------|--------|--------|
| Konsol (stdout) | INFO | Tarama ilerlemesi, sinyal sayısı |
| `bot_1H.log` | DEBUG | Tüm detaylar (timeframe'e özel) |
| `errors.log` | ERROR | Hatalar ve istisnalar |

---

## Lisans

MIT
