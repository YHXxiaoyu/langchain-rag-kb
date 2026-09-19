"""
工具函数单元测试
==============
测试那些"纯逻辑"的小工具:密码加密、登录令牌、检索融合算法、缓存、报错翻译。
这些测试不需要联网、不需要数据库,跑得飞快。
"""
import time

from app.rag.retriever import rrf_fuse
from app.security import create_access_token, decode_token, hash_password, verify_password
from app.utils.cache import TTLCache
from app.utils.errors import friendly_api_error


class TestPassword:
    """密码加密:绝不能存明文,也不能被轻易破解"""

    def test_hash_is_not_plaintext(self):
        """加密结果不等于原文"""
        hashed = hash_password("mypassword123")
        assert hashed != "mypassword123"
        assert hashed.startswith("$2")  # bcrypt 的特征开头

    def test_verify_correct_password(self):
        """正确密码能验证通过"""
        hashed = hash_password("mypassword123")
        assert verify_password("mypassword123", hashed) is True

    def test_verify_wrong_password(self):
        """错误密码被拒绝"""
        hashed = hash_password("mypassword123")
        assert verify_password("wrongpassword", hashed) is False

    def test_same_password_gets_different_hash(self):
        """同一个密码两次加密结果不同(加了随机盐,防止撞库)"""
        assert hash_password("abc123456") != hash_password("abc123456")

    def test_very_long_password(self):
        """超长密码不会导致程序崩溃(bcrypt 只认前 72 字节)"""
        long_password = "这是一个非常特别以及极其长的中文密码" * 20
        hashed = hash_password(long_password)
        assert verify_password(long_password, hashed) is True

    def test_broken_hash_returns_false(self):
        """数据库里的哈希格式异常时,返回"验证失败"而不是崩溃"""
        assert verify_password("anything", "这不是一个合法的哈希") is False


class TestJWT:
    """登录令牌:能发能验,篡改和伪造一律无效"""

    def test_create_and_decode(self):
        """签发后能正常解析,内容正确"""
        token = create_access_token(user_id=42, username="tester", role="user")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["username"] == "tester"
        assert payload["role"] == "user"

    def test_fake_token_rejected(self):
        """随手编的令牌无效"""
        assert decode_token("fake.token.here") is None

    def test_tampered_token_rejected(self):
        """被改过的令牌无效(防伪签名对不上)"""
        token = create_access_token(user_id=1, username="a", role="user")
        tampered = token[:-6] + "abcdef"
        assert decode_token(tampered) is None


class TestRRF:
    """RRF 融合算法:两路都排名靠前的,融合后应该更靠前"""

    def test_document_in_both_lists_wins(self):
        """同时出现在两路结果里的文档,分数应该高于只出现一次的"""
        scores = rrf_fuse([["a", "b", "c"], ["d", "a", "e"]])
        assert scores["a"] > scores["b"]
        assert scores["a"] > scores["d"]

    def test_higher_rank_gets_higher_score(self):
        """同一条路上,排名第一的分数高于排名第二的"""
        scores = rrf_fuse([["first", "second"]])
        assert scores["first"] > scores["second"]

    def test_empty_input(self):
        """空输入不应报错"""
        assert rrf_fuse([]) == {}
        assert rrf_fuse([[], []]) == {}


class TestTTLCache:
    """问答缓存:存得进、取得出、会过期、会淘汰"""

    def test_set_and_get(self):
        cache = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("问题", "答案")
        assert cache.get("问题") == "答案"

    def test_expired_item_returns_none(self):
        """过期后取不到(避免用过时的答案)"""
        cache = TTLCache(maxsize=10, ttl_seconds=0)
        cache.set("问题", "答案")
        time.sleep(0.01)
        assert cache.get("问题") is None

    def test_evicts_oldest_when_full(self):
        """容量满了以后,最久没用过的被淘汰"""
        cache = TTLCache(maxsize=2, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # 容量已满,淘汰最老的 a
        assert cache.get("a") is None
        assert cache.get("c") == 3

    def test_hit_rate_calculation(self):
        """命中率计算正确(用于统计面板展示)"""
        cache = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("k", "v")
        cache.get("k")        # 命中
        cache.get("不存在")    # 未命中
        assert cache.hit_rate == 50.0

    def test_clear(self):
        """清空后取不到任何内容(知识库变动时会调用)"""
        cache = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("k", "v")
        cache.clear()
        assert cache.get("k") is None
        assert cache.size == 0


class TestFriendlyError:
    """报错翻译:把阿里云的英文技术错误变成看得懂的中文"""

    def test_arrearage_translated(self):
        """欠费提示"""
        msg = friendly_api_error(Exception("Error code: 400 - {'code': 'Arrearage'}"))
        assert "余额不足" in msg

    def test_invalid_key_translated(self):
        """密钥无效提示"""
        msg = friendly_api_error(Exception("InvalidApiKey: invalid api key"))
        assert "密钥" in msg

    def test_unknown_error_kept(self):
        """认不出的错误原样返回(方便排查)"""
        msg = friendly_api_error(Exception("某个奇怪的错误"))
        assert "某个奇怪的错误" in msg
