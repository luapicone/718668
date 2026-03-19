"""
grid.py — Motor del Grid Bot
==============================
Lógica central del grid trading:
- Calcula el rango automáticamente con ATR
- Genera los niveles de la grilla
- Detecta cuándo el precio cruza un nivel
- Decide si comprar o vender en cada nivel
"""

import pandas as pd
import ccxt
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

import config
from logger import log


@dataclass
class Orden:
    """Representa una orden en la grilla."""
    nivel:      int           # Posición en la grilla (0 = más bajo)
    precio:     float         # Precio del nivel
    tipo:       str           # "COMPRA" o "VENTA"
    ejecutada:  bool  = False
    precio_exec:float = 0.0
    timestamp:  Optional[datetime] = None
    pnl:        float = 0.0


@dataclass
class Grid:
    """Estado completo de la grilla."""
    precio_min:     float         # Límite inferior del rango
    precio_max:     float         # Límite superior del rango
    niveles:        List[float]   # Lista de precios de cada nivel
    capital_nivel:  float         # Capital asignado a cada nivel
    ordenes:        List[Orden] = field(default_factory=list)
    pnl_total:      float = 0.0
    trades_total:   int   = 0
    activa:         bool  = True


def obtener_precio_actual(exchange: ccxt.Exchange) -> float:
    """Obtiene el precio actual del par."""
    ticker = exchange.fetch_ticker(config.SYMBOL)
    return ticker["last"]


def calcular_atr(exchange: ccxt.Exchange) -> float:
    """
    Calcula el ATR en el timeframe configurado.
    Se usa para determinar el rango óptimo del grid.
    """
    ohlcv = exchange.fetch_ohlcv(
        config.SYMBOL,
        timeframe=config.ATR_TIMEFRAME,
        limit=50
    )
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift()).abs()
    lc  = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(span=config.ATR_PERIOD, adjust=False).mean().iloc[-1]

    log.debug(f"ATR ({config.ATR_TIMEFRAME}): {atr:.4f}")
    return atr


def crear_grid(precio_actual: float, atr: float) -> Grid:
    """
    Crea la grilla automáticamente basándose en el precio y ATR.

    El rango es: precio_actual ± (ATR × ATR_GRID_MULT)
    Los niveles se distribuyen equitativamente dentro del rango.
    El capital se divide en partes iguales entre los niveles.

    Ejemplo con precio=2300, ATR=50, mult=3, niveles=10:
      Rango: 2300 ± 150 = [2150, 2450]
      Paso entre niveles: (2450-2150) / 10 = 30 USDT
      Niveles: 2150, 2180, 2210, ..., 2450
      Capital por nivel: 500 / 10 = 50 USDT
    """
    rango       = atr * config.ATR_GRID_MULT
    precio_min  = precio_actual - rango
    precio_max  = precio_actual + rango
    paso        = (precio_max - precio_min) / config.GRID_NIVELES
    capital_niv = config.CAPITAL_USDT / config.GRID_NIVELES

    niveles = [precio_min + (i * paso) for i in range(config.GRID_NIVELES + 1)]

    log.info(f"Grid creado:")
    log.info(f"  Rango: {precio_min:.2f} — {precio_max:.2f} USDT")
    log.info(f"  Niveles: {config.GRID_NIVELES} | Paso: {paso:.2f} USDT")
    log.info(f"  Capital por nivel: {capital_niv:.2f} USDT")
    log.info(f"  ATR usado: {atr:.4f} | Mult: {config.ATR_GRID_MULT}x")

    # Crear órdenes iniciales
    ordenes = []
    for i, precio_nivel in enumerate(niveles):
        # Niveles por debajo del precio actual = órdenes de COMPRA
        # Niveles por encima del precio actual = órdenes de VENTA
        if precio_nivel < precio_actual:
            tipo = "COMPRA"
        else:
            tipo = "VENTA"

        ordenes.append(Orden(
            nivel=i,
            precio=round(precio_nivel, 2),
            tipo=tipo,
        ))

    return Grid(
        precio_min=precio_min,
        precio_max=precio_max,
        niveles=niveles,
        capital_nivel=capital_niv,
        ordenes=ordenes,
    )


def precio_en_rango(grid: Grid, precio: float) -> bool:
    """Verifica si el precio está dentro del rango del grid."""
    return grid.precio_min <= precio <= grid.precio_max


def evaluar_grid(grid: Grid, precio_actual: float, precio_anterior: float) -> List[Orden]:
    """
    Evalúa qué órdenes se deben ejecutar basándose en el movimiento del precio.

    Lógica:
    - Si el precio BAJÓ y cruzó un nivel de COMPRA → ejecutar compra
    - Si el precio SUBIÓ y cruzó un nivel de VENTA → ejecutar venta

    Por cada COMPRA ejecutada, se crea automáticamente una orden de VENTA
    en el nivel inmediatamente superior (y viceversa).
    """
    ordenes_a_ejecutar = []

    for orden in grid.ordenes:
        if orden.ejecutada:
            continue

        # Precio bajó y cruzó el nivel → ejecutar COMPRA
        if orden.tipo == "COMPRA" and precio_anterior > orden.precio >= precio_actual:
            ordenes_a_ejecutar.append(orden)

        # Precio subió y cruzó el nivel → ejecutar VENTA
        elif orden.tipo == "VENTA" and precio_anterior < orden.precio <= precio_actual:
            ordenes_a_ejecutar.append(orden)

    return ordenes_a_ejecutar


def calcular_pnl_grid(grid: Grid) -> dict:
    """Calcula las métricas de performance del grid."""
    ejecutadas = [o for o in grid.ordenes if o.ejecutada]
    compras    = [o for o in ejecutadas if o.tipo == "COMPRA"]
    ventas     = [o for o in ejecutadas if o.tipo == "VENTA"]

    return {
        "trades_total":  grid.trades_total,
        "pnl_total":     round(grid.pnl_total, 4),
        "compras":       len(compras),
        "ventas":        len(ventas),
        "capital_usado": round(len(compras) * grid.capital_nivel, 2),
    }