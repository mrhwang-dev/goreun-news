import pytest
from llm import _extract_json, _is_retryable

def test_extract_json():
    text1 = '```json\n{"key": "value"}\n```'
    assert _extract_json(text1) == {"key": "value"}
    
    text2 = 'Some text\n{"a": 1, "b": {"c": 2}}\nMore text'
    assert _extract_json(text2) == {"a": 1, "b": {"c": 2}}

def test_is_retryable():
    assert _is_retryable(Exception("429 Too Many Requests")) == True
    assert _is_retryable(Exception("rate limit exceeded")) == True
    assert _is_retryable(Exception("timeout")) == True
    
    assert _is_retryable(Exception("404 not found")) == False
    assert _is_retryable(Exception("API key not valid")) == False
