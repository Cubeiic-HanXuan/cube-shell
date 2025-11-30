import logging
from contextlib import suppress

import paramiko
import socket
import threading
import select
import time


class ForwarderManager:
    def __init__(self):
        self.tunnels = {}
        self.ssh_clients = {}

    def add_tunnel(self, tunnel_id, tunnel):
        self.tunnels[tunnel_id] = tunnel

    def remove_tunnel(self, tunnel_id):
        if tunnel_id in self.tunnels:
            tunnel = self.tunnels[tunnel_id]
            tunnel.stop()

            # 给隧道一些时间来完全关闭
            time.sleep(1)
            # 如果 SSH 客户端没有其他隧道关联，则关闭 SSH 客户端
            self.close_ssh_client(tunnel.ssh_client)
            del self.tunnels[tunnel_id]

    def close_ssh_client(self, ssh_client):
        if ssh_client in self.ssh_clients:
            with suppress(Exception):
                ssh_client.close()
            del self.ssh_clients[ssh_client]

    def start_tunnel(self, tunnel_id, tunnel_type, local_host, local_port, remote_host=None, remote_port=None,
                     ssh_host=None,
                     ssh_port=None, ssh_user=None, ssh_password=None, key_type=None, key_file=None):

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
            if private_key:
                ssh_client.connect(hostname=ssh_host, port=ssh_port, username=ssh_user, pkey=private_key)
            else:
                ssh_client.connect(hostname=ssh_host, port=ssh_port, username=ssh_user, password=ssh_password)

            transport = ssh_client.get_transport()

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
        except Exception as e:
            logging.error(f"Error starting tunnel: {e}")
            with suppress(Exception):
                ssh_client.close()
            raise


class LocalPortForwarder(threading.Thread):
    """
    本地端口转发
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
        self.running = False
        self.listen_socket = None
        self.client_socket = None
        self.lock = threading.Lock()  # 添加锁

    def stop(self):
        with self.lock:  # 使用锁保护对 running 的修改
            self.running = False
        if self.listen_socket:
            try:
                self.listen_socket.close()
                self.listen_socket = None
                logging.info(f"Socket on port {self.local_port} has been closed")
            except Exception as e:
                logging.error(f"Exception in ForwardServer.stop: {e}")

    def run(self):
        self.running = True
        try:
            # 创建本地监听的套接字
            self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.listen_socket.bind((self.local_host, self.local_port))  # 增加异常处理
            except Exception as e:
                logging.error(f"Error binding socket: {e}")
                return
            self.listen_socket.listen(100)
            logging.info(f"Listening for connections on {self.local_host}:{self.local_port}...")

            while self.running:
                try:
                    client_socket, addr = self.listen_socket.accept()
                    logging.info(f"Received connection from {addr[0]}:{addr[1]}")

                    self.client_socket = client_socket

                    # 通过 SSH 隧道创建新的通道
                    channel = self.ssh_transport.open_channel(
                        kind='direct-tcpip',
                        dest_addr=(self.remote_host, self.remote_port),
                        src_addr=addr
                    )

                    if channel:
                        # 创建转发线程
                        threading.Thread(target=self.forward_data, args=(client_socket, channel)).start()
                    else:
                        logging.warning("Failed to open channel.")
                        client_socket.close()
                except socket.timeout:
                    # 可以在这里增加一个超时检查，防止无限等待
                    pass
                except Exception as e:
                    self.running = False
                    logging.error(f"Error accepting connection: {e}")
        finally:
            self.stop()

    def forward_data(self, client_socket, channel):
        try:
            while self.running:
                # 使用 select 监听 client_socket 和 channel
                r, w, x = select.select([client_socket, channel], [], [])
                # 如果 client_socket 有数据可读
                if client_socket in r:
                    try:
                        data = client_socket.recv(1024)
                        if len(data) <= 0:
                            # 如果没有读取到数据，说明连接已关闭
                            break
                        # 将数据发送到 channel
                        channel.send(data)
                    except Exception as e:
                        print(f"Error receiving data from client: {e}")
                        break
                # 如果 channel 有数据可读
                if channel in r:
                    try:
                        data = channel.recv(1024)
                        if len(data) <= 0:
                            # 如果没有读取到数据，说明连接已关闭
                            break
                        # 将数据发送回 client_socket
                        client_socket.send(data)
                    except Exception as e:
                        print(f"Error receiving data from channel: {e}")
                        break
        finally:
            with self.lock:
                self.running = False
            channel.close()
            client_socket.close()
            print("Connection closed.")


class RemotePortForwarder(threading.Thread):
    """
    远程端口转发
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
        self.running = False
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()  # 添加锁

    def stop(self):
        with self._lock:
            self.running = False
        self._shutdown_event.set()

    def run(self):
        self.running = True
        self._shutdown_event.clear()
        self.ssh_transport.request_port_forward('', self.local_port)

        while self.running and not self._shutdown_event.is_set():
            chan = self.ssh_transport.accept(1000)
            if chan is None or not self.running:
                continue

            thr = threading.Thread(target=self.handle, args=(chan,))
            thr.setDaemon(True)
            thr.start()

    def handle(self, chan):
        sock = socket.socket()
        try:
            sock.connect((self.remote_host, self.remote_port))
        except (socket.error, Exception) as e:
            logging.error(f"Forwarding failed: {e}")
            self._close_resources(chan, sock)
            return

        logging.info(f"Connected! Tunnel open {chan.origin_addr} -> ({self.remote_host}, {self.remote_port})")

        while self.running and not self._shutdown_event.is_set():
            r, w, x = select.select([sock, chan], [], [])
            if sock in r:
                data = sock.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                sock.send(data)

        self._close_resources(chan, sock)
        logging.info(f"Tunnel closed from {chan.origin_addr}")

    def _close_resources(self, chan, sock):
        chan.close()
        sock.close()


class DynamicPortForwarder(threading.Thread):
    def __init__(self, ssh_client, tunnel_id, ssh_transport, local_host, local_port):
        super().__init__()
        self.tunnel_id = tunnel_id
        self.ssh_transport = ssh_transport
        self.ssh_client = ssh_client
        self.local_host = local_host
        self.local_port = local_port
        self.server_socket = None
        self._stop_event = threading.Event()
        # self.running = False
        self.channels = []
        self.channels_lock = threading.Lock()  # 添加锁

    def run(self):
        try:
            # 创建一个SOCKS5代理服务器
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.local_host, self.local_port))
            self.server_socket.listen(10)

            logging.info(f"SOCKS5 proxy listening on {self.local_host}:{self.local_port}")

            while not self._stop_event.is_set():
                client_socket, addr = self.server_socket.accept()
                logging.info(f"Accepted connection from {addr}")
                threading.Thread(target=self._handle_client, args=(client_socket,)).start()

        except Exception as e:
            logging.error(f"Error occurred in DynamicPortForwarder thread.: {e}")
            self.stop()

    def stop(self):
        self._stop_event.set()
        if self.server_socket:
            self.server_socket.close()
        # 关闭所有已打开的通道
        with self.channels_lock:
            for channel in self.channels:
                channel.close()
            self.channels.clear()

    def _handle_client(self, client_socket):
        try:
            # 接收客户端请求
            request = client_socket.recv(4096)

            # 解析SOCKS5请求
            if request[0] == 0x05:  # SOCKS5协议
                # 发送SOCKS5认证响应
                client_socket.send(b"\x05\x00")

                # 接收SOCKS5连接请求
                request = client_socket.recv(4096)

                # 解析目标地址和端口
                dst_addr_type = request[3]
                if dst_addr_type == 0x01:  # IPv4
                    dst_addr = socket.inet_ntoa(request[4:8])
                    dst_port = int.from_bytes(request[8:10], byteorder='big')
                elif dst_addr_type == 0x03:  # 域名
                    dst_addr = request[5:5 + request[4]].decode('utf-8')
                    dst_port = int.from_bytes(request[5 + request[4]:7 + request[4]], byteorder='big')
                elif dst_addr_type == 0x04:  # IPv6
                    dst_addr = socket.inet_ntop(socket.AF_INET6, request[4:20])
                    dst_port = int.from_bytes(request[20:22], byteorder='big')
                else:
                    raise Exception("Unsupported address type")

                # 创建到远程服务器的通道
                try:
                    channel = self.ssh_transport.open_channel("direct-tcpip", (dst_addr, dst_port),
                                                              (self.local_host, 0))
                    if channel:
                        with self.channels_lock:
                            self.channels.append(channel)
                except paramiko.ChannelException as e:
                    logging.error(f"Failed to open SSH channel to {dst_addr}:{dst_port}. Error: {e}")
                    client_socket.send(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")  # 发送SOCKS5连接失败响应
                    client_socket.close()
                    return

                # 发送SOCKS5连接成功响应
                response = b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + dst_port.to_bytes(2, byteorder='big')
                client_socket.send(response)

                try:
                    # 转发数据
                    while not self._stop_event.is_set():
                        r, w, x = select.select([client_socket, channel], [], [], 1)
                        if client_socket in r:
                            data = client_socket.recv(4096)
                            if len(data) == 0:
                                break
                            channel.send(data)
                        if channel in r:
                            data = channel.recv(4096)
                            if len(data) == 0:
                                break
                            client_socket.send(data)
                finally:
                    channel.close()
                    client_socket.close()
                    with self.channels_lock:
                        self.channels.remove(channel)
                    logging.info("Connection closed.")

        except Exception as e:
            logging.error(f"Error handling channel: {e}")
            client_socket.close()


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
