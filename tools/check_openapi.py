from pathlib import Path
from tools.export_openapi import render_openapi


def main() -> None:
    if Path("contracts/openapi.json").read_text(encoding="utf-8") != render_openapi():
        raise SystemExit("contracts/openapi.json is stale")


if __name__ == "__main__":
    main()
