"""
重建知识库(演示前的一键"重置"工具)
==================================
小白理解:把知识库清空,然后重新上传 sample_kb 文件夹里的全部样例资料。
什么时候用?
  - 演示前,想要一个干净整齐的知识库
  - 修改了样例文档后,想让新内容生效

用法(需先启动后端):cd backend && venv\\Scripts\\python.exe tools\\rebuild_kb.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

BASE = "http://127.0.0.1:8000"
SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample_kb"


def main() -> int:
    if not SAMPLE_DIR.exists():
        print(f"❌ 找不到样例文档目录: {SAMPLE_DIR}")
        print("   请先运行:venv\\Scripts\\python.exe tools\\make_samples.py")
        return 1

    client = httpx.Client(base_url=BASE, timeout=300)

    # ---------- 登录 ----------
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    if resp.status_code != 200:
        print("❌ 登录失败,请确认后端已启动且管理员密码为默认值")
        return 1
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    print("✓ 管理员登录成功\n")

    # ---------- 清空旧文档 ----------
    old_docs = client.get("/api/kb/documents", headers=headers).json()
    for doc in old_docs:
        client.delete(f"/api/kb/documents/{doc['id']}", headers=headers)
    print(f"🗑️  已清空 {len(old_docs)} 份旧文档")

    # ---------- 上传全部样例文档 ----------
    files = []
    for path in sorted(SAMPLE_DIR.iterdir()):
        if path.is_file():
            files.append(("files", (path.name, open(path, "rb"), "application/octet-stream")))

    if not files:
        print(f"❌ {SAMPLE_DIR} 里没有文件")
        return 1

    resp = client.post("/api/kb/documents", headers=headers, files=files)
    for _, (_, fh, _) in files:
        fh.close()

    if resp.status_code != 200:
        print(f"❌ 上传失败: {resp.text[:200]}")
        return 1
    print(f"📤 已上传 {len(resp.json())} 份文档\n")

    # ---------- 等待后台处理完成 ----------
    print("⏳ 等待后台解析入库(大文件需要一点时间)...")
    for _ in range(120):  # 最多等 4 分钟
        time.sleep(2)
        docs = client.get("/api/kb/documents", headers=headers).json()
        busy = [d for d in docs if d["status"] in ("pending", "processing")]
        if not busy:
            break

    # ---------- 汇报结果 ----------
    stats = client.get("/api/kb/stats", headers=headers).json()
    print()
    print("=" * 60)
    for doc in sorted(docs, key=lambda x: x["id"]):
        mark = "✅" if doc["status"] == "completed" else "❌"
        print(f"  {mark} {doc['filename']:<30} {doc['chunk_count']:>3} 张卡片")
    print("=" * 60)
    print(f"  文档总数:{stats['document_count']} 份 | 知识卡片:{stats['chunk_count']} 张")
    print(f"  处理失败:{stats['failed_count']} 份")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
