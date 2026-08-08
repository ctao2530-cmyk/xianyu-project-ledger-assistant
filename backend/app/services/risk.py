from __future__ import annotations

import re


RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("报价需确认", re.compile(r"报价|价格|预算|多少钱|[¥￥]|\d+(?:\.\d+)?\s*(?:元|块)")),
    ("退款需确认", re.compile(r"退款|退钱|退货|售后")),
    ("账号密码需确认", re.compile(r"账号|密码|验证码|密钥|api\s*key|token", re.I)),
    ("联系方式需确认", re.compile(r"微信|vx|电话|手机号|邮箱|qq", re.I)),
    ("交付时间需确认", re.compile(r"交付|工期|截止|多久|几天|什么时候|今天|明天|本周")),
    ("支付方式需确认", re.compile(r"支付|付款|转账|收款|支付宝|银行卡|定金")),
    ("自动发送需确认", re.compile(r"自动发送|自动回复|无人值守")),
    ("商品操作需确认", re.compile(r"删除商品|下架商品|删除宝贝|下架宝贝")),
)


def detect_risks(text: str) -> list[str]:
    return [label for label, pattern in RISK_PATTERNS if pattern.search(text)]
