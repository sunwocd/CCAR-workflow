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


def make_spec_doc(url: str, doc_number: str, title: str, publish_date: str) -> Document:
    return Document(
        title=title,
        url=url,
        category="标准规范",
        category_id="15",
        doc_number=doc_number,
        office_unit="航空器适航审定司",
        sign_date=publish_date,
        publish_date=publish_date,
    )


class DetectChangesRepostTests(unittest.TestCase):
    """CAAC re-publishes documents under new URLs; re-posts must not be new."""

    KNOWN_URL = "http://www.caac.gov.cn/a/t20260916_1.html"
    KNOWN_TITLE = "小型、中型民用无人驾驶航空器操控员训练要求"

    def _storage(self, tmp: str) -> Storage:
        storage = Storage(str(Path(tmp) / "regulations.json"))
        storage.save(StorageState(
            last_check="2026-09-16T00:00:00",
            documents={
                "15": [
                    make_spec_doc(
                        self.KNOWN_URL, "MH/T 2021-2026",
                        self.KNOWN_TITLE, "2026-08-04",
                    ).to_dict(),
                ],
            },
        ))
        return storage

    def test_same_doc_number_new_url_is_reposted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            repost = make_spec_doc(
                "http://www.caac.gov.cn/a/t20260930_2.html",
                "MH/T 2021-2026", self.KNOWN_TITLE, "2026-08-04",
            )
            changes = storage.detect_changes({"15": [repost]})
            self.assertEqual(0, changes.new_count)
            self.assertEqual(1, changes.reposted_count)

    def test_typo_doc_number_same_title_and_date_is_reposted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            repost = make_spec_doc(
                "http://www.caac.gov.cn/a/t20260930_2.html",
                "MH/T 1021-2026", self.KNOWN_TITLE, "2026-08-04",
            )
            changes = storage.detect_changes({"15": [repost]})
            self.assertEqual(0, changes.new_count)
            self.assertEqual(1, changes.reposted_count)

    def test_same_title_different_date_is_new(self):
        """A revised standard keeps its title but gets a new date — still new."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            revision = make_spec_doc(
                "http://www.caac.gov.cn/a/t20271001_3.html",
                "MH/T 2021-2027", self.KNOWN_TITLE, "2027-08-04",
            )
            changes = storage.detect_changes({"15": [revision]})
            self.assertEqual(1, changes.new_count)
            self.assertEqual(0, changes.reposted_count)

    def test_title_whitespace_variation_still_reposted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            repost = make_spec_doc(
                "http://www.caac.gov.cn/a/t20260930_2.html",
                "MH/T 1087-2026",
                "小型、中型民用无人驾驶航空器操控员训练要求 ",
                "2026-08-04",
            )
            changes = storage.detect_changes({"15": [repost]})
            self.assertEqual(1, changes.reposted_count)

    def test_unrelated_new_url_is_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            novel = make_spec_doc(
                "http://www.caac.gov.cn/a/t20260930_9.html",
                "MH/T 5093-2026", "民航相干多普勒测风激光雷达建设规范", "2026-09-01",
            )
            changes = storage.detect_changes({"15": [novel]})
            self.assertEqual(1, changes.new_count)
            self.assertEqual(0, changes.reposted_count)


if __name__ == "__main__":
    unittest.main()
