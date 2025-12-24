import threading
import time
from collections import deque
from typing import Dict, Any

import re
import socket
import paramiko
import uuid

from function import parse_data, util


class SshClient(object):

    def __init__(self, host, port, username, password, key_type, key_file, on_connect_success=None,
                 callback_param=None):
        self.id = str(uuid.uuid4())
        self.host, self.port, self.username, self.password, self.key_type, self.key_file = host, port, username, \
            password, key_type, key_file

        # 添加连接成功回调函数参数
        self.on_connect_success = on_connect_success
        self.callback_param = callback_param

        self.system_info_dict = None
        self.cpu_use, self.mem_use, self.disk_use, self.receive_speed, self.transmit_speed = 0, 0, 0, 0, 0

        # 数据历史和平滑处理
        self._data_history = {
            'cpu': deque(maxlen=5),
            'memory': deque(maxlen=5),
            'disk': deque(maxlen=5),
            'network': {'rx': deque(maxlen=5), 'tx': deque(maxlen=5)}
        }
        # 上次网络读数
        self._last_net_data = None
        self._last_net_time = 0
        # 上次CPU读数
        self._last_cpu_data = None
        self._last_cpu_time = 0
        # 监控间隔(秒)
        self.monitor_interval = 2.0

        self.timer1, self.timer2 = None, None
        self.Shell = None
        self.pwd = ''
        self.isConnected = False
        self.buffer1 = ['▉', '']
        self.buffer3 = ''
        # self.buffer_write = b''
        # 当接收到方向键盘输入时，需要刷新终端
        self.need_refresh_flags = False
        # 下载文件大小
        self.total_size = 0
        # 加载私钥
        if key_type == 'Ed25519Key':
            # ssh-ed25519
            self.private_key = paramiko.Ed25519Key.from_private_key_file(key_file)
        elif key_type == 'RSAKey':
            self.private_key = paramiko.RSAKey.from_private_key_file(key_file)
        elif key_type == 'ECDSAKey':
            self.private_key = paramiko.ECDSAKey.from_private_key_file(key_file)
        elif key_type == 'DSSKey':
            self.private_key = paramiko.DSSKey.from_private_key_file(key_file)
        elif key_type == '':
            self.private_key = None

        # 重连相关属性
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 1  # 初始重连延迟（秒）
        self.heartbeat_interval = 30  # 心跳间隔
        self.lock = threading.Lock()  # 线程锁
        self.active = True  # 连接状态标志
        self._reconnecting = False  # 防抑制并发重连

        # 初始化时直接创建 SSH 客户端
        self._init_ssh_client()
        self.close_sig = 1

        # 是否已经加载过常用容器列表
        self.refresh_docker_common_containers_has_executed = False

    def _init_ssh_client(self):
        """初始化 SSH 客户端"""
        with self.lock:
            self.conn = paramiko.SSHClient()
            self.conn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.channel = None
            self.transport = None

    def is_connected(self):
        """检查连接是否有效"""
        try:
            if self.transport and self.transport.is_active():
                # 发送测试包验证连接
                self.transport.send_ignore()
                return True
            return False
        except Exception as e:
            util.logger.debug(f"连接检查失败: {str(e)}")
            return False

    def connect(self, on_connect_success=None, callback_param=None):
        """
        建立 SSH 连接的方法。
        参数:
        - on_connect_success: 可选的连接成功回调函数，会覆盖初始化时设置的回调
        """
        # 如果提供了新的回调函数，则覆盖初始化时设置的回调
        if on_connect_success is not None:
            self.on_connect_success = on_connect_success

        # 如果提供了新的回调参数，则覆盖初始化时设置的参数
        if callback_param is not None:
            self.callback_param = callback_param

        # 移除循环重试逻辑，因为这会阻塞线程并可能导致递归调用
        # 如果连接失败，抛出异常，由调用者（如 ConnectRunnable）处理重试或报错
        try:
            if self.private_key:
                self.conn.connect(hostname=self.host, port=self.port, username=self.username, pkey=self.private_key,
                                  timeout=5, banner_timeout=15)
            else:
                self.conn.connect(hostname=self.host, port=self.port, username=self.username,
                                  password=self.password, timeout=5, banner_timeout=15)

            # 连接成功后初始化
            self.transport = self.conn.get_transport()
            self.transport.set_keepalive(self.heartbeat_interval)
            self._setup_channel()
            self._start_heartbeat()
            self.reconnect_attempts = 0  # 重置重试计数器

            # 调用连接成功的回调函数
            if self.on_connect_success:
                try:
                    self.on_connect_success(self, self.callback_param)
                except Exception as callback_error:
                    util.logger.error(f"Error in connection success callback: {callback_error}")

            return
        except paramiko.ssh_exception.AuthenticationException:
            util.logger.error("Authentication failed.")
            self.active = False
            raise
        except Exception as e:
            util.logger.error(f"Connection error: {e}")
            self.active = False
            raise

    def _setup_channel(self):
        """设置会话通道"""
        with self.lock:
            try:
                if not self.transport or not self.transport.is_active():
                    self.transport = self.conn.get_transport()
                if not self.transport or not self.transport.is_active():
                    raise RuntimeError("Transport is not active")
                self.channel = self.transport.open_session()
                self.channel.get_pty(term="xterm-256color", width=100, height=200)
                self.channel.invoke_shell()
                self.isConnected = True
            except Exception as e:
                util.logger.error(f"通道初始化失败: {str(e)}")
                raise

    def _start_heartbeat(self):
        """启动心跳线程"""

        def heartbeat():
            while self.active and self.is_connected():
                try:
                    # 使用transport心跳，避免通道被占用或已关闭导致异常
                    if self.transport and self.transport.is_active():
                        try:
                            self.transport.send_ignore()
                        except Exception:
                            pass
                    time.sleep(self.heartbeat_interval)
                except Exception as e:
                    util.logger.warning(f"心跳失败: {str(e)}")
                    # 心跳失败通常意味着连接已断开
                    # 不要在心跳线程中触发重连，这会导致复杂的线程交互和递归问题
                    # 只需退出循环，后续操作会因连接断开而失败，并可能触发重连
                    break 

        # 只有在没有正在运行的心跳线程时才启动
        if not hasattr(self, '_heartbeat_thread') or not self._heartbeat_thread.is_alive():
            self._heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
            self._heartbeat_thread.start()

    def _trigger_reconnect(self):
        """触发重新连接 - 简化版"""
        # 只有当连接被标记为活动时才尝试重连
        if not self.active:
            return

        with self.lock:
            if self._reconnecting:
                return
            self._reconnecting = True
            # 检查是否已经超过最大重试次数
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                util.logger.error("达到最大重连次数，停止重连")
                self._reconnecting = False
                return

            util.logger.info("尝试重新连接...")
            try:
                # 增加重试计数
                self.reconnect_attempts += 1
                
                # 关闭旧连接
                try:
                    if self.channel:
                        self.channel.close()
                    if self.conn:
                        self.conn.close()
                except:
                    pass
                    
                # 轻微延迟，避免复用刚关闭的连接导致通道打开失败
                time.sleep(min(1.0, 0.2 * self.reconnect_attempts))
                # 重新初始化客户端对象，避免旧state残留
                self._init_ssh_client()
                # 重新连接 - 注意：这可能会阻塞，最好在非UI线程调用
                # 由于 connect() 移除了循环，这里可以捕获异常
                try:
                    self.connect()
                finally:
                    self._reconnecting = False
                
            except Exception as e:
                util.logger.error(f"重连失败: {str(e)}")
                # 不要在这里递归调用或等待，让下一次操作触发重连或由用户手动重试
                self._reconnecting = False

    def safe_execute(self, func, *args, **kwargs):
        """执行操作的通用安全包装"""
        # 如果连接已主动关闭，直接返回
        if not self.active:
            return None

        try:
            if not self.is_connected():
                self._trigger_reconnect()
                if not self.is_connected():
                    return None
            return func(*args, **kwargs)
        except (paramiko.SSHException,
                paramiko.ssh_exception.ChannelException,
                paramiko.ssh_exception.NoValidConnectionsError,
                EOFError,
                OSError,
                socket.timeout,
                TimeoutError,
                BrokenPipeError) as e:
            util.logger.error(f"连接异常: {str(e)}")
            self._trigger_reconnect()
            # 尝试一次重连后，如果成功则重试操作，否则返回None
            if self.is_connected():
                try:
                    return func(*args, **kwargs)
                except:
                    return None
            return None
        except Exception as e:
            util.logger.error(f"操作失败: {str(e)}")
            return None

    # 下面是一个便利方法，可以在已经连接的客户端上设置回调并立即触发
    def set_and_trigger_connect_callback(self, callback, callback_param=None):
        """
        设置连接成功的回调并立即触发（如果已连接）

        参数:
        - callback: 连接成功的回调函数，接受SshClient实例和额外参数
        - callback_param: 传递给回调函数的额外参数
        """
        self.on_connect_success = callback

        if callback_param is not None:
            self.callback_param = callback_param

        if self.isConnected and self.on_connect_success:
            try:
                self.on_connect_success(self, self.callback_param)
            except Exception as e:
                util.logger.error(f"Error in connection success callback: {e}")

    def get_read_wait(self):
        """
       获取用于读取操作的等待对象。

       返回:
       - 当前 SSH 通道，用于轮询读取操作。
       """
        return self.channel

    def write(self, data):
        """
       向 SSH 通道写入数据。

       参数:
       - data: 要写入的数据。
       """
        self.channel.send(data)

    # def read(self):
    #     """
    #     从 SSH 通道读取数据，并写入到屏幕。
    #     """
    #     try:
    #         if self.channel.recv_ready():
    #             output = self.channel.recv(4096)
    #             #self.write_to_screen(output)
    #     except Exception as e:
    #         util.logger.error(f"Error while reading from channel: {e}")

    def close(self):
        """
       关闭 SSH 连接，并从多路复用器中移除该后端。
       """

        try:
            self.active = False
            if self.channel:
                self.conn.close()
                self.close_sig = 0
            # 结束心跳线程
            try:
                if hasattr(self, '_heartbeat_thread') and self._heartbeat_thread.is_alive():
                    # 心跳线程将因active=False自然退出，这里小幅等待
                    time.sleep(0.05)
            except:
                pass
        except Exception as e:
            util.logger.debug(f"关闭连接时出错: {str(e)}")
        # finally:
        #     super().close()

    def _exec(self, cmd, pty):
        """实际的命令执行方法"""
        stdin, stdout, stderr = self.conn.exec_command(
            command=cmd,
            get_pty=pty,
            timeout=30
        )
        return stdout.read().decode('utf8')

    def _sudo_exec(self, cmd, pty):
        """实际的命令执行方法"""
        if self.username == 'root':
            stdin, stdout, stderr = self.conn.exec_command(command=cmd, get_pty=pty, timeout=30)
        else:
            stdin, stdout, stderr = self.conn.exec_command(command=f'sudo -S {cmd}', get_pty=pty, timeout=30)
            if self.password:
                stdin.write(f"{self.password}\n")
                stdin.flush()
        return stdout.read().decode('utf8')

    def sudo_exec(self, cmd='', pty=False):
        return self.safe_execute(self._sudo_exec, cmd, pty)

    def exec(self, cmd='', pty=False):
        """
        远程执行命令
        :param cmd:
        :param pty:
        :return:
        """
        return self.safe_execute(self._exec, cmd, pty)

    def send(self, data):
        """
        发送字符
        :param data: 要发送的数据，可以是字符串或字节
        :return:
        """
        self.channel.send(data)

    # sftp
    def open_sftp(self) -> paramiko.sftp_client:
        """
        在SSH服务器上打开一个SFTP会话
        :return: 一个新的"SFTPClient"会话对象
        """
        # sftp_client = self.conn.open_sftp()
        # return sftp_client
        return self.safe_execute(self.conn.open_sftp)

    @staticmethod
    def del_more_space(line: str) -> list:
        s = line.strip()
        if not s or s.startswith('total'):
            return []
        parts = re.split(r'\s+', s)
        if len(parts) < 9:
            return []
        return parts[:8] + [' '.join(parts[8:])]

    def get_cpu_stats(self) -> Dict[str, Any]:
        """获取详细的CPU使用率统计

        Returns:
            Dict包含总体使用率和各核心使用率
        """
        try:
            # 获取第一次CPU状态
            output1 = self.exec(cmd="cat /proc/stat")
            if not output1:
                return {
                    'total_usage': 0,
                    'user_usage': 0,
                    'system_usage': 0,
                    'iowait': 0,
                    'cores_usage': []
                }
            cpu_data1 = parse_data.parse_cpu_data(output1)

            # 等待足够的时间间隔
            time.sleep(self.monitor_interval)

            # 获取第二次CPU状态
            output2 = self.exec(cmd="cat /proc/stat")
            if not output2:
                return {
                    'total_usage': 0,
                    'user_usage': 0,
                    'system_usage': 0,
                    'iowait': 0,
                    'cores_usage': []
                }
            cpu_data2 = parse_data.parse_cpu_data(output2)

            # 计算CPU使用率
            usage_stats = parse_data.calculate_cpu_usage(cpu_data1, cpu_data2)

            # 应用平滑处理
            self._smooth_value('cpu', usage_stats['total_usage'])

            return usage_stats
        except Exception as e:
            util.logger.error(f"获取CPU统计失败: {str(e)}")
            return {
                'total_usage': 0,
                'user_usage': 0,
                'system_usage': 0,
                'iowait': 0,
                'cores_usage': []
            }

    # 内存统计数据收集
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取详细的内存使用统计

        Returns:
            包含内存统计信息的字典
        """
        try:
            output = self.exec(cmd="free -m")
            if not output:
                return {
                    'total': 0,
                    'used': 0,
                    'free': 0,
                    'shared': 0,
                    'cache': 0,
                    'available': 0,
                    'usage_percent': 0
                }

            memory_stats = parse_data.parse_memory_data(output)

            # 应用平滑处理
            self._smooth_value('memory', memory_stats['usage_percent'])

            return memory_stats
        except Exception as e:
            util.logger.error(f"获取内存统计失败: {str(e)}")
            return {
                'total': 0,
                'used': 0,
                'free': 0,
                'shared': 0,
                'cache': 0,
                'available': 0,
                'usage_percent': 0
            }

    # 磁盘统计数据收集
    def get_disk_stats(self) -> Dict[str, Any]:
        """获取详细的磁盘使用统计

        Returns:
            包含磁盘使用信息的字典
        """
        try:
            # 获取磁盘空间使用情况
            df_output = self.exec(cmd="df -h")
            if not df_output:
                return {
                    'partitions': [],
                    'io': {},
                    'root_usage': 0,
                    'total_usage': 0
                }

            # 获取磁盘IO性能数据 (如果有iostat命令)
            try:
                io_output = self.exec(cmd="iostat -d -x 1 2 | tail -n +4")
                has_io_data = True
            except:
                io_output = ""
                has_io_data = False

            # 解析数据
            partitions = parse_data.parse_disk_data(df_output)

            # 如果有IO数据，解析它
            io_stats = {}
            if has_io_data:
                io_stats = parse_data.parse_io_data(io_output)

            # 计算所有分区的总使用率
            total_size = sum(p.get('size_mb', 0) for p in partitions)
            total_used = sum(p.get('used_mb', 0) for p in partitions)
            
            if total_size > 0:
                total_usage_percent = (total_used / total_size) * 100
            else:
                total_usage_percent = 0
            
            # 使用总使用率进行平滑处理
            self._smooth_value('disk', total_usage_percent)
            
            # 获取根分区使用率（仅供参考）
            root_usage = next((p['usage_percent'] for p in partitions if p['mount_point'] == '/'), 0)

            return {
                'partitions': partitions,
                'io': io_stats,
                'root_usage': root_usage,
                'total_usage': total_usage_percent
            }
        except Exception as e:
            util.logger.error(f"获取磁盘统计失败: {str(e)}")
            return {
                'partitions': [],
                'io': {},
                'root_usage': 0
            }

    # 网络统计数据收集
    def get_network_stats(self) -> Dict[str, Any]:
        """获取详细的网络使用统计

        Returns:
            包含网络接口和速率的字典
        """
        try:
            # 获取第一次网络状态
            output1 = self.exec(cmd="cat /proc/net/dev")
            if not output1:
                return {
                    'interfaces': [],
                    'total_rx_speed': 0,
                    'total_tx_speed': 0
                }
            net_data1 = parse_data.parse_network_data(output1)
            timestamp1 = time.time()

            # 等待足够的时间间隔
            time.sleep(self.monitor_interval)

            # 获取第二次网络状态
            output2 = self.exec(cmd="cat /proc/net/dev")
            if not output2:
                return {
                    'interfaces': [],
                    'total_rx_speed': 0,
                    'total_tx_speed': 0
                }
            net_data2 = parse_data.parse_network_data(output2)
            timestamp2 = time.time()

            # 计算网络速率
            interval = timestamp2 - timestamp1
            stats = parse_data.calculate_network_speed(net_data1, net_data2, interval)

            # 应用平滑处理
            main_interface = parse_data.get_main_interface(stats['interfaces'])
            if main_interface:
                self._smooth_value('network', {'rx': main_interface['rx_speed'], 'tx': main_interface['tx_speed']})

                # 更新总速率
                stats['total_rx_speed'] = main_interface['rx_speed']
                stats['total_tx_speed'] = main_interface['tx_speed']

            return stats
        except Exception as e:
            util.logger.error(f"获取网络统计失败: {str(e)}")
            return {
                'interfaces': [],
                'total_rx_speed': 0,
                'total_tx_speed': 0
            }

    # 数据平滑处理
    def _smooth_value(self, data_type: str, value: Any, alpha: float = 0.3) -> Any:
        """使用EMA平滑数据

        Args:
            data_type: 数据类型
            value: 新值
            alpha: 平滑因子 (0-1)，越小平滑效果越强

        Returns:
            平滑后的值
        """
        # 特殊处理网络数据
        if data_type == 'network':
            rx_value = value['rx']
            tx_value = value['tx']

            # 对RX添加到历史并计算平均值
            self._data_history['network']['rx'].append(rx_value)
            smoothed_rx = sum(self._data_history['network']['rx']) / len(self._data_history['network']['rx'])

            # 对TX添加到历史并计算平均值
            self._data_history['network']['tx'].append(tx_value)
            smoothed_tx = sum(self._data_history['network']['tx']) / len(self._data_history['network']['tx'])

            self.receive_speed = smoothed_rx
            self.transmit_speed = smoothed_tx

            return {'rx': smoothed_rx, 'tx': smoothed_tx}
        else:
            # 普通数值平滑
            self._data_history[data_type].append(value)
            smoothed = sum(self._data_history[data_type]) / len(self._data_history[data_type])

            # 更新相应属性
            if data_type == 'cpu':
                self.cpu_use = smoothed
            elif data_type == 'memory':
                self.mem_use = smoothed
            elif data_type == 'disk':
                self.disk_use = smoothed

            return smoothed

    def get_datas(self, conn):
        """持续监控系统状态的后台线程方法"""

        # 获取主机基本信息
        try:
            host_info = conn.exec(cmd='hostnamectl')
            conn.system_info_dict = parse_data.parse_hostnamectl_output(host_info)
        except Exception as e:
            util.logger.error(f"获取主机信息失败: {str(e)}")
            conn.system_info_dict = {}

        # 监控循环
        while conn.active:
            try:

                if conn.close_sig == 0:
                    break

                # CPU监控
                cpu_stats = conn.get_cpu_stats()
                conn.cpu_use = cpu_stats['total_usage']

                # 内存监控
                memory_stats = conn.get_memory_stats()
                conn.mem_use = memory_stats['usage_percent']

                # 磁盘监控
                disk_stats = conn.get_disk_stats()
                conn.disk_use = disk_stats['root_usage']

                # 网络监控
                network_stats = conn.get_network_stats()
                # 更新变量由_smooth_value处理

                # 间隔时间
                time.sleep(max(1.0, conn.monitor_interval - 2))  # 减去已用的测量时间

            except EOFError as e:
                util.logger.error(f"EOFError: {e}")
                time.sleep(5)
            except Exception as e:
                if conn.active:
                    util.logger.error(f"监控异常: {e}")
                time.sleep(5)

        util.logger.info("系统监控已停止")
