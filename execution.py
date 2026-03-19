"""
execution.py — Ejecución de órdenes del Grid Bot
"""

import ccxt
from datetime import datetime

import config
from grid import Grid, Orden
from logger import log


def ejecutar_orden(exchange: ccxt.Exchange, orden: Orden, grid: Grid) -> bool:
    """
    Ejecuta una orden de la grilla.
    Retorna True si se ejecutó correctamente.
    """
    cantidad = grid.capital_nivel / orden.precio

    if config.PAPER_TRADING:
        log.info(
            f"[PAPER] {orden.tipo} nivel {orden.nivel} | "
            f"Precio: {orden.precio:.2f} | "
            f"Cantidad: {cantidad:.6f} ETH | "
            f"Valor: {grid.capital_nivel:.2f} USDT"
        )
        orden.ejecutada   = True
        orden.precio_exec = orden.precio
        orden.timestamp   = datetime.now()

        # Calcular PnL si es una venta (completó el ciclo compra→venta)
        if orden.tipo == "VENTA":
            # Buscar la compra correspondiente en el nivel inferior
            nivel_compra = orden.nivel - 1
            compra_ref = next(
                (o for o in grid.ordenes if o.nivel == nivel_compra and o.tipo == "COMPRA" and o.ejecutada),
                None
            )
            if compra_ref:
                paso = grid.niveles[1] - grid.niveles[0] if len(grid.niveles) > 1 else 0
                pnl  = cantidad * paso
                orden.pnl    = pnl
                grid.pnl_total += pnl
                log.info(f"  ✅ Ciclo completado | PnL: +{pnl:.4f} USDT | Total: +{grid.pnl_total:.4f} USDT")

        grid.trades_total += 1

        # Crear orden opuesta en el nivel adyacente
        crear_orden_opuesta(grid, orden)
        return True

    else:
        try:
            if orden.tipo == "COMPRA":
                resultado = exchange.create_limit_buy_order(
                    config.SYMBOL, cantidad, orden.precio
                )
            else:
                resultado = exchange.create_limit_sell_order(
                    config.SYMBOL, cantidad, orden.precio
                )
            log.info(f"Orden {orden.tipo} enviada | ID: {resultado['id']} | Precio: {orden.precio:.2f}")
            orden.ejecutada   = True
            orden.precio_exec = orden.precio
            orden.timestamp   = datetime.now()
            grid.trades_total += 1
            crear_orden_opuesta(grid, orden)
            return True

        except ccxt.InsufficientFunds:
            log.error(f"Fondos insuficientes para orden en nivel {orden.nivel}")
            return False
        except ccxt.ExchangeError as e:
            log.error(f"Error al ejecutar orden: {e}")
            return False


def crear_orden_opuesta(grid: Grid, orden_ejecutada: Orden):
    """
    Después de ejecutar una compra, crea una venta en el nivel superior.
    Después de ejecutar una venta, crea una compra en el nivel inferior.
    Esta es la mecánica core del grid trading.
    """
    from grid import Orden

    if orden_ejecutada.tipo == "COMPRA":
        nivel_opuesto = orden_ejecutada.nivel + 1
        tipo_opuesto  = "VENTA"
    else:
        nivel_opuesto = orden_ejecutada.nivel - 1
        tipo_opuesto  = "COMPRA"

    # Verificar que el nivel existe
    if nivel_opuesto < 0 or nivel_opuesto >= len(grid.niveles):
        return

    precio_opuesto = grid.niveles[nivel_opuesto]

    # Verificar que no existe ya una orden activa en ese nivel
    existe = any(
        o for o in grid.ordenes
        if o.nivel == nivel_opuesto and o.tipo == tipo_opuesto and not o.ejecutada
    )

    if not existe:
        nueva_orden = Orden(
            nivel=nivel_opuesto,
            precio=round(precio_opuesto, 2),
            tipo=tipo_opuesto,
        )
        grid.ordenes.append(nueva_orden)
        log.debug(f"Nueva orden {tipo_opuesto} creada en nivel {nivel_opuesto} ({precio_opuesto:.2f})")
