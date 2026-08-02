from __future__ import annotations

import pytest

from agent.runtime.code_parser import GeneratedCodeError, extract_python_code


def test_extracts_python_markdown_block() -> None:
    result = extract_python_code("```python\nprint('test')\n```")

    assert result == "print('test')"


def test_extracts_plain_markdown_block() -> None:
    result = extract_python_code("```\nprint('test')\n```")

    assert result == "print('test')"


def test_accepts_plain_python_without_markdown() -> None:
    result = extract_python_code("value = 1\nprint(value)")

    assert "print(value)" in result


def test_rejects_empty_response() -> None:
    with pytest.raises(GeneratedCodeError) as exc_info:
        extract_python_code("")

    assert "empty" in str(exc_info.value).lower()


def test_rejects_syntax_error() -> None:
    with pytest.raises(GeneratedCodeError) as exc_info:
        extract_python_code("```python\nif True print('oops')\n```")

    assert "valid python" in str(exc_info.value).lower()


def test_uses_last_valid_code_block() -> None:
    text = "```python\nthis is not python\n```\n\n```python\nprint('ok')\n```"

    assert extract_python_code(text) == "print('ok')"


def test_rejects_subprocess_import() -> None:
    with pytest.raises(GeneratedCodeError) as exc_info:
        extract_python_code("```python\nimport subprocess\n```")

    assert "Forbidden import detected: subprocess" in str(exc_info.value)


def test_rejects_requests_import() -> None:
    with pytest.raises(GeneratedCodeError) as exc_info:
        extract_python_code("```python\nimport requests\n```")

    assert "Forbidden import detected: requests" in str(exc_info.value)


def test_rejects_eval_call() -> None:
    with pytest.raises(GeneratedCodeError) as exc_info:
        extract_python_code("```python\neval('1 + 1')\n```")

    assert "Forbidden call detected: eval" in str(exc_info.value)


def test_allows_common_data_stack() -> None:
    code = """
```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.DataFrame({"value": [1, 2, 3]})
print(df["value"].sum())
```
"""

    result = extract_python_code(code)

    assert "import pandas as pd" in result
