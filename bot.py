"""
bot.py — Grid Bot principal
Escribe estado.json en cada ciclo para el dashboard.
"""

import json
import time
import sys
from datetime import date, datetime
import os

import ccxt

import config
from logger import log
from grid import crear_grid, obtener_precio_actual, calcular_atr, evaluar_grid, precio_en_rango, calcular_pnl_grid
from execution import ejecutar_orden


def verificar_circuit_breaker(pnl_diario: float) -> bool:
    perdida_max = config.CAPITAL_USDT * config.MAX_DAILY_LOSS_PCT
    if pnl_diario <= -perdida_max:
        log.warning(f"CIRCUIT BREAKER — Pérdida: {pnl_diario:.2f} USDT")
        return True
    return False


def guardar_estado(grid, precio_actual, pnl_diario, posiciones_abiertas, historial):
    """Escribe estado.json con datos 100% reales del bot."""
    try:
        paso = grid.niveles[1] - grid.niveles[0] if len(grid.niveles) > 1 else 1

        # Niveles del grid
        niveles_info = []
        for i, pn in enumerate(grid.niveles):
            dist = ((precio_actual - pn) / precio_actual) * 100
            niveles_info.append({
                "nivel":      i,
                "precio":     round(pn, 2),
                "dist_pct":   round(dist, 2),
                "compra_act": 1 if any(p["nivel"] == i for p in posiciones_abiertas) else 0,
                "es_actual":  1 if abs(precio_actual - pn) < paso / 2 else 0,
            })

        # PnL flotante total
        pnl_flotante = sum(p["pnl_flot"] for p in posiciones_abiertas)

        metricas = calcular_pnl_grid(grid)

        estado = {
            "precio":              round(precio_actual, 2),
            "precio_min":          round(grid.precio_min, 2),
            "precio_max":          round(grid.precio_max, 2),
            "pnl_total":           round(metricas["pnl_total"], 4),
            "pnl_diario":          round(pnl_diario, 4),
            "pnl_flotante":        round(pnl_flotante, 4),
            "trades_total":        metricas["trades_total"],
            "ciclos":              len(historial),
            "posiciones_abiertas": posiciones_abiertas,
            "niveles":             niveles_info,
            "historial":           historial[-20:],
            "ultima_update":       datetime.now().strftime("%H:%M:%S"),
        }

        with open("estado.json.tmp", "w") as f:
             json.dump(estado, f)
        os.replace("estado.json.tmp", "estado.json")

    except Exception as e:
        log.debug(f"Error guardando estado: {e}")


def main():
    log.info("=" * 55)
    log.info("  GRID BOT INICIADO")
    log.info(f"  Par: {config.SYMBOL} | Capital: {config.CAPITAL_USDT} USDT")
    log.info(f"  Niveles: {config.GRID_NIVELES} | ATR mult: {config.ATR_GRID_MULT}x")
    log.info(f"  Modo: {'PAPER TRADING' if config.PAPER_TRADING else 'REAL'}")
    log.info("=" * 55)

    exchange = ccxt.binance({
        "apiKey":          config.API_KEY,
        "secret":          config.API_SECRET,
        "enableRateLimit": True,
    })

    precio_actual   = obtener_precio_actual(exchange)
    atr             = calcular_atr(exchange)
    grid            = crear_grid(precio_actual, atr)
    precio_anterior = precio_actual
    pnl_diario      = 0.0
    fecha_hoy       = date.today()

    # posiciones_abiertas: dict nivel -> info de la compra abierta
    posiciones_abiertas_dict = {}
    # historial: lista de ciclos completados (compra + venta)
    historial = []

    log.info(f"Grid inicializado | Precio: {precio_actual:.2f} | Rango: {grid.precio_min:.2f}-{grid.precio_max:.2f}")

    while True:
        try:
            # Reset PnL diario
            if date.today() != fecha_hoy:
                pnl_diario = 0.0
                fecha_hoy  = date.today()
                log.info("Nuevo día — PnL diario reseteado")

            # Circuit breaker
            if verificar_circuit_breaker(pnl_diario):
                log.warning("Bot pausado 1 hora...")
                time.sleep(3600)
                continue

            precio_actual = obtener_precio_actual(exchange)

            # Recalcular grid si el precio sale del rango
            if not precio_en_rango(grid, precio_actual):
                if config.RECALCULAR_RANGO:
                    log.info(f"Precio {precio_actual:.2f} fuera del rango. Recalculando...")
                    atr  = calcular_atr(exchange)
                    grid = crear_grid(precio_actual, atr)
                    posiciones_abiertas_dict = {}  # reset posiciones al recalcular
                    log.info(f"Nuevo rango: {grid.precio_min:.2f} — {grid.precio_max:.2f}")
                else:
                    time.sleep(config.LOOP_INTERVAL)
                    continue

            # Evaluar y ejecutar órdenes
            ordenes_ejecutar = evaluar_grid(grid, precio_actual, precio_anterior)

            for orden in ordenes_ejecutar:
                exito = ejecutar_orden(exchange, orden, grid)
                if not exito:
                    continue

                if orden.tipo == "COMPRA":
                    # Registrar posición abierta
                    capital_nv = grid.capital_nivel
                    posiciones_abiertas_dict[orden.nivel] = {
                        "nivel":      orden.nivel,
                        "p_compra":   round(orden.precio_exec, 2),
                        "valor_usdt": round(capital_nv, 2),
                        "hora_compra": datetime.now().strftime("%H:%M:%S"),
                    }

                elif orden.tipo == "VENTA" and orden.pnl > 0:
                    pnl_diario += orden.pnl

                    # Buscar la compra correspondiente (nivel de compra = nivel venta - 1)
                    nivel_compra = orden.nivel - 1
                    compra_info  = posiciones_abiertas_dict.pop(nivel_compra, None)

                    if compra_info:
                        # Agregar al historial como ciclo completado
                        historial.insert(0, {
                            "hora_compra": compra_info["hora_compra"],
                            "hora_venta":  datetime.now().strftime("%H:%M:%S"),
                            "nivel":       nivel_compra,
                            "p_compra":    compra_info["p_compra"],
                            "p_venta":     round(orden.precio_exec, 2),
                            "capital":     compra_info["valor_usdt"],
                            "pnl":         round(orden.pnl, 4),
                        })
                        if len(historial) > 50:
                            historial.pop()

            # Calcular PnL flotante de posiciones abiertas
            posiciones_lista = []
            for nv, pos in posiciones_abiertas_dict.items():
                capital_nv = pos["valor_usdt"]
                cant       = capital_nv / pos["p_compra"]
                valor_act  = cant * precio_actual
                pnl_flot   = valor_act - capital_nv
                posiciones_lista.append({
                    "nivel":       pos["nivel"],
                    "p_compra":    pos["p_compra"],
                    "valor_usdt":  round(capital_nv, 2),
                    "valor_act":   round(valor_act, 2),
                    "pnl_flot":    round(pnl_flot, 4),
                    "pnl_pct":     round((pnl_flot / capital_nv) * 100, 2),
                    "hora_compra": pos["hora_compra"],
                })

            metricas = calcular_pnl_grid(grid)
            log.info(
                f"Precio: {precio_actual:.2f} | "
                f"Rango: {grid.precio_min:.0f}-{grid.precio_max:.0f} | "
                f"Trades: {metricas['trades_total']} | "
                f"PnL: {metricas['pnl_total']:+.4f} USDT | "
                f"Abiertas: {len(posiciones_lista)}"
            )

            guardar_estado(grid, precio_actual, pnl_diario, posiciones_lista, historial)
            precio_anterior = precio_actual

        except KeyboardInterrupt:
            metricas = calcular_pnl_grid(grid)
            log.info(f"Bot detenido | Trades: {metricas['trades_total']} | PnL: {metricas['pnl_total']:+.4f} USDT")
            sys.exit(0)

        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)

        time.sleep(config.LOOP_INTERVAL)


if __name__ == "__main__":
    main()