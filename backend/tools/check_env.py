"""
环境自检脚本(排错小工具)
==========================
一次性检查三件事,以后遇到"问答没反应"这类问题也可以先跑它:
  1. 配置是否齐全(密钥有没有填)
  2. 阿里云百炼的三个服务能否连通:对话大模型 / 向量化 / 重排序
  3. 数据目录是否就绪

用法:在 backend 目录执行
  venv\\Scripts\\python.exe tools\\check_env.py
"""
import sys
from pathlib import Path

# 让脚本能找到上一级目录里的 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台中文防乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

from app.config import CHROMA_DIR, DATA_DIR, UPLOAD_DIR, settings

# 结果收集:每项检查记录 (名称, 是否通过, 说明)
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一项检查结果并即时打印"""
    results.append((name, ok, detail))
    mark = "✅" if ok else "❌"
    print(f"{mark} {name}" + (f"  →  {detail}" if detail else ""))


def main() -> int:
    print("=" * 64)
    print("  小鱼知识库问答系统 — 环境自检")
    print("=" * 64)

    # ---------- 1. 配置检查 ----------
    print("\n【第 1 步】配置检查")
    check("配置文件 backend/.env 已加载", True, f"大模型={settings.llm_model}")
    key = settings.dashscope_api_key.strip()
    check(
        "DASHSCOPE_API_KEY 已填写",
        bool(key),
        f"长度 {len(key)} 位,开头 {key[:8]}..." if key else "请在 backend/.env 中填写",
    )
    if not key:
        print("\n⚠️  密钥未填写,后续连通性测试跳过。")
        return 1

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    base = settings.dashscope_base_url

    # ---------- 2. 连通性测试:对话模型 ----------
    print("\n【第 2 步】阿里云服务连通性测试(会消耗极少量的免费额度)")
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            headers=headers,
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": "回答一个字:好"}],
                "max_tokens": 10,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            answer = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            check(
                f"对话模型 {settings.llm_model} 可用",
                True,
                f"回答“{answer}”,消耗 {usage.get('total_tokens', '?')} tokens",
            )
        else:
            check(
                f"对话模型 {settings.llm_model} 可用",
                False,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
    except Exception as exc:
        check(f"对话模型 {settings.llm_model} 可用", False, f"请求异常: {exc}")

    # ---------- 3. 连通性测试:向量化模型 ----------
    try:
        resp = httpx.post(
            f"{base}/embeddings",
            headers=headers,
            json={
                "model": settings.embedding_model,
                "input": ["这是一段测试文本"],
                "dimensions": settings.embedding_dim,
                "encoding_format": "float",
            },
            timeout=60,
        )
        if resp.status_code == 200:
            vec = resp.json()["data"][0]["embedding"]
            check(
                f"向量模型 {settings.embedding_model} 可用",
                True,
                f"返回 {len(vec)} 维向量",
            )
        else:
            check(
                f"向量模型 {settings.embedding_model} 可用",
                False,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
    except Exception as exc:
        check(f"向量模型 {settings.embedding_model} 可用", False, f"请求异常: {exc}")

    # ---------- 4. 连通性测试:重排序模型(依次尝试两种接口风格) ----------
    rerank_ok = False
    rerank_detail = ""
    # 风格 A:百炼原生接口(国内标准端点)
    payload = {
        "model": settings.rerank_model,
        "input": {"query": "手机电池容量", "documents": ["电池容量5000mAh", "屏幕尺寸6.7英寸"]},
        "parameters": {"top_n": 2},
    }
    for url, body in [
        (f"https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank", payload),
        (
            f"{base}/reranks",
            {
                "model": settings.rerank_model,
                "query": "手机电池容量",
                "documents": ["电池容量5000mAh", "屏幕尺寸6.7英寸"],
                "top_n": 2,
            },
        ),
    ]:
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=60)
            if resp.status_code == 200:
                rerank_ok = True
                rerank_detail = f"接口 {url.split('aliyuncs.com')[1][:40]} 可用"
                break
            rerank_detail = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except Exception as exc:
            rerank_detail = f"请求异常: {exc}"
    check(f"重排序模型 {settings.rerank_model} 可用", rerank_ok, rerank_detail)

    # ---------- 5. 数据目录检查 ----------
    print("\n【第 3 步】数据目录检查")
    for name, path in [("数据根目录", DATA_DIR), ("上传文件目录", UPLOAD_DIR), ("向量库目录", CHROMA_DIR)]:
        path.mkdir(parents=True, exist_ok=True)
        check(f"{name}就绪", True, str(path))

    # ---------- 汇总 ----------
    print("\n" + "=" * 64)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  自检结果:{passed}/{total} 项通过")
    if passed == total:
        print("  🎉 环境完全就绪,可以开始开发!")
    else:
        print("  ⚠️  有项目未通过,请查看上面的 ❌ 说明")
    print("=" * 64)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
