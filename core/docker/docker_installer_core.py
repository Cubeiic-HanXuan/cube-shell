import json
import re
import time
from typing import Dict, List, Tuple, Optional, Callable, Any

from core.docker import repo


class DockerInstallerCore:
    """
    Docker和Docker Compose安装器的核心类
    负责检测Linux发行版并安装Docker和Docker Compose
    """

    # 支持的Linux发行版
    SUPPORTED_DISTROS = [
        "ubuntu", "debian", "centos", "fedora", "rhel", "amzn", "opensuse", "sles", "arch",
        "alpine", "rocky", "almalinux"
    ]

    def __init__(self, ssh_client):
        """
        初始化Docker安装器

        Args:
            ssh_client: SSH客户端对象
        """
        self.ssh_client = ssh_client
        self.distro_info = None
        self.docker_info = None
        self.docker_compose_info = None

    def _read_channel_output(self, channel, output_callback: Optional[Callable[[str, str], None]] = None) \
            -> Tuple[str, str]:
        """
        读取channel的输出

        Args:
            channel: SSH channel对象
            output_callback: 输出回调函数

        Returns:
            Tuple[str, str]: (stdout, stderr)
        """
        _stdout_list = []
        _stderr_list = []

        while True:
            # 读取标准输出
            if channel.recv_ready():
                output = channel.recv(4096).decode('utf-8')
                _stdout_list.append(output)  # 追加到列表
                if output_callback:
                    output_callback(output, "")

            # 读取标准错误
            if channel.recv_stderr_ready():
                error = channel.recv_stderr(4096).decode('utf-8')
                _stderr_list.append(error)  # 追加到列表
                if output_callback:
                    output_callback("", error)

            # 如果channel已关闭，退出循环
            if channel.closed:
                break

            time.sleep(0.2)

        return ''.join(_stdout_list), ''.join(_stderr_list)

    def _execute_command(self, command: str, sudo_password: Optional[str] = None, timeout: int = 300,
                         output_callback: Optional[Callable[[str, str], None]] = None) -> Tuple[str, str, int]:
        """
        执行SSH命令并返回标准格式的结果

        Args:
            command: 要执行的命令
            sudo_password: sudo密码，如果需要的话
            timeout: 命令超时时间（秒），默认5分钟
            output_callback: 输出回调函数，接收(stdout, stderr)参数

        Returns:
            Tuple[str, str, int]: (stdout, stderr, exit_code)
        """
        try:

            if self.ssh_client.username == "root":
                # 如果当前用户是root，则不需要sudo
                sudo_password = None

            # 如果命令需要sudo权限，添加-S选项
            if command.startswith(('apt-get', 'yum', 'dnf', 'zypper', 'apk', 'pacman', 'systemctl', 'service',
                                   'rc-service', 'usermod', 'chmod', 'ln', 'mkdir', 'tee', 'cp', 'sed')):
                if sudo_password:
                    # 带伪终端执行 sudo -S，允许 sudo 从 stdin 读取密码
                    command = f"sudo -S {command}"
                else:
                    command = f"sudo {command}"

            # 直接执行命令，不使用nohup和临时文件
            stdin, stdout, stderr = self.ssh_client.conn.exec_command(command=command, get_pty=True, timeout=timeout)
            channel = stdout.channel

            # 如果提供了sudo密码，等待密码提示并输入密码
            if sudo_password:
                # sudo 会通过 stdin 读取密码，写入密码并回车
                stdin.write(f"{sudo_password}\n")
                stdin.flush()

            # 读取输出
            # _stderr = stderr.read().decode('utf8')
            # _stdout = stdout.read().decode('utf8')

            _stdout, _stderr = self._read_channel_output(channel, output_callback)

            # 获取退出码
            exit_code = stdout.channel.recv_exit_status()
            # 处理特殊的退出码
            if exit_code == 100 and 'apt-get' in command:
                # apt-get 返回100通常表示没有找到包，这不是错误
                exit_code = 0
            elif exit_code == 127:
                # 不存在的命令
                exit_code = 0

            return _stdout, _stderr, exit_code

        except Exception as e:
            # 如果出现异常，返回错误信息
            error_msg = str(e)
            if output_callback:
                output_callback("", f"错误: {error_msg}")
            return "", error_msg, 1

    def detect_os(self) -> Dict[str, str]:
        """
        检测目标系统的操作系统信息

        Returns:
            Dict: 包含操作系统信息的字典
        """
        # 尝试使用lsb_release获取系统信息
        stdout, stderr, exit_code = self._execute_command(
            "command -v lsb_release > /dev/null && lsb_release -a 2>/dev/null || echo 'Not available'")

        # 尝试读取os-release文件
        stdout2, stderr2, exit_code2 = self._execute_command("cat /etc/os-release 2>/dev/null || echo 'Not available'")

        # 检查是否使用其他发行版特定的文件
        stdout3, stderr3, exit_code3 = self._execute_command(
            "cat /etc/redhat-release 2>/dev/null || cat /etc/centos-release 2>/dev/null || cat /etc/alpine-release "
            "2>/dev/null || echo 'Not available'")

        # 内核版本
        kernel_stdout, kernel_stderr, kernel_exit_code = self._execute_command("uname -r")

        # 解析获取的信息
        distro_info = self._parse_os_info(stdout, stdout2, stdout3)

        distro_info['kernel'] = kernel_stdout.strip() if kernel_exit_code == 0 else "未知"

        self.distro_info = distro_info
        return distro_info

    def _parse_os_info(self, lsb_output: str, os_release_output: str, other_release_output: str) -> Dict[str, str]:
        """
        解析OS信息输出

        Args:
            lsb_output: lsb_release输出
            os_release_output: /etc/os-release内容
            other_release_output: 其他发行版特定文件内容

        Returns:
            Dict: 包含操作系统信息的字典
        """
        result = {
            'id': 'unknown',
            'name': 'Unknown Linux',
            'version': 'unknown',
            'version_id': 'unknown',
            'pretty_name': 'Unknown Linux Distribution'
        }

        # 从os-release解析信息
        if "Not available" not in os_release_output:
            for line in os_release_output.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    key = key.lower()

                    if key == 'id':
                        result['id'] = value
                    elif key == 'name':
                        result['name'] = value
                    elif key == 'version':
                        result['version'] = value
                    elif key == 'version_id':
                        result['version_id'] = value
                    elif key == 'pretty_name':
                        result['pretty_name'] = value

        # 从lsb_release解析信息
        if "Not available" not in lsb_output:
            for line in lsb_output.splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    value = value.strip()
                    key = key.strip()

                    if key == 'Distributor ID':
                        result['id'] = value.lower()
                    elif key == 'Description':
                        result['pretty_name'] = value
                    elif key == 'Release':
                        result['version'] = value
                        result['version_id'] = value

        # 检查其他发行版特定的文件
        if "Not available" not in other_release_output:
            # CentOS/RHEL
            if "CentOS" in other_release_output:
                result['id'] = 'centos'
                result['name'] = 'CentOS Linux'
                match = re.search(r'release\s+(\d+(\.\d+)*)', other_release_output)
                if match:
                    result['version'] = match.group(1)
                    result['version_id'] = match.group(1)
                    result['pretty_name'] = f"CentOS Linux {match.group(1)}"

            # RHEL
            elif "Red Hat Enterprise Linux" in other_release_output:
                result['id'] = 'rhel'
                result['name'] = 'Red Hat Enterprise Linux'
                match = re.search(r'release\s+(\d+(\.\d+)*)', other_release_output)
                if match:
                    result['version'] = match.group(1)
                    result['version_id'] = match.group(1)
                    result['pretty_name'] = f"Red Hat Enterprise Linux {match.group(1)}"

            # Alpine
            elif len(other_release_output.strip()) < 10 and other_release_output.strip().replace('.', '').isdigit():
                result['id'] = 'alpine'
                result['name'] = 'Alpine Linux'
                result['version'] = other_release_output.strip()
                result['version_id'] = other_release_output.strip()
                result['pretty_name'] = f"Alpine Linux v{other_release_output.strip()}"

        return result

    def is_supported_distro(self) -> bool:
        """
        检查当前检测到的发行版是否在支持列表中

        Returns:
            bool: 是否是支持的发行版
        """
        if not self.distro_info:
            self.detect_os()

        distro_id = self.distro_info.get('id', '').lower()

        # 检查ID是否在支持列表中
        for supported in self.SUPPORTED_DISTROS:
            if supported in distro_id:
                return True

        return False

    def check_docker(self) -> Dict[str, Any]:
        """
        检查Docker是否已安装及其版本

        Returns:
            Dict: Docker安装状态和版本信息
        """
        password = self.ssh_client.password

        # 检查docker命令
        docker_cmd, docker_stderr, docker_exit = self._execute_command("command -v docker", password)

        # 正确的判断方式：命令执行成功(exit_code=0)且返回的路径非空
        is_installed = docker_exit == 0 and docker_cmd.strip() != ""

        result = {
            'installed': is_installed,
            'path': docker_cmd.strip() if is_installed else None,
            'version': None,
            'version_details': None,
            'running': False,
            'service_enabled': False
        }

        # 如果已安装，获取版本
        if result['installed']:
            # 获取Docker版本
            version_stdout, version_stderr, version_exit = self._execute_command("docker --version")
            if version_exit == 0:
                result['version'] = version_stdout.strip()

                # 获取详细版本信息
                info_stdout, info_stderr, info_exit = self._execute_command("docker info")
                if info_exit == 0:
                    result['version_details'] = info_stdout

                # 检查Docker服务状态
                service_stdout, service_stderr, service_exit = (
                    self._execute_command("systemctl is-active docker", password))
                if service_exit != 0:
                    result['running'] = 'running' in service_stdout.lower() or 'active' in service_stdout.lower()

                # 检查服务是否开机启动
                enabled_stdout, enabled_stderr, enabled_exit = (
                    self._execute_command("systemctl is-enabled docker", password))
                if enabled_exit != 0:
                    result['service_enabled'] = 'enabled' in enabled_stdout.lower()

        self.docker_info = result
        return result

    def check_docker_compose(self) -> Dict[str, Any]:
        """
        检查Docker Compose是否已安装及其版本

        Returns:
            Dict: Docker Compose安装状态和版本信息
        """
        # 检查docker-compose命令(v1版本)
        compose_v1_cmd, compose_v1_stderr, compose_v1_exit = self._execute_command("command -v docker-compose")

        # 检查docker compose命令(v2版本)
        compose_v2_stdout, compose_v2_stderr, compose_v2_exit = self._execute_command(
            "docker compose version 2>/dev/null || echo 'Not available'")

        # 正确判断V1版本是否安装：命令执行成功且返回路径非空
        v1_installed = compose_v1_exit == 0 and compose_v1_cmd.strip() != ""

        # 正确判断V2版本是否可用：检查输出不包含"Not available"
        v2_available = 'Not' not in compose_v2_stdout

        result = {
            'installed': v1_installed or v2_available,
            'v1_path': compose_v1_cmd.strip() if v1_installed else None,
            'v2_available': v2_available,
            'version': None
        }

        # 获取版本信息
        if result['installed']:
            if v1_installed:
                # V1版本
                version_stdout, version_stderr, version_exit = self._execute_command("docker-compose --version")
                if version_exit == 0:
                    result['version'] = version_stdout.strip()
            elif v2_available:
                # V2版本
                result['version'] = compose_v2_stdout.strip()

        self.docker_compose_info = result
        return result

    def configure_docker_daemon(self, config: Dict[str, Any],
                                progress_callback: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
        """
        配置Docker守护进程

        Args:
            config: daemon.json的配置内容
            progress_callback: 进度回调函数，接收(状态信息, 进度百分比)

        Returns:
            Dict: 配置结果信息
        """
        result = {
            'success': True,
            'message': '配置成功',
            'steps': []
        }

        password = self.ssh_client.password

        try:
            # 创建配置目录
            if progress_callback:
                progress_callback("创建Docker配置目录...", 10)

            mkdir_cmd = "mkdir -p /etc/docker"
            stdout, stderr, exit_code = self._execute_command(mkdir_cmd, password)
            result['steps'].append({
                'cmd': mkdir_cmd,
                'success': exit_code == 0,
                'output': stdout,
                'error': stderr
            })

            if exit_code != 0:
                result['success'] = False
                result['message'] = f"创建配置目录失败: {stderr}"
                return result

            # 备份现有配置
            if progress_callback:
                progress_callback("备份现有配置...", 30)

            backup_cmd = "cp /etc/docker/daemon.json /etc/docker/daemon.json.bak 2>/dev/null || true"
            stdout, stderr, exit_code = self._execute_command(backup_cmd, password)
            result['steps'].append({
                'cmd': backup_cmd,
                'success': True,  # 备份失败不是错误
                'output': stdout,
                'error': stderr
            })

            # 写入新配置
            if progress_callback:
                progress_callback("写入新配置...", 50)

            config_json = json.dumps(config, indent=2)
            write_cmd = f"echo '{config_json}' | sudo tee /etc/docker/daemon.json"
            stdout, stderr, exit_code = self._execute_command(write_cmd, password)
            result['steps'].append({
                'cmd': write_cmd,
                'success': exit_code == 0,
                'output': stdout,
                'error': stderr
            })

            if exit_code != 0:
                result['success'] = False
                result['message'] = f"写入配置失败: {stderr}"
                return result

            # 重启Docker服务
            if progress_callback:
                progress_callback("重启Docker服务...", 70)

            restart_cmd = "systemctl restart docker"
            stdout, stderr, exit_code = self._execute_command(restart_cmd, password)
            result['steps'].append({
                'cmd': restart_cmd,
                'success': exit_code == 0,
                'output': stdout,
                'error': stderr
            })

            if exit_code != 0:
                result['success'] = False
                result['message'] = f"重启Docker服务失败: {stderr}"
                return result

            if progress_callback:
                progress_callback("配置完成", 100)

            return result

        except Exception as e:
            result['success'] = False
            result['message'] = f"配置过程中出现错误: {str(e)}"
            return result

    def get_installation_commands(self) -> Dict[str, List[str]]:
        """
        根据系统类型返回安装Docker的命令列表

        Returns:
            Dict: 包含不同阶段Docker安装命令的字典
        """
        if not self.distro_info:
            self.detect_os()

        distro_id = self.distro_info.get('id', '').lower()
        version = float(self.distro_info.get('version', '').lower()[:2])

        # 安装命令结构
        commands = {
            'pre_install': [],  # 安装前的准备命令
            'repo_setup': [],  # 设置仓库的命令
            'install': [],  # 安装Docker的命令
            'post_install': [],  # 安装后的配置命令
            'docker_compose': [],  # 安装Docker Compose的命令
            'service_enable': []  # 启用Docker服务的命令
        }

        # 配置sudo免密码
        if self.ssh_client.username != 'root':
            commands['pre_install'].extend([
                "echo '$USER ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/$USER",
                "sudo chmod 440 /etc/sudoers.d/$USER"
            ])

        # 根据发行版添加特定的预安装命令
        if 'rocky' in distro_id:
            # Oracle Linux
            commands['pre_install'].extend([
                "dnf update",
                "yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo",
                "sed -i 's/download.docker.com/mirrors.aliyun.com\/docker-ce/' /etc/yum.repos.d/docker-ce.repo",
                # 清空安装缓存
                "dnf makecache"
            ])
            commands['repo_setup'] = []
            commands['install'] = [
                "dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y"
            ]
        if 'almalinux' in distro_id:
            # Oracle Linux
            commands['pre_install'].extend([
                "dnf update",
                "yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo",
                "sed -i 's/download.docker.com/mirrors.aliyun.com\/docker-ce/' /etc/yum.repos.d/docker-ce.repo",
                # 清空安装缓存
                "dnf makecache"
            ])
            commands['repo_setup'] = []
            commands['install'] = [
                "dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y"
            ]

        # 基于发行版的具体命令
        elif 'ubuntu' in distro_id or 'debian' in distro_id:
            # Ubuntu/Debian系
            stdout, stderr, exit_code = self._execute_command("dpkg --print-architecture", self.ssh_client.password)
            if exit_code == 0:
                if 'amd64' in stdout:
                    commands['pre_install'].extend([
                        # 更新包列表
                        f'echo "{repo.ubuntu_repo_list_amd64}" | sudo tee /etc/apt/sources.list',
                        "apt update -y"
                    ])
                else:
                    commands['pre_install'].extend([
                        f'echo "{repo.ubuntu_repo_list_arm64}" | sudo tee /etc/apt/sources.list',
                        "apt-get update -y"
                    ])

            if 'ubuntu' in distro_id:
                # Ubuntu 在安装 docker 可能由于apt-get更新进程导致apt-get不可用
                commands['pre_install'].extend(repo.ubuntu_pre_install)
            if 'debian' in distro_id:
                commands['pre_install'].extend(repo.debian_pre_install)

            commands['repo_setup'] = repo.ubuntu_repo_setup
            commands['install'] = [
                "apt-get install -y docker-ce docker-ce-cli containerd.io"
            ]

        elif 'centos' in distro_id or 'rhel' in distro_id or 'amzn' in distro_id:
            if version < 8:
                commands['pre_install'].extend(repo.centOS7_pre_install)
            if version >= 8:
                commands['pre_install'].extend(repo.centOS8_pre_install)

            if version < 8:
                commands['repo_setup'] = repo.centOS7_repo_setup
                commands['install'] = [
                    "yum install -y docker-ce"
                ]
            if version >= 8:
                # RHEL/CentOS/Fedora系
                commands['repo_setup'] = repo.centOS8_repo_setup
                commands['install'] = [
                    "dnf install docker-ce docker-ce-cli containerd.io -y"
                ]

        elif 'fedora' in distro_id:
            commands['pre_install'].extend([
                "dnf makecache -q",
                "dnf install -y dnf-plugins-core"
            ])
            # RHEL/CentOS/Fedora系
            commands['repo_setup'] = [
                # 卸载旧版本
                """dnf remove -y docker \
                  docker-client \
                  docker-client-latest \
                  docker-common \
                  docker-latest \
                  docker-latest-logrotate \
                  docker-logrotate \
                  docker-selinux \
                  docker-engine-selinux \
                  docker-engine""",
                # "dnf remove docker-ce docker-ce-cli containerd.io docker-compose-plugin",
                # 更新系统软件包
                "dnf update -y",
                "dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo",
                #  把官方软件仓库地址替换为镜像站：
                "sed -i 's+https://download.docker.com+https://mirrors.aliyun.com/docker-ce+' /etc/yum.repos.d/docker-ce.repo"
            ]
            commands['install'] = [
                # 安装 docker
                "dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
            ]

        elif 'opensuse' in distro_id or 'sles' in distro_id:
            # openSUSE/SLES
            commands['pre_install'].extend([
                "zypper refresh",
                "zypper install -y ca-certificates curl"
            ])
            commands['repo_setup'] = [
                "zypper addrepo https://download.docker.com/linux/sles/docker-ce.repo"
            ]
            commands['install'] = [
                "zypper install -y docker-ce docker-ce-cli containerd.io"
            ]

        elif 'alpine' in distro_id:
            # Alpine Linux
            commands['pre_install'].extend([
                "apk add --no-cache ca-certificates curl"
            ])
            commands['repo_setup'] = []  # 不需要额外设置仓库
            commands['install'] = [
                "apk add --no-cache docker"
            ]

        elif 'arch' in distro_id:
            # Arch Linux
            commands['pre_install'].extend([
                "pacman -Sy --noconfirm ca-certificates curl"
            ])
            commands['repo_setup'] = []  # 不需要额外设置仓库
            commands['install'] = [
                "pacman -Sy --noconfirm docker"
            ]

        else:
            # 不支持的发行版，使用通用脚本
            commands['repo_setup'] = []
            commands['install'] = [
                "curl -fsSL https://get.docker.com | sh"
            ]

        # 通用的安装后命令
        commands['post_install'] = [
            "usermod -aG docker $USER 2>/dev/null || echo 'Skipping user group update'",
            "systemctl start docker"
        ]

        # 通用的启用服务命令
        commands['service_enable'] = [
            "systemctl enable docker"
        ]

        # Docker Compose安装命令
        commands['docker_compose'] = repo.docker_compose

        return commands

    def install_docker(self, progress_callback: Optional[Callable[[str, int], None]] = None,
                       sudo_password: Optional[str] = None) -> Dict[str, Any]:
        """
        安装Docker，实时返回执行信息

        Args:
            progress_callback: 进度回调函数，接收(状态信息, 进度百分比, 命令输出)
            sudo_password: sudo密码，如果需要的话

        Returns:
            Dict: 安装结果信息
        """
        if not self.distro_info:
            if progress_callback:
                progress_callback("检测操作系统...", 5)
            self.detect_os()

        # 获取安装命令
        if progress_callback:
            progress_callback("准备安装命令...", 10)
        commands = self.get_installation_commands()

        result = {
            'success': True,
            'message': '安装成功',
            'steps': [],
            'docker_info': None,
            'docker_compose_info': None
        }

        # 检查Docker是否已安装
        if progress_callback:
            progress_callback("检查是否已安装Docker...", 15)
        docker_info = self.check_docker()

        if docker_info['installed']:
            result['success'] = True
            result['message'] = f"Docker已安装 ({docker_info['version']})"
            result['docker_info'] = docker_info

            if progress_callback:
                progress_callback(f"Docker已安装 ({docker_info['version']})", 30)
        else:
            # 执行预安装命令
            if progress_callback:
                progress_callback("安装依赖项...", 20)

            for cmd in commands['pre_install']:
                stdout, stderr, exit_code = self._execute_command(
                    cmd,
                    sudo_password=sudo_password,
                    output_callback=lambda out, err: progress_callback(f"执行: {cmd}\n{out}{err}", 20)
                    if progress_callback else None
                )

                result['steps'].append({
                    'cmd': cmd,
                    'success': exit_code == 0,
                    'output': stdout,
                    'error': stderr
                })

                if exit_code != 0:
                    result['success'] = False
                    result['message'] = f"安装依赖项失败: {stderr}"
                    return result

            # 设置仓库
            if progress_callback:
                progress_callback("配置Docker仓库...", 35)

            for cmd in commands['repo_setup']:
                # 实时执行命令并返回输出
                stdout, stderr, exit_code = self._execute_command(
                    cmd,
                    sudo_password=sudo_password,
                    output_callback=lambda out, err: progress_callback(f"执行: {cmd}\n{out}{err}", 35)
                    if progress_callback else None
                )

                result['steps'].append({
                    'cmd': cmd,
                    'success': exit_code == 0,
                    'output': stdout,
                    'error': stderr
                })

                if exit_code != 0 and not cmd.endswith("|| echo 'Skipping'"):
                    result['success'] = False
                    result['message'] = f"配置Docker仓库失败: {stderr}"
                    return result

            # 安装Docker
            if progress_callback:
                progress_callback("安装Docker引擎...", 50)

            for cmd in commands['install']:

                # 实时执行命令并返回输出
                stdout, stderr, exit_code = self._execute_command(
                    cmd,
                    sudo_password=sudo_password,
                    output_callback=lambda out, err: progress_callback(f"执行: {cmd}\n{out}{err}", 50)
                    if progress_callback else None
                )

                result['steps'].append({
                    'cmd': cmd,
                    'success': exit_code == 0,
                    'output': stdout,
                    'error': stderr
                })

                if exit_code != 0:
                    result['success'] = False
                    result['message'] = f"Docker安装失败: {stderr}"
                    return result

            # 安装后配置
            if progress_callback:
                progress_callback("配置Docker...", 70)

            for cmd in commands['post_install']:
                # 实时执行命令并返回输出
                stdout, stderr, exit_code = self._execute_command(
                    cmd,
                    sudo_password=sudo_password,
                    output_callback=lambda out, err: progress_callback(f"执行: {cmd}\n{out}{err}", 70)
                    if progress_callback else None
                )

                result['steps'].append({
                    'cmd': cmd,
                    'success': exit_code == 0,
                    'output': stdout,
                    'error': stderr
                })

            # 启用服务
            if progress_callback:
                progress_callback("设置Docker自启动...", 80)

            for cmd in commands['service_enable']:
                # 实时执行命令并返回输出

                stdout, stderr, exit_code = self._execute_command(
                    cmd,
                    sudo_password=sudo_password,
                    output_callback=lambda out, err: progress_callback(f"执行: {cmd}\n{out}{err}", 80)
                    if progress_callback else None
                )

                result['steps'].append({
                    'cmd': cmd,
                    'success': exit_code == 0,
                    'output': stdout,
                    'error': stderr
                })

            # 再次检查Docker
            if progress_callback:
                progress_callback("验证Docker安装...", 90)

            docker_info = self.check_docker()
            result['docker_info'] = docker_info

            if not docker_info['installed']:
                result['success'] = False
                result['message'] = "Docker未能成功安装"
            else:
                result['message'] = f"Docker安装成功 ({docker_info['version']})"

        # 检查Docker Compose是否已安装
        # compose_info = self.check_docker_compose()
        # result['docker_compose_info'] = compose_info

        if progress_callback:
            progress_callback("完成", 100)

        return result

    def install_docker_compose(self, progress_callback: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
        """
        安装Docker Compose

        Args:
            progress_callback: 进度回调函数，接收(状态信息, 进度百分比)

        Returns:
            Dict: 安装结果信息
        """
        if not self.distro_info:
            if progress_callback:
                progress_callback("检测操作系统...", 5)
            self.detect_os()

        # 检查Docker Compose是否已安装
        if progress_callback:
            progress_callback("检查Docker Compose...", 10)
        compose_info = self.check_docker_compose()

        result = {
            'success': True,
            'message': '安装成功',
            'steps': [],
            'docker_compose_info': None
        }

        if compose_info['installed']:
            result['success'] = True
            result['message'] = f"Docker Compose已安装 ({compose_info['version']})"
            result['docker_compose_info'] = compose_info

            if progress_callback:
                progress_callback(f"Docker Compose已安装 ({compose_info['version']})", 100)

            return result

        # 获取安装命令
        if progress_callback:
            progress_callback("准备安装命令...", 20)
        commands = self.get_installation_commands()

        # 安装Docker Compose
        if progress_callback:
            progress_callback("安装Docker Compose...", 40)

        for i, cmd in enumerate(commands['docker_compose']):
            progress = 40 + int(50 * i / len(commands['docker_compose']))
            if progress_callback:
                progress_callback(f"执行: {cmd}", progress)

            stdout, stderr, exit_code = self._execute_command(cmd)
            result['steps'].append({
                'cmd': cmd,
                'success': exit_code == 0,
                'output': stdout,
                'error': stderr
            })

            if exit_code != 0 and not cmd.endswith("|| echo 'Skipping'"):
                result['success'] = False
                result['message'] = f"Docker Compose安装失败: {stderr}"
                return result

        # 检查安装是否成功
        if progress_callback:
            progress_callback("验证Docker Compose安装...", 90)
        compose_info = self.check_docker_compose()
        result['docker_compose_info'] = compose_info

        if not compose_info['installed']:
            result['success'] = False
            result['message'] = "Docker Compose未能成功安装"
        else:
            result['message'] = f"Docker Compose安装成功 ({compose_info['version']})"

        if progress_callback:
            progress_callback("完成", 100)

        return result

    def test_docker_installation(self) -> Dict[str, Any]:
        """
        测试Docker安装是否正常工作

        Returns:
            Dict: 测试结果信息
        """
        result = {
            'success': True,
            'message': 'Docker工作正常',
            'tests': []
        }

        # 测试Docker版本
        stdout, stderr, exit_code = self._execute_command("docker --version")
        result['tests'].append({
            'name': 'Docker版本',
            'success': exit_code == 0,
            'output': stdout,
            'error': stderr
        })

        if exit_code != 0:
            result['success'] = False
            result['message'] = "Docker未正确安装"
            return result

        # 测试Docker信息
        stdout, stderr, exit_code = self._execute_command("docker info")
        result['tests'].append({
            'name': 'Docker信息',
            'success': exit_code == 0,
            'output': stdout,
            'error': stderr
        })

        if exit_code != 0:
            result['success'] = False
            result['message'] = "Docker守护进程未运行"
            return result

        # 测试运行hello-world容器
        stdout, stderr, exit_code = self._execute_command("docker run --rm hello-world")
        result['tests'].append({
            'name': 'Hello World测试',
            'success': exit_code == 0,
            'output': stdout,
            'error': stderr
        })

        if exit_code != 0:
            result['success'] = False
            result['message'] = "Docker无法运行容器"
            return result

        # 测试Docker Compose
        stdout, stderr, exit_code = self._execute_command("docker-compose --version || docker compose version")
        result['tests'].append({
            'name': 'Docker Compose版本',
            'success': exit_code == 0,
            'output': stdout,
            'error': stderr
        })
        if exit_code != 0:
            result['success'] = False
            result['message'] = "Docker Compose未正确安装"
            return result

        return result
