"""Where the app keeps its files (%APPDATA%\\TransparencyApp).

The old app wrote data.json/error_log.txt into whatever the current
directory happened to be. A legacy data.json sitting next to the executable
is migrated on first run.
"""

import logging
import logging.handlers
import os
import shutil
import sys

APP_DIR_NAME = "TransparencyApp"


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(app_data_dir(), "config.json")


def ledger_path() -> str:
    return os.path.join(app_data_dir(), "session.json")


def log_path() -> str:
    return os.path.join(app_data_dir(), "app.log")


def install_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(name: str) -> str:
    """Bundled asset path (works from source and from a PyInstaller exe)."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(install_dir(), name)


def migrate_legacy_config():
    """Move a v1 data.json living next to the app into %APPDATA%."""
    if os.path.exists(config_path()):
        return
    legacy = os.path.join(install_dir(), "data.json")
    if os.path.exists(legacy):
        try:
            shutil.copy(legacy, config_path())
            os.replace(legacy, legacy + ".migrated")
        except OSError:
            pass


def setup_logging(level=logging.INFO):
    logger = logging.getLogger("transparency_app")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger
