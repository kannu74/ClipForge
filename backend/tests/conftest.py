import os
import tempfile

import pytest

# Point CLIPFORGE_DATA_DIR at a temp dir before app.config is imported anywhere,
# so tests never touch real project data.
_tmp = tempfile.mkdtemp(prefix="clipforge_test_")
os.environ["CLIPFORGE_DATA_DIR"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
