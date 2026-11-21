"""Architecture guardrail and experience extraction regression tests."""
import ast
import unittest

from jobbot import scan, scan_experience


class ArchitectureAuditTests(unittest.TestCase):
    def test_duplicate_definitions_detected_in_same_scope(self):
        from scripts.architecture_audit import duplicate_definitions
        tree = ast.parse("def a(): pass\ndef a(): pass\nclass B:\n def c(self): pass\n def c(self): pass")
        self.assertEqual(len(duplicate_definitions(tree)), 2)

    def test_readability_advisories_are_nonblocking(self):
        from scripts.architecture_audit import readability_findings
        tree = ast.parse("def BadName():\\n    pass")
        self.assertTrue(any("unconventional" in item for item in readability_findings(tree, "sample.py")))

    def test_unrelated_methods_are_not_reported(self):
        from scripts.architecture_audit import duplicate_definitions
        tree = ast.parse("class A:\n def run(self): pass\nclass B:\n def run(self): pass")
        self.assertEqual(duplicate_definitions(tree), [])

    def test_scan_experience_public_api_remains_available(self):
        self.assertIs(scan.YEARS, scan_experience.YEARS)
        self.assertIs(scan.experience_bounds, scan_experience.experience_bounds)
        self.assertIs(scan.stated_experience, scan_experience.stated_experience)
        self.assertEqual(scan.stated_years("Minimum 3 years of professional experience")[0], 3.0)


if __name__ == "__main__":
    unittest.main()
