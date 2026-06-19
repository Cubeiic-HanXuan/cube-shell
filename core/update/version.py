"""
语义化版本比较(纯函数,零第三方依赖)。

兼容以下写法:
- ``v2.7.0`` / ``2.7.0``(可选 ``v`` 前缀)
- ``2.7.0`` vs ``2.10.0``(按数值而非字典序比较)
- ``2.7.0`` 正式版 > ``2.7.0-beta`` 预发布
- ``2.7.0-rc.2`` > ``2.7.0-rc.1``
- ``2.7.0+build.5`` 构建元数据被忽略

无法解析的版本串按"相等"处理(返回 0),避免把脏数据误判为新版本。
"""
import re
from typing import List, Optional, Tuple

# 版本号正则:主.次.修 可选,后接可选预发布(-xxx)与构建元数据(+xxx)
_VERSION_RE = re.compile(
    r'^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?'
    r'(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$'
)

# 预发布类型排序:dev < alpha/a < beta/b < rc < (正式版,无 pre)
# 正式版的 rank 固定为 1,任何预发布都小于 1
_PRE_RANK = {'dev': -3, 'alpha': -2, 'a': -2, 'beta': -1, 'b': -1, 'rc': 0}


def parse_version(s: str) -> Optional[Tuple[Tuple[int, int, int], int, List]]:
    """解析版本串。

    返回 ``((major, minor, patch), pre_rank, pre_parts)``:
    - 正式版 ``pre_rank=1``、``pre_parts=[]``(永远大于任何预发布)
    - 预发布 ``pre_rank`` 取自 ``_PRE_RANK``、``pre_parts`` 为数字标识符列表
    - 无法解析返回 ``None``
    """
    m = _VERSION_RE.match((s or '').strip())
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    pre = m.group(4)
    if not pre:
        return ((major, minor, patch), 1, [])
    parts = pre.split('.')
    head = parts[0].lower()
    mt = re.match(r'([a-z]+)(\d*)', head)
    key = mt.group(1) if mt else head
    pre_rank = _PRE_RANK.get(key, -4)  # 未知标识按最弱处理,避免误判为新版
    num = int(mt.group(2)) if mt and mt.group(2) else 0
    rest = []
    for p in parts[1:]:
        rest.append(int(p) if p.isdigit() else p)
    return ((major, minor, patch), pre_rank, [num] + rest)


def compare_versions(a: str, b: str) -> int:
    """比较两个版本串。

    :return: ``a > b`` 返回 1,``a < b`` 返回 -1,相等返回 0;
             任一无法解析按 0 处理(视为相等,保守不升级)。
    """
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return 0
    # 1. 主版本号逐位数值比较
    if pa[0] != pb[0]:
        return 1 if pa[0] > pb[0] else -1
    # 2. 同版本号下正式版 > 预发布
    if pa[1] != pb[1]:
        return 1 if pa[1] > pb[1] else -1
    # 3. 同预发布类型,逐个比较数字标识符
    for x, y in zip(pa[2], pb[2]):
        if x == y:
            continue
        # SemVar 规定:数字标识符永远小于字母标识符
        if isinstance(x, int) and not isinstance(y, int):
            return -1
        if isinstance(y, int) and not isinstance(x, int):
            return 1
        return 1 if x > y else -1
    # 4. 字段更少的预发布版本更小(2.7.0-rc.1 > 2.7.0-rc.1.beta)
    if len(pa[2]) != len(pb[2]):
        return 1 if len(pa[2]) > len(pb[2]) else -1
    return 0


def is_newer(remote: str, local: str) -> bool:
    """远端版本是否比本地版本新。"""
    return compare_versions(remote, local) > 0
