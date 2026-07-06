"""Entry point: python -m transparency_app (and the frozen exe)."""

import logging

from .app import AppController


def main():
    try:
        AppController().run()
    except Exception:
        logging.getLogger("transparency_app").exception("fatal error")
        raise


if __name__ == "__main__":
    main()
