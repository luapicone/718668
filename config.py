"""
config.py — Grid Bot ETH/USDT
===============================
El bot divide un rango de precios en N niveles y opera
automáticamente comprando abajo y vendiendo arriba.
"""

# ─── EXCHANGE ────────────────────────────────────────────────────────────────
EXCHANGE_ID     = "binance"
API_KEY         = "dlmhcVv8dBl0bcK9306S441olVl8lz4NXeBI5nLjVeAbdFW1P3xzU1DdYAMugCIv"
API_SECRET      = "ANKRnTFs3nGyeirJ7U8SVzlWjVWhMnivBg62QMlEM3parOzqJgxUeePZ0C631bFz"
PAPER_TRADING   = True

# ─── TRADING ─────────────────────────────────────────────────────────────────
SYMBOL          = "ETH/USDT"
CAPITAL_USDT    = 200.0           # Capital total para el grid

# ─── CONFIGURACIÓN DEL GRID ──────────────────────────────────────────────────
GRID_NIVELES    = 10              # Cantidad de niveles en la grilla
# El capital se divide equitativamente entre todos los niveles
# Con 500 USDT y 10 niveles = 50 USDT por nivel

# Multiplicador del ATR para calcular el rango automáticamente
# El bot calcula: rango = precio_actual ± (ATR × ATR_GRID_MULT)
# Más grande = rango más amplio, menos trades pero más ganancia por trade
# Más chico  = rango más ajustado, más trades pero menos ganancia por trade
ATR_GRID_MULT   = 5
ATR_PERIOD      = 14
ATR_TIMEFRAME   = "1h"           # Timeframe para calcular el ATR del rango

# ─── GESTIÓN DE RIESGO ───────────────────────────────────────────────────────
# Si el precio sale del rango, el bot pausa y recalcula
RECALCULAR_RANGO = True          # True = recalcula automáticamente si sale del rango
MAX_DAILY_LOSS_PCT = 0.05        # 5% pérdida máxima diaria

# ─── COMPORTAMIENTO ──────────────────────────────────────────────────────────
LOOP_INTERVAL   = 15              # Revisa cada 15 segundos (grid necesita ser más rápido)
