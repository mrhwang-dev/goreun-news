import pytest
from fetch_community import _parse_ruliweb, _parse_theqoo

def test_parse_ruliweb():
    html = '''
    <tr>
        <td>
            <a class="subject_link" href="/best/123">테스트 루리웹</a>
        </td>
        <td class="recomd">10</td>
        <td class="hit">100</td>
    </tr>
    '''
    res = _parse_ruliweb(html)
    assert len(res) == 1
    assert res[0]["title"] == "테스트 루리웹"
    assert res[0]["link"] == "https://bbs.ruliweb.com/best/123"
    assert res[0]["recommends"] == 10
    assert res[0]["views"] == 100

def test_parse_theqoo():
    html = '''
    <tr>
        <td>
            <a href="/hot/456">테스트 더쿠</a>
        </td>
        <td class="m_no">200</td>
    </tr>
    '''
    res = _parse_theqoo(html)
    assert len(res) == 1
    assert res[0]["title"] == "테스트 더쿠"
    assert res[0]["link"] == "https://theqoo.net/hot/456"
    assert res[0]["views"] == 200
