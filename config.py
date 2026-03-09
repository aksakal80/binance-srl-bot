# ─── Telegram ───
TELEGRAM_TOKEN    = ""          # Bot token
# CHAT_ID --chat-id argümanıyla verilir (her timeframe farklı kanal)

# ─── Timeframe ───
ACTIVE_TIMEFRAME  = "1H"        # Dışarıdan --timeframe ile override edilir
CANDLE_LIMIT      = 300          # Her sembol için çekilecek mum sayısı
SCAN_INTERVAL_SEC = 900          # 15 dakika

# ─── Sinyal Eşikleri ───
NEAR_PCT          = 1.0          # %1  → YAKIN
APPROACH_PCT      = 3.0          # %3  → YAKLAŞIYOR
MIN_CONFIDENCE    = 2            # Minimum güven skoru (altındakiler gönderilmez)

# ─── İndikatör Parametreleri ───
RSI_PERIOD        = 14
RSI_SUPPORT_MAX   = 40
RSI_RESIST_MIN    = 60
VOL_SPIKE_MULT    = 1.5
VOL_LOOKBACK      = 20
WR_PERIOD         = 10
EMA_SHORT         = 20
EMA_LONG          = 50

# ─── Destek/Direnç Parametreleri ───
SWING_WINDOW      = 2
CLUSTER_TOL_PCT   = 0.3
MIN_VOLUME_USDT   = 500_000

# ─── Best 20 ───
BEST_N            = 20

# ─── Grafik ───
CHART_CANDLES     = 80
CHART_BG_COLOR    = "#0d1117"
CHART_UP_COLOR    = "#00c896"
CHART_DOWN_COLOR  = "#ff4560"
CHART_TEMP_DIR    = "tmp_charts"
