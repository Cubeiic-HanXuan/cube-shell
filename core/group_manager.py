# -*- coding: utf-8 -*-
"""
设备分组配置管理模块。
使用独立的 groups.json 文件存储分组信息。
"""

import json
import os

import appdirs


def _get_groups_file_path():
    """获取 groups.json 的完整路径"""
    config_dir = appdirs.user_config_dir("cube-shell", appauthor=False)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "groups.json")


def _empty_data():
    """返回空的分组数据结构"""
    return {"groups": [], "device_group_map": {}}


def load_groups() -> dict:
    """读取 groups.json，文件不存在或格式错误时返回空结构"""
    path = _get_groups_file_path()
    if not os.path.exists(path):
        return _empty_data()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 确保返回的数据结构完整
        if not isinstance(data, dict):
            return _empty_data()
        if "groups" not in data or not isinstance(data["groups"], list):
            data["groups"] = []
        if "device_group_map" not in data or not isinstance(data["device_group_map"], dict):
            data["device_group_map"] = {}
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return _empty_data()


def save_groups(data: dict) -> None:
    """写入 groups.json，确保 UTF-8 编码"""
    path = _get_groups_file_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_group(name: str) -> bool:
    """创建新分组，名称已存在则返回 False"""
    data = load_groups()
    if name in data["groups"]:
        return False
    data["groups"].append(name)
    save_groups(data)
    return True


def rename_group(old_name: str, new_name: str) -> bool:
    """重命名分组，同步更新 device_group_map 中所有引用"""
    data = load_groups()
    if old_name not in data["groups"]:
        return False
    if new_name in data["groups"]:
        return False
    # 更新分组列表
    idx = data["groups"].index(old_name)
    data["groups"][idx] = new_name
    # 更新设备映射中的引用
    for device, group in data["device_group_map"].items():
        if group == old_name:
            data["device_group_map"][device] = new_name
    save_groups(data)
    return True


def delete_group(name: str) -> None:
    """删除分组，对应的设备从 device_group_map 中移除（归入未分组）"""
    data = load_groups()
    if name not in data["groups"]:
        return
    data["groups"].remove(name)
    # 移除属于该分组的设备映射
    devices_to_remove = [
        device for device, group in data["device_group_map"].items()
        if group == name
    ]
    for device in devices_to_remove:
        del data["device_group_map"][device]
    save_groups(data)


def move_device_to_group(device_name: str, group_name: str) -> None:
    """将设备分配到指定分组"""
    data = load_groups()
    data["device_group_map"][device_name] = group_name
    save_groups(data)


def remove_device_from_group(device_name: str) -> None:
    """将设备从分组移除（从 device_group_map 删除该键）"""
    data = load_groups()
    if device_name in data["device_group_map"]:
        del data["device_group_map"][device_name]
        save_groups(data)


def get_device_group(device_name: str):
    """获取设备所属分组名，无分组返回 None"""
    data = load_groups()
    return data["device_group_map"].get(device_name, None)


def get_grouped_devices(all_device_names: list) -> dict:
    """
    接受所有设备名列表，返回按分组组织的有序字典。
    返回格式：
    {
        "华东地区": ["设备A", "设备C"],
        "华南地区": ["设备B"],
        "__ungrouped__": ["设备D", "设备E"]
    }
    注意：只返回 groups 列表中存在的分组 + __ungrouped__
    如果某分组无设备也包含在结果中（空列表）
    __ungrouped__ 只在存在未分组设备时才包含
    """
    data = load_groups()
    device_group_map = data["device_group_map"]
    groups = data["groups"]

    result = {}
    # 初始化所有分组（含空列表）
    for group in groups:
        result[group] = []

    ungrouped = []
    for device_name in all_device_names:
        group = device_group_map.get(device_name)
        if group and group in groups:
            result[group].append(device_name)
        else:
            ungrouped.append(device_name)

    # 只在存在未分组设备时才包含 __ungrouped__
    if ungrouped:
        result["__ungrouped__"] = ungrouped

    return result


def on_device_deleted(device_name: str) -> None:
    """设备删除时清理分组映射"""
    data = load_groups()
    if device_name in data["device_group_map"]:
        del data["device_group_map"][device_name]
        save_groups(data)


def on_device_renamed(old_name: str, new_name: str) -> None:
    """设备重命名时更新分组映射中的键"""
    data = load_groups()
    if old_name in data["device_group_map"]:
        data["device_group_map"][new_name] = data["device_group_map"].pop(old_name)
        save_groups(data)
