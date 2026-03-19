"""
logger.py — Sistema de logging del Grid Bot
"""

import logging
import os
from datetime import datetime


def setup_logger(name: str = "grid_bot") -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    hoy      = datetime.now().strftime("%Y-%m-%d")
    log_file = f"logs/grid_{hoy}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S"
    )

    consola = logging.StreamHandler()
    consola.setLevel(logging.INFO)
    consola.setFormatter(fmt)

    archivo = logging.FileHandler(log_file, encoding="utf-8")
    archivo.setLevel(logging.DEBUG)
    archivo.setFormatter(fmt)

    logger.addHandler(consola)
    logger.addHandler(archivo)

    return logger


log = setup_logger()
