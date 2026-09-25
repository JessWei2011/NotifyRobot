import unittest
from unittest.mock import patch, MagicMock
import discord
from src.stockcenter_client import fetch_stockcenter_tags, build_stockcenter_tags_embed


class TestStockCenterClient(unittest.TestCase):
    @patch("requests.post")
    def test_fetch_stockcenter_tags_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "code": "2330",
            "name": "台積電",
            "market": "TW",
            "category": "半導體",
            "date": "09/24",
            "price": 2475.0,
            "change": 25.0,
            "change_pct": 1.02,
            "volume_lots": 15000,
            "tags": {
                "kline": ["🚀 均線多頭排列 (強勢多方)"],
                "volume": ["🔥 爆量攻擊長紅"],
                "kd": ["📈 KD 多方強勢推進"],
                "macd": ["📈 MACD 多頭推升"],
                "rsi": ["RSI(14): 65.0 強勢"],
                "chips": ["🔥 土洋同步大買"],
            },
        }
        mock_post.return_value = mock_resp

        data = fetch_stockcenter_tags("2330", force=True)
        self.assertTrue(data["ok"])
        self.assertEqual(data["code"], "2330")

        embed = build_stockcenter_tags_embed("2330")
        self.assertIsInstance(embed, discord.Embed)
        self.assertIn("台積電", embed.title)
        self.assertEqual(len(embed.fields), 6)

    @patch("requests.post")
    def test_fetch_stockcenter_tags_connection_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        data = fetch_stockcenter_tags("2330", force=True)
        self.assertFalse(data["ok"])
        self.assertIn("無法連線至 StockCenter", data["error"])

        embed = build_stockcenter_tags_embed("2330")
        self.assertIsInstance(embed, discord.Embed)
        self.assertIn("連線異常", embed.footer.text)

    @patch("src.stockcenter_client.fetch_stockcenter_tags")
    @patch("src.stock_query.build_full_stock_watchlist_report")
    def test_build_integrated_stock_embed_success(self, mock_report, mock_tags):
        from src.stockcenter_client import build_integrated_stock_embed
        mock_tags.return_value = {
            "ok": True,
            "code": "2330",
            "name": "台積電",
            "market": "TW",
            "tags": {
                "kline": ["🚀 均線多頭排列"],
                "volume": ["📉 縮量整理"],
                "kd": ["📈 KD 金叉"],
                "macd": ["📈 MACD 紅柱"],
                "rsi": ["RSI: 60"],
                "chips": ["🔥 外資大買"],
            },
        }
        mock_report.return_value = {
            "text": "📊 【自選股盤後籌碼報告】2330 台積電...",
            "color": 0x10B981,
            "name": "台積電",
            "market_sector": "上市・半導體",
        }

        embed = build_integrated_stock_embed("2330")
        self.assertIsNotNone(embed)
        self.assertIn("自選股盤後籌碼報告", embed.description)
        self.assertEqual(len(embed.fields), 6)
        self.assertIn("聯合全方位量化分析報告", embed.footer.text)


if __name__ == "__main__":
    unittest.main()
