"""
JumpServer URL Scheme 处理模块
支持解析 jms:// 和 ssh:// 协议 URL，以及命令行参数
"""
import argparse
import base64
import json
import os
import urllib.parse
import logging

logger = logging.getLogger(__name__)


def parse_arguments():
    """
    解析命令行参数
    支持：
      - 位置参数 url（如 jms://ssh?token=xxx 或 ssh://user@host:port）
      - --url 标志参数（同上）
      - --host, --port, --user, --password 直接指定连接信息

    返回 (args, remaining_argv)
    remaining_argv 用于传给 QApplication
    """
    parser = argparse.ArgumentParser(description='CubeShell - SSH Terminal Client')
    parser.add_argument('url', nargs='?', default=None,
                        help='URL scheme (jms://... or ssh://...)')
    parser.add_argument('--url', dest='url_flag', default=None,
                        help='URL scheme via flag')
    parser.add_argument('--host', default=None, help='SSH host address')
    parser.add_argument('--port', type=int, default=22, help='SSH port (default: 22)')
    parser.add_argument('--user', default=None, help='SSH username')
    parser.add_argument('--password', default=None, help='SSH password')

    args, remaining = parser.parse_known_args()
    return args, remaining


def _parse_jms_base64(payload):
    """
    尝试将 payload 作为 Base64 编码的 JSON 解析（JumpServer v2 格式）。
    成功返回 connection_info dict，失败返回 None。
    """
    try:
        # 补齐 Base64 padding
        missing_padding = len(payload) % 4
        if missing_padding:
            payload += '=' * (4 - missing_padding)

        decoded_bytes = base64.b64decode(payload, validate=True)
        data = json.loads(decoded_bytes.decode('utf-8'))
    except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        return None

    # 必须包含 endpoint 和 token 字段才认为是有效的 v2 格式
    endpoint = data.get('endpoint')
    token = data.get('token')
    if not endpoint or not token:
        return None

    asset = data.get('asset', {})

    print(f"[CubeShell] parse_jms_url: detected Base64 payload, decoded JSON keys: {list(data.keys())}")
    print(f"[CubeShell] parse_jms_url: endpoint={data.get('endpoint')}, asset={asset.get('name')}")

    connection_info = {
        'host': endpoint['host'],
        'port': int(endpoint.get('port', 2222)),
        'user': f"JMS-{token['id']}",
        'password': token['value'],
        'asset_name': asset.get('name', ''),
        'protocol': data.get('protocol', 'ssh'),
    }

    logger.info(f"Parsed JMS Base64 URL: host={connection_info['host']}, "
                f"port={connection_info['port']}, user={connection_info['user']}, "
                f"asset={connection_info['asset_name']}")

    return connection_info


def _parse_jms_query_string(without_scheme):
    """
    解析旧格式 JumpServer URL（query string 形式）作为 fallback。
    格式: jms://ssh?token=xxx&server=xxx
    """
    # 分离路径和查询参数
    if '?' in without_scheme:
        path_part, query_string = without_scheme.split('?', 1)
    else:
        path_part = without_scheme
        query_string = ''

    params = urllib.parse.parse_qs(query_string)

    # 提取路径中的信息
    asset_id = None
    if '/' in path_part:
        parts = path_part.split('/')
        if parts[0] == 'asset' and len(parts) > 1:
            asset_id = parts[1]

    connection_info = {
        'token': params.get('token', [None])[0],
        'server': params.get('server', [None])[0],
        'host': params.get('host', [None])[0],
        'port': int(params.get('port', ['22'])[0]),
        'user': params.get('user', [params.get('account', [None])[0]])[0],
        'password': params.get('password', [None])[0],
        'protocol': params.get('protocol', ['ssh'])[0],
        'asset_id': asset_id,
    }

    logger.info(f"Parsed JMS URL (legacy): host={connection_info['host']}, "
                f"port={connection_info['port']}, user={connection_info['user']}, "
                f"has_token={'yes' if connection_info['token'] else 'no'}")

    return connection_info


def parse_jms_url(url):
    """
    解析 JumpServer Deep Link URL

    支持两种格式：
      1. Base64 JSON 格式（v2）：jms://<base64_encoded_json>
      2. Query String 格式（旧版 fallback）：jms://ssh?token=<token>&server=<server>

    返回 connection_info 字典，失败返回 None。
    """
    if not url or not url.startswith('jms://'):
        return None

    try:
        without_scheme = url[6:].rstrip('/')  # 去掉 'jms://' 及浏览器自动追加的尾部斜线

        # 尝试 Base64 JSON 格式（v2）：payload 中不含 '?' 或 '/' 等 URL 特征字符
        if '?' not in without_scheme and '/' not in without_scheme:
            result = _parse_jms_base64(without_scheme)
            if result:
                return result

        # 即使包含特殊字符，也尝试一次 Base64 解码（容错）
        result = _parse_jms_base64(without_scheme)
        if result:
            return result

        # Fallback: 旧格式 query string 解析
        return _parse_jms_query_string(without_scheme)

    except Exception as e:
        logger.error(f"Failed to parse JMS URL '{url}': {e}")
        return None


def parse_ssh_url(url):
    """
    解析标准 SSH URL

    格式示例：
      ssh://user@host:port
      ssh://user:password@host:port
      ssh://host:port
      ssh://host

    返回字典：
    {
        'host': str,
        'port': int,
        'user': str or None,
        'password': str or None,
    }
    """
    if not url or not url.startswith('ssh://'):
        return None

    try:
        parsed = urllib.parse.urlparse(url)

        host = parsed.hostname
        port = parsed.port or 22
        user = parsed.username
        password = parsed.password

        if not host:
            logger.error(f"No host found in SSH URL: {url}")
            return None

        # URL 解码
        if user:
            user = urllib.parse.unquote(user)
        if password:
            password = urllib.parse.unquote(password)

        connection_info = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
        }

        logger.info(f"Parsed SSH URL: host={host}, port={port}, user={user}")

        return connection_info

    except Exception as e:
        logger.error(f"Failed to parse SSH URL '{url}': {e}")
        return None


def parse_cubeshell_url(url_string):
    """
    解析 cubeshell:// 协议 URL

    格式示例：
      cubeshell://open-local?path=/path/to/folder

    返回字典：
    {
        'scheme': 'cubeshell',
        'action': str,       # e.g. 'open-local'
        'path': str,         # URL decoded 路径
    }

    如果 path 参数缺失、路径不存在或不是目录，返回 None。
    """
    if not url_string or not url_string.startswith('cubeshell://'):
        return None

    try:
        parsed = urllib.parse.urlparse(url_string)
        action = parsed.netloc  # e.g. 'open-local'

        # 解析 query string 获取 path 参数
        params = urllib.parse.parse_qs(parsed.query)
        path_list = params.get('path')

        if not path_list or not path_list[0]:
            logger.warning(f"Missing 'path' parameter in cubeshell URL: {url_string}")
            return None

        path = urllib.parse.unquote(path_list[0])

        # 验证路径存在且为目录
        if not os.path.exists(path):
            logger.warning(f"Path does not exist: {path}")
            return None

        if not os.path.isdir(path):
            logger.warning(f"Path is not a directory: {path}")
            return None

        result = {
            'scheme': 'cubeshell',
            'action': action,
            'path': path,
        }

        logger.info(f"Parsed cubeshell URL: action={action}, path={path}")

        return result

    except Exception as e:
        logger.error(f"Failed to parse cubeshell URL '{url_string}': {e}")
        return None


def resolve_connection_info(args):
    """
    从命令行参数中解析出最终的 connection_info

    优先级：URL参数 > 命令行标志参数

    返回 connection_info dict 或 None（如果没有提供连接信息）
    """
    url = args.url or args.url_flag

    if url:
        if url.startswith('jms://'):
            return parse_jms_url(url)
        elif url.startswith('ssh://'):
            return parse_ssh_url(url)
        elif url.startswith('cubeshell://'):
            return parse_cubeshell_url(url)
        else:
            logger.warning(f"Unsupported URL scheme: {url}")
            return None
    elif args.host:
        return {
            'host': args.host,
            'port': args.port,
            'user': args.user,
            'password': args.password,
        }

    return None
