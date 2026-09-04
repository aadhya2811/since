import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must be set before app.config is imported anywhere.
_tmp = tempfile.mkdtemp()
os.environ["SINCE_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SINCE_PROVIDER"] = "simulated"
os.environ["SINCE_FALLBACK_PROVIDER"] = ""
os.environ["SINCE_SCHEDULER_ENABLED"] = "false"
os.environ["SINCE_AUTH_DEV_RETURN_CODE"] = "true"
os.environ["SINCE_LOG_LEVEL"] = "WARNING"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.market.resilient import ResilientProvider  # noqa: E402
from app.market.service import MarketService  # noqa: E402
from app.market.news import SimulatedNewsProvider  # noqa: E402
from app.market.simulated import SimulatedProvider  # noqa: E402


@pytest.fixture()
def sim() -> SimulatedProvider:
    return SimulatedProvider()


@pytest.fixture()
def client(sim):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    svc = MarketService(ResilientProvider([sim]), settings, [SimulatedNewsProvider()])
    app = create_app(market=svc)
    with TestClient(app) as c:
        c.market = svc  # type: ignore[attr-defined]
        yield c


def login(client: TestClient, email="tester@example.com", device="pytest") -> dict:
    r = client.post("/api/auth/request-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = client.post("/api/auth/verify", json={"email": email, "code": code, "device_label": device})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
