from __future__ import annotations

import ast
import re


MAX_CODE_SIZE = 100_000
FENCED_BLOCK_PATTERN = re.compile(r"```(?:python)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
BANNED_IMPORT_ROOTS = {
    "ctypes",
    "ensurepip",
    "ftplib",
    "httpx",
    "multiprocessing",
    "paramiko",
    "pexpect",
    "pip",
    "resource",
    "requests",
    "socket",
    "subprocess",
    "urllib",
}
BANNED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "input",
    "os.system",
    "os.popen",
    "pathlib.Path.rmdir",
    "pathlib.Path.unlink",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
    "shutil.rmtree",
}
BANNED_CALL_PREFIXES = {
    "os.spawn",
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
        if isinstance(node.value, ast.Call):
            constructor_name = _resolve_call_name(node.value.func)
            if constructor_name:
                return f"{constructor_name}.{node.attr}"
    return None


def _validate_ast(tree: ast.AST) -> None:
    import_aliases: dict[str, str] = {}

    def resolve_alias(name: str | None) -> str | None:
        if not name:
            return None
        parts = name.split(".")
        mapped_root = import_aliases.get(parts[0], parts[0])
        if len(parts) == 1:
            return mapped_root
        return ".".join([mapped_root, *parts[1:]])

    def resolve_pathlib_method_name(node: ast.Call) -> str | None:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return None
        owner_name = resolve_alias(_resolve_call_name(func.value))
        if owner_name == "pathlib.Path":
            return f"pathlib.Path.{func.attr}"
        if isinstance(func.value, ast.Call):
            constructor_name = resolve_alias(_resolve_call_name(func.value.func))
            if constructor_name == "pathlib.Path":
                return f"pathlib.Path.{func.attr}"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                import_aliases[alias.asname or root] = alias.name
                if root in BANNED_IMPORT_ROOTS:
                    raise GeneratedCodeError(f"Forbidden import detected: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            for alias in node.names:
                import_aliases[alias.asname or alias.name] = f"{module}.{alias.name}".strip(".")
            if root in BANNED_IMPORT_ROOTS:
                raise GeneratedCodeError(f"Forbidden import detected: {module}")
        elif isinstance(node, ast.Call):
            call_name = resolve_alias(_resolve_call_name(node.func))
            pathlib_method_name = resolve_pathlib_method_name(node)
            if pathlib_method_name:
                call_name = pathlib_method_name
            if call_name in BANNED_CALLS:
                raise GeneratedCodeError(f"Forbidden call detected: {call_name}")
            if call_name and any(call_name.startswith(prefix) for prefix in BANNED_CALL_PREFIXES):
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
