"""Secret scan and redaction: nothing that looks like a secret is sent to the LLM.

The scan reports where secrets are (file, line, kind), never their values. The redactor masks
every pattern match and every exact value the scan found, in any text."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

PATTERNS = {
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"
        r"[\s\S]*?(?:-----END (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----|\Z)"
    ),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "api_key": re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"),
    "stripe_key": re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    "url_credentials": re.compile(r"(?<=://)[^/\s:@'\"]+:[^/\s@'\"]+(?=@)"),
}
# name = "value" assignments whose name says secret; only the value is masked
ASSIGNMENT = re.compile(
    r"(?i)\b([\w-]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|access[_-]?key|auth[_-]?key"
    r"|client[_-]?secret|private[_-]?key)[\w-]*)\b(\s*[:=]\s*)(['\"])([^'\"\s]{6,})\3"
)
SECRET_FILES = [
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".pypirc",
    ".npmrc",
    "credentials*.json",
    "*secret*.json",
    "*secrets*.y*ml",
    "service-account*.json",
]
SAFE_VALUES = {"changeme", "password", "example", "xxxxxx", "your-api-key", "dummy", "test"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}
MAX_BYTES = 1_000_000


def is_secret_file(path: str) -> bool:
    """True for files whose whole content is treated as secret (.env, keys, credentials)."""
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_FILES) and name != ".env.example"


def find_secrets(text: str) -> list[tuple[str, str, int]]:
    """(kind, value, offset) of every secret-looking string in a text."""
    found = []
    for kind, pattern in PATTERNS.items():
        found += [(kind, m.group(0), m.start()) for m in pattern.finditer(text)]
    for m in ASSIGNMENT.finditer(text):
        value = m.group(4)
        if value.lower() not in SAFE_VALUES and not value.startswith(("{", "$", "<", "%")):
            found.append(("assigned_secret", value, m.start(4)))
    return found


def scan(repo_dir: str) -> dict:
    """Scan a project: secret files and secret-looking strings, without their values.

    Returns {"files": [...], "findings": [{"path", "line", "kind"}], "values": set} where
    "values" stays in memory for the redactor and is never written out."""
    root = Path(repo_dir)
    files, findings, values = [], [], set()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or SKIP_DIRS & set(Path(rel).parts):
            continue
        if is_secret_file(rel):
            files.append(rel)
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for kind, value, offset in find_secrets(text):
            findings.append({"path": rel, "line": text.count("\n", 0, offset) + 1, "kind": kind})
            values.add(value)
    return {"files": files, "findings": findings, "values": values}


class Redactor:
    """Masks secrets in any text: known values from a scan, plus every pattern."""

    def __init__(self, values: set[str] | None = None):
        self.values = sorted(values or set(), key=len, reverse=True)

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for value in self.values:
            text = text.replace(value, "[REDACTED]")
        for kind, pattern in PATTERNS.items():
            text = pattern.sub(f"[REDACTED:{kind}]", text)

        def mask(m: re.Match) -> str:
            value = m.group(4)
            if value.lower() in SAFE_VALUES or value.startswith(("{", "$", "<", "%")):
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}{m.group(3)}[REDACTED]{m.group(3)}"

        return ASSIGNMENT.sub(mask, text)


def public_findings(result: dict) -> dict:
    """The scan result without the values, safe to log or show."""
    return {"files": result["files"], "findings": result["findings"]}
