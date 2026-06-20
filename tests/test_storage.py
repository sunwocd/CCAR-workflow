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


if __name__ == "__main__":
    unittest.main()
