import argparse
from pathlib import Path

from .app import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="WeChat / QQ AI desktop panel")
    parser.add_argument("--access-config", help="Explicit installed access deployment configuration")
    args = parser.parse_args(argv)
    run(config_path=Path(args.access_config) if args.access_config else None)


if __name__ == "__main__":
    main()
