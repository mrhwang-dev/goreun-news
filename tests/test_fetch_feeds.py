import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock, patch
import fetch_feeds


class TestFetchFeeds(unittest.TestCase):
    def test_parse_ts_formats(self):
        # RFC822 format
        dt1 = fetch_feeds._parse_ts("Wed, 22 Jul 2026 08:00:00 GMT")
        self.assertIsNotNone(dt1)
        self.assertEqual(dt1.year, 2026)

        # ISO8601 format
        dt2 = fetch_feeds._parse_ts("2026-07-22T08:00:00Z")
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.year, 2026)

        # Invalid format
        self.assertIsNone(fetch_feeds._parse_ts("invalid date"))

    @patch("urllib.request.urlopen")
    def test_fetch_xml_euc_kr_normalization(self, mock_urlopen):
        euc_kr_xml = '<?xml version="1.0" encoding="EUC-KR"?><rss><channel><item><title>테스트</title></item></channel></rss>'.encode("euc-kr")
        
        mock_response = MagicMock()
        mock_response.read.return_value = euc_kr_xml
        mock_response.headers.get.return_value = "text/xml; charset=euc-kr"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        xml_str = fetch_feeds._fetch_xml("http://example.com/rss")
        self.assertIn('encoding="utf-8"', xml_str)
        self.assertIn("테스트", xml_str)


if __name__ == "__main__":
    unittest.main()
