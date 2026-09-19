"""
接口冒烟测试(快速体检)
======================
"冒烟测试"是行话:指快速跑一遍主要功能,看看有没有"冒烟"(严重问题)。

这个脚本会自动测试注册、登录、权限校验、改密码的完整流程,
每次改完用户相关代码都可以跑一次,几秒出结果。

用法(需先启动后端):cd backend && venv\\Scripts\\python.exe tools\\smoke_test.py
"""
import random
import sys

# Windows 控制台中文防乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

BASE = "http://127.0.0.1:8000"  # 后端地址

passed, failed = 0, 0


def check(name: str, condition: bool, detail: str = "") -> None:
    """记录一项测试结果"""
    global passed, failed
    if condition:
        passed += 1
        print(f"✅ {name}" + (f"  →  {detail}" if detail else ""))
    else:
        failed += 1
        print(f"❌ {name}" + (f"  →  {detail}" if detail else ""))


def main() -> int:
    # 每次运行用随机用户名,避免和上次的测试数据冲突
    test_user = f"smoke_{random.randint(10000, 99999)}"
    test_pass = "test123456"
    new_pass = "newpass654321"

    print("=" * 64)
    print("  用户系统冒烟测试")
    print("=" * 64)
    print(f"  本次测试账号: {test_user}\n")

    with httpx.Client(base_url=BASE, timeout=30) as client:
        # ---------- 1. 注册 ----------
        r = client.post("/api/auth/register", json={"username": test_user, "password": test_pass})
        check("注册新用户", r.status_code == 201, f"HTTP {r.status_code}")
        token = r.json().get("access_token", "") if r.status_code == 201 else ""

        # ---------- 2. 重复注册应被拒绝 ----------
        r = client.post("/api/auth/register", json={"username": test_user, "password": test_pass})
        check("重复用户名被拒绝", r.status_code == 400, r.json().get("detail", ""))

        # ---------- 3. 密码太短应被拒绝 ----------
        r = client.post("/api/auth/register", json={"username": f"{test_user}_x", "password": "123"})
        check("过短密码被拒绝", r.status_code == 422, f"HTTP {r.status_code}")

        # ---------- 4. 正确密码登录 ----------
        r = client.post("/api/auth/login", json={"username": test_user, "password": test_pass})
        check("正确密码登录成功", r.status_code == 200, f"HTTP {r.status_code}")

        # ---------- 5. 错误密码登录应被拒绝 ----------
        r = client.post("/api/auth/login", json={"username": test_user, "password": "wrong-password"})
        check("错误密码被拒绝", r.status_code == 401, r.json().get("detail", ""))

        # ---------- 6. 带令牌查询自己 ----------
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        ok = r.status_code == 200 and r.json().get("username") == test_user
        check("携带令牌查询本人信息", ok, f"角色={r.json().get('role') if ok else '?'}")

        # ---------- 7. 不带令牌应被拒绝 ----------
        r = client.get("/api/auth/me")
        check("无令牌访问被拒绝", r.status_code == 401, f"HTTP {r.status_code}")

        # ---------- 8. 伪造令牌应被拒绝 ----------
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer fake.token.here"})
        check("伪造令牌被拒绝", r.status_code == 401, f"HTTP {r.status_code}")

        # ---------- 9. 修改密码 ----------
        r = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"old_password": test_pass, "new_password": new_pass},
        )
        check("修改密码成功", r.status_code == 200, r.json().get("message", ""))

        # ---------- 10. 旧密码应登录失败 ----------
        r = client.post("/api/auth/login", json={"username": test_user, "password": test_pass})
        check("旧密码已失效", r.status_code == 401, f"HTTP {r.status_code}")

        # ---------- 11. 新密码应登录成功 ----------
        r = client.post("/api/auth/login", json={"username": test_user, "password": new_pass})
        check("新密码登录成功", r.status_code == 200, f"HTTP {r.status_code}")

        # ---------- 12. 管理员账号可登录 ----------
        r = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        is_admin = r.status_code == 200 and r.json().get("user", {}).get("role") == "admin"
        check("管理员账号 admin 登录且角色正确", is_admin, f"HTTP {r.status_code}")

    print("\n" + "=" * 64)
    print(f"  测试结果: {passed} 通过 / {failed} 失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
