"""
检索质量评估脚本(性能评估数据来源)
==================================
小白理解:这个脚本用来"考试评分" —— 拿 10 道有标准答案的商品问题,
分别让三种检索方案去"找资料",看谁找得准。

三种方案对比(本项目检索方案选型的依据):
  方案 A:纯向量检索           —— 最常见的入门做法
  方案 B:混合检索(向量+关键词)—— 加入关键词召回
  方案 C:混合检索 + 重排序     —— 本系统采用的完整方案

评分规则:
  每道题我们事先知道"正确答案在哪段文字里"(关键词)。检索出来的前 4 条里
  只要有一条包含这个关键词,就算"答对"。同时记录正确答案排在第几位。

用法:cd backend && venv\\Scripts\\python.exe tools\\evaluate.py
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.rag.retriever import hybrid_retrieve
from app.rag.vectorstore import get_vectorstore


# ==================== 测试题库 ====================
# expect_keyword:正确答案里必须包含的关键词(用它判断"找对没有")
# expect_file:    正确答案来自哪份文档(参考信息)
TEST_CASES = [
    {"question": "星辰X1手机的电池容量是多少?", "expect_keyword": "5000mAh", "expect_file": "星辰X1手机产品说明书.pdf"},
    {"question": "星辰Book 16 Pro 的屏幕分辨率是多少?", "expect_keyword": "3.2K", "expect_file": "商品参数总表.xlsx"},
    {"question": "星云Buds Pro 降噪耳机的降噪深度是多少?", "expect_keyword": "48", "expect_file": "耳机产品说明.txt"},
    {"question": "七天无理由退货的运费谁承担?", "expect_keyword": "买家承担", "expect_file": "常见问题FAQ.md"},
    {"question": "星辰Pad 11 平板的电池容量是多少?", "expect_keyword": "8600mAh", "expect_file": "商品参数总表.xlsx"},
    {"question": "星辰Watch 5 智能手表的续航是多久?", "expect_keyword": "14天", "expect_file": "商品参数总表.xlsx"},
    {"question": "空气净化器保修几年?", "expect_keyword": "2年", "expect_file": "商品参数总表.xlsx"},
    {"question": "星云Buds 无线耳机的防水等级是多少?", "expect_keyword": "IPX4", "expect_file": "耳机产品说明.txt"},
    {"question": "星辰机械键盘有多重?", "expect_keyword": "860g", "expect_file": "商品参数总表.xlsx"},
    {"question": "保修期内哪些情况不在保修范围?", "expect_keyword": "进水", "expect_file": "星辰X1手机产品说明书.pdf"},
]


def evaluate_plain_vector(case: dict, k: int = 4) -> tuple[bool, int, float]:
    """方案 A:纯向量检索。返回 (是否命中, 命中的名次, 耗时秒)"""
    store = get_vectorstore()
    t0 = time.perf_counter()
    docs = store.similarity_search(case["question"], k=k)
    cost = time.perf_counter() - t0

    for rank, doc in enumerate(docs, start=1):
        if case["expect_keyword"] in doc.page_content:
            return True, rank, cost
    return False, 0, cost


async def evaluate_hybrid(case: dict, use_rerank: bool) -> tuple[bool, int, float]:
    """方案 B/C:混合检索(可选重排序)。返回 (是否命中, 命中的名次, 耗时秒)"""
    t0 = time.perf_counter()
    chunks = await hybrid_retrieve(case["question"], top_n=4, use_rerank=use_rerank)
    cost = time.perf_counter() - t0

    for rank, chunk in enumerate(chunks, start=1):
        if case["expect_keyword"] in chunk.content:
            return True, rank, cost
    return False, 0, cost


def summarize(name: str, results: list[tuple[bool, int, float]]) -> dict:
    """把一组测试结果汇总成指标"""
    total = len(results)
    hits = sum(1 for hit, _, _ in results if hit)
    mrr = sum(1 / rank for hit, rank, _ in results if hit and rank > 0) / total
    avg_cost = sum(cost for _, _, cost in results) / total
    return {
        "name": name,
        "hit_rate": round(hits / total * 100, 1),   # 命中率(%)
        "mrr": round(mrr, 3),                        # 平均倒数排名(越高越好)
        "avg_seconds": round(avg_cost, 3),           # 平均耗时(秒)
        "detail": results,
    }


async def main() -> int:
    print("=" * 72)
    print("  检索质量评估 —— 三种方案对比(性能评估数据)")
    print(f"  测试题目:{len(TEST_CASES)} 道 | 判定标准:前 4 条资料中包含正确答案")
    print("=" * 72)

    # 先确认知识库有内容
    store = get_vectorstore()
    total = store._collection.count()
    if total == 0:
        print("❌ 知识库是空的!请先在管理页上传样例文档(或运行 tools/make_samples.py 生成后上传)")
        return 1
    print(f"  知识库当前有 {total} 张知识卡片\n")

    results_a, results_b, results_c = [], [], []

    # 逐题测试(打印进度,因为混合检索要调用网络接口,需要一点时间)
    for i, case in enumerate(TEST_CASES, start=1):
        print(f"[{i}/{len(TEST_CASES)}] {case['question']}")

        hit_a, rank_a, cost_a = evaluate_plain_vector(case)
        results_a.append((hit_a, rank_a, cost_a))
        print(f"          A 纯向量:      {'✅ 命中(第' + str(rank_a) + '位)' if hit_a else '❌ 未命中'}  {cost_a:.3f}s")

        hit_b, rank_b, cost_b = await evaluate_hybrid(case, use_rerank=False)
        results_b.append((hit_b, rank_b, cost_b))
        print(f"          B 混合检索:    {'✅ 命中(第' + str(rank_b) + '位)' if hit_b else '❌ 未命中'}  {cost_b:.3f}s")

        hit_c, rank_c, cost_c = await evaluate_hybrid(case, use_rerank=True)
        results_c.append((hit_c, rank_c, cost_c))
        print(f"          C 混合+重排:   {'✅ 命中(第' + str(rank_c) + '位)' if hit_c else '❌ 未命中'}  {cost_c:.3f}s")

    # ---------- 汇总 ----------
    summaries = [
        summarize("A 纯向量检索", results_a),
        summarize("B 混合检索(向量+关键词)", results_b),
        summarize("C 混合检索 + 重排序(本系统)", results_c),
    ]

    print("\n" + "=" * 72)
    print("  评估结果汇总")
    print("=" * 72)
    print(f"  {'方案':<34}{'命中率':<12}{'MRR':<10}{'平均耗时'}")
    print("  " + "-" * 68)
    for s in summaries:
        print(f"  {s['name']:<32}{str(s['hit_rate']) + '%':<12}{s['mrr']:<10}{s['avg_seconds']}s")

    # 提升幅度(优化效果最直观的一句总结)
    base, final = summaries[0], summaries[2]
    print("\n  📈 优化效果:")
    print(f"     命中率:{base['hit_rate']}% → {final['hit_rate']}%(提升 {final['hit_rate'] - base['hit_rate']:.1f} 个百分点)")
    print(f"     MRR:  {base['mrr']} → {final['mrr']}")
    print(f"     平均耗时:{base['avg_seconds']}s → {final['avg_seconds']}s")

    # ---------- 保存成 Markdown 报告(可直接放进项目文档) ----------
    report_path = Path(__file__).resolve().parent.parent.parent / "docs" / "检索质量评估报告.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 检索质量评估报告",
        "",
        f"- 评估时间:{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 知识库规模:{total} 张知识卡片",
        f"- 测试题目:{len(TEST_CASES)} 道,判定标准为「前 4 条检索结果中包含正确答案」",
        "",
        "## 三种方案对比",
        "",
        "| 方案 | 命中率 | MRR | 平均耗时(秒) |",
        "|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(f"| {s['name']} | {s['hit_rate']}% | {s['mrr']} | {s['avg_seconds']} |")
    lines += [
        "",
        f"> 优化效果:命中率从 {base['hit_rate']}% 提升到 {final['hit_rate']}%,"
        f"MRR 从 {base['mrr']} 提升到 {final['mrr']}。",
        "",
        "## 逐题明细",
        "",
        "| 测试问题 | A 纯向量 | B 混合检索 | C 混合+重排 |",
        "|---|---|---|---|",
    ]
    for i, case in enumerate(TEST_CASES):
        cells = []
        for res in (results_a[i], results_b[i], results_c[i]):
            hit, rank, _ = res
            cells.append(f"命中(第{rank}位)" if hit else "未命中")
        lines.append(f"| {case['question']} | {cells[0]} | {cells[1]} | {cells[2]} |")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  📄 报告已保存:{report_path}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
