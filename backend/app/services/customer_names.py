"""Keep a captured customer name independent from later notification titles."""

_PLACEHOLDERS = {"", "闲鱼客户", "微信客户", "客户", "未知客户", "工作台通知", "系统通知", "我完成了评价"}


def stable_customer_name(current: str | None, candidate: str | None) -> str:
    current = (current or "").strip()
    candidate = (candidate or "").strip()
    if current not in _PLACEHOLDERS:
        return current
    if candidate not in _PLACEHOLDERS:
        return candidate
    return "闲鱼客户"
