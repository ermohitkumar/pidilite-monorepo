import sys
import pytest

if __name__ == "__main__":
    pytest.main(
        ["tests/test_keywords.py::TestKeywordManagement::test_list_keywords_success", "-s", "-v"])
