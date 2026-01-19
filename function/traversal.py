def frpc(server_addr, token, ant_type, local_port, remote_port):
    """
    客户端配置文件
    :param server_addr: 服务端IP地址
    :param token: 认证密钥
    :param ant_type: 穿透类型 (TCP/HTTP/UDP)
    :param local_port: 本地端口（客户端代理端口）
    :param remote_port: 远程端口（服务端代理端口）
    :return:
    """
    return f"""serverAddr = "{server_addr}"
serverPort = 7000
auth.token = "{token}"

{proxy_config(ant_type, local_port, remote_port, server_addr)}
"""


def proxy_config(ant_type, local_port, remote_port, server_addr=""):
    """
    生成代理配置
    :param ant_type: 代理类型 TCP/HTTP/UDP
    :param local_port: 本地端口
    :param remote_port: 远程端口
    :param server_addr: 服务器地址（HTTP类型需要）
    """
    proxy_type = ant_type.lower()
    
    if proxy_type == "http":
        # HTTP 类型：用于域名绑定的 HTTP 服务
        # 访问方式: http://服务器IP:服务端端口
        return f"""[[proxies]]
name = "http_proxy"
type = "http"
localIP = "127.0.0.1"
localPort = {local_port}
customDomains = ["{server_addr}"]
"""
    elif proxy_type == "udp":
        # UDP 类型：用于 DNS、游戏服务器等 UDP 协议服务
        return f"""[[proxies]]
name = "udp_proxy"
type = "udp"
localIP = "127.0.0.1"
localPort = {local_port}
remotePort = {remote_port}
"""
    else:
        # TCP 类型：最通用，支持任何 TCP 协议
        return f"""[[proxies]]
name = "tcp_proxy"
type = "tcp"
localIP = "127.0.0.1"
localPort = {local_port}
remotePort = {remote_port}
"""


def frps(token, ant_type="tcp", http_port=None):
    """
    服务端配置文件
    :param token: 认证密钥
    :param ant_type: 代理类型
    :param http_port: HTTP 虚拟主机端口（仅 HTTP 类型需要）
    :return:
    """
    config = f"""bindPort = 7000
auth.token = "{token}"
"""
    
    # HTTP 类型需要配置 vhostHTTPPort
    if ant_type.lower() == "http" and http_port:
        config += f"vhostHTTPPort = {http_port}\n"
    
    return config
