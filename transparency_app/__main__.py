"""Entry point: python -m transparency_app (and the frozen exe).

Pass --self-test to bring the whole app up headlessly (engine + real window),
exercise it briefly, tear it down and exit 0. CI runs this against the built
executable to prove the exact bytes users download actually start.
"""

import faulthandler
import logging
import sys

from .app import AppController


def main():
    if "--self-test" in sys.argv:
        faulthandler.dump_traceback_later(30, exit=True)
        ok = AppController().self_test()
        print("self-test:", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
    try:
        AppController().run()
    except Exception:
        logging.getLogger("transparency_app").exception("fatal error")
        raise


if __name__ == "__main__":
    main()
