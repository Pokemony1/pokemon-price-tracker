from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from typing import Iterable


# Projektroot = mappen over /tools
ROOT = Path(__file__).resolve().parents[1]

# Output filnavn
OUT_NAME = f"CHATGPT_BUNDLE_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
OUT_PATH = ROOT / OUT_NAME

# Maks filstørrelse (undgå kæmpe logs/artifacts)
MAX_BYTES_PER_FILE = 1_000_000  # 1 MB

# Mapper vi aldrig vil tage med
EXCLUDE_DIRS = {
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".cache",
}

# Filnavne vi aldrig vil tage med
EXCLUDE_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "service_account.json",
    "credentials.json",
    "token.json",
}

# Filtyper vi aldrig vil tage med (typiske secrets/binaries)
EXCLUDE_EXTS = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".der",
    ".crt",
    ".cer",
    ".sqlite",
    ".db",
}

# Tilladte teksttyper (vi inkluderer også filer uden suffix som fx .gitignore)
ALLOWED_TEXT_EXTS = {
    ".py",
    ".yml",
    ".yaml",
    ".txt",
    ".md",
    ".toml",
    ".json",
    ".ini",
    ".cfg",
    ".csv",
    ".ts",
    ".js",
    ".html",
    ".css",
    ".sh",
    ".ps1",
}

# Filer uden suffix der ofte er relevante
ALLOWED_NAME_FILES = {
    "requirements.txt",
    ".gitignore",
    "Dockerfile",
    "Makefile",
    "README",
    "README.md",
    "README.txt",
}


# ----------------------------
# Redaction (maskering)
# ----------------------------

# Private key blocks (service accounts, PEM osv.)
RE_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Generic "secret-ish" JSON lines: "token": "...."
RE_JSON_SECRET_LINE = re.compile(
    r'(^\s*"(?:[^"]*?(?:key|token|secret|password|private_key|client_secret)[^"]*?)"\s*:\s*)"([^"]*)(".*$)',
    re.IGNORECASE | re.MULTILINE,
)

# Env-style: SOMETHING_SECRET=...
RE_ENV_SECRET_LINE = re.compile(
    r"^(?P<lhs>\s*[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*)(?P<rhs>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

# YAML-ish: something_secret: value
RE_YAML_SECRET_LINE = re.compile(
    r"^(?P<lhs>\s*[^:#\n]*(?:key|token|secret|password|private_key|client_secret)\s*:\s*)(?P<rhs>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

# Very long base64-ish strings (typisk keys/tokens), men kun hvis linjen også indeholder et “secret” keyword
RE_LONG_B64 = re.compile(r"[A-Za-z0-9+/=]{60,}")


def redact_text(text: str) -> tuple[str, int]:
    """
    Returnerer (redacted_text, redaction_count)
    """
    redactions = 0

    # 1) Private key block
    if RE_PRIVATE_KEY_BLOCK.search(text):
        text = RE_PRIVATE_KEY_BLOCK.sub("<<REDACTED PRIVATE KEY BLOCK>>", text)
        redactions += 1

    # 2) JSON secret lines
    def _json_sub(m: re.Match) -> str:
        nonlocal redactions
        redactions += 1
        return f'{m.group(1)}"<<REDACTED>>"{m.group(3)}'

    text = RE_JSON_SECRET_LINE.sub(_json_sub, text)

    # 3) ENV secret lines
    def _env_sub(m: re.Match) -> str:
        nonlocal redactions
        redactions += 1
        return f"{m.group('lhs')}<<REDACTED>>"

    text = RE_ENV_SECRET_LINE.sub(_env_sub, text)

    # 4) YAML secret lines
    def _yaml_sub(m: re.Match) -> str:
        nonlocal redactions
        redactions += 1
        rhs = m.group("rhs")
        # hvis rhs er tom eller bare en reference, lad den stå
        if rhs.strip() == "" or "secrets." in rhs or "${{" in rhs:
            return m.group(0)
        # hvis der står en lang token-lignende streng, maskér
        if RE_LONG_B64.search(rhs) or len(rhs.strip()) > 20:
            return f"{m.group('lhs')}<<REDACTED>>"
        return m.group(0)

    text = RE_YAML_SECRET_LINE.sub(_yaml_sub, text)

    return text, redactions


# ----------------------------
# Fil-udvælgelse
# ----------------------------

def is_excluded(path: Path) -> bool:
    # dir exclude
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True

    # file name exclude
    if path.name in EXCLUDE_FILES:
        return True

    # ext exclude
    if path.suffix.lower() in EXCLUDE_EXTS:
        return True

    # output bundle itself (hvis du kører flere gange)
    if path.name.startswith("CHATGPT_BUNDLE_") and path.suffix.lower() == ".txt":
        return True

    return False


def is_allowed_text_file(path: Path) -> bool:
    if path.name in ALLOWED_NAME_FILES:
        return True
    if path.suffix.lower() in ALLOWED_TEXT_EXTS:
        return True
    # files with no suffix but small and likely text (fx "LICENSE")
    if path.suffix == "" and path.stat().st_size <= MAX_BYTES_PER_FILE:
        # undgå binære uden suffix: check for null bytes hurtigt
        try:
            sample = path.read_bytes()[:2048]
            if b"\x00" in sample:
                return False
            return True
        except Exception:
            return False
    return False


def iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if is_excluded(p):
            continue
        try:
            if p.stat().st_size > MAX_BYTES_PER_FILE:
                continue
        except Exception:
            continue
        if is_allowed_text_file(p):
            files.append(p)
    return sorted(files)


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"<<COULD NOT READ FILE: {e}>>"


# ----------------------------
# “Fortæl alt” (auto-overblik)
# ----------------------------

RE_OS_GETENV = re.compile(r'os\.getenv\(\s*["\']([^"\']+)["\']\s*(?:,\s*["\'][^"\']*["\'])?\)', re.IGNORECASE)
RE_GH_SECRET = re.compile(r"\${{\s*secrets\.([A-Z0-9_]+)\s*}}", re.IGNORECASE)


def extract_env_vars(text: str) -> set[str]:
    out: set[str] = set()
    for m in RE_OS_GETENV.finditer(text):
        out.add(m.group(1))
    for m in RE_GH_SECRET.finditer(text):
        out.add(m.group(1))
    return out


def build_overview(files: Iterable[Path]) -> tuple[str, set[str]]:
    env_vars: set[str] = set()
    important: list[str] = []

    # prøv at finde “main”/entrypoints
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if rel.endswith("pokemon_price_tracker/main.py"):
            important.append(rel)
        if rel.startswith(".github/workflows/"):
            important.append(rel)

    # env vars scan
    for f in files:
        try:
            txt = read_text_safe(f)
        except Exception:
            continue
        vars_found = extract_env_vars(txt)
        env_vars.update(vars_found)

    overview_lines = []
    overview_lines.append("PROJECT OVERVIEW (auto-generated)")
    overview_lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    overview_lines.append(f"Root: {ROOT}")
    overview_lines.append("")
    overview_lines.append("Key files detected:")
    if important:
        for x in sorted(set(important)):
            overview_lines.append(f"- {x}")
    else:
        overview_lines.append("- (none detected)")
    overview_lines.append("")
    overview_lines.append("Environment variables referenced in code/workflows:")
    if env_vars:
        for v in sorted(env_vars):
            overview_lines.append(f"- {v}")
    else:
        overview_lines.append("- (none found)")
    overview_lines.append("")

    return "\n".join(overview_lines), env_vars


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    files = iter_repo_files(ROOT)

    overview, _ = build_overview(files)

    # build header
    header = []
    header.append("CHATGPT CODE BUNDLE (SAFE EXPORT)")
    header.append("=" * 80)
    header.append(overview)
    header.append("Included files:")
    for f in files:
        header.append(f"- {f.relative_to(ROOT)}")
    header.append("\n" + "=" * 80 + "\n")

    redaction_log: list[str] = []
    total_redactions = 0

    with OUT_PATH.open("w", encoding="utf-8", errors="replace") as w:
        w.write("\n".join(header))

        for f in files:
            rel = f.relative_to(ROOT)
            text = read_text_safe(f)
            redacted_text, count = redact_text(text)
            if count:
                redaction_log.append(f"- {rel}  (redactions: {count})")
                total_redactions += count

            w.write(f"\n\n### FILE: {rel}\n")
            w.write("```text\n")
            w.write(redacted_text)
            if not redacted_text.endswith("\n"):
                w.write("\n")
            w.write("```\n")

        w.write("\n\n" + "=" * 80 + "\n")
        w.write("REDACTION SUMMARY\n")
        w.write(f"Total redactions applied: {total_redactions}\n")
        if redaction_log:
            w.write("Files with redactions:\n")
            w.write("\n".join(redaction_log) + "\n")
        else:
            w.write("No redactions were necessary.\n")

    print(f"✅ Skrevet: {OUT_PATH}")


if __name__ == "__main__":
    main()
