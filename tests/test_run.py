import pytest
from datetime import datetime, timedelta, timezone
from run import detect_breaking, BREAKING_MAX_AGE_HOURS, BREAKING_MAX

def test_detect_breaking():
    now = datetime.now(timezone.utc)
    
    items = [
        {"title": "[속보] 테스트1", "ts": now, "outlet": "A", "link": "1"},
        {"title": "[1보] 테스트2", "ts": now - timedelta(hours=1), "outlet": "B", "link": "2"},
        {"title": "[긴급] 테스트3", "ts": now - timedelta(hours=2), "outlet": "C", "link": "3"},
        {"title": "일반 기사", "ts": now, "outlet": "D", "link": "4"},
        {"title": "[속보] 너무 오래된 기사", "ts": now - timedelta(hours=4), "outlet": "E", "link": "5"},
        {"title": "[속보] 최신", "ts": now + timedelta(minutes=10), "outlet": "F", "link": "6"},
    ]
    
    # Add more to test BREAKING_MAX
    for i in range(15):
        items.append({
            "title": f"[속보] 루프 {i}", 
            "ts": now - timedelta(minutes=i), 
            "outlet": "X", 
            "link": f"x{i}"
        })
        
    result = detect_breaking(items)
    
    # Max count
    assert len(result) == BREAKING_MAX
    
    # Check old item is excluded
    assert not any(r["link"] == "5" for r in result)
    
    # Check normal item is excluded
    assert not any(r["link"] == "4" for r in result)
    
    # Check sorted by time (newest first)
    # The newest is '6'
    assert result[0]["link"] == "6"
    
    # Format check
    assert "time" in result[0]
    assert "outlet" in result[0]
    assert "title" in result[0]
    assert "link" in result[0]
