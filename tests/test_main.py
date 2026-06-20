import unittest

from src.crawler import Document
from src.main import _select_download_documents


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


if __name__ == "__main__":
    unittest.main()
