import re
from typing import Dict, List, Any, Optional, Tuple

from function import util


def parse_network_data(output: str) -> Dict[str, Dict[str, int]]:
    """解析/proc/net/dev输出

    Args:
        output: /proc/net/dev输出

    Returns:
        网络接口数据字典
    """
    interfaces = {}
    lines = output.strip().split('\n')

    # 跳过前两行（标题行）
    for line in lines[2:]:
        if ':' not in line:
            continue

        name, data = line.split(':', 1)
        name = name.strip()

        # 跳过lo接口
        if name == 'lo':
            continue

        values = data.split()

        if len(values) >= 16:
            interfaces[name] = {
                'rx_bytes': int(values[0]),
                'rx_packets': int(values[1]),
                'rx_errors': int(values[2]),
                'rx_dropped': int(values[3]),
                'tx_bytes': int(values[8]),
                'tx_packets': int(values[9]),
                'tx_errors': int(values[10]),
                'tx_dropped': int(values[11])
            }

    return interfaces


def calculate_network_speed(prev_data: Dict, curr_data: Dict, interval: float) -> Dict[str, Any]:
    """根据两次网络快照计算速率

    Args:
        prev_data: 第一次网络数据
        curr_data: 第二次网络数据
        interval: 时间间隔(秒)

    Returns:
        网络速率数据
    """
    if interval <= 0:
        interval = 0.1  # 防止除零错误

    interface_stats = []

    for name, curr in curr_data.items():
        if name in prev_data:
            prev = prev_data[name]

            # 计算速率
            rx_bytes_delta = curr['rx_bytes'] - prev['rx_bytes']
            tx_bytes_delta = curr['tx_bytes'] - prev['tx_bytes']

            rx_speed = rx_bytes_delta / interval
            tx_speed = tx_bytes_delta / interval

            interface_stats.append({
                'name': name,
                'rx_speed': rx_speed,
                'tx_speed': tx_speed,
                'rx_bytes': curr['rx_bytes'],
                'tx_bytes': curr['tx_bytes'],
                'rx_errors': curr['rx_errors'],
                'tx_errors': curr['tx_errors']
            })

    return {
        'interfaces': interface_stats
    }


def get_main_interface(interfaces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """识别主要网络接口（最活跃的非lo接口）

    Args:
        interfaces: 接口列表

    Returns:
        主要接口数据
    """
    if not interfaces:
        return None

    # 按rx_speed + tx_speed排序，获取最活跃的接口
    sorted_interfaces = sorted(
        interfaces,
        key=lambda x: x.get('rx_speed', 0) + x.get('tx_speed', 0),
        reverse=True
    )

    return sorted_interfaces[0] if sorted_interfaces else None


def parse_cpu_data(output: str) -> Dict[str, Any]:
    """解析/proc/stat的输出

    Args:
        output: 命令输出文本

    Returns:
        包含CPU数据的字典
    """
    lines = output.strip().split('\n')

    result = {
        'total': None,
        'cores': []
    }

    for line in lines:
        parts = line.split()
        if not parts:
            continue

        if parts[0] == 'cpu':  # 总CPU行
            # user, nice, system, idle, iowait, irq, softirq, steal
            result['total'] = [int(x) for x in parts[1:9]]
        elif parts[0].startswith('cpu') and parts[0][3:].isdigit():  # CPU核心
            # 同样的格式，但是针对单个核心
            result['cores'].append([int(x) for x in parts[1:9]])

    return result


def calculate_cpu_usage(prev_data: Dict[str, Any], curr_data: Dict[str, Any]) -> Dict[str, Any]:
    """根据两次CPU快照计算使用率

    Args:
        prev_data: 第一次CPU数据
        curr_data: 第二次CPU数据

    Returns:
        CPU使用率数据
    """

    def calculate_usage(prev: List[int], curr: List[int]) -> Tuple[float, float, float, float]:
        prev_total = sum(prev)
        curr_total = sum(curr)

        # idle是第4个值(索引3)，iowait是第5个值(索引4)
        prev_idle = prev[3]
        curr_idle = curr[3]

        prev_iowait = prev[4]
        curr_iowait = curr[4]

        # 计算总的、用户空间和系统空间的使用率
        delta_total = curr_total - prev_total
        delta_idle = curr_idle - prev_idle
        delta_iowait = curr_iowait - prev_iowait
        delta_user = (curr[0] + curr[1]) - (prev[0] + prev[1])  # user + nice
        delta_system = curr[2] - prev[2]  # system

        # 避免除零错误
        if delta_total == 0:
            return 0.0, 0.0, 0.0, 0.0

        total_usage = 100.0 * (1.0 - float(delta_idle) / float(delta_total))
        user_usage = 100.0 * float(delta_user) / float(delta_total)
        system_usage = 100.0 * float(delta_system) / float(delta_total)
        iowait_usage = 100.0 * float(delta_iowait) / float(delta_total)

        return total_usage, user_usage, system_usage, iowait_usage

    # 计算总体CPU使用率
    total_usage, user_usage, system_usage, iowait = calculate_usage(
        prev_data['total'], curr_data['total']
    )

    # 计算每个核心的使用率
    cores_usage = []
    for i in range(min(len(prev_data['cores']), len(curr_data['cores']))):
        core_usage, _, _, _ = calculate_usage(prev_data['cores'][i], curr_data['cores'][i])
        cores_usage.append(core_usage)

    return {
        'total_usage': total_usage,
        'user_usage': user_usage,
        'system_usage': system_usage,
        'iowait': iowait,
        'cores_usage': cores_usage
    }


def parse_size_value(size_str: str) -> float:
    """解析带单位的大小值

    Args:
        size_str: 如 "4.9G", "550M"

    Returns:
        以MB为单位的浮点数值
    """
    # 去除字符串中可能的颜色代码
    clean_str = re.sub(r'\x1b\[[0-9;]*m', '', size_str)

    # 尝试直接解析浮点数
    try:
        return float(clean_str)
    except ValueError:
        pass

    # 带单位的解析
    match = re.match(r'^([\d.]+)([KMGTP])?i?[Bb]?$', clean_str, re.IGNORECASE)
    if match:
        value, unit = match.groups()
        value = float(value)

        if unit:
            unit = unit.upper()
            if unit == 'K':
                value /= 1024
            elif unit == 'G':
                value *= 1024
            elif unit == 'T':
                value *= 1024 * 1024
            elif unit == 'P':
                value *= 1024 * 1024 * 1024

        return value

    return 0.0


def parse_disk_data(output: str) -> List[Dict[str, Any]]:
    """解析df命令输出

    Args:
        output: df命令输出

    Returns:
        分区列表
    """
    partitions = []
    lines = output.strip().split('\n')

    # 跳过标题行
    for line in lines[1:]:
        parts = re.split(r'\s+', line.strip())
        if len(parts) >= 6:
            try:
                # 从百分比中提取数字
                usage_str = parts[4].rstrip('%')
                usage_percent = float(usage_str)

                partition = {
                    'filesystem': parts[0],
                    'size': parts[1],
                    'used': parts[2],
                    'available': parts[3],
                    'usage_percent': usage_percent,
                    'mount_point': parts[5]
                }
                partitions.append(partition)
            except (ValueError, IndexError):
                continue

    return partitions


def parse_io_data(output: str) -> Dict[str, Any]:
    """解析iostat命令输出

    Args:
        output: iostat命令输出

    Returns:
        IO统计信息
    """
    io_stats = {}
    lines = output.strip().split('\n')

    for line in lines:
        parts = re.split(r'\s+', line.strip())
        if len(parts) >= 6:
            try:
                device = parts[0]
                # iostat -x 输出格式中的重要列
                reads_per_sec = float(parts[2])
                writes_per_sec = float(parts[3])

                # 通常第5列是IO百分比
                io_percent = float(parts[parts.index('%util')] if '%util' in parts else parts[-1])

                io_stats[device] = {
                    'reads_per_sec': reads_per_sec,
                    'writes_per_sec': writes_per_sec,
                    'io_percent': io_percent
                }
            except (ValueError, IndexError):
                continue

    return io_stats


def parse_load_average(output: str) -> List[float]:
    """解析uptime命令获取负载平均值

    Args:
        output: uptime命令输出

    Returns:
        包含1分钟、5分钟和15分钟平均负载的列表
    """
    try:
        # 负载格式: load average: 0.52, 0.58, 0.59
        match = re.search(r'load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', output)
        if match:
            return [float(match.group(1)), float(match.group(2)), float(match.group(3))]
    except:
        pass

    return [0.0, 0.0, 0.0]


def parse_memory_data(output: str) -> Dict[str, Any]:
    """解析free命令输出

    Args:
        output: free命令输出

    Returns:
        包含内存信息的字典
    """
    lines = output.strip().split('\n')
    memory_stats = {
        'total': 0,
        'used': 0,
        'free': 0,
        'shared': 0,
        'cache': 0,
        'available': 0,
        'usage_percent': 0
    }

    if len(lines) >= 2:
        # 'free -m' 输出格式:
        #              total        used        free      shared  buff/cache   available
        # Mem:           7.7G        4.9G        550M        334M        2.3G        2.1G
        mem_parts = re.split(r'\s+', lines[1].strip())

        if len(mem_parts) >= 7:
            # 解析值（去掉单位）
            try:
                total = parse_size_value(mem_parts[1])
                used = parse_size_value(mem_parts[2])
                free = parse_size_value(mem_parts[3])
                shared = parse_size_value(mem_parts[4])
                cache = parse_size_value(mem_parts[5])
                available = parse_size_value(mem_parts[6])

                # 计算实际使用率(不包括缓存)
                if total > 0:
                    usage_percent = ((total - available) / total) * 100
                else:
                    usage_percent = 0

                memory_stats = {
                    'total': total,
                    'used': used,
                    'free': free,
                    'shared': shared,
                    'cache': cache,
                    'available': available,
                    'usage_percent': usage_percent
                }
            except (ValueError, IndexError) as e:
                util.logger.error(f"解析内存数据失败: {str(e)}")

    return memory_stats


def parse_hostnamectl_output(output):
    """
    系统信息解析
    解析 hostnamectl 命令的输出，并返回字典。
    参数:
    输出(str):来自hostnamectl命令的输出。
    退货:
    dict:包含解析信息的字典。
    """
    result = {}
    lines = output.strip().split('\n')
    for line in lines:
        key_value = line.split(":", 1)
        if len(key_value) == 2:
            key = key_value[0].strip()
            value = key_value[1].strip()
            result[key] = value

    return result
