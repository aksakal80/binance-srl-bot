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
- **Çoklu Timeframe (Multiprocessing)** — Tek komutla 5 timeframe paralel çalıştırma desteği
- **Telegram Forum Konusu (Alt Konu) Desteği** — Her timeframe sinyallerini farklı bir forum alt konusuna gönderir
- **Binance API Anahtarı** — API key ile rate limit 1200 → 6000 ağırlık (key olmadan da çalışır)
- **Otomatik Loglama** — Her process kendi `bot_{TF}.log` dosyasına yazar, hata `errors.log`'a

---

## Gereksinimler

- Python 3.11+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather) üzerinden oluşturun)
- Telegram Chat ID (grup ID'si)
- Telegram Forum Konu ID'leri (Telegram forum grubundaki her alt konunun ID'si — opsiyonel)
- Binance API anahtarı (opsiyonel, rate limit artışı için önerilir)

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

## ⚙️ Kimlik Bilgilerini Ayarlama (bot.py Dosyasını Düzenle)

`bot.py` dosyasını bir metin editörüyle (Notepad, VS Code, vb.) açın.
Dosyanın başındaki şu satırları bulun ve kendi bilgilerinizi girin:

```python
# ─── Telegram ───
TELEGRAM_TOKEN     = ""   # ← BotFather'dan aldığınız token (örn: "123456:ABC-DEF...")
TELEGRAM_CHAT_ID   = ""   # ← Grubun ID'si (örn: "-1001234567890")
TELEGRAM_THREAD_ID = ""   # ← Forum alt konu ID (yoksa boş bırakın)

# ─── Binance API ───
BINANCE_API_KEY    = ""   # ← Binance API anahtarınız (opsiyonel, boş bırakılabilir)
BINANCE_API_SECRET = ""   # ← Binance gizli anahtarınız (opsiyonel, boş bırakılabilir)
```

Örnek dolu hâli:

```python
TELEGRAM_TOKEN     = "8576023339:AAFoHQ5YfN..."
TELEGRAM_CHAT_ID   = "-1003880760948"
TELEGRAM_THREAD_ID = ""
BINANCE_API_KEY    = "nCNQe7GcuSq..."
BINANCE_API_SECRET = "rwBWrQybI6Tl..."
```

Kaydedin ve botu başlatın:

```bash
# 5 timeframe — her biri kendi forum alt konusuna
python bot.py --multi \
    --tf 1H:-1003880760948:2 \
    --tf 4H:-1003880760948:4 \
    --tf 8H:-1003880760948:7 \
    --tf 12H:-1003880760948:13 \
    --tf 1D:-1003880760948:9
```

---

## Binance API Anahtarı

Binance API anahtarı **opsiyoneldir** — bot public endpoint'leri (fiyat ve mum verisi) kullandığından key olmadan da çalışır. Ancak key ile Binance rate limit önemli ölçüde artar (1200 → 6000 ağırlık/dakika), bu da çok sayıda coin tararken daha güvenli çalışma sağlar.

> **Not:** Binance API anahtarı oluştururken sadece **Okuma** iznini verin. Emir verme (spot/futures trade) izni gerekmez.

---

## Telegram Forum Konusu (Alt Konu) Kurulumu

Bot, Telegram **forum gruplarındaki** alt konulara (topics) doğrudan sinyal gönderebilir. 5 ayrı timeframe için 5 ayrı alt konu açtıysanız her biri farklı bir konuya yönlendirilebilir.

### Chat ID ve Topic (Thread) ID Nedir?

| Değer | Açıklama | Örnek |
|-------|----------|-------|
| **Chat ID** | Telegram grubunuzun ID'si — tüm konular için aynıdır | `-1001234567890` |
| **Thread ID** | Her alt konunun (topic) kendine özel ID'si | `12345`, `67890` |

> ⚠️ Chat ID ve Thread ID farklı şeylerdir. "Alt konunun linki" = Thread ID'dir. Her 5 alt konunun farklı bir Thread ID'si vardır, ama hepsinin Chat ID'si aynı grup ID'sidir.

### Thread ID'yi Nasıl Bulursunuz?

**Yöntem 1 — Telegram Web Uygulaması:**
1. [web.telegram.org](https://web.telegram.org) adresine gidin
2. Grubunuzu açın, ilgili alt konuya (topic) tıklayın
3. Tarayıcının adres çubuğuna bakın:
   ```
   https://web.telegram.org/k/#-1001234567890_12345
                                        ^grup_id  ^thread_id
   ```
   Alttaki sayı (`12345`) Thread ID'dir.

**Yöntem 2 — @getidsbot:**
1. Telegram'da [@getidsbot](https://t.me/getidsbot)'u açın
2. İlgili alt konudan herhangi bir mesajı bu bota iletin (forward edin)
3. Bot size `Message thread ID: 12345` gibi bir yanıt verecektir

**Yöntem 3 — Bot günlüğü:**
1. Bota grupta herhangi bir mesaj gönderin (alt konu içinden)
2. Botun günlüğünü (log) kontrol edin — gelen güncelleme içinde `message_thread_id` değerini göreceksiniz

### bot.py İçindeki Sabitler

```python
# ─── Telegram ───
TELEGRAM_TOKEN     = "123456:ABCdef..."   # Bot token
TELEGRAM_CHAT_ID   = "-1001234567890"     # Grubun ID'si (tüm konular için aynı)
TELEGRAM_THREAD_ID = "12345"              # Tek timeframe modunda varsayılan konu ID'si
```

> **Not:** Çoklu timeframe (`--multi`) modunda her `--tf` argümanına ayrı Thread ID vermeniz gerekir (aşağıya bakın).

---

## Başlatma

### Tek timeframe — forum konusuz (klasik kullanım)

```bash
# Varsayılan 1h timeframe
python bot.py --token BOT_TOKEN --chat-id -100GRUBID

# 4 saatlik mum
python bot.py --token BOT_TOKEN --chat-id -100GRUBID --timeframe 4h
```

### Tek timeframe — forum konusuna gönder

```bash
# 1 saatlik timeframe, sinyal "1H Sinyalleri" konusuna gider
python bot.py --token BOT_TOKEN --chat-id -100GRUBID --thread-id 12345 --timeframe 1h
```

### Çoklu timeframe — her biri farklı forum konusuna (önerilen kullanım)

```bash
# 5 timeframe paralel başlatılır, her biri kendi forum alt konusuna yazar
python bot.py --token BOT_TOKEN --multi \
    --tf 1H:-100GRUBID:11111 \
    --tf 4H:-100GRUBID:22222 \
    --tf 8H:-100GRUBID:33333 \
    --tf 12H:-100GRUBID:44444 \
    --tf 1D:-100GRUBID:55555
```

`--tf` argümanı `TIMEFRAME:CHAT_ID:THREAD_ID` formatındadır.
- `1H` — timeframe
- `-100GRUBID` — grubun chat ID'si (tüm satırlarda aynı)
- `11111` — o timeframe için açtığınız forum alt konusunun Thread ID'si

### Forum konusu olmayan çoklu timeframe (eski format, hâlâ desteklenir)

```bash
python bot.py --token BOT_TOKEN --multi \
    --tf 1H:-100111 \
    --tf 4H:-100222 \
    --tf 4H:-100333
```

---

## Tüm Komut Satırı Argümanları

| Argüman | Açıklama | Örnek |
|---------|----------|-------|
| `--token` | Telegram bot token | `--token 123456:ABC...` |
| `--chat-id` | Telegram grup chat ID | `--chat-id -1001234567890` |
| `--thread-id` | Forum alt konu (topic) ID — tek timeframe modunda | `--thread-id 12345` |
| `--timeframe` | Mum timeframe (tek mod) | `--timeframe 4h` |
| `--multi` | Çoklu timeframe modunu etkinleştirir | `--multi` |
| `--tf` | `TIMEFRAME:CHAT_ID:THREAD_ID` üçlüsü (multi modda tekrarlanabilir) | `--tf 1H:-100GRUBID:12345` |
| `--api-key` | Binance API anahtarı (bot.py'yi override eder) | `--api-key abc123` |
| `--api-secret` | Binance gizli anahtarı (bot.py'yi override eder) | `--api-secret xyz789` |

> Thread ID **opsiyoneldir** — forum konusu kullanmıyorsanız sadece `TIMEFRAME:CHAT_ID` formatını kullanabilirsiniz.

---

## Yapılandırma (bot.py Sabitleri)

`bot.py` dosyasının başında yer alan sabitler:

| Sabit | Varsayılan | Açıklama |
|-------|-----------|----------|
| `TELEGRAM_TOKEN` | `""` | Telegram bot token (--token ile override edilebilir) |
| `TELEGRAM_CHAT_ID` | `""` | Varsayılan grup chat ID (--chat-id ile override edilebilir) |
| `TELEGRAM_THREAD_ID` | `""` | Varsayılan forum konu ID'si — opsiyonel (--thread-id ile override edilebilir) |
| `BINANCE_API_KEY` | `""` | Binance API anahtarı (--api-key ile override edilebilir) |
| `BINANCE_API_SECRET` | `""` | Binance gizli anahtarı (--api-secret ile override edilebilir) |
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

Her process kendi log dosyasına yazar (multiprocessing modunda da ayrı tutulur):

| Dosya | Seviye | İçerik |
|-------|--------|--------|
| Konsol (stdout) | INFO | Tarama ilerlemesi, sinyal sayısı (`[TF]` etiketi ile) |
| `bot_1H.log` | DEBUG | Tüm detaylar (timeframe'e özel) |
| `bot_4H.log` | DEBUG | Tüm detaylar (timeframe'e özel) |
| `errors.log` | ERROR | Hatalar ve istisnalar (tüm process'lerden) |

---

## Lisans

MIT


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
