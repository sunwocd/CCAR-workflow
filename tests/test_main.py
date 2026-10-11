import unittest
from unittest import mock

from src import main as src_main
from src.crawler import Document
from src.main import (
    _filter_documents_by_category,
    _find_missing_r2_urls,
    _parse_category_filter,
    _select_download_documents,
    _select_notify_attachments,
)
from src.storage import ChangeResult, StorageState


def make_doc(url: str, category_id: str = "13") -> Document:
    return Document(
        title=f"Doc {url}",
        url=url,
        category="民航规章",
        category_id=category_id,
        doc_number="",
        office_unit="",
    )


class DownloadSelectionTests(unittest.TestCase):
    def test_updated_documents_are_skipped_by_default(self):
        new_doc = make_doc("https://example.test/new")
        updated_doc = make_doc("https://example.test/updated")

        selected = _select_download_documents(
            {"13": [new_doc]},
            {"13": [updated_doc]},
        )

        self.assertEqual({"13": [new_doc]}, selected)

    def test_updated_documents_can_be_included_explicitly(self):
        new_doc = make_doc("https://example.test/new")
        updated_doc = make_doc("https://example.test/updated")

        selected = _select_download_documents(
            {"13": [new_doc]},
            {"13": [updated_doc]},
            include_updated=True,
        )

        self.assertEqual({"13": [new_doc, updated_doc]}, selected)


class R2UrlValidationTests(unittest.TestCase):
    def test_reports_downloaded_pdf_urls_missing_from_r2_map(self):
        missing = _find_missing_r2_urls(
            {
                "https://example.test/has-url",
                "https://example.test/missing-url",
            },
            {
                "https://example.test/has-url": "https://files.example.test/doc.pdf",
            },
        )

        self.assertEqual(["https://example.test/missing-url"], missing)


class NotifyCategoryFilterTests(unittest.TestCase):
    def test_parse_category_filter_ignores_blank_items(self):
        self.assertEqual({"13", "14", "15"}, _parse_category_filter(" 13,14 , 15 , "))

    def test_parse_category_filter_empty_means_no_filter(self):
        self.assertEqual(set(), _parse_category_filter(None))
        self.assertEqual(set(), _parse_category_filter(""))

    def test_filter_keeps_only_selected_categories(self):
        documents = {
            "9": [make_doc("https://example.test/notice", "9")],
            "13": [make_doc("https://example.test/ccar", "13")],
            "15": [make_doc("https://example.test/standard", "15")],
        }

        filtered = _filter_documents_by_category(documents, {"13", "15"})

        self.assertEqual(["13", "15"], sorted(filtered))
        self.assertEqual(documents["13"], filtered["13"])

    def test_empty_filter_keeps_every_category(self):
        documents = {
            "9": [make_doc("https://example.test/notice", "9")],
            "13": [make_doc("https://example.test/ccar", "13")],
        }

        self.assertEqual(documents, _filter_documents_by_category(documents, set()))

    def test_filter_without_matches_returns_empty_mapping(self):
        documents = {"9": [make_doc("https://example.test/notice", "9")]}

        self.assertEqual({}, _filter_documents_by_category(documents, {"13", "14", "15"}))

    def test_attachments_without_filter_keep_everything(self):
        by_category = {
            "9": ["downloads/other/notice.pdf"],
            "13": ["downloads/regulation/ccar.pdf"],
        }

        selected = _select_notify_attachments(
            ["downloads/other/notice.pdf", "downloads/regulation/ccar.pdf"],
            by_category,
            set(),
        )

        self.assertEqual(
            ["downloads/other/notice.pdf", "downloads/regulation/ccar.pdf"], selected
        )

    def test_attachments_are_limited_to_notified_categories(self):
        selected = _select_notify_attachments(
            [
                "downloads/other/notice.pdf",
                "downloads/regulation/ccar.pdf",
                "downloads/specification/standard.pdf",
            ],
            {
                "9": ["downloads/other/notice.pdf"],
                "13": ["downloads/regulation/ccar.pdf"],
                "15": ["downloads/specification/standard.pdf"],
            },
            {"13", "14", "15"},
        )

        self.assertEqual(
            ["downloads/regulation/ccar.pdf", "downloads/specification/standard.pdf"],
            selected,
        )


class _FakeStorage:
    """Storage stub: one known doc per crawled category, no download index."""

    def __init__(self, path):
        self.data_path = path
        self.updated_state = None

    def load(self):
        state = StorageState()
        state.documents = {
            cat: [make_doc(f"https://example.test/{cat}/known", cat)]
            for cat in ("9", "13", "15")
        }
        return state

    def detect_changes(self, current_documents):
        return ChangeResult(new_documents=self.new_documents)

    def load_download_index(self):
        return {}

    def save_download_index(self, index):
        pass

    def sync_js_files(self, documents, js_dir, r2_url_map=None):
        return {}

    def update_state(self, documents):
        self.updated_state = documents


class _FakeCrawler:
    def __init__(self, storage):
        self.storage = storage

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetch_all_categories(self, category_ids, perpage):
        return {cat: list(docs) for cat, docs in self.storage.new_documents.items()}

    def download_document_file(self, doc, save_base_path):
        return f"{save_base_path}.pdf"


class _FakeNotifier:
    sent = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def format_update_message(self, docs_by_category):
        self.sent = {"categories": sorted(docs_by_category), "attachments": []}
        return ("title", "text", "html")

    def send_all(self, title, text, html, attachments=None):
        self.sent["attachments"] = attachments or []
        return {"Email": True}


class _FakeR2:
    enabled = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class NotifyCategoryFlowTests(unittest.TestCase):
    """Run main() with stubbed collaborators to check the end-to-end filtering."""

    def _run(self, new_documents, argv):
        storage = _FakeStorage("data/regulations.json")
        storage.new_documents = new_documents
        notifier = _FakeNotifier()
        notifier.sent = None

        with mock.patch.object(src_main, "Storage", return_value=storage), \
             mock.patch.object(src_main, "CaacCrawler", lambda: _FakeCrawler(storage)), \
             mock.patch.object(src_main, "Notifier", lambda: notifier), \
             mock.patch.object(src_main, "R2Uploader", lambda: _FakeR2()), \
             mock.patch("sys.argv", ["main", *argv, "--notify", "1"]), \
             mock.patch.dict("os.environ", {"NOTIFY_CATEGORIES": ""}):
            exit_code = src_main.main()

        self.assertEqual(0, exit_code)
        return notifier.sent, storage.updated_state

    def test_notification_is_limited_to_selected_categories(self):
        new_documents = {
            "9": [make_doc("https://example.test/9/notice", "9")],
            "13": [make_doc("https://example.test/13/ccar", "13")],
            "15": [make_doc("https://example.test/15/standard", "15")],
        }

        sent, updated_state = self._run(new_documents, ["--notify-categories", "13,14,15"])

        self.assertEqual(["标准规范", "民航规章"], sent["categories"])
        self.assertEqual(2, len(sent["attachments"]))
        self.assertTrue(all("notice" not in path for path in sent["attachments"]))
        # Crawling/state must stay complete even though only 13/15 were emailed.
        self.assertEqual(["13", "15", "9"], sorted(updated_state))

    def test_stays_quiet_when_only_other_categories_changed(self):
        sent, updated_state = self._run(
            {"9": [make_doc("https://example.test/9/notice", "9")]},
            ["--notify-categories", "13,14,15"],
        )

        self.assertIsNone(sent)
        self.assertEqual(["9"], sorted(updated_state))

    def test_without_filter_every_category_is_notified(self):
        new_documents = {
            "9": [make_doc("https://example.test/9/notice", "9")],
            "13": [make_doc("https://example.test/13/ccar", "13")],
        }

        sent, _ = self._run(new_documents, [])

        self.assertEqual(["民航规章", "通知公告"], sent["categories"])


if __name__ == "__main__":
    unittest.main()
