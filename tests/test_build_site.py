import pytest
from build_site import _esc, _render_ticker, _tab, _render_bias_bar, _favicon

def test_esc():
    assert _esc('a & b < c > d " e \' f') == 'a &amp; b &lt; c &gt; d &quot; e &#x27; f'

def test_render_ticker():
    breaking = [{"time": "12:00", "title": "Test Title", "outlet": "Test Outlet", "link": "http://test.com"}]
    html = _render_ticker(breaking)
    assert 'href="http://test.com"' in html
    assert 'Test Title' in html
    assert 'Test Outlet' in html
    
    html_empty = _render_ticker([])
    assert html_empty == ""

def test_tab():
    html = _tab("Test Tab", 5, "cat", "test_val", True, "dot_test")
    assert 'aria-selected="true"' in html
    assert 'data-filter="cat"' in html
    assert 'data-value="test_val"' in html
    assert 'Test Tab' in html
    assert '5' in html

def test_render_bias_bar():
    bias = {"progressive": 2, "moderate": 1, "conservative": 3}
    html = _render_bias_bar(bias)
    assert 'bg-blue-500' in html # progressive
    assert 'bg-neutral-400' in html # moderate
    assert 'bg-red-500' in html # conservative
    assert 'width:33.3%' in html
    assert 'width:16.7%' in html
    assert 'width:50.0%' in html
    
    html_empty = _render_bias_bar(None)
    assert html_empty == ""

def test_favicon():
    url = "https://example.com/test"
    fav = _favicon(url)
    assert "www.google.com/s2/favicons" in fav
    assert "domain=example.com" in fav
