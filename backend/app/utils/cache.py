"""
问答缓存(省时又省钱的"常用答案小本本")
=====================================
小白理解:热门问题(比如"怎么退货?")一天可能被问几十遍。
每次都让 AI 重新思考一遍,既慢又费钱。我们把它第一次的答案记在小本本上,
下次有人问同样的问题,直接翻本子回答 —— 响应时间从 3 秒变成 0.01 秒,且不花一分钱。

两个安全措施:
  1. 只缓存"独立完整的问题"(第一轮提问)。因为"它的屏幕多大?"这种追问
     换个对话场景意思完全不同,缓存了会答非所问。
  2. 知识库内容有变动时(上传/删除文档),整本小本本作废重记,避免答案过时。
"""
import time
from collections import OrderedDict
from typing import Any

from app.utils.logger import logger


class TTLCache:
    """
    带过期时间的缓存。

    小白理解:
      - TTL(过期时间):本子上的答案最多保留 1 小时,超时自动作废
      - 容量上限:本子最多记 200 条,记满了就把最老的擦掉
    """

    def __init__(self, maxsize: int = 200, ttl_seconds: int = 3600) -> None:
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self.hits = 0      # 命中次数(直接翻到答案)
        self.misses = 0    # 未命中次数(需要重新问 AI)

    def get(self, key: str) -> Any | None:
        """查缓存:有且没过期就返回,否则返回 None"""
        item = self._data.get(key)
        if item is None:
            self.misses += 1
            return None

        saved_at, value = item
        if time.time() - saved_at > self._ttl:
            # 过期了,顺手删掉
            del self._data[key]
            self.misses += 1
            return None

        # 挪到队尾:表示"最近刚用过"(淘汰时优先淘汰最久没用的)
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        """存缓存:超过容量时淘汰最久没用过的那条"""
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (time.time(), value)

        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)  # 淘汰最早的那条

    def clear(self) -> None:
        """清空缓存(知识库变动时调用)"""
        if self._data:
            logger.info(f"🧹 问答缓存已清空({len(self._data)} 条)")
        self._data.clear()

    @property
    def size(self) -> int:
        """当前缓存条数"""
        return len(self._data)

    @property
    def hit_rate(self) -> float:
        """缓存命中率:命中次数 / 总查询次数(统计面板展示用)"""
        total = self.hits + self.misses
        return round(self.hits / total * 100, 1) if total else 0.0


# 全局缓存实例:整个系统共用一个
answer_cache = TTLCache(maxsize=200, ttl_seconds=3600)
