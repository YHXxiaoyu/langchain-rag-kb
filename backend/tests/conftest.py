"""
pytest 测试配置
==============
小白理解:自动化测试的"总开关"。

关键设计:测试用的数据库是独立的一份(data/test.db),不会碰到你真实的
账号和数据。每次跑测试前会自动把旧的测试库删掉,保证从零开始。
"""
import os
import sys
from pathlib import Path

# 让测试能 import 到 app 包(必须在导入 app 之前)
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ["DB_FILENAME"] = "test.db"  # 关键:切到测试数据库,不动真实数据

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import DATA_DIR  # noqa: E402

# 清掉上次遗留的测试数据库文件,保证每次从干净状态开始
_test_db = DATA_DIR / "test.db"
if _test_db.exists():
    _test_db.unlink()

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """
    测试用的"浏览器"(FastAPI 官方测试客户端)。
    用 with 进入会触发应用的启动流程(建表、创建管理员账号)。
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client: TestClient) -> str:
    """管理员登录,拿到令牌(很多测试都要用)"""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert resp.status_code == 200, "管理员登录失败,检查初始化逻辑"
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def user_token(client: TestClient) -> str:
    """注册一个普通用户,拿到令牌"""
    resp = client.post(
        "/api/auth/register",
        json={"username": "pytest_user", "password": "test123456"},
    )
    assert resp.status_code == 201, "普通用户注册失败"
    return resp.json()["access_token"]


@pytest.fixture
def admin_headers(admin_token: str) -> dict:
    """管理员请求头"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def user_headers(user_token: str) -> dict:
    """普通用户请求头"""
    return {"Authorization": f"Bearer {user_token}"}
