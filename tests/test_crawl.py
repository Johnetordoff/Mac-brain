import tempfile
import unittest
from pathlib import Path

from macbrain import db
from macbrain.crawl import crawl_step


class FilesystemCrawlTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="macbrain-crawl-"))
        for i in range(75):
            (self.root / f"d{i:03d}").mkdir()
        big = self.root / "d074" / "large.bin"
        big.write_bytes(b"x" * (1024 * 1024))
        db.reset_filesystem_crawl([str(self.root)])

    def test_crawl_resumes_wide_directory(self):
        first = crawl_step(
            roots=[self.root],
            max_directories=1,
            max_entries_per_directory=50,
            min_large_mb=1,
        )
        self.assertFalse(first["complete"])
        self.assertEqual(first["directories_scanned"], 1)
        self.assertGreater(first["frontier_directories"], 0)

        second = crawl_step(
            roots=[self.root],
            max_directories=1,
            max_entries_per_directory=50,
            min_large_mb=1,
        )
        self.assertFalse(second["complete"])

        final = crawl_step(
            roots=[self.root],
            max_directories=100,
            max_entries_per_directory=50,
            min_large_mb=1,
        )
        self.assertTrue(final["complete"])
        paths = {row["path"] for row in final["largest_files"]}
        self.assertIn(str(self.root / "d074" / "large.bin"), paths)

    def test_crawl_is_read_only(self):
        marker = self.root / "d001" / "keep.txt"
        marker.write_text("keep")
        small = self.root / "d002" / "small.txt"
        small.write_text("abc")
        crawl_step(
            roots=[self.root],
            max_directories=100,
            max_entries_per_directory=200,
            min_large_mb=1,
        )
        crawl_step(
            roots=[self.root],
            max_directories=100,
            max_entries_per_directory=200,
            min_large_mb=1,
        )
        self.assertEqual(marker.read_text(), "keep")
        item = db.get_filesystem_inventory(str(small))
        self.assertIsNotNone(item)
        self.assertEqual(item["bytes"], 3)
        self.assertEqual(item["necessity_state"], "unknown")

    def test_classification_survives_normal_recrawl(self):
        target = self.root / "d003" / "candidate.bin"
        target.write_bytes(b"x" * 17)
        crawl_step(
            roots=[self.root],
            max_directories=100,
            max_entries_per_directory=200,
            min_large_mb=1,
        )
        crawl_step(
            roots=[self.root],
            max_directories=100,
            max_entries_per_directory=200,
            min_large_mb=1,
        )
        db.classify_filesystem_path(
            str(target),
            "probably_unnecessary",
            "Human review marked this as a cleanup candidate.",
        )
        target.write_bytes(b"x" * 23)
        db.enqueue_filesystem_paths([(str(target.parent), 1)])
        crawl_step(
            roots=[self.root],
            max_directories=1,
            max_entries_per_directory=200,
            min_large_mb=1,
        )
        item = db.get_filesystem_inventory(str(target))
        self.assertEqual(item["bytes"], 23)
        self.assertEqual(item["necessity_state"], "probably_unnecessary")
        self.assertIn("Human review", item["necessity_evidence"])


if __name__ == "__main__":
    unittest.main()
