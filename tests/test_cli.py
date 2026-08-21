import unittest
from contextlib import redirect_stderr
from io import StringIO

from sensei.cli import parse_args


class CliTests(unittest.TestCase):
    def test_fast_and_model_id_are_mutually_exclusive(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--fast", "--model-id", "another-model"])

    def test_one_shot_mode_parses(self) -> None:
        args = parse_args(["--prompt", "Differentiate x^2", "--mode", "hint"])
        self.assertEqual("Differentiate x^2", args.prompt)
        self.assertEqual("hint", args.mode)


if __name__ == "__main__":
    unittest.main()
