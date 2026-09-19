"""
接口测试(用户系统 / 权限 / 会话管理)
===================================
用真实的请求流程测试各个接口的行为是否符合预期。
测试跑在独立的测试数据库上,不会影响真实数据。
"""
from fastapi.testclient import TestClient

# ==================== 用户系统 ====================

class TestRegister:
    def test_register_success(self, client: TestClient):
        """注册成功:返回 201 和登录令牌(注册即登录)"""
        resp = client.post(
            "/api/auth/register",
            json={"username": "reg_test_1", "password": "pass123456"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["access_token"]
        assert data["user"]["username"] == "reg_test_1"
        assert data["user"]["role"] == "user"  # 新用户一律是普通用户

    def test_register_duplicate_username(self, client: TestClient):
        """用户名重复被拒绝"""
        payload = {"username": "dup_user", "password": "pass123456"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        resp = client.post("/api/auth/register", json=payload)
        assert resp.status_code == 400
        assert "已被注册" in resp.json()["detail"]

    def test_register_short_password(self, client: TestClient):
        """密码太短被拒绝(参数校验返回 422)"""
        resp = client.post(
            "/api/auth/register",
            json={"username": "short_pw_user", "password": "123"},
        )
        assert resp.status_code == 422

    def test_register_username_with_space(self, client: TestClient):
        """用户名带空格被拒绝"""
        resp = client.post(
            "/api/auth/register",
            json={"username": "has space", "password": "pass123456"},
        )
        assert resp.status_code == 422

    def test_cannot_register_as_admin(self, client: TestClient):
        """不能通过注册接口造出管理员账号"""
        resp = client.post(
            "/api/auth/register",
            json={"username": "faker_admin", "password": "pass123456", "role": "admin"},
        )
        assert resp.status_code == 201
        assert resp.json()["user"]["role"] == "user"  # role 参数被忽略


class TestLogin:
    def test_login_success(self, client: TestClient):
        """管理员用默认密码能登录,角色正确"""
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"

    def test_login_wrong_password(self, client: TestClient):
        """密码错误被拒绝"""
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pw"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient):
        """不存在的用户:返回与密码错误相同的提示(不泄露用户名是否存在)"""
        resp = client.post("/api/auth/login", json={"username": "nobody", "password": "any"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "用户名或密码错误"


class TestMe:
    def test_me_with_token(self, client: TestClient, user_headers: dict):
        """带令牌能查到自己的信息"""
        resp = client.get("/api/auth/me", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "pytest_user"

    def test_me_without_token(self, client: TestClient):
        """不带令牌被拒绝"""
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_fake_token(self, client: TestClient):
        """伪造令牌被拒绝"""
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer fake.token.here"})
        assert resp.status_code == 401


class TestChangePassword:
    def test_change_password_flow(self, client: TestClient):
        """完整改密流程:旧密码验证 → 改密 → 旧密码失效 → 新密码可登录"""
        username, old_pw, new_pw = "pwd_change_user", "oldpass123", "newpass456"

        resp = client.post("/api/auth/register", json={"username": username, "password": old_pw})
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 改密码
        resp = client.post(
            "/api/auth/change-password",
            headers=headers,
            json={"old_password": old_pw, "new_password": new_pw},
        )
        assert resp.status_code == 200

        # 旧密码失效
        assert client.post("/api/auth/login", json={"username": username, "password": old_pw}).status_code == 401
        # 新密码可用
        assert client.post("/api/auth/login", json={"username": username, "password": new_pw}).status_code == 200

    def test_change_password_wrong_old(self, client: TestClient, user_headers: dict):
        """旧密码填错时被拒绝"""
        resp = client.post(
            "/api/auth/change-password",
            headers=user_headers,
            json={"old_password": "wrong-old-pw", "new_password": "whatever123"},
        )
        assert resp.status_code == 400


# ==================== 权限隔离 ====================

class TestPermission:
    """核心安全测试:普通用户绝不能碰到知识库管理"""

    def test_user_cannot_list_documents(self, client: TestClient, user_headers: dict):
        assert client.get("/api/kb/documents", headers=user_headers).status_code == 403

    def test_user_cannot_upload(self, client: TestClient, user_headers: dict):
        resp = client.post(
            "/api/kb/documents",
            headers=user_headers,
            files={"files": ("t.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 403

    def test_user_cannot_delete_document(self, client: TestClient, user_headers: dict):
        assert client.delete("/api/kb/documents/1", headers=user_headers).status_code == 403

    def test_user_cannot_view_stats(self, client: TestClient, user_headers: dict):
        assert client.get("/api/kb/stats", headers=user_headers).status_code == 403

    def test_user_cannot_view_dashboard(self, client: TestClient, user_headers: dict):
        assert client.get("/api/admin/stats", headers=user_headers).status_code == 403

    def test_admin_can_list_documents(self, client: TestClient, admin_headers: dict):
        assert client.get("/api/kb/documents", headers=admin_headers).status_code == 200

    def test_admin_can_view_stats(self, client: TestClient, admin_headers: dict):
        resp = client.get("/api/kb/stats", headers=admin_headers)
        assert resp.status_code == 200
        assert "chunk_count" in resp.json()

    def test_admin_can_view_dashboard(self, client: TestClient, admin_headers: dict):
        resp = client.get("/api/admin/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data and "cache" in data


# ==================== 会话管理 ====================

class TestConversations:
    def test_create_and_list(self, client: TestClient, user_headers: dict):
        """新建会话后能在列表里看到"""
        resp = client.post("/api/conversations", headers=user_headers, json={"title": "测试会话"})
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

        resp = client.get("/api/conversations", headers=user_headers)
        assert resp.status_code == 200
        assert any(c["id"] == conv_id for c in resp.json())

    def test_rename(self, client: TestClient, user_headers: dict):
        """重命名生效"""
        conv_id = client.post(
            "/api/conversations", headers=user_headers, json={"title": "旧名字"}
        ).json()["id"]

        resp = client.patch(f"/api/conversations/{conv_id}", headers=user_headers, json={"title": "新名字"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "新名字"

    def test_delete(self, client: TestClient, user_headers: dict):
        """删除后列表里不再出现"""
        conv_id = client.post(
            "/api/conversations", headers=user_headers, json={"title": "待删除"}
        ).json()["id"]

        assert client.delete(f"/api/conversations/{conv_id}", headers=user_headers).status_code == 200

        resp = client.get("/api/conversations", headers=user_headers)
        assert not any(c["id"] == conv_id for c in resp.json())

    def test_messages_of_empty_conversation(self, client: TestClient, user_headers: dict):
        """新会话的历史消息是空的"""
        conv_id = client.post(
            "/api/conversations", headers=user_headers, json={"title": "空会话"}
        ).json()["id"]
        resp = client.get(f"/api/conversations/{conv_id}/messages", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cannot_access_others_conversation(self, client: TestClient, user_headers: dict, admin_headers: dict):
        """越权访问别人的会话:返回 404(连"存在"都不告诉对方)"""
        # 普通用户建一个会话
        conv_id = client.post(
            "/api/conversations", headers=user_headers, json={"title": "私人会话"}
        ).json()["id"]

        # 管理员(另一个用户)想访问
        assert client.get(f"/api/conversations/{conv_id}/messages", headers=admin_headers).status_code == 404
        assert client.delete(f"/api/conversations/{conv_id}", headers=admin_headers).status_code == 404

    def test_conversation_requires_login(self, client: TestClient):
        """未登录不能访问会话接口"""
        assert client.get("/api/conversations").status_code == 401
        assert client.post("/api/conversations", json={"title": "x"}).status_code == 401
