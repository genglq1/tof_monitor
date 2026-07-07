from loguru import logger
import sys
from pathlib import Path

def setup_logger(log_dir: str = "logs", level: str = "INFO"):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level)
    logger.add(Path(log_dir) / "app_{time}.log", rotation="1 day", level=level)
    return logger