"""
dashboard.py — Dashboard del Grid Bot
Correr: python3 dashboard.py
Abrir:  http://localhost:5002
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import ccxt
import config
from logger import log

_lock  = threading.Lock()
_datos = {}


def loop():
    exchange = ccxt.binance({"enableRateLimit": True})
    while True:
        try:
            # 1. Precio en vivo de Binance
            ticker = exchange.fetch_ticker(config.SYMBOL)
            precio = round(ticker["last"], 2)

            # 2. Leer estado.json del bot
            bot = {}
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")
            if os.path.exists(path):
                with open(path) as f:
                    bot = json.load(f)
                bot_activo = (time.time() - os.path.getmtime(path)) < 60
            else:
                bot_activo = False

            # 3. Armar respuesta
            datos = {
                "precio":              precio,
                "bot_activo":          bot_activo,
                "precio_min":          bot.get("precio_min", 0),
                "precio_max":          bot.get("precio_max", 0),
                "pnl_total":           bot.get("pnl_total", 0),
                "pnl_diario":          bot.get("pnl_diario", 0),
                "pnl_flotante":        bot.get("pnl_flotante", 0),
                "trades_total":        bot.get("trades_total", 0),
                "ciclos":              bot.get("ciclos", 0),
                "posiciones_abiertas": bot.get("posiciones_abiertas", []),
                "historial":           bot.get("historial", []),
                "ultima_update":       bot.get("ultima_update", "—"),
            }

            with _lock:
                _datos.update(datos)

        except Exception as e:
            log.error(f"Dashboard error: {e}")

        time.sleep(10)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/api/estado":
            body = json.dumps(_datos).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        elif self.path in ("/", "/dashboard.html"):
            html = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(html, "rb") as f:
                self.wfile.write(f.read())

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    log.info("Esperando primer dato...")
    time.sleep(5)
    log.info("Dashboard en http://localhost:5002")
    HTTPServer(("localhost", 5002), Handler).serve_forever()