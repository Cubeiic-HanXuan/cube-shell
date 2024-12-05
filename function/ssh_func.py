import time

import paramiko

from core.backend import BaseBackend
from core.mux import mux
from function import parse_data


class SshClient(BaseBackend):

    def __init__(self, host, port, username, password, key_type, key_file):
        super(SshClient, self).__init__()
        self.host, self.port, self.username, self.password, self.key_type, self.key_file = host, port, username, \
            password, key_type, key_file

        self.system_info_dict = None
        self.cpu_use, self.mem_use, self.disk_use, self.receive_speed, self.transmit_speed = 0, 0, 0, 0, 0
        self.docker_info = []
        self.timer1, self.timer2 = None, None
        self.Shell = None
        self.pwd = ''
        self.isConnected = False
        self.buffer1 = ['▉', '']
        self.buffer3 = ''
        self.buffer_write = b''
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

        # 初始化 SSH 客户端和通道状态
        self.conn = paramiko.SSHClient()
        self.conn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.channel = None
        self.close_sig = 1

    def connect(self):
        """
        建立 SSH 连接的方法。
        """
        try:
            if self.private_key:
                self.conn.connect(hostname=self.host, port=self.port,
                                  username=self.username, pkey=self.private_key, timeout=10)
            else:
                self.conn.connect(hostname=self.host, port=self.port,
                                  username=self.username, password=self.password, timeout=10)
        except paramiko.ssh_exception.AuthenticationException:
            print("Authentication failed.")
        except Exception as e:
            print(f"Connection error: {e}")

        self.channel = self.conn.get_transport().open_session()
        self.channel.get_pty(width=200, height=400)
        self.channel.invoke_shell()
        mux.add_backend(self)

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
            print(f"Error while reading from channel: {e}")

    def close(self):
        """
       关闭 SSH 连接，并从多路复用器中移除该后端。
       """
        if self.channel:
            self.conn.close()
            mux.remove_and_close(self)
            self.close_sig = 0

    def exec(self, cmd='', pty=False):
        """
        远程执行命令
        :param cmd:
        :param pty:
        :return:
        """
        stdin, stdout, stderr = self.conn.exec_command(timeout=10, command=cmd, get_pty=pty)
        ack = stdout.read().decode('utf8')
        return ack

    def send(self, data):
        """
        发送字符
        :param data:
        :return:
        """
        self.channel.send(data)

    # sftp
    def open_sftp(self) -> paramiko.sftp_client:
        """
        在SSH服务器上打开一个SFTP会话
        :return: 一个新的“.SFTPClient”会话对象
        """
        sftp_client = self.conn.open_sftp()
        return sftp_client

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
        while True:
            try:
                if self.close_sig == 0:
                    break
                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='cat /proc/stat')
                cpuinfo1 = stdout.read().decode('utf8')
                time.sleep(1)
                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='cat /proc/stat')
                cpuinfo2 = stdout.read().decode('utf8')

                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='df')
                diskinfo = stdout.read().decode('utf8')

                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='free')
                meminfo = stdout.read().decode('utf8')

                # 命令：列出所有doker 容器
                stdin, stdout, stderr = self.conn.exec_command(timeout=10, bufsize=100, command='docker ps -a')
                procinfo = stdout.read().decode('utf8')

                c_u1, c_idle1 = self.cpu_use_data(cpuinfo1)
                c_u2, c_idle2 = self.cpu_use_data(cpuinfo2)
                self.cpu_use = int((1 - (c_idle2 - c_idle1) / (c_u2 - c_u1)) * 100)
                self.mem_use = self.mem_use_data(meminfo)
                self.disk_use = self.disk_use_data(diskinfo)

                self.docker_info = parse_data.parse_docker_ps_output(procinfo)

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
                print(f"EOFError: {e}")
            except Exception as e:
                print(f"Unexpected error: {e}")
                print(f"连接已经关闭")


if __name__ == '__main__':
    session = SshClient('192.168.31.162', 22, 'firefly', 'firefly')
    session.connect()
    sftp = session.open_sftp()
