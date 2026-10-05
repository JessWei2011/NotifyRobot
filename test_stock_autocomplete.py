import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.stock_query import resolver, StockResolver
from src.bot_service import stock_autocomplete, _resolve_command_code


class TestStockAutocompleteAndResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resolver.refresh_if_needed()

    def test_exact_code_resolution(self):
        res = resolver.resolve_symbol_or_candidates("2330")
        self.assertEqual(res["status"], "exact")
        self.assertEqual(res["code"], "2330")
        self.assertEqual(res["name"], "台積電")

    def test_exact_name_resolution(self):
        res = resolver.resolve_symbol_or_candidates("台積電")
        self.assertEqual(res["status"], "exact")
        self.assertEqual(res["code"], "2330")
        self.assertEqual(res["name"], "台積電")

    def test_single_fuzzy_match(self):
        # 「台積」在上市櫃僅有台積電
        res = resolver.resolve_symbol_or_candidates("台積")
        self.assertEqual(res["status"], "exact")
        self.assertEqual(res["code"], "2330")
        self.assertEqual(res["name"], "台積電")

    def test_ambiguous_fuzzy_match(self):
        # 「富」會匹配到富邦金、富喬、富邦媒等多檔
        res = resolver.resolve_symbol_or_candidates("富")
        self.assertEqual(res["status"], "ambiguous")
        self.assertTrue(len(res["candidates"]) > 1)
        names = [c["name"] for c in res["candidates"]]
        self.assertTrue(any("富" in n for n in names))

    def test_not_found(self):
        res = resolver.resolve_symbol_or_candidates("無此股票九九九")
        self.assertEqual(res["status"], "not_found")
        self.assertEqual(res["candidates"], [])

    def test_search_stocks_limit_and_popular(self):
        # 空字串預設推薦熱門股
        empty_matches = resolver.search_stocks("", limit=10)
        self.assertTrue(len(empty_matches) <= 10)
        codes = [m["code"] for m in empty_matches]
        self.assertIn("2330", codes)

        # 搜尋 "23" 前綴
        matches_23 = resolver.search_stocks("23", limit=25)
        self.assertTrue(len(matches_23) <= 25)
        self.assertTrue(all("23" in m["code"] or "23" in m["name"] for m in matches_23))

    def test_stock_autocomplete_async(self):
        async def _test():
            interaction = MagicMock()
            choices = await stock_autocomplete(interaction, "台積")
            self.assertTrue(len(choices) >= 1)
            self.assertEqual(choices[0].name, "2330 台積電")
            self.assertEqual(choices[0].value, "2330")

            empty_choices = await stock_autocomplete(interaction, "")
            self.assertTrue(1 <= len(empty_choices) <= 25)

        asyncio.run(_test())

    def test_resolve_command_code_exact(self):
        async def _test():
            interaction = MagicMock()
            interaction.response = MagicMock()
            interaction.response.send_message = AsyncMock()

            # 1. 傳入純代號
            code = await _resolve_command_code(interaction, "2330")
            self.assertEqual(code, "2330")
            interaction.response.send_message.assert_not_called()

            # 2. 傳入股名
            code_tsmc = await _resolve_command_code(interaction, "台積電")
            self.assertEqual(code_tsmc, "2330")
            interaction.response.send_message.assert_not_called()

        asyncio.run(_test())

    def test_resolve_command_code_ambiguous(self):
        async def _test():
            interaction = MagicMock()
            interaction.response = MagicMock()
            interaction.response.send_message = AsyncMock()

            code = await _resolve_command_code(interaction, "富")
            self.assertIsNone(code)
            interaction.response.send_message.assert_called_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertTrue(kwargs.get("ephemeral"))
            self.assertIn("找不到完全相符的股票「富」", args[0])
            self.assertIn("您是不是要找", args[0])

        asyncio.run(_test())

    def test_resolve_command_code_not_found(self):
        async def _test():
            interaction = MagicMock()
            interaction.response = MagicMock()
            interaction.response.send_message = AsyncMock()

            code = await _resolve_command_code(interaction, "不存在股票XYZ")
            self.assertIsNone(code)
            interaction.response.send_message.assert_called_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertTrue(kwargs.get("ephemeral"))
            self.assertIn("查無此股票代號或名稱", args[0])

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
