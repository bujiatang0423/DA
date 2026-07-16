from pathlib import Path

def test_runtime_files_do_not_reference_la() -> None:
    forbidden = ("/Users/bujiatang/workspace/" + "LA", "../" + "LA/")
    matches: list[str] = []
    for root in (Path("backend"), Path("web/src"), Path("strategies/manifest.json")):
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                matches.extend(f"{path}: {value}" for value in forbidden if value in text)
    assert matches == []

def test_repository_contains_no_symlinks() -> None:
    assert not [str(path) for path in Path(".").rglob("*") if path.is_symlink()]
