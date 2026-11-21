import sys

from .pipeline import run_sync


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    source = argv[0] if argv else "orders"
    try:
        saved, _ = run_sync(source)
    except KeyError:
        print("ERROR: sync failed")
        return 1
    print(f"{saved} rows synced from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
