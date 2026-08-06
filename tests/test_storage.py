import json
import tempfile
import unittest
from pathlib import Path

from src.crawler import Document
from src.storage import Storage, StorageState


def make_doc(url: str, title: str) -> Document:
    return Document(
        title=title,
        url=url,
        category="民航规章",
        category_id="13",
        doc_number="",
        office_unit="",
    )


class StorageUpdateStateTests(unittest.TestCase):
    def test_update_state_keeps_previous_docs_missing_from_partial_current_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "regulations.json"
            storage = Storage(str(data_path))
            storage.save(StorageState(
                last_check="2026-06-19T00:00:00",
                documents={
                    "13": [
                        make_doc("https://example.test/kept", "Old title").to_dict(),
                        make_doc("https://example.test/missing-this-run", "Historical").to_dict(),
                    ],
                },
            ))

            storage.update_state({
                "13": [
                    make_doc("https://example.test/kept", "Updated title"),
                ],
            })

            reloaded = Storage(str(data_path)).load()
            docs = reloaded.documents["13"]

            self.assertEqual(
                ["https://example.test/kept", "https://example.test/missing-this-run"],
                [doc["url"] for doc in docs],
            )
            self.assertEqual("Updated title", docs[0]["title"])
            self.assertEqual("Historical", docs[1]["title"])


class StoragePdfUrlPreservationTests(unittest.TestCase):
    def test_update_state_preserves_pdf_url_for_seen_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "regulations.json"
            storage = Storage(str(data_path))
            prev_doc = make_doc("https://example.test/kept", "Old title").to_dict()
            prev_doc["pdf_url"] = "https://flighttoolbox.hudawang.cn/regulation/CCAR-1.pdf"
            storage.save(StorageState(
                last_check="2026-06-19T00:00:00",
                documents={"13": [prev_doc]},
            ))

            storage.update_state({"13": [make_doc("https://example.test/kept", "Updated title")]})

            reloaded = Storage(str(data_path)).load()
            doc = reloaded.documents["13"][0]
            self.assertEqual("Updated title", doc["title"])
            self.assertEqual(
                "https://flighttoolbox.hudawang.cn/regulation/CCAR-1.pdf",
                doc["pdf_url"],
            )

    def test_build_pdf_url_fallback_matches_downloads_and_r2_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "regulations.json"
            (Path(tmp) / "downloads.json").write_text(
                json.dumps({"records": {
                    "http://www.caac.gov.cn/a.html": {"relative_path": "regulation/CCAR-91-R4一般运行和飞行规则.pdf"},
                }}),
                encoding="utf-8",
            )
            (Path(tmp) / "r2_uploads.json").write_text(
                json.dumps({"records": {
                    "regulation/CCAR-91-R4一般运行和飞行规则.pdf": {
                        "r2_url": "https://flighttoolbox.hudawang.cn/regulation/CCAR-91-R4一般运行和飞行规则.pdf",
                    },
                    "normative/失效!AC-66-R1民用航空器维修人员执照.pdf": {
                        "r2_url": "https://flighttoolbox.hudawang.cn/normative/失效!AC-66-R1民用航空器维修人员执照.pdf",
                    },
                }}),
                encoding="utf-8",
            )

            from src.storage import build_pdf_url_fallback

            by_url, by_filename = build_pdf_url_fallback(str(data_path))

            self.assertEqual(
                "https://flighttoolbox.hudawang.cn/regulation/CCAR-91-R4一般运行和飞行规则.pdf",
                by_url["http://www.caac.gov.cn/a.html"],
            )
            self.assertIn("AC-66-R1民用航空器维修人员执照", by_filename)
            self.assertEqual(
                "https://flighttoolbox.hudawang.cn/normative/失效!AC-66-R1民用航空器维修人员执照.pdf",
                by_filename["AC-66-R1民用航空器维修人员执照"],
            )

    def test_read_js_data_accepts_named_export_variable(self):
        from src.storage import _read_js_data

        with tempfile.TemporaryDirectory() as tmp:
            js_path = Path(tmp) / "regulation.js"
            js_path.write_text(
                "var regulationData = [\n"
                '  {"title": "A", "url": "http://example.test/a", "pdf_url": "https://flighttoolbox.hudawang.cn/a.pdf"}\n'
                "];\n",
                encoding="utf-8",
            )
            parsed = _read_js_data(js_path)
            self.assertEqual(1, len(parsed))
            self.assertEqual("https://flighttoolbox.hudawang.cn/a.pdf", parsed[0]["pdf_url"])


if __name__ == "__main__":
    unittest.main()
