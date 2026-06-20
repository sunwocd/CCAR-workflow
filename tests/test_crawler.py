import unittest

from src.crawler import CaacCrawler, _looks_like_waf_block


class SearchUrlTests(unittest.TestCase):
    def setUp(self):
        self.crawler = CaacCrawler()

    def test_regulation_uses_official_regulation_channel(self):
        url = self.crawler._build_search_url("13", 200, "-fabuDate")

        self.assertIn("page=1", url)
        self.assertIn("channelid=269689", url)
        self.assertIn("perpage=200", url)
        self.assertIn("orderby=-fabuDate", url)
        self.assertNotIn("was_custom_expr", url)
        self.assertNotIn("fl=13", url)

    def test_normative_uses_official_normative_channel_with_fl(self):
        url = self.crawler._build_search_url("14", 50, "-DOCRELTIME")

        self.assertIn("page=1", url)
        self.assertIn("channelid=238066", url)
        self.assertIn("perpage=50", url)
        self.assertIn("orderby=-DOCRELTIME", url)
        self.assertIn("fl=14", url)
        self.assertNotIn("was_custom_expr", url)

    def test_default_category_uses_public_topic_channel_with_fl(self):
        url = self.crawler._build_search_url("9", 10, "-fabuDate")

        self.assertIn("page=1", url)
        self.assertIn("channelid=211383", url)
        self.assertIn("perpage=10", url)
        self.assertIn("orderby=-fabuDate", url)
        self.assertIn("fl=9", url)
        self.assertNotIn("was_custom_expr", url)


class WafDetectionTests(unittest.TestCase):
    def test_detects_caac_cloud_protection_page(self):
        html = """
        <html>
          <head><title>502 Bad Gateway</title></head>
          <body>
            <p>您的IP: 62.243.189.100</p>
            <p>网站访问者 云防护节点 源站服务器</p>
            <p>Event ID: abcdef.waf</p>
          </body>
        </html>
        """

        self.assertTrue(_looks_like_waf_block(html))

    def test_normal_search_page_is_not_waf_block(self):
        html = """
        <html>
          <body>
            <table class="t_table">
              <tr><td><a href="/XXGK/XXGK/MHGZ/202606/t20260618.html">公共航空运输企业经营许可规定</a></td></tr>
            </table>
          </body>
        </html>
        """

        self.assertFalse(_looks_like_waf_block(html))


if __name__ == "__main__":
    unittest.main()
