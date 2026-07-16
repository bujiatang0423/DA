import json
from backend.app.bootstrap.application import build_application

def render_openapi() -> str:
    return json.dumps(build_application().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

def main() -> None:
    with open("contracts/openapi.json", "w", encoding="utf-8") as target:
        target.write(render_openapi())

if __name__ == "__main__": main()
