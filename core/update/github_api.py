"""
GitHub Releases API 检查。

通过 ``https://api.github.com/repos/Cubeiic-HanXuan/cube-shell/releases/latest``
拉取最新发行版信息。使用标准库 ``urllib``,零新依赖。

注意事项:
- GitHub REST API **强制要求 User-Agent 头**,缺失直接 403。
- 匿名访问限频 60 次/小时,手动触发频率低,实际很难触发;触发时识别为
  ``RateLimitError`` 由 UI 层给出友好提示。
"""
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List

GITHUB_API = "https://api.github.com/repos/Cubeiic-HanXuan/cube-shell/releases/latest"
RELEASE_PAGE = "https://github.com/Cubeiic-HanXuan/cube-shell/releases/latest"
USER_AGENT = "cube-shell-updater (+https://github.com/Cubeiic-HanXuan/cube-shell)"


@dataclass
class AssetInfo:
    """单个 release 资源(安装包)。"""
    name: str
    browser_download_url: str
    size: int
    content_type: str = ""


@dataclass
class ReleaseInfo:
    """最新 release 元信息。"""
    tag_name: str  # 原始,可能带 v 前缀
    name: str
    body: str  # 更新说明(markdown 原文)
    html_url: str  # 浏览器打开的 release 页(兜底用)
    assets: List[AssetInfo] = field(default_factory=list)


class GitHubApiError(Exception):
    """GitHub API 通用错误(含可读中文消息)。"""


class RateLimitError(GitHubApiError):
    """触发匿名限频(60 次/小时)。"""


def fetch_latest_release(timeout: float = 15.0) -> ReleaseInfo:
    """拉取最新 release。

    :param timeout: 单次请求超时秒数
    :return: ``ReleaseInfo``
    :raises GitHubApiError: 网络/HTTP/解析失败(消息可直接展示给用户)
    :raises RateLimitError: 触发匿名限频
    """
    socket.setdefaulttimeout(timeout)
    req = urllib.request.Request(GITHUB_API, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            remaining = e.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                raise RateLimitError(
                    "GitHub API 访问过于频繁(匿名限频 60 次/小时),请稍后再试,或手动访问 Release 页。"
                )
            raise GitHubApiError(f"GitHub API 拒绝访问(HTTP {e.code})。")
        if e.code == 404:
            raise GitHubApiError("未找到任何 Release,请确认仓库已发布版本。")
        raise GitHubApiError(f"GitHub API 请求失败(HTTP {e.code})。")
    except urllib.error.URLError as e:
        raise GitHubApiError(f"无法连接 GitHub,请检查网络:{e.reason}")
    except socket.timeout:
        raise GitHubApiError("连接 GitHub 超时,请检查网络或代理设置。")
    except GitHubApiError:
        raise
    except Exception as e:
        raise GitHubApiError(f"解析 Release 失败:{e}")

    assets = [
        AssetInfo(
            name=a.get("name", ""),
            browser_download_url=a.get("browser_download_url", ""),
            size=int(a.get("size", 0) or 0),
            content_type=a.get("content_type", ""),
        )
        for a in data.get("assets", [])
    ]
    return ReleaseInfo(
        tag_name=(data.get("tag_name") or "").strip(),
        name=(data.get("name") or "").strip(),
        body=(data.get("body") or "").strip(),
        html_url=data.get("html_url", "") or RELEASE_PAGE,
        assets=assets,
    )
