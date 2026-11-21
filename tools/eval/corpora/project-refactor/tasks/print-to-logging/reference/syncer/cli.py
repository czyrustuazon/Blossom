import logging
import sys

from .pipeline import run_sync

logger = logging.getLogger(__name__)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    source = argv[0] if argv else "orders"
    try:
        saved, _ = run_sync(source)
    except KeyError:
        logger.error("sync failed")
        return 1
    print(f"{saved} rows synced from {source}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
