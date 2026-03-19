"""
backtest.py — Backtesting del Grid Bot
========================================
Simula el grid trading sobre datos históricos.
Uso: python3 backtest.py
"""

import time
import pandas as pd
import ccxt

import config
from logger import log


def descargar_historico(dias: int = 90) -> pd.DataFrame:
    exchange = ccxt.binance()
    duracion_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                   "1h": 3_600_000, "4h": 14_400_000}.get("15m", 900_000)

    velas_totales = dias * 24 * 4  # 15m = 4 velas por hora
    bloques       = (velas_totales // 1000) + 1
    since         = exchange.milliseconds() - (dias * 24 * 60 * 60 * 1000)

    log.info(f"Descargando {dias} días de datos para backtest...")
    todos = []
    for bloque in range(bloques):
        try:
            ohlcv = exchange.fetch_ohlcv(config.SYMBOL, timeframe="15m",
                                          since=since, limit=1000)
            if not ohlcv:
                break
            todos.extend(ohlcv)
            since = ohlcv[-1][0] + duracion_ms
            time.sleep(0.3)
        except Exception as e:
            log.error(f"Error bloque {bloque+1}: {e}")
            break

    df = pd.DataFrame(todos, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp").sort_index()
    log.info(f"Total: {len(df)} velas | {df.index[0]} → {df.index[-1]}")
    return df


def calcular_atr_historico(df: pd.DataFrame) -> float:
    """Calcula el ATR promedio del período para definir el rango del grid."""
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift()).abs()
    lc  = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    # Convertir ATR de 15m a equivalente de 1h (multiplicar por 2)
    atr = tr.ewm(span=config.ATR_PERIOD, adjust=False).mean().mean() * 2
    return atr


def correr_backtest(df: pd.DataFrame) -> dict:
    """
    Simula el grid bot vela por vela.
    El grid se recalcula cada vez que el precio sale del rango.
    """
    FEE = 0.001  # 0.1% por trade en Binance spot

    # Calcular ATR inicial
    atr          = calcular_atr_historico(df.head(100))
    precio_init  = df["close"].iloc[0]

    # Crear grid inicial
    rango        = atr * config.ATR_GRID_MULT
    precio_min   = precio_init - rango
    precio_max   = precio_init + rango
    paso         = (precio_max - precio_min) / config.GRID_NIVELES
    capital_niv  = config.CAPITAL_USDT / config.GRID_NIVELES

    pnl_total    = 0.0
    trades_total = 0
    grids_creados= 1
    capital      = config.CAPITAL_USDT

    # Estado del grid: diccionario nivel → precio_compra (None si no hay compra activa)
    compras_activas = {}  # nivel: precio_compra

    registros = []

    for i in range(1, len(df)):
        precio    = df["close"].iloc[i]
        precio_ant= df["close"].iloc[i-1]

        # Recalcular grid si el precio sale del rango
        if config.RECALCULAR_RANGO and (precio < precio_min or precio > precio_max):
            # CORRECCIÓN: cerrar todas las compras abiertas al precio actual
            for nivel, p_compra in compras_activas.items():
                ganancia  = (precio - p_compra) * (capital_niv / p_compra)
                fee       = capital_niv * FEE * 2
                pnl_neto  = ganancia - fee
                pnl_total += pnl_neto
                capital   += pnl_neto
                registros.append({
                    "fecha":   df.index[i],
                    "compra":  p_compra,
                    "venta":   precio,
                    "pnl":     pnl_neto,
                    "capital": capital,
                })
            atr       = calcular_atr_historico(df.iloc[max(0,i-100):i])
            rango     = atr * config.ATR_GRID_MULT
            precio_min= precio - rango
            precio_max= precio + rango
            paso      = (precio_max - precio_min) / config.GRID_NIVELES
            compras_activas = {}
            grids_creados  += 1
            log.debug(f"Grid recalculado en vela {i} | Nuevo rango: {precio_min:.2f}-{precio_max:.2f}")
            continue

        # Calcular en qué nivel está el precio
        nivel_actual = int((precio - precio_min) / paso)
        nivel_ant    = int((precio_ant - precio_min) / paso)

        # Precio bajó → ejecutar COMPRA en el nivel cruzado
        if nivel_actual < nivel_ant:
            for nivel in range(nivel_ant - 1, nivel_actual - 1, -1):
                if 0 <= nivel < config.GRID_NIVELES:
                    precio_nivel = precio_min + (nivel * paso)
                    if nivel not in compras_activas:
                        compras_activas[nivel] = precio_nivel
                        fee = capital_niv * FEE
                        pnl_total -= fee
                        trades_total += 1
                        log.debug(f"COMPRA nivel {nivel} @ {precio_nivel:.2f}")

        # Precio subió → ejecutar VENTA en el nivel cruzado
        elif nivel_actual > nivel_ant:
            for nivel in range(nivel_ant, nivel_actual):
                if nivel in compras_activas:
                    precio_compra = compras_activas[nivel]
                    precio_venta  = precio_min + ((nivel + 1) * paso)
                    ganancia      = (precio_venta - precio_compra) * (capital_niv / precio_compra)
                    fee           = capital_niv * FEE * 2
                    pnl_neto      = ganancia - fee
                    pnl_total    += pnl_neto
                    capital      += pnl_neto
                    trades_total += 1
                    del compras_activas[nivel]
                    registros.append({
                        "fecha":   df.index[i],
                        "compra":  precio_compra,
                        "venta":   precio_venta,
                        "pnl":     pnl_neto,
                        "capital": capital,
                    })
                    log.debug(f"VENTA nivel {nivel} @ {precio_venta:.2f} | PnL: +{pnl_neto:.4f}")

    # Calcular métricas
    if not registros:
        return {"trades": 0}

    df_r = pd.DataFrame(registros)
    running_max  = df_r["capital"].cummax()
    drawdown     = (df_r["capital"] - running_max) / running_max * 100
    max_drawdown = drawdown.min()

    trades_ganadores = len(df_r[df_r["pnl"] > 0])
    win_rate         = trades_ganadores / len(df_r) * 100

    return {
        "trades":           trades_total,
        "ciclos_completos": len(registros),
        "grids_creados":    grids_creados,
        "win_rate_pct":     round(win_rate, 1),
        "pnl_total_usdt":   round(pnl_total, 2),
        "retorno_pct":      round(pnl_total / config.CAPITAL_USDT * 100, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "capital_final":    round(capital, 2),
        "pnl_por_ciclo":    round(df_r["pnl"].mean(), 4),
    }


def imprimir_reporte(metricas: dict, dias: int):
    if metricas.get("trades", 0) == 0:
        print("\nNo se generaron trades. Ajustá ATR_GRID_MULT o GRID_NIVELES.\n")
        return

    wr = metricas.get("win_rate_pct", 0)
    dd = metricas.get("max_drawdown_pct", 0)
    r  = metricas.get("retorno_pct", 0)

    print("\n" + "=" * 52)
    print("          REPORTE DE BACKTESTING — GRID BOT")
    print("=" * 52)
    print(f"  Par:                  {config.SYMBOL}")
    print(f"  Período:              {dias} días")
    print(f"  Capital:              {config.CAPITAL_USDT:.2f} USDT")
    print(f"  Niveles:              {config.GRID_NIVELES}")
    print(f"  ATR mult:             {config.ATR_GRID_MULT}x")
    print("-" * 52)
    print(f"  Trades totales:       {metricas.get('trades', 0)}")
    print(f"  Ciclos completos:     {metricas.get('ciclos_completos', 0)}")
    print(f"  Grids recalculados:   {metricas.get('grids_creados', 0)}")
    print(f"  Win rate:             {wr:.1f}%")
    print(f"  PnL total:            {metricas.get('pnl_total_usdt', 0):+.2f} USDT")
    print(f"  PnL por ciclo:        {metricas.get('pnl_por_ciclo', 0):+.4f} USDT")
    print(f"  Retorno:              {r:+.2f}%")
    print(f"  Max drawdown:         {dd:.2f}%")
    print(f"  Capital final:        {metricas.get('capital_final', 0):.2f} USDT")
    print("=" * 52)
    print("\n  INTERPRETACION:")
    print(f"  Win rate      {'Excelente' if wr > 80 else 'Bueno' if wr > 60 else 'Regular'}")
    print(f"  Retorno       {'Bueno' if r > 10 else 'Regular' if r > 0 else 'Negativo'}")
    print(f"  Drawdown      {'Controlado' if dd > -15 else 'Alto'}")
    print("=" * 52 + "\n")


if __name__ == "__main__":
    DIAS   = 360
    datos  = descargar_historico(dias=DIAS)
    metrs  = correr_backtest(datos)
    imprimir_reporte(metrs, dias=DIAS)
