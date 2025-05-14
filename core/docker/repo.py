# Ubuntu/Debian系
ubuntu_repo_list_amd64 = """
deb https://mirrors.aliyun.com/ubuntu/ noble main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu/ noble main restricted universe multiverse

deb https://mirrors.aliyun.com/ubuntu/ noble-security main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu/ noble-security main restricted universe multiverse

deb https://mirrors.aliyun.com/ubuntu/ noble-updates main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu/ noble-updates main restricted universe multiverse

# deb https://mirrors.aliyun.com/ubuntu/ noble-proposed main restricted universe multiverse
# deb-src https://mirrors.aliyun.com/ubuntu/ noble-proposed main restricted universe multiverse

deb https://mirrors.aliyun.com/ubuntu/ noble-backports main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu/ noble-backports main restricted universe multiverse

"""
ubuntu_repo_list_arm64 = """
deb https://mirrors.aliyun.com/ubuntu-ports/ noble main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu-ports/ noble main restricted universe multiverse

deb https://mirrors.aliyun.com/ubuntu-ports/ noble-security main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu-ports/ noble-security main restricted universe multiverse

deb https://mirrors.aliyun.com/ubuntu-ports/ noble-updates main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu-ports/ noble-updates main restricted universe multiverse

# deb https://mirrors.aliyun.com/ubuntu-ports/ noble-proposed main restricted universe multiverse
# deb-src https://mirrors.aliyun.com/ubuntu-ports/ noble-proposed main restricted universe multiverse

deb https://mirrors.aliyun.com/ubuntu-ports/ noble-backports main restricted universe multiverse
deb-src https://mirrors.aliyun.com/ubuntu-ports/ noble-backports main restricted universe multiverse

"""

ubuntu_repo_setup = [
    # 卸载旧的docker
    "apt-get remove docker docker-engine docker.io containerd runc",
    # 获取软件最新源
    "apt-get update -y",
    # 用于通过HTTPS来获取仓库
    "apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release software-properties-common"
]
ubuntu_pre_install = [
    # 禁用自动更新服务
    "systemctl stop unattended-upgrades",
    "systemctl disable unattended-upgrades",

    # 等待apt锁释放
    # Ubuntu 在安装 docker 可能由于apt-get更新进程导致apt-get不可用
    "while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do echo '等待apt锁释放...'; sleep 1; done",
    "while sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1; do echo '等待apt锁释放...'; sleep 1; done",
    # 安装GPG证书
    "curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | sudo apt-key add -",
    # 验证
    "apt-key fingerprint 0EBFCD88",
    # 设置稳定版仓库
    """
    sudo add-apt-repository "deb [arch=$(dpkg --print-architecture)] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable" -y
    """,
    # 更新 apt 包索引
    "apt-get update -y"
]
debian_pre_install = [
    # 安装GPG证书
    "curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/debian/gpg | sudo apt-key add -",
    # 验证
    "apt-key fingerprint 0EBFCD88",
    """
    sudo add-apt-repository "deb [arch=$(dpkg --print-architecture)] https://mirrors.aliyun.com/docker-ce/linux/debian $(lsb_release -cs) stable" -y
    """,
    "apt-get update -y"
]

# RHEL/CentOS/Fedora系
CentOS7_Base = """
# CentOS-Base.repo
#
# The mirror system uses the connecting IP address of the client and the
# update status of each mirror to pick mirrors that are updated to and
# geographically close to the client.  You should use this for CentOS updates
# unless you are manually picking other mirrors.
#
# If the mirrorlist= does not work for you, as a fall back you can try the 
# remarked out baseurl= line instead.
#
#
 
[base]
name=CentOS-$releasever - Base
baseurl=http://vault.centos.org/7.9.2009/os/$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
 
#released updates 
[updates]
name=CentOS-$releasever - Updates
baseurl=http://vault.centos.org/7.9.2009/updates/$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
 
#additional packages that may be useful
[extras]
name=CentOS-$releasever - Extras
baseurl=http://vault.centos.org/7.9.2009/extras/$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
 
#additional packages that extend functionality of existing packages
[centosplus]
name=CentOS-$releasever - Plus
baseurl=http://vault.centos.org/7.9.2009/centosplus/$basearch/
gpgcheck=1
enabled=0
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
"""
centOS7_pre_install = [
    # Centos8于2021年年底停止了服务,需要修改可用的镜像源
    "curl -o /etc/yum.repos.d/CentOS-Base.repo https://mirrors.aliyun.com/repo/Centos-7.repo",
    "yum clean all",
    "yum makecache"
]
centOS7_repo_setup = [
    # 安装yum工具
    "yum install -y yum-utils device-mapper-persistent-data lvm2 --skip-broken",
    "yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo",
    "sed -i 's/download.docker.com/mirrors.aliyun.com\/docker-ce/g' /etc/yum.repos.d/docker-ce.repo",
    "yum makecache fast"
]
centOS8_pre_install = [
    # Centos8于2021年年底停止了服务,需要修改可用的镜像源
    "curl -o /etc/yum.repos.d/CentOS-Base.repo https://mirrors.aliyun.com/repo/Centos-8.repo",
    "yum clean all",
    "yum makecache"
]
centOS8_repo_setup = [
    # 安装镜像源配置工具
    "dnf install -y yum-utils",
    # 添加阿里云镜像源
    "yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo"
]

# Docker Compose安装命令
docker_compose = [
    "curl -L \"https://github.com/docker/compose/releases/download/v2.23.3/docker-compose-$(uname -s)-$(uname "
    "-m)\" -o /usr/local/bin/docker-compose",
    "chmod +x /usr/local/bin/docker-compose",
    "ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose 2>/dev/null || echo 'Skipping symlink "
    "creation'"
]
