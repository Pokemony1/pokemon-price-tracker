from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

# Projektroot = mappen hvor dette script ligger i tools/
ROOT = Path(__file__).resolve().parents[1]

# Hvad vi vil samle (koder + workflow + requirements)
INCLUDE_PATHS = [
    Path("pokemon_price_tracker"),
    Path(".github/workflows"),
    Path("requirements.txt"),
    Path(".gitignore"),
]

# Hvad vi ALDRIG vil tage med (secrets/venv/cache/git)
EXCLUDE_DIRS = {
    "venv",
    ".venv",
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
}

EXCLUDE_FILES = {
    ".env",
    "service_account.json",
}

# Filtyper vi tager med fra mapper
ALLOWED_EXTS = {".py", ".yml", ".yaml", ".txt", ".md"}


def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts.intersection(EXCLUDE_DIRS):
        return True
    if path.name in EXCLUDE_FILES:
        return True
    return False


def iter_files(base: Path) -> list[Path]:
    files: list[Path] = []
    if base.is_file():
        if not is_excluded(base) and (base.suffix in ALLOWED_EXTS or base.name in {"requirements.txt", ".gitignore"}):
            files.append(base)
        return files

    for p in base.rglob("*"):
        if p.is_dir():
            continue
        if is_excluded(p):
            continue
        if p.suffix in ALLOWED_EXTS or p.name in {"requirements.txt", ".gitignore"}:
            files.append(p)
    return sorted(files)


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"<<COULD NOT READ FILE: {e}>>"


def main() -> None:
    out_name = f"CHATGPT_BUNDLE_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
    out_path = ROOT / out_name

    all_files: list[Path] = []
    for rel in INCLUDE_PATHS:
        target = (ROOT / rel).resolve()
        if target.exists():
            all_files.extend(iter_files(target))

    # Fjern dubletter
    seen = set()
    unique_files: list[Path] = []
    for f in all_files:
        if f not in seen:
            unique_files.append(f)
            seen.add(f)

    header = []
    header.append("CHATGPT CODE BUNDLE")
    header.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    header.append(f"Project root: {ROOT}")
    header.append("")
    header.append("Included files:")
    for f in unique_files:
        header.append(f"- {f.relative_to(ROOT)}")
    header.append("\n" + "=" * 80 + "\n")

    with out_path.open("w", encoding="utf-8", errors="replace") as w:
        w.write("\n".join(header))

        for f in unique_files:
            rel = f.relative_to(ROOT)
            w.write(f"\n\n### FILE: {rel}\n")
            w.write("```text\n")
            w.write(read_text_safe(f))
            if not read_text_safe(f).endswith("\n"):
                w.write("\n")
            w.write("```\n")

    print(f"✅ Skrevet: {out_path}")


if __name__ == "__main__":
    main()
