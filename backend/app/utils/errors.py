"""
阿里云报错翻译器(把英文技术错误变成人话)
======================================
小白理解:阿里云服务出问题时,返回的是一串英文技术术语
(比如 Arrearage、Throttling、InvalidApiKey),看不懂也不知道该怎么办。
这个小工具负责把它们翻译成"发生了什么 + 该怎么办"的中文提示。
"""


def friendly_api_error(exc: Exception | str) -> str:
    """
    把异常信息翻译成给用户看的中文提示。
    认不出来的错误,原样返回前 200 个字(方便排查)。
    """
    text = str(exc)

    # 账户欠费 / 免费额度用完
    if "Arrearage" in text or "overdue-payment" in text or "good standing" in text:
        return "阿里云账户余额不足(免费额度可能已用完),请前往阿里云百炼控制台充值后重试"

    # 密钥无效或未开通服务
    if "InvalidApiKey" in text or "invalid_api_key" in text or "Invalid API-key" in text:
        return "API 密钥无效或未开通百炼服务,请检查 backend/.env 中的 DASHSCOPE_API_KEY"

    # 调用太频繁
    if "Throttling" in text or "rate limit" in text.lower() or "Requests rate limit" in text:
        return "调用过于频繁,已触发阿里云限流,请稍等片刻再试"

    # 模型不存在或未开通
    if "ModelNotFound" in text or "model not exist" in text.lower():
        return "所选模型不可用,请检查 backend/.env 中的模型名称是否正确"

    # 内容审核未通过
    if "DataInspectionFailed" in text or "inappropriate content" in text.lower():
        return "内容未通过安全检查,请调整提问后重试"

    # 网络问题
    if "Timeout" in text or "timeout" in text.lower():
        return "调用阿里云服务超时,请检查网络后重试"

    return text[:200]
