from pathlib import Path


class UnsafeArtifactPath(ValueError):
    pass


def resolve_artifact(root: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise UnsafeArtifactPath("absolute artifact path")
    base = root.resolve()
    result = (base / relative_path).resolve()
    if not result.is_relative_to(base):
        raise UnsafeArtifactPath("artifact path escapes root")
    return result
