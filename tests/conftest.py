import os
import sys

TEST_ROOT = os.path.dirname(__file__)
PROJECT_SRC = os.path.abspath(os.path.join(TEST_ROOT, "..", "src"))

if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)
