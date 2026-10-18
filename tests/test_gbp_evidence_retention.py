import unittest
from agent import gbp_signal_lab

class EvidenceTest(unittest.TestCase):
    def test_module_present(self):
        self.assertTrue(callable(gbp_signal_lab.update))
