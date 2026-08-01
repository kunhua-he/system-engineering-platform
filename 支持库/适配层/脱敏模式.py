"""脱敏模式：通用敏感信息正则（适配层安全边界共享）。"""

from __future__ import annotations

import re

# 通用密钥/凭据片段正则（脱敏工具与密钥引用共用，避免跨层反向依赖）
密钥片段模式 = re.compile(r"(gh[pous]_|sk-|eyJ|AKIA|-----BEGIN)[^\s，。；]+", re.IGNORECASE)
