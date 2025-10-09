import pytest
import pandas as pd
import numpy as np

# Temporarily add the parent directory to the path to allow imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now, import the module
import analysis_toolkit

# Test cases for the run_aggregation function
def test_run_aggregation_sum():
    """
    Tests the run_aggregation function with the 'sum' aggregation.
    """
    data = {'category': ['A', 'B', 'A', 'B'], 'value': [10, 20, 5, 15]}
    df = pd.DataFrame(data)
    result_df = analysis_toolkit.run_aggregation(df, 'category', 'value', 'sum')
    
    # Expected output is sorted by the aggregated value, descending
    expected_data = {'category': ['B', 'A'], 'value_sum': [35, 15]}
    expected_df = pd.DataFrame(expected_data)
    pd.testing.assert_frame_equal(result_df, expected_df)

def test_run_aggregation_mean():
    """
    Tests the run_aggregation function with the 'mean' aggregation.
    """
    data = {'category': ['A', 'B', 'A', 'B'], 'value': [10, 20, 5, 15]}
    df = pd.DataFrame(data)
    result_df = analysis_toolkit.run_aggregation(df, 'category', 'value', 'mean')

    # Expected output is sorted by the aggregated value, descending
    expected_data = {'category': ['B', 'A'], 'value_mean': [17.5, 7.5]}
    expected_df = pd.DataFrame(expected_data)
    pd.testing.assert_frame_equal(result_df, expected_df)

# Test cases for the run_variance function
def test_run_variance():
    """
    Tests the run_variance function.
    """
    data = {
        'product': ['A', 'B', 'C'],
        'sales_2023': [100, 200, 150],
        'sales_2024': [110, 210, 140]
    }
    df = pd.DataFrame(data)
    result_df = analysis_toolkit.run_variance(df, 'product', 'sales_2023', 'sales_2024')

    # Expected output is sorted by 'delta', descending
    expected_data = {
        'product': ['A', 'B', 'C'],
        'sales_2023': [100, 200, 150],
        'sales_2024': [110, 210, 140],
        'delta': [10, 10, -10],
        'pct_change': [10.0, 5.0, -6.666667]
    }
    # Note: The function sorts by delta, but since two values are the same, the original order of A and B is preserved.
    expected_df = pd.DataFrame(expected_data).sort_values('delta', ascending=False, kind='mergesort').reset_index(drop=True)
    pd.testing.assert_frame_equal(result_df, expected_df, atol=1e-6)

# Test cases for the run_filter_and_sort function
def test_run_filter_and_sort_ascending():
    """
    Tests the run_filter_and_sort function with ascending sort.
    """
    data = {'name': ['A', 'B', 'C', 'D'], 'value': [10, 5, 20, 15]}
    df = pd.DataFrame(data)
    result_df = analysis_toolkit.run_filter_and_sort(df, 'value', ascending=True, limit=3)
    expected_df = df.sort_values('value', kind='mergesort').head(3).reset_index(drop=True)
    pd.testing.assert_frame_equal(result_df, expected_df)

def test_run_filter_and_sort_descending():
    """
    Tests the run_filter_and_sort function with descending sort.
    """
    data = {'name': ['A', 'B', 'C', 'D'], 'value': [10, 5, 20, 15]}
    df = pd.DataFrame(data)
    result_df = analysis_toolkit.run_filter_and_sort(df, 'value', ascending=False, limit=3)
    expected_df = df.sort_values('value', ascending=False, kind='mergesort').head(3).reset_index(drop=True)
    pd.testing.assert_frame_equal(result_df, expected_df)

def test_run_filter_and_sort_with_filter():
    """
    Tests the run_filter_and_sort function with a filter applied.
    """
    data = {'name': ['A', 'B', 'C', 'A'], 'value': [10, 5, 20, 15]}
    df = pd.DataFrame(data)
    # Added missing ascending and limit arguments
    result_df = analysis_toolkit.run_filter_and_sort(df, 'value', ascending=False, limit=10, filter_col='name', filter_val='A')
    expected_df = df[df['name'] == 'A'].sort_values('value', ascending=False, kind='mergesort').reset_index(drop=True)
    pd.testing.assert_frame_equal(result_df, expected_df)

# Test cases for the run_describe function
def test_run_describe():
    """
    Tests the run_describe function.
    """
    data = {'numeric': [1, 2, 3, 4, 5], 'text': ['A', 'B', 'C', 'D', 'E']}
    df = pd.DataFrame(data)
    result_df = analysis_toolkit.run_describe(df)
    
    # Expected output is the transposed description of numeric columns
    expected_df = df.select_dtypes(include=["number"]).describe().transpose()
    expected_df = expected_df.reset_index().rename(columns={"index": "column"})
    pd.testing.assert_frame_equal(result_df, expected_df)