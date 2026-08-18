import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestDiscoveryTests(unittest.TestCase):
    def test_no_pytest_style_tests_are_invisible_to_unittest_discovery(self):
        invisible = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    invisible.append(f"{path.name}:{node.lineno}:{node.name}")
        self.assertEqual(
            invisible,
            [],
            "product verification uses unittest discovery; top-level test functions are inert",
        )


if __name__ == "__main__":
    unittest.main()
