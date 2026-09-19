"""
Locust 压力测试脚本(模拟 100 人同时使用)
========================================
小白理解:Locust 是一个"虚拟用户生成器"。它会同时放出 100 个"机器人",
每个机器人像一个真人那样操作网站 —— 登录、翻会话、提问 —— 并记录下
每一次操作花了多久、有没有失败。

5 个场景(由浅入深,可以单独跑,也可以一起跑):

  ① HealthUser     健康检查   —— 不碰数据库和 AI,测"服务本身能扛多少请求"
  ② LoginStormUser 登录风暴   —— 100 人同时登录,测密码校验会不会拖慢系统
  ③ BrowseUser     会话浏览   —— 建会话/看列表/翻历史,测数据库的并发能力
  ④ CachedChatUser 提问(缓存)—— 问那 20 个预热过的问题,走完整流程但秒回
  ⑤ FullChatUser   提问(全流程)—— 随机问题,完整走一遍"检索 → 生成 → 存库"

怎么跑(先跑过 prepare.py 和启动压测后端):
    cd backend
    venv\\Scripts\\python.exe -m locust -f tools\\stress\\locustfile.py

然后浏览器打开 http://localhost:8089 就能看到实时图表。

全程不调用阿里云(后端开着模拟模式),所以跑多久都不花钱。
"""
import itertools
import json
import random
import threading
import time
from pathlib import Path

import requests
from locust import HttpUser, between, events, task

# ==================== 读取准备阶段造好的数据 ====================

_STRESS_DIR = Path(__file__).resolve().parent

try:
    _ACCOUNTS = json.loads((_STRESS_DIR / "accounts.json").read_text(encoding="utf-8"))
    _WARM_QUESTIONS = json.loads((_STRESS_DIR / "warm_questions.json").read_text(encoding="utf-8"))
except FileNotFoundError:
    raise SystemExit(
        "\n❌ 找不到压测数据文件。请先运行数据准备脚本:\n"
        "   cd backend && venv\\Scripts\\python.exe tools\\stress\\prepare.py\n"
    )

# 给每个虚拟用户分配一个不同的压测账号(轮流发,不重复)
_account_lock = threading.Lock()
_account_cursor = itertools.count()


def next_account() -> dict:
    """取下一个压测账号(多个虚拟用户不会撞到同一个账号)"""
    with _account_lock:
        index = next(_account_cursor) % len(_ACCOUNTS)
    return _ACCOUNTS[index]


# ==================== 上报自定义指标 ====================

def report(name: str, elapsed_ms: float, ok: bool = True, error: str | None = None) -> None:
    """
    把一条"自定义记录"上报给 Locust 的统计面板。

    为什么需要它?因为 Locust 自带的计时器只统计"整个请求花了多久",
    而流式问答有两个更有意义的指标:
      ① 首字延迟 —— 用户等多久看到第一个字(体验好不好就看它)
      ② 完整耗时 —— 整个回答写完要多久
    这两个数字必须手动上报,报表里才能看到。
    """
    try:
        events.request.fire(
            request_type="POST",
            name=name,
            response_time=elapsed_ms,
            response_length=0,
            exception=error if not ok else None,
            context={},
        )
    except TypeError:
        # 兼容不同版本的 Locust(老版本参数少)
        events.request.fire(
            request_type="POST",
            name=name,
            response_time=elapsed_ms,
            response_length=0,
        )


# ==================== 流式提问的公共逻辑 ====================

def sse_chat(host: str, token: str, question: str, conversation_id: int | None, name: str) -> None:
    """
    发一次提问,把整条流式回答读完,并上报两个指标。

    注意:这里用 requests 直接发请求(而不是 Locust 自带的客户端),
    因为要一边收一边计时,才能算出"首字延迟";Locust 自带的计时器做不到。
    """
    url = f"{host}/api/chat"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"question": question, "conversation_id": conversation_id}

    start = time.perf_counter()
    first_char_ms: float | None = None
    ok = True
    error: str | None = None
    answer_chars = 0

    try:
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=180) as resp:
            if resp.status_code != 200:
                ok = False
                error = f"HTTP {resp.status_code}"
                try:
                    error = resp.json().get("detail", error)
                except Exception:
                    pass
            else:
                for raw in resp.iter_lines():
                    if not raw:
                        continue
                    if first_char_ms is None:
                        first_char_ms = (time.perf_counter() - start) * 1000
                    answer_chars += len(raw)
    except Exception as exc:
        ok = False
        error = f"{type(exc).__name__}: {exc}"

    total_ms = (time.perf_counter() - start) * 1000

    if not ok:
        # 失败时只记一条,避免把错误率算成两倍
        report(f"{name} [完整回答]", total_ms, False, error)
        return

    report(f"{name} [首字延迟]", first_char_ms if first_char_ms else total_ms, True)
    report(f"{name} [完整回答]", total_ms, True)


# ==================== 场景一:健康检查 ====================

class HealthUser(HttpUser):
    """健康检查:最轻量的请求,用来测"服务本身每秒能处理多少个请求" """

    weight = 1
    wait_time = between(0.5, 1.5)

    @task
    def health(self):
        self.client.get("/api/health", name="/api/health")


# ==================== 场景二:登录风暴 ====================

class LoginStormUser(HttpUser):
    """
    登录风暴:不停地登录。
    每次登录都要做一次密码校验(bcrypt),这是纯 CPU 计算 ——
    这个场景专门用来暴露"密码校验会不会拖慢整个系统"的问题。
    """

    weight = 1
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.account = next_account()

    @task
    def login(self):
        self.client.post(
            "/api/auth/login",
            json={"username": self.account["username"], "password": self.account["password"]},
            name="/api/auth/login",
        )


# ==================== 场景三:会话浏览 ====================

class BrowseUser(HttpUser):
    """
    会话浏览:像真人一样翻看自己的会话列表、开新会话、读历史消息、删掉不要的。
    这个场景主要在压数据库(每次建会话、发消息都要写库)。
    """

    weight = 1
    wait_time = between(1, 3)

    def on_start(self):
        account = next_account()
        # 给这个虚拟用户的后续请求都带上登录令牌
        self.client.headers.update({"Authorization": f"Bearer {account['token']}"})
        self.conversations: list[int] = []

    @task(3)
    def list_conversations(self):
        self.client.get("/api/conversations", name="/api/conversations [列表]")

    @task(2)
    def create_conversation(self):
        resp = self.client.post(
            "/api/conversations",
            json={"title": f"压测会话 {random.randint(1, 9999)}"},
            name="/api/conversations [新建]",
        )
        if resp.status_code == 201:
            self.conversations.append(resp.json()["id"])

    @task(2)
    def read_messages(self):
        if not self.conversations:
            return
        conv_id = random.choice(self.conversations)
        self.client.get(f"/api/conversations/{conv_id}/messages", name="/api/conversations [历史消息]")

    @task(1)
    def delete_conversation(self):
        if not self.conversations:
            return
        conv_id = self.conversations.pop(0)
        self.client.delete(f"/api/conversations/{conv_id}", name="/api/conversations [删除]")


# ==================== 场景四:提问(命中缓存) ====================

class CachedChatUser(HttpUser):
    """
    提问——缓存命中:反复问那 20 个预热过的问题。
    走的是完整的流式问答流程(SSE、权限校验、存数据库),
    但因为答案已经在缓存里,不会调用 AI —— 相当于"蹭热点问题的真实用户"。
    """

    weight = 1
    wait_time = between(3, 6)

    def on_start(self):
        self.token = next_account()["token"]

    @task
    def ask(self):
        question = random.choice(_WARM_QUESTIONS)
        # conversation_id 传 None:每次开新会话,这样才会走缓存
        sse_chat(self.host, self.token, question, None, "/api/chat [缓存命中]")


# ==================== 场景五:提问(完整流程) ====================

class FullChatUser(HttpUser):
    """
    提问——完整流程:问随机问题,完整走一遍
    "查询改写 → 混合检索 → 重排序 → 流式生成 → 存数据库"。
    AI 由本地模拟器扮演,所以这一场跑下来一分钱不花。
    """

    weight = 1
    wait_time = between(3, 6)

    def on_start(self):
        self.token = next_account()["token"]

    @task
    def ask(self):
        # 问题后面加个随机编号:保证每次问的都不一样,不会撞到缓存
        base = random.choice(_WARM_QUESTIONS).rstrip("?？")
        question = f"{base}(第 {random.randint(1, 999999)} 次咨询)"
        sse_chat(self.host, self.token, question, None, "/api/chat [全流程]")
