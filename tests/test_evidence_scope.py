import unittest
from pathlib import Path

from core.doc_parser import DealRoomParser, iter_evidence_nodes
from core.evidence_scope import (
    build_evidence_inventory,
    evidence_scope_for_anchors,
    evidence_scope_for_citations,
)
from scripts.query_deal_room import query


class EvidenceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path("deal_rooms/sample_ma_acquisition").resolve()
        cls.documents = DealRoomParser().parse_deal_room_folder(str(cls.folder))
        cls.inventory = build_evidence_inventory(
            cls.documents,
            source_snapshot_sha256="a" * 64,
        )
        cls.passage = query(cls.folder, "EBITDA debt leverage", limit=1)[0]

    def test_scope_is_recomputed_from_current_parser_inventory(self):
        scope = evidence_scope_for_anchors(self.inventory, [{
            "citation": self.passage["citation"],
            "source_sha256": self.passage["source_sha256"],
            "requested_parts": [],
        }])
        self.assertIsNotNone(scope)
        self.assertEqual(scope["admitted_passage_count"], 1)
        self.assertEqual(scope["corpus_document_count"], len(self.documents))
        self.assertGreaterEqual(
            scope["corpus_parsed_node_count"], scope["corpus_searchable_node_count"],
        )
        self.assertFalse(scope["semantic_coverage_measured"])
        self.assertFalse(scope["full_document_review_claimed"])

    def test_wrong_source_hash_or_missing_anchor_cannot_restore_scope(self):
        self.assertIsNone(evidence_scope_for_anchors(self.inventory, [{
            "citation": self.passage["citation"],
            "source_sha256": "0" * 64,
            "requested_parts": [],
        }]))
        self.assertIsNone(evidence_scope_for_citations(
            self.inventory, ["[missing.txt#node:missing]"],
        ))

    def test_inventory_digest_changes_when_current_parser_text_changes(self):
        original = self.inventory["inventory_sha256"]
        document = self.documents[0]
        first_node = next(
            node for node, _titles in iter_evidence_nodes(document.root_node)
            if isinstance(node.content, str) and node.content
        )
        old_content = first_node.content
        try:
            first_node.content = old_content + " changed"
            changed = build_evidence_inventory(
                self.documents,
                source_snapshot_sha256="a" * 64,
            )
        finally:
            first_node.content = old_content
        self.assertNotEqual(changed["inventory_sha256"], original)

    def test_duplicate_parser_citation_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate parser citation"):
            build_evidence_inventory(
                [self.documents[0], self.documents[0]],
                source_snapshot_sha256="a" * 64,
            )


if __name__ == "__main__":
    unittest.main()
