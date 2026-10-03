"""Create an allowlisted submission ZIP; never include local secrets or caches."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {"README.md", "CAPABILITIES.md", "ARCHITECTURE.md", "VALIDATION.md", "pyproject.toml",
             "requirements.lock", "mcp-tools.json", ".env.example", ".gitignore", ".gitattributes", "LIVE_VALIDATION.json"}
DIRECTORIES = {"wc_connector", "scripts", "tests", "test-store"}
ALLOWED_SUFFIXES = {".py", ".php", ".sh", ".yaml", ".md"}


def submission_files():
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if not path.is_file() or path.is_symlink():
            continue
        if len(relative.parts) == 1 and relative.name in TOP_FILES:
            yield path
        elif relative.as_posix() == ".github/workflows/verify.yml":
            yield path
        elif (relative.parts[0] in DIRECTORIES and (path.suffix in ALLOWED_SUFFIXES or relative.name == "Caddyfile")
              and all(not part.startswith(".") and part != "__pycache__" for part in relative.parts)
              and len(relative.parts) <= 3):
            yield path


def main():
    target = ROOT.parent / "woocommerce-connector-submission.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in submission_files():
            archive.write(path, Path(ROOT.name) / path.relative_to(ROOT))
    print(f"Created {target.name} with allowlisted source and documentation.")


if __name__ == "__main__":
    main()
