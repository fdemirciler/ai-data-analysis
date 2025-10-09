import pytest
import json
import base64
import pandas as pd
import subprocess
import sys
import io
import textwrap

# Temporarily add the parent directory to the path to allow imports
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Get the path to the worker script
WORKER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'worker.py'))

# Sample DataFrame for testing, encoded as Parquet
@pytest.fixture
def sample_parquet_b64():
    """
    Provides a base64-encoded Parquet representation of a sample DataFrame.
    """
    df = pd.DataFrame({'col1': [1, 2], 'col2': ['A', 'B']})
    buffer = io.BytesIO()
    df.to_parquet(buffer)
    return base64.b64encode(buffer.getvalue()).decode('ascii')

# Test cases for the worker script using subprocess
def test_worker_success(sample_parquet_b64):
    """
    Tests the worker script with a valid code snippet that should execute successfully.
    """
    # Use textwrap.dedent to remove leading whitespace from the code string
    code = textwrap.dedent("""
        def run(df, ctx):
            return {
                'table': df.to_dict(orient='records'),
                'metrics': {'rows': len(df)},
                'chartData': {}
            }
    """)
    input_data = json.dumps({
        "code": code,
        "parquet_b64": sample_parquet_b64,
        "ctx": {"question": "test"}
    })
    
    result = subprocess.run(
        [sys.executable, WORKER_PATH],
        input=input_data,
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Worker script failed with stderr: {result.stderr}"
    output = json.loads(result.stdout)
    
    assert "error" not in output, f"Expected no error, but got: {output.get('error')}"
    assert output["table"] == [{'col1': 1, 'col2': 'A'}, {'col1': 2, 'col2': 'B'}]
    assert output["metrics"] == {'rows': 2}

def test_worker_execution_error(sample_parquet_b64):
    """
    Tests that the worker catches a runtime error from the user code.
    The error is a NameError because ValueError is not in the sandboxed scope.
    """
    code = "def run(df, ctx):\n    raise ValueError('Test Error')"
    input_data = json.dumps({
        "code": code,
        "parquet_b64": sample_parquet_b64,
        "ctx": {}
    })
    
    result = subprocess.run(
        [sys.executable, WORKER_PATH],
        input=input_data,
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"Worker script failed with stderr: {result.stderr}"
    output = json.loads(result.stdout)
    
    assert "error" in output
    # The sandbox has restricted builtins, so this will raise a NameError, not a ValueError.
    # This is the correct behavior to test.
    assert "name 'ValueError' is not defined" in output["error"]

def test_worker_invalid_json_input():
    """
    Tests the worker with malformed JSON input.
    The script should exit with a non-zero status code and report to stderr.
    """
    input_data = "not valid json"
    
    result = subprocess.run(
        [sys.executable, WORKER_PATH],
        input=input_data,
        capture_output=True,
        text=True
    )
    
    assert result.returncode != 0
    assert "Invalid input payload" in result.stderr

def test_worker_missing_keys_in_input(sample_parquet_b64):
    """
    Tests the worker with valid JSON but missing required keys.
    The script should exit with a non-zero code and report to stderr.
    """
    input_data = json.dumps({"parquet_b64": sample_parquet_b64}) # Missing 'code'
    
    result = subprocess.run(
        [sys.executable, WORKER_PATH],
        input=input_data,
        capture_output=True,
        text=True
    )

    assert result.returncode != 0
    assert "Missing 'code' field" in result.stderr