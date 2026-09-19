"""
压测数据准备脚本(跑压测之前先跑这个)
====================================
小白理解:要模拟"100 个人同时使用",得先有 100 个账号。

这个脚本做两件事:
  ① 造 100 个压测账号(用户名 stress001 ~ stress100),把登录令牌存到 accounts.json
  ② 用 20 个固定问题"预热"问答缓存 —— 每个问题先问一遍,
     之后压测时再问同样的问题就能秒回(不经过 AI,也不花钱)

用法(先启动压测模式的后端,见 操作手册.md):
    cd backend
    venv\\Scripts\\python.exe tools\\stress\\prepare.py

注意事项:
  - 必须是"压测模式"的后端(环境变量 MOCK_LLM=1),否则预热会真的调用阿里云花钱
  - 账号数据存在 tools/stress/accounts.json,里面是压测账号的登录令牌,不要外传
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

# 让脚本能 import 到 app 包(取配置用)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import settings  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
STRESS_DIR = Path(__file__).resolve().parent
ACCOUNTS_FILE = STRESS_DIR / "accounts.json"
QUESTIONS_FILE = STRESS_DIR / "warm_questions.json"

# 压测账号数量与统一密码
ACCOUNT_COUNT = 100
ACCOUNT_PASSWORD = "stress123456"

# 并发度:造账号时同时发几个请求(太高会把电脑 CPU 占满,10 个比较稳妥)
CONCURRENCY = 10

# 用于预热缓存的 20 个问题(都来自样例知识库,贴近真实使用场景)
WARM_QUESTIONS = [
    "星辰X1手机的电池容量是多少?",
    "星辰X1支持快充吗?充电功率多大?",
    "星辰X1的屏幕参数是什么?",
    "星辰X1手机有多重?",
    "笔记本电脑的配置怎么样?",
    "笔记本电脑的续航时间是多久?",
    "耳机的续航时间是多久?",
    "耳机支持降噪吗?",
    "冰箱收到后需要静置多久才能通电?",
    "空调的保修期是几年?",
    "下单后多久发货?",
    "支持哪些配送方式?",
    "满多少金额包邮?",
    "一般多久能收到货?",
    "支持哪些支付方式?",
    "怎么开发票?",
    "七天无理由退货需要满足什么条件?",
    "退货的运费由谁承担?",
    "商品出现质量问题怎么办?",
    "怎么联系人工客服?",
]


async def _register_one(client: httpx.AsyncClient, index: int) -> dict | None:
    """
    造一个账号:优先注册;如果已经存在(上次跑过),就直接登录。
    返回 {用户名, 密码, 登录令牌}
    """
    username = f"stress{index:03d}"
    payload = {"username": username, "password": ACCOUNT_PASSWORD}

    # 先试注册(注册接口成功后会直接返回令牌,省一次登录)
    resp = await client.post(f"{BASE_URL}/api/auth/register", json=payload)
    if resp.status_code == 201:
        return {"username": username, "password": ACCOUNT_PASSWORD, "token": resp.json()["access_token"]}

    # 注册失败(多半是账号已存在)—— 改用登录
    resp = await client.post(f"{BASE_URL}/api/auth/login", json=payload)
    if resp.status_code == 200:
        return {"username": username, "password": ACCOUNT_PASSWORD, "token": resp.json()["access_token"]}

    print(f"  ❌ {username} 注册/登录都失败:HTTP {resp.status_code} {resp.text[:120]}")
    return None


async def create_accounts() -> list[dict]:
    """批量造 100 个压测账号(同时发 10 个请求,快一些)"""
    print(f"\n[1/3] 正在创建 {ACCOUNT_COUNT} 个压测账号...")
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=60) as client:
        async def worker(i: int) -> dict | None:
            async with semaphore:
                return await _register_one(client, i)

        results = await asyncio.gather(*(worker(i) for i in range(1, ACCOUNT_COUNT + 1)))

    accounts = [a for a in results if a]
    print(f"      ✅ 成功 {len(accounts)} / {ACCOUNT_COUNT} 个账号")
    return accounts


async def warm_cache(accounts: list[dict]) -> int:
    """
    预热问答缓存:用 20 个不同账号各问一个问题。
    (每个账号只问一次 —— 因为限流是"每人每分钟 20 次",分散开就不会被拦)
    """
    print(f"\n[2/3] 正在预热问答缓存({len(WARM_QUESTIONS)} 个问题)...")
    warmed = 0

    async with httpx.AsyncClient(timeout=180) as client:
        for i, question in enumerate(WARM_QUESTIONS):
            account = accounts[i % len(accounts)]
            headers = {"Authorization": f"Bearer {account['token']}"}

            # conversation_id 传 None:每次开一个新会话。
            # 为什么必须开新会话?因为缓存只对"新会话的第一个问题"生效。
            payload = {"question": question, "conversation_id": None}

            try:
                async with client.stream("POST", f"{BASE_URL}/api/chat", json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        print(f"      ⚠️  「{question}」失败:HTTP {resp.status_code} {body[:80]}")
                        continue
                    # 必须把整条流读完 —— 回答写完的那一刻才会存进缓存
                    async for _ in resp.aiter_lines():
                        pass
                warmed += 1
                print(f"      ✓ {question}")
            except Exception as exc:
                print(f"      ⚠️  「{question}」出错: {exc}")

    print(f"      ✅ 预热完成 {warmed} / {len(WARM_QUESTIONS)} 个问题")
    return warmed


async def verify_cache(accounts: list[dict]) -> bool:
    """
    验证预热是否真的生效:随便挑一个问题再问一次,看返回里有没有 "cached": true 标记。
    """
    print("\n[3/3] 验证缓存是否生效...")
    question = WARM_QUESTIONS[0]
    account = accounts[-1]  # 换一个账号(保证不是靠"同一账号的历史"生效)
    headers = {"Authorization": f"Bearer {account['token']}"}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/api/chat",
            json={"question": question, "conversation_id": None},
            headers=headers,
        ) as resp:
            async for line in resp.aiter_lines():
                if '"cached": true' in line or '"cached":true' in line:
                    print(f"      ✅ 缓存生效!再问「{question}」时秒回,不经过 AI")
                    return True

    print("      ⚠️  没有检测到缓存标记 —— 请确认后端是用 MOCK_LLM=1 启动的")
    return False


async def main() -> int:
    print("=" * 68)
    print("  压力测试数据准备")
    print("=" * 68)

    # 安全检查:必须是模拟模式,否则预热会真的花钱调阿里云
    if not settings.mock_llm:
        print("\n❌ 危险:当前后端没有开启模拟模式!")
        print("   如果继续,预热会真的调用阿里云 AI 并产生费用。")
        print("   请用 MOCK_LLM=1 启动后端后再运行本脚本(见 操作手册.md)。")
        return 1
    print("   ✅ 已确认后端处于模拟模式(不会产生任何 AI 费用)")

    accounts = await create_accounts()
    if not accounts:
        print("\n❌ 一个账号都没造出来 —— 请确认后端已启动( http://127.0.0.1:8000/api/health )")
        return 1

    ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
    QUESTIONS_FILE.write_text(json.dumps(WARM_QUESTIONS, ensure_ascii=False, indent=2), encoding="utf-8")

    await warm_cache(accounts)
    await verify_cache(accounts)

    print("\n" + "=" * 68)
    print(f"   准备完成!账号已存到 {ACCOUNTS_FILE.name}({len(accounts)} 个)")
    print("   下一步:运行 locust 开始压测(见 操作手册.md)")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
