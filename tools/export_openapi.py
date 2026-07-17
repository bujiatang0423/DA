import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != ROOT]
sys.path.insert(0, str(ROOT))

from backend.app.bootstrap.application import build_application


def render_openapi() -> str:
    return (
        json.dumps(build_application().openapi(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )


def main() -> None:
    with (ROOT / "contracts/openapi.json").open("w", encoding="utf-8") as target:
        target.write(render_openapi())


if __name__ == "__main__":
    main()
