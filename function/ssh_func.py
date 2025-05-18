import threading
import time

import paramiko

from core.pty.backend import BaseBackend
from core.pty.mux import mux
from function import parse_data, util


class SshClient(BaseBackend):

    def __init__(self, host, port, username, password, key_type, key_file, on_connect_success=None,
                 callback_param=None):
        super(SshClient, self).__init__()
        self.host, self.port, self.username, self.password, self.key_type, self.key_file = host, port, username, \
            password, key_type, key_file

        # 添加连接成功回调函数参数
        self.on_connect_success = on_connect_success
        self.callback_param = callback_param

        self.system_info_dict = None
        self.cpu_use, self.mem_use, self.disk_use, self.receive_speed, self.transmit_speed = 0, 0, 0, 0, 0
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
        self.reconnect_delay = 5  # 初始重连延迟（秒）
        self.heartbeat_interval = 30  # 心跳间隔
        self.lock = threading.Lock()  # 线程锁
        self.active = True  # 连接状态标志

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

        while self.reconnect_attempts < self.max_reconnect_attempts and self.active:
            try:
                if self.private_key:
                    self.conn.connect(hostname=self.host, port=self.port, username=self.username, pkey=self.private_key,
                                      timeout=2, banner_timeout=15)
                else:
                    self.conn.connect(hostname=self.host, port=self.port, username=self.username,
                                      password=self.password, timeout=2, banner_timeout=15)

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
                raise
            except Exception as e:
                util.logger.error(f"Connection error: {e}")
                self.reconnect_attempts += 1
                delay = self.reconnect_delay * 2 ** (self.reconnect_attempts - 1)
                util.logger.warning(
                    f"连接失败 ({self.reconnect_attempts}/{self.max_reconnect_attempts}), {delay}秒后重试...")
                time.sleep(delay)

        # 重试失败处理
        self.active = False
        raise ConnectionError(f"无法建立连接，已尝试 {self.max_reconnect_attempts} 次")

    def _setup_channel(self):
        """设置会话通道"""
        with self.lock:
            try:
                self.channel = self.transport.open_session()
                self.channel.get_pty(term="xterm-256color", width=100, height=200)
                self.channel.invoke_shell()
                self.isConnected = True
                mux.add_backend(self)
            except Exception as e:
                util.logger.error(f"通道初始化失败: {str(e)}")
                raise

    def _start_heartbeat(self):
        """启动心跳线程"""
        def heartbeat():
            while self.active and self.is_connected():
                try:
                    # 使用现有通道发送空包
                    self.channel.send("\x00")
                    time.sleep(self.heartbeat_interval)
                except Exception as e:
                    util.logger.warning(f"心跳失败: {str(e)}")
                    self._trigger_reconnect()

        threading.Thread(target=heartbeat, daemon=True).start()

    def _trigger_reconnect(self):
        """触发重新连接"""
        if self.active and self.reconnect_attempts < self.max_reconnect_attempts:
            util.logger.info("尝试重新连接...")
            try:
                self.connect()
            except Exception as e:
                util.logger.error(f"重连失败: {str(e)}")

    def safe_execute(self, func, *args, **kwargs):
        """执行操作的通用安全包装"""
        try:
            if not self.is_connected():
                self._trigger_reconnect()
            return func(*args, **kwargs)
        except (paramiko.SSHException, EOFError) as e:
            util.logger.error(f"连接异常: {str(e)}")
            self._trigger_reconnect()
            return self.safe_execute(func, *args, **kwargs)
        except Exception as e:
            util.logger.error(f"操作失败: {str(e)}")
            raise

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

    def read(self):
        """
        从 SSH 通道读取数据，并写入到屏幕。
        """
        try:
            if self.channel.recv_ready():
                output = self.channel.recv(4096)
                self.write_to_screen(output)
        except Exception as e:
            util.logger.error(f"Error while reading from channel: {e}")

    def close(self):
        """
       关闭 SSH 连接，并从多路复用器中移除该后端。
       """
        self.active = False
        # if self.channel:
        #     self.conn.close()
        #     mux.remove_and_close(self)
        #     self.close_sig = 0
        try:
            if self.channel:
                self.channel.close()
            if self.transport:
                self.transport.close()
        except Exception as e:
            util.logger.debug(f"关闭连接时出错: {str(e)}")
        finally:
            super().close()

    def _exec(self, cmd, pty):
        """实际的命令执行方法"""
        stdin, stdout, stderr = self.conn.exec_command(
            command=cmd,
            get_pty=pty,
            timeout=30
        )
        return stdout.read().decode('utf8')

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
        l = line.split(' ')
        ln = []
        for ll in l:
            if ll == ' ' or ll == '':
                pass
            elif ll != ' ' and ll != '':
                ln.append(ll)
        return ln

    def cpu_use_data(self, info: str) -> tuple:
        lines = info.split('\n')
        for l in lines:
            if l.startswith('cpu'):
                ll = self.del_more_space(l)
                i = int(ll[1]) + int(ll[2]) + int(ll[3]) + int(ll[4]) + int(ll[5]) + int(ll[6]) + int(ll[7])
                return i, int(ll[4])

    def disk_use_data(self, info: str) -> int:
        lines = info.split('\n')
        for l in lines:
            if l.endswith('/'):
                ll = self.del_more_space(l)
                if len(ll[4]) == 3:
                    return int(ll[4][0:2])
                elif len(ll[4]) == 2:
                    return int(ll[4][0:1])
                elif len(ll[4]) == 4:
                    return int(ll[4][0:3])

    def mem_use_data(self, info: str) -> int:
        lines = info.split('\n')
        for l in lines:
            if l.startswith('Mem'):
                ll = self.del_more_space(l)
                return int((int(ll[2])) / int(ll[1]) * 100)

    def get_datas(self):
        # 获取主机信息
        stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='hostnamectl')
        host_info = stdout.read().decode('utf8')
        self.system_info_dict = parse_data.parse_hostnamectl_output(host_info)
        while self.active:
            try:
                if not self.is_connected():
                    self._trigger_reconnect()
                # if self.close_sig == 0:
                #     break
                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='cat /proc/stat')
                cpuinfo1 = stdout.read().decode('utf8')
                time.sleep(1)
                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='cat /proc/stat')
                cpuinfo2 = stdout.read().decode('utf8')

                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='df')
                diskinfo = stdout.read().decode('utf8')

                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='free')
                meminfo = stdout.read().decode('utf8')

                c_u1, c_idle1 = self.cpu_use_data(cpuinfo1)
                c_u2, c_idle2 = self.cpu_use_data(cpuinfo2)
                self.cpu_use = int((1 - (c_idle2 - c_idle1) / (c_u2 - c_u1)) * 100)
                self.mem_use = self.mem_use_data(meminfo)
                self.disk_use = self.disk_use_data(diskinfo)

                # 获取网卡流量
                stdin1, stdout1, stderr1 = self.conn.exec_command(timeout=10, bufsize=100, command='cat /proc/net/dev')
                netinfo = stdout1.read().decode('utf8')
                dev1 = parse_data.parse_net_dev(netinfo)
                merged_initial_data = parse_data.merge_network_data(dev1)
                # 设置时间间隔
                time.sleep(1)
                stdin2, stdout2, stderr2 = self.conn.exec_command(timeout=10, bufsize=100, command='cat /proc/net/dev')
                netinfo1 = stdout2.read().decode('utf8')
                dev2 = parse_data.parse_net_dev(netinfo1)
                merged_current_data = parse_data.merge_network_data(dev2)
                # 计算速度
                self.receive_speed, self.transmit_speed = parse_data.calculate_speed(merged_initial_data,
                                                                                     merged_current_data, 1)
                # time.sleep(1)
            except EOFError as e:
                util.logger.error(f"EOFError: {e}")
            except Exception as e:
                util.logger.error(f"Unexpected error: {e}")
                util.logger.info("连接已经关闭")
                #time.sleep(1)


if __name__ == '__main__':
    session = SshClient('192.168.31.162', 22, 'firefly', 'firefly')
    session.connect()
    sftp = session.open_sftp()
