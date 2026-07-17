import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != ROOT]
sys.path.insert(0, str(ROOT))

from tools.export_openapi import render_openapi


def main() -> None:
    if (ROOT / "contracts/openapi.json").read_text(encoding="utf-8") != render_openapi():
        raise SystemExit("contracts/openapi.json is stale")


if __name__ == "__main__":
    main()
