import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch
import summarize


class TestSummarizeIndexing(unittest.TestCase):
    @patch("summarize._save_cache")
    @patch("summarize._load_cache")
    @patch("summarize.call_with_fallback")
    def test_label_clusters_sparse_indexing(self, mock_llm, mock_load_cache, mock_save_cache):
        clusters = [[{"title": f"기사 제목 {i}", "outlet": "언론사", "link": f"http://a.com/{i}", "ts": None}] for i in range(10)]
        
        # Populate cache for all indices EXCEPT 3 and 7
        clusters_cache = {}
        for i in range(10):
            if i not in (3, 7):
                key = summarize._stable_cluster_key(clusters[i])
                clusters_cache[key] = {"keep": True, "label": f"캐시 라벨 {i}", "summary": f"캐시 요약 {i}", "category": "사회", "t": 100}

        mock_load_cache.return_value = {"clusters": clusters_cache, "refined": {}, "policy": {}}

        # Simulate LLM returning 0-indexed response for the 2 items requested: id 0 (sub_idx 0 -> to_ask[0]=3), id 1 (sub_idx 1 -> to_ask[1]=7)
        mock_llm.return_value = (
            {
                "clusters": [
                    {"id": 0, "keep": True, "label": "신규 라벨 3", "summary": "신규 요약 3", "category": "정치"},
                    {"id": 1, "keep": True, "label": "신규 라벨 7", "summary": "신규 요약 7", "category": "경제"},
                ]
            },
            "gemini",
        )

        results = summarize.label_clusters(clusters)
        
        # Verify indices 3 and 7 were correctly populated despite LLM returning 0-indexed items
        self.assertIn(3, results)
        self.assertIn(7, results)
        self.assertEqual(results[3]["label"], "신규 라벨 3")
        self.assertEqual(results[7]["label"], "신규 라벨 7")


if __name__ == "__main__":
    unittest.main()
