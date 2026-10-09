import unittest
import reader

class OutcomeBlocks(unittest.TestCase):
    def test_native_text_blocks_retain_checks_only(self):
        blocks = [{"type": "input_text", "text": "source dump\n294 passed in 8.4s\nProcess exited with code 0"}, {"type": "image", "data": "not text"}]
        self.assertEqual(reader._compact_outcome(blocks), "294 passed in 8.4s\nProcess exited with code 0")

    def test_nested_json_output(self):
        self.assertEqual(reader._compact_outcome('{"content":[{"text":"All checks passed!"}]}'), "All checks passed!")

    def test_repeated_desktop_cursor_is_partial(self):
        pages = [{"thread":{"id":"t"},"page":{"hasMore":True,"nextCursor":"c"},"turns":[]},
                 {"thread":{"id":"t"},"page":{"cursor":"c","hasMore":True,"nextCursor":"c"},"turns":[]}]
        result=reader.desktop_pages(pages,"2026-10-08","Asia/Shanghai")
        self.assertEqual(result["coverage"][0]["status"],"partial")
        self.assertIn("repeated next-page cursor",result["coverage"][0]["notes"])
