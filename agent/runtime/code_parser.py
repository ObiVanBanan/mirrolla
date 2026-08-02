from __future__ import annotations

import ast
import re


MAX_CODE_SIZE = 100_000
FENCED_BLOCK_PATTERN = re.compile(r"```(?:python)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
BANNED_IMPORT_ROOTS = {
    "pip",
    "requests",
    "socket",
    "subprocess",
    "urllib",
    "urllib3",
}
BANNED_CALLS = {
    "compile",
    "eval",
    "exec",
    "os.system",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
}


class GeneratedCodeError(ValueError):
    pass


def _normalize_text(text: str) -> str:
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()


def _format_syntax_error(exc: SyntaxError) -> str:
    line = exc.lineno or "?"
    offset = exc.offset or "?"
    return f"Generated code is not valid Python (line {line}, column {offset})"


def _resolve_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _resolve_call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in BANNED_IMPORT_ROOTS:
                    raise GeneratedCodeError(f"Forbidden import detected: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in BANNED_IMPORT_ROOTS:
                raise GeneratedCodeError(f"Forbidden import detected: {module}")
        elif isinstance(node, ast.Call):
            call_name = _resolve_call_name(node.func)
            if call_name in BANNED_CALLS:
                raise GeneratedCodeError(f"Forbidden call detected: {call_name}")


def _parse_candidate(candidate: str) -> str:
    normalized = _normalize_text(candidate)
    if not normalized:
        raise GeneratedCodeError("Generated code is empty")
    if len(normalized) > MAX_CODE_SIZE:
        raise GeneratedCodeError("Generated code exceeds the maximum size limit")
    try:
        tree = ast.parse(normalized)
    except SyntaxError as exc:
        raise GeneratedCodeError(_format_syntax_error(exc)) from exc
    _validate_ast(tree)
    return normalized


def extract_python_code(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        raise GeneratedCodeError("Generated code is empty")

    matches = FENCED_BLOCK_PATTERN.findall(normalized)
    last_error: GeneratedCodeError | None = None
    for block in reversed(matches):
        try:
            return _parse_candidate(block)
        except GeneratedCodeError as exc:
            last_error = exc
            if "not valid Python" in str(exc):
                continue
            raise

    if matches and last_error is not None:
        raise last_error

    return _parse_candidate(normalized)
