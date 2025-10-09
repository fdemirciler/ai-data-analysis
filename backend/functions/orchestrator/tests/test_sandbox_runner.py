import pytest

# Temporarily add the parent directory to the path to allow imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now, import the module
import sandbox_runner

# Test cases for validate_code, updated to match the implementation
@pytest.mark.parametrize("code, expected_is_valid, expected_errors, expected_warnings", [
    # 1. Valid code
    (
        "import pandas as pd\ndef run(df, ctx):\n    return {'table': [], 'metrics': {}, 'chartData': {}}",
        True,
        [],
        []
    ),
    # 2. Missing run function
    (
        "import pandas as pd\nprint('hello')",
        False,
        ["Missing required function: def run(df, ctx):"],
        []
    ),
    # 3. Disallowed import (os)
    (
        "import os\ndef run(df, ctx):\n    return {}",
        False,
        ["Import not allowed: os", "Forbidden import: os"], # It flags both
        []
    ),
    # 4. Malformed code (SyntaxError)
    (
        "def run(df, ctx):\n  print('hello'",
        False,
        # This error message can be version-specific. Using the one from the test environment.
        ["SyntaxError: '(' was never closed (<unknown>, line 2)"],
        []
    ),
    # 5. Allowed imports in 'rich' mode
    (
        "import pandas\nimport numpy\nimport math\nimport matplotlib\ndef run(df, ctx):\n    return {}",
        True,
        [],
        []
    ),
    # 6. Forbidden function call (eval)
    (
        "def run(df, ctx):\n    eval('1+1')",
        False,
        ["Forbidden call: eval"],
        []
    ),
    # 7. Use of dunder attribute
    (
        "def run(df, ctx):\n    print(df.__class__)",
        False,
        ["Use of dunder attributes is not allowed"],
        []
    ),
    # 8. Use of complex dtype (which is disallowed)
    (
        "def run(df, ctx):\n    df['new'] = df['col'].astype('complex128')",
        False,
        ["Complex dtype is not allowed (astype(complex))."],
        []
    ),
])
def test_validate_code(code, expected_is_valid, expected_errors, expected_warnings, monkeypatch):
    """
    Tests the validate_code function with various code snippets.
    """
    # Ensure we are in 'rich' mode to allow matplotlib etc.
    monkeypatch.setattr(sandbox_runner, "_SANDBOX_MODE", "rich")
    # Reloading the allowed imports based on the mode
    monkeypatch.setattr(sandbox_runner, "ALLOWED_IMPORTS", set(sandbox_runner.ALLOWED_IMPORTS_BASE).union(sandbox_runner.ALLOWED_IMPORTS_RICH))

    is_valid, errors, warnings = sandbox_runner.validate_code(code)

    assert is_valid == expected_is_valid
    # Sort lists to ensure comparison is order-independent
    assert sorted(errors) == sorted(expected_errors)
    assert sorted(warnings) == sorted(expected_warnings)