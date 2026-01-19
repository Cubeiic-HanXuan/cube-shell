import logging
import os
import select
import socket
import struct
import threading
from contextlib import suppress

import paramiko

# 常量配置
BUFFER_SIZE = 8192  # 增大缓冲区以提升性能
SOCKET_TIMEOUT = 1.0  # socket 超时时间（秒）
SELECT_TIMEOUT = 1.0  # select 超时时间（秒）
TRANSPORT_CHECK_INTERVAL = 30  # Transport 存活检查间隔（秒）


class ForwarderManager:
    def __init__(self):
        self.tunnels = {}
        self.ssh_clients = {}
        self._lock = threading.Lock()

    def add_tunnel(self, tunnel_id, tunnel):
        with self._lock:
            self.tunnels[tunnel_id] = tunnel

    def remove_tunnel(self, tunnel_id):
        with self._lock:
            if tunnel_id in self.tunnels:
                tunnel = self.tunnels[tunnel_id]
                tunnel.stop()
                # 如果 SSH 客户端没有其他隧道关联，则关闭 SSH 客户端
                self._close_ssh_client_unsafe(tunnel.ssh_client)
                del self.tunnels[tunnel_id]

    def _close_ssh_client_unsafe(self, ssh_client):
        """内部方法：关闭 SSH 客户端（调用前需持有锁）"""
        if ssh_client is None:
            return
        # 从字典中移除并关闭
        if ssh_client in self.ssh_clients:
            del self.ssh_clients[ssh_client]
        with suppress(Exception):
            ssh_client.close()

    def close_ssh_client(self, ssh_client):
        with self._lock:
            self._close_ssh_client_unsafe(ssh_client)

    def is_transport_alive(self, transport):
        """检查 SSH Transport 是否仍然存活"""
        if transport is None:
            return False
        try:
            return transport.is_active() and transport.is_authenticated()
        except Exception:
            return False

    def start_tunnel(self, tunnel_id, tunnel_type, local_host, local_port, remote_host=None, remote_port=None,
                     ssh_host=None,
                     ssh_port=None, ssh_user=None, ssh_password=None, key_type=None, key_file=None):

        # 检查本地端口权限（非 root 用户不能绑定 < 1024 的端口）
        if local_port < 1024 and os.name != 'nt':  # Windows 不需要检查
            if os.getuid() != 0:
                raise PermissionError(
                    f"绑定端口 {local_port} 需要 root 权限。\n"
                    f"请使用大于 1024 的端口（如 1080、8080 等），或使用 sudo 运行。"
                )

        # 加载私钥
        private_key = None
        if key_type == 'Ed25519Key':
            private_key = paramiko.Ed25519Key.from_private_key_file(key_file)
        elif key_type == 'RSAKey':
            private_key = paramiko.RSAKey.from_private_key_file(key_file)
        elif key_type == 'ECDSAKey':
            private_key = paramiko.ECDSAKey.from_private_key_file(key_file)
        elif key_type == 'DSSKey':
            private_key = paramiko.DSSKey.from_private_key_file(key_file)

        ssh_client = paramiko.SSHClient()
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            connect_kwargs = dict(
                hostname=ssh_host,
                port=ssh_port,
                username=ssh_user,
                timeout=10,
                banner_timeout=30,
                auth_timeout=20,
                allow_agent=True,  # 允许使用 SSH agent
                look_for_keys=True,  # 允许查找默认密钥
            )
            if private_key:
                ssh_client.connect(pkey=private_key, **connect_kwargs)
            elif ssh_password:
                ssh_client.connect(password=ssh_password, **connect_kwargs)
            else:
                # 尝试无密码连接（依赖 SSH agent 或默认密钥）
                ssh_client.connect(**connect_kwargs)

            transport = ssh_client.get_transport()

            # 设置 keepalive 以保持连接存活
            if transport:
                transport.set_keepalive(30)

            if tunnel_type == 'local':
                tunnel = LocalPortForwarder(ssh_client, tunnel_id, transport, remote_host, remote_port, local_host,
                                            local_port)
            elif tunnel_type == 'remote':
                tunnel = RemotePortForwarder(ssh_client, tunnel_id, transport, local_host, local_port, remote_host,
                                             remote_port)
            elif tunnel_type == 'dynamic':
                tunnel = DynamicPortForwarder(ssh_client, tunnel_id, transport, local_host, local_port)
            else:
                raise ValueError("Invalid tunnel type.")

            tunnel.start()

            return tunnel, ssh_client, transport
        except paramiko.AuthenticationException as e:
            logging.error(f"SSH 认证失败: {e}")
            with suppress(Exception):
                ssh_client.close()
            raise Exception(f"SSH 认证失败，请检查用户名/密码/密钥是否正确: {e}")
        except paramiko.SSHException as e:
            logging.error(f"SSH 连接错误: {e}")
            with suppress(Exception):
                ssh_client.close()
            raise Exception(f"SSH 连接失败: {e}")
        except socket.error as e:
            logging.error(f"网络连接错误: {e}")
            with suppress(Exception):
                ssh_client.close()
            raise Exception(f"无法连接到 SSH 服务器 {ssh_host}:{ssh_port}: {e}")
        except Exception as e:
            logging.error(f"Error starting tunnel: {e}")
            with suppress(Exception):
                ssh_client.close()
            raise


class LocalPortForwarder(threading.Thread):
    """
    本地端口转发
    支持多个并发连接，每个连接独立管理
    """

    def __init__(self, ssh_client, tunnel_id, ssh_transport, remote_host, remote_port, local_host, local_port):
        super(LocalPortForwarder, self).__init__()
        self.daemon = True
        self.tunnel_id = tunnel_id
        self.ssh_transport = ssh_transport
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_host = local_host
        self.local_port = local_port
        self.ssh_client = ssh_client
        self._stop_event = threading.Event()
        self.listen_socket = None
        self._active_connections = []
        self._conn_lock = threading.Lock()

    def stop(self):
        self._stop_event.set()
        # 关闭监听 socket
        if self.listen_socket:
            try:
                self.listen_socket.close()
                self.listen_socket = None
                logging.info(f"Socket on port {self.local_port} has been closed")
            except Exception as e:
                logging.error(f"Exception in ForwardServer.stop: {e}")
        # 关闭所有活动连接
        with self._conn_lock:
            for conn in self._active_connections:
                with suppress(Exception):
                    conn.close()
            self._active_connections.clear()

    def run(self):
        try:
            # 创建本地监听的套接字
            self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listen_socket.settimeout(SOCKET_TIMEOUT)  # 设置超时以支持优雅停止

            try:
                self.listen_socket.bind((self.local_host, self.local_port))
            except OSError as e:
                if e.errno == 98 or e.errno == 48:  # 端口已被占用
                    logging.error(f"端口 {self.local_port} 已被占用")
                else:
                    logging.error(f"Error binding socket: {e}")
                return
            except Exception as e:
                logging.error(f"Error binding socket: {e}")
                return

            self.listen_socket.listen(100)
            logging.info(f"Listening for connections on {self.local_host}:{self.local_port}...")

            while not self._stop_event.is_set():
                try:
                    client_socket, addr = self.listen_socket.accept()
                    logging.info(f"Received connection from {addr[0]}:{addr[1]}")

                    # 检查 transport 是否仍然存活
                    if not self.ssh_transport or not self.ssh_transport.is_active():
                        logging.error("SSH transport is not active, closing connection")
                        client_socket.close()
                        self._stop_event.set()
                        break

                    # 通过 SSH 隧道创建新的通道
                    try:
                        channel = self.ssh_transport.open_channel(
                            kind='direct-tcpip',
                            dest_addr=(self.remote_host, self.remote_port),
                            src_addr=addr,
                            timeout=10
                        )
                    except Exception as e:
                        logging.error(f"Failed to open SSH channel: {e}")
                        client_socket.close()
                        continue

                    if channel:
                        with self._conn_lock:
                            self._active_connections.append(client_socket)
                        # 创建转发线程
                        t = threading.Thread(
                            target=self._forward_data,
                            args=(client_socket, channel),
                            daemon=True
                        )
                        t.start()
                    else:
                        logging.warning("Failed to open channel.")
                        client_socket.close()

                except socket.timeout:
                    # 超时是正常的，继续循环检查停止事件
                    continue
                except OSError as e:
                    if self._stop_event.is_set():
                        break
                    logging.error(f"Error accepting connection: {e}")
        except Exception as e:
            logging.error(f"LocalPortForwarder error: {e}")
        finally:
            self.stop()

    def _forward_data(self, client_socket, channel):
        """双向转发数据，每个连接独立管理"""
        try:
            while not self._stop_event.is_set():
                # 使用 select 监听 client_socket 和 channel，并设置超时
                try:
                    r, w, x = select.select([client_socket, channel], [], [], SELECT_TIMEOUT)
                except (ValueError, OSError):
                    # socket 已关闭
                    break

                if not r:
                    # 超时，继续循环
                    continue

                # 如果 client_socket 有数据可读
                if client_socket in r:
                    try:
                        data = client_socket.recv(BUFFER_SIZE)
                        if len(data) <= 0:
                            break
                        channel.send(data)
                    except Exception as e:
                        logging.debug(f"Error receiving data from client: {e}")
                        break

                # 如果 channel 有数据可读
                if channel in r:
                    try:
                        data = channel.recv(BUFFER_SIZE)
                        if len(data) <= 0:
                            break
                        client_socket.send(data)
                    except Exception as e:
                        logging.debug(f"Error receiving data from channel: {e}")
                        break
        finally:
            # 仅关闭当前连接，不影响其他连接
            with suppress(Exception):
                channel.close()
            with suppress(Exception):
                client_socket.close()
            with self._conn_lock:
                if client_socket in self._active_connections:
                    self._active_connections.remove(client_socket)
            logging.debug("Connection closed.")


class RemotePortForwarder(threading.Thread):
    """
    远程端口转发
    将远程服务器的端口转发到本地
    """

    def __init__(self, ssh_client, tunnel_id, ssh_transport, local_host, local_port, remote_host, remote_port):
        super(RemotePortForwarder, self).__init__()
        self.daemon = True
        self.tunnel_id = tunnel_id
        self.ssh_transport = ssh_transport
        self.local_host = local_host
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.ssh_client = ssh_client
        self._shutdown_event = threading.Event()
        self._active_handlers = []
        self._handler_lock = threading.Lock()

    def stop(self):
        self._shutdown_event.set()
        # 取消端口转发请求
        with suppress(Exception):
            if self.ssh_transport and self.ssh_transport.is_active():
                self.ssh_transport.cancel_port_forward('', self.local_port)
        # 关闭所有活动的处理线程的 socket
        with self._handler_lock:
            self._active_handlers.clear()

    def run(self):
        try:
            # 请求远程端口转发
            self.ssh_transport.request_port_forward('', self.local_port)
            logging.info(f"Remote port forwarding started on port {self.local_port}")

            while not self._shutdown_event.is_set():
                # accept 设置超时以便检查停止事件
                chan = self.ssh_transport.accept(timeout=SELECT_TIMEOUT)
                if chan is None or self._shutdown_event.is_set():
                    continue

                # 检查 transport 是否仍然存活
                if not self.ssh_transport.is_active():
                    logging.error("SSH transport is not active")
                    break

                t = threading.Thread(
                    target=self._handle_connection,
                    args=(chan,),
                    daemon=True
                )
                t.start()

        except Exception as e:
            logging.error(f"RemotePortForwarder error: {e}")
        finally:
            self.stop()

    def _handle_connection(self, chan):
        """处理单个连接的转发"""
        sock = socket.socket()
        sock.settimeout(10)  # 连接超时

        try:
            sock.connect((self.remote_host, self.remote_port))
            sock.settimeout(None)  # 连接后取消超时
        except (socket.error, Exception) as e:
            logging.error(f"Forwarding failed to {self.remote_host}:{self.remote_port}: {e}")
            self._close_resources(chan, sock)
            return

        origin_addr = getattr(chan, 'origin_addr', ('unknown', 0))
        logging.info(f"Connected! Tunnel open {origin_addr} -> ({self.remote_host}, {self.remote_port})")

        try:
            while not self._shutdown_event.is_set():
                try:
                    r, w, x = select.select([sock, chan], [], [], SELECT_TIMEOUT)
                except (ValueError, OSError):
                    break

                if not r:
                    continue

                if sock in r:
                    try:
                        data = sock.recv(BUFFER_SIZE)
                        if len(data) == 0:
                            break
                        chan.send(data)
                    except Exception:
                        break

                if chan in r:
                    try:
                        data = chan.recv(BUFFER_SIZE)
                        if len(data) == 0:
                            break
                        sock.send(data)
                    except Exception:
                        break
        finally:
            self._close_resources(chan, sock)
            logging.info(f"Tunnel closed from {origin_addr}")

    def _close_resources(self, chan, sock):
        with suppress(Exception):
            chan.close()
        with suppress(Exception):
            sock.close()


class DynamicPortForwarder(threading.Thread):
    """
    动态端口转发（SOCKS5 代理）
    创建一个本地 SOCKS5 代理服务器，通过 SSH 隧道转发所有连接
    """

    # SOCKS5 协议常量
    SOCKS_VERSION = 0x05
    SOCKS_AUTH_NONE = 0x00
    SOCKS_CMD_CONNECT = 0x01
    SOCKS_ATYP_IPV4 = 0x01
    SOCKS_ATYP_DOMAIN = 0x03
    SOCKS_ATYP_IPV6 = 0x04

    def __init__(self, ssh_client, tunnel_id, ssh_transport, local_host, local_port):
        super().__init__()
        self.daemon = True
        self.tunnel_id = tunnel_id
        self.ssh_transport = ssh_transport
        self.ssh_client = ssh_client
        self.local_host = local_host
        self.local_port = local_port
        self.server_socket = None
        self._stop_event = threading.Event()
        self._active_channels = []
        self._channels_lock = threading.Lock()

    def run(self):
        try:
            # 创建 SOCKS5 代理服务器
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(SOCKET_TIMEOUT)  # 设置超时以支持优雅停止

            try:
                self.server_socket.bind((self.local_host, self.local_port))
            except OSError as e:
                if e.errno == 98 or e.errno == 48:  # EADDRINUSE
                    logging.error(f"端口 {self.local_port} 已被占用")
                elif e.errno == 13:  # EACCES
                    logging.error(f"没有权限绑定端口 {self.local_port}，请使用大于 1024 的端口")
                else:
                    logging.error(f"绑定端口失败: {e}")
                return

            self.server_socket.listen(100)  # 增加最大等待连接数
            logging.info(f"SOCKS5 proxy listening on {self.local_host}:{self.local_port}")

            while not self._stop_event.is_set():
                try:
                    client_socket, addr = self.server_socket.accept()
                    logging.info(f"Accepted connection from {addr}")

                    # 检查 transport 是否仍然存活
                    if not self.ssh_transport or not self.ssh_transport.is_active():
                        logging.error("SSH transport is not active, rejecting connection")
                        client_socket.close()
                        continue

                    t = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket,),
                        daemon=True
                    )
                    t.start()

                except socket.timeout:
                    # 超时是正常的，继续循环检查停止事件
                    continue
                except OSError as e:
                    if self._stop_event.is_set():
                        break
                    logging.error(f"Error accepting connection: {e}")

        except Exception as e:
            logging.error(f"Error in DynamicPortForwarder thread: {e}")
        finally:
            self.stop()

    def stop(self):
        self._stop_event.set()

        # 关闭服务器 socket
        if self.server_socket:
            with suppress(Exception):
                self.server_socket.close()
            self.server_socket = None

        # 关闭所有已打开的通道
        with self._channels_lock:
            for channel in self._active_channels:
                with suppress(Exception):
                    channel.close()
            self._active_channels.clear()

    def _handle_client(self, client_socket):
        """处理 SOCKS5 客户端连接"""
        channel = None
        try:
            client_socket.settimeout(30)  # 客户端超时

            # SOCKS5 握手
            if not self._socks5_handshake(client_socket):
                return

            # 解析 SOCKS5 请求
            dst_addr, dst_port = self._parse_socks5_request(client_socket)
            if not dst_addr:
                return

            logging.info(f"SOCKS5 connecting to {dst_addr}:{dst_port}")

            # 创建到远程服务器的 SSH 通道
            try:
                channel = self.ssh_transport.open_channel(
                    "direct-tcpip",
                    (dst_addr, dst_port),
                    (self.local_host, 0),
                    timeout=15
                )
            except paramiko.ChannelException as e:
                logging.error(f"Failed to open SSH channel to {dst_addr}:{dst_port}: {e}")
                self._send_socks5_error(client_socket, 0x05)  # Connection refused
                return
            except Exception as e:
                logging.error(f"SSH channel error: {e}")
                self._send_socks5_error(client_socket, 0x01)  # General failure
                return

            if not channel:
                logging.error(f"Failed to open channel to {dst_addr}:{dst_port}")
                self._send_socks5_error(client_socket, 0x01)  # General failure
                return

            # 注册通道
            with self._channels_lock:
                self._active_channels.append(channel)

            # 发送 SOCKS5 连接成功响应
            response = bytes([
                self.SOCKS_VERSION, 0x00, 0x00, self.SOCKS_ATYP_IPV4,
                0, 0, 0, 0,  # 绑定地址 0.0.0.0
                (dst_port >> 8) & 0xff, dst_port & 0xff  # 端口
            ])
            client_socket.send(response)

            client_socket.settimeout(None)  # 转发时取消超时

            # 双向转发数据
            self._forward_data(client_socket, channel)

        except socket.timeout:
            logging.warning("SOCKS5 client timeout")
        except Exception as e:
            logging.error(f"Error handling SOCKS5 client: {e}")
        finally:
            with suppress(Exception):
                client_socket.close()
            if channel:
                with suppress(Exception):
                    channel.close()
                with self._channels_lock:
                    if channel in self._active_channels:
                        self._active_channels.remove(channel)
            logging.debug("SOCKS5 connection closed.")

    def _socks5_handshake(self, client_socket):
        """处理 SOCKS5 握手"""
        try:
            # 接收客户端问候
            data = client_socket.recv(256)
            if len(data) < 2:
                return False

            version = data[0]
            if version != self.SOCKS_VERSION:
                logging.warning(f"Unsupported SOCKS version: {version}")
                return False

            # 发送无认证响应
            client_socket.send(bytes([self.SOCKS_VERSION, self.SOCKS_AUTH_NONE]))
            return True

        except Exception as e:
            logging.error(f"SOCKS5 handshake error: {e}")
            return False

    def _parse_socks5_request(self, client_socket):
        """解析 SOCKS5 连接请求"""
        try:
            # 接收 SOCKS5 连接请求
            data = client_socket.recv(256)
            if len(data) < 4:
                self._send_socks5_error(client_socket, 0x01)
                return None, None

            version, cmd, rsv, atyp = data[0], data[1], data[2], data[3]

            if version != self.SOCKS_VERSION:
                self._send_socks5_error(client_socket, 0x01)
                return None, None

            if cmd != self.SOCKS_CMD_CONNECT:
                logging.warning(f"Unsupported SOCKS5 command: {cmd}")
                self._send_socks5_error(client_socket, 0x07)  # Command not supported
                return None, None

            # 解析目标地址
            dst_addr = None
            dst_port = None

            if atyp == self.SOCKS_ATYP_IPV4:
                # IPv4
                if len(data) < 10:
                    self._send_socks5_error(client_socket, 0x01)
                    return None, None
                dst_addr = socket.inet_ntoa(data[4:8])
                dst_port = struct.unpack('!H', data[8:10])[0]

            elif atyp == self.SOCKS_ATYP_DOMAIN:
                # 域名
                if len(data) < 5:
                    self._send_socks5_error(client_socket, 0x01)
                    return None, None
                domain_len = data[4]
                if len(data) < 5 + domain_len + 2:
                    self._send_socks5_error(client_socket, 0x01)
                    return None, None
                dst_addr = data[5:5 + domain_len].decode('utf-8')
                dst_port = struct.unpack('!H', data[5 + domain_len:7 + domain_len])[0]

            elif atyp == self.SOCKS_ATYP_IPV6:
                # IPv6
                if len(data) < 22:
                    self._send_socks5_error(client_socket, 0x01)
                    return None, None
                dst_addr = socket.inet_ntop(socket.AF_INET6, data[4:20])
                dst_port = struct.unpack('!H', data[20:22])[0]

            else:
                logging.warning(f"Unsupported address type: {atyp}")
                self._send_socks5_error(client_socket, 0x08)  # Address type not supported
                return None, None

            return dst_addr, dst_port

        except Exception as e:
            logging.error(f"SOCKS5 request parsing error: {e}")
            self._send_socks5_error(client_socket, 0x01)
            return None, None

    def _send_socks5_error(self, client_socket, error_code):
        """发送 SOCKS5 错误响应"""
        try:
            response = bytes([
                self.SOCKS_VERSION, error_code, 0x00, self.SOCKS_ATYP_IPV4,
                0, 0, 0, 0, 0, 0
            ])
            client_socket.send(response)
        except Exception:
            pass

    def _forward_data(self, client_socket, channel):
        """双向转发数据"""
        try:
            while not self._stop_event.is_set():
                try:
                    r, w, x = select.select([client_socket, channel], [], [], SELECT_TIMEOUT)
                except (ValueError, OSError):
                    break

                if not r:
                    continue

                if client_socket in r:
                    try:
                        data = client_socket.recv(BUFFER_SIZE)
                        if len(data) == 0:
                            break
                        channel.send(data)
                    except Exception:
                        break

                if channel in r:
                    try:
                        data = channel.recv(BUFFER_SIZE)
                        if len(data) == 0:
                            break
                        client_socket.send(data)
                    except Exception:
                        break
        except Exception as e:
            logging.debug(f"Forward data error: {e}")


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
