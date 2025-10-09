import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

# Temporarily add the parent directory to the path to allow imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now, import the module
import gemini_client

# Fixture to correctly mock the Gemini client dependencies
@pytest.fixture
def mock_gemini_client(monkeypatch):
    """
    Mocks the Gemini API key, configure function, and the GenerativeModel 
    to prevent actual API calls and configuration errors.
    """
    # Patch the module-level _API_KEY variable directly
    monkeypatch.setattr(gemini_client, "_API_KEY", "test-key")
    
    # Patch the genai.configure function to do nothing
    monkeypatch.setattr(gemini_client.genai, "configure", lambda api_key: None)
    
    # Reset the _configured flag to ensure the mock setup runs
    monkeypatch.setattr(gemini_client, "_configured", False)

    with patch('gemini_client.genai.GenerativeModel') as mock_genai_model:
        mock_response = MagicMock()
        mock_response.text = "Default mocked response"
        mock_genai_model.return_value.generate_content.return_value = mock_response
        yield mock_genai_model

# Test cases for format_final_response
def test_format_final_response(mock_gemini_client):
    """
    Tests the format_final_response function.
    """
    question = "What are the total sales per region?"
    df = pd.DataFrame({'region': ['North', 'South'], 'sales': [1000, 1500]})
    
    mock_response = MagicMock()
    mock_response.text = "The total sales for the North region are 1000 and for the South region are 1500."
    mock_gemini_client.return_value.generate_content.return_value = mock_response
    
    result = gemini_client.format_final_response(question, df)
    
    assert "summary" in result
    assert result["summary"] == mock_response.text

# Test cases for generate_summary
def test_generate_summary(mock_gemini_client):
    """
    Tests the generate_summary function.
    """
    question = "Summarize the data"
    table_sample = [{"col1": "a", "col2": 1}, {"col1": "b", "col2": 2}]
    metrics = {"rows": 2, "columns": 2}
    
    mock_response = MagicMock()
    mock_response.text = "This is a summary of the data."
    mock_gemini_client.return_value.generate_content.return_value = mock_response
    
    summary = gemini_client.generate_summary(question, table_sample, metrics)
    
    assert summary == mock_response.text

# Test cases for repair_code
def test_repair_code(mock_gemini_client):
    """
    Tests the repair_code function.
    """
    question = "Fix this code"
    schema_snippet = "col1: string, col2: int"
    sample_rows = [{"col1": "a", "col2": 1}]
    code_to_fix = "print(df.col1)"
    error_msg = "NameError: name 'df' is not defined"

    mock_response = MagicMock()
    mock_response.text = "```python\ndef run(df, ctx):\n    print('hello')\n```"
    mock_gemini_client.return_value.generate_content.return_value = mock_response
    
    repaired_code = gemini_client.repair_code(question, schema_snippet, sample_rows, code_to_fix, error_msg)
    
    assert "def run(df, ctx):" in repaired_code
    assert "print('hello')" in repaired_code

# Test cases for reconstruct_code_from_tool_call
def test_reconstruct_code_from_tool_call():
    """
    Tests the reconstruct_code_from_tool_call function, which does not call the API.
    """
    tool = "AGGREGATE"
    params = {"dimension": "region", "metric": "sales", "func": "sum"}
    
    code = gemini_client.reconstruct_code_from_tool_call(tool, params, "")
    
    assert "import pandas as pd" in code
    assert "def run(df: pd.DataFrame, ctx: dict) -> dict:" in code
    assert "df.groupby('region', dropna=False).agg({'sales': 'sum'}).reset_index()" in code
    assert "return {" in code

# Test cases for reconstruct_presentational_code
def test_reconstruct_presentational_code(mock_gemini_client):
    """
    Tests the reconstruct_presentational_code function.
    """
    question = "Show me the code for the last analysis"
    schema_snippet = "col1: string, col2: int"
    sample_rows = [{"col1": "a", "col2": 1}]
    last_exec_code = "print(df)"

    mock_response = MagicMock()
    mock_response.text = "```python\ndef run(df, ctx):\n    print(df)\n```"
    mock_gemini_client.return_value.generate_content.return_value = mock_response
    
    code = gemini_client.reconstruct_presentational_code(question, schema_snippet, sample_rows, last_exec_code)
    
    assert "def run(df, ctx):" in code
    assert "print(df)" in code