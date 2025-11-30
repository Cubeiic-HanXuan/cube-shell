"""
颜色方案模块 - 从Konsole终端模拟器转换而来

Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>

转换为Python PySide6版本
"""

import os
import random
from typing import Optional, List, Dict

# 直接导入PySide6
from PySide6.QtCore import QSettings, QDir, QFileInfo
from PySide6.QtGui import QColor

from qtermwidget.character_color import ColorEntry, TABLE_COLORS
from qtermwidget.tools import get_color_schemes_dirs, add_custom_color_scheme_dir


class ColorScheme:
    """
    代表终端显示的颜色方案。
    
    颜色方案包括用于绘制文本和字符背景的颜色调色板，
    以及显示背景的不透明度级别。
    
    对应C++: class ColorScheme
    """
    
    # 默认颜色表 - 对应C++: const ColorEntry ColorScheme::defaultTable[TABLE_COLORS]
    defaultTable = [
        # IBM标准颜色代码，对暗色进行轻微伽马校正以补偿明亮的X屏幕
        # 包含8种ansiterm/xterm颜色，2种强度
        
        # 默认前景色和背景色
        ColorEntry(QColor(0x00, 0x00, 0x00), False),  # 默认前景色（黑色）
        ColorEntry(QColor(0xFF, 0xFF, 0xFF), True),   # 默认背景色（白色）
        
        # 标准8色
        ColorEntry(QColor(0x00, 0x00, 0x00), False),  # 黑色
        ColorEntry(QColor(0xB2, 0x18, 0x18), False),  # 红色
        ColorEntry(QColor(0x18, 0xB2, 0x18), False),  # 绿色
        ColorEntry(QColor(0xB2, 0x68, 0x18), False),  # 黄色
        ColorEntry(QColor(0x18, 0x18, 0xB2), False),  # 蓝色
        ColorEntry(QColor(0xB2, 0x18, 0xB2), False),  # 品红色
        ColorEntry(QColor(0x18, 0xB2, 0xB2), False),  # 青色
        ColorEntry(QColor(0xB2, 0xB2, 0xB2), False),  # 白色
        
        # 高亮色
        ColorEntry(QColor(0x00, 0x00, 0x00), False),  # 高亮前景色（黑色）
        ColorEntry(QColor(0xFF, 0xFF, 0xFF), True),   # 高亮背景色（白色）
        ColorEntry(QColor(0x68, 0x68, 0x68), False),  # 高亮黑色
        ColorEntry(QColor(0xFF, 0x54, 0x54), False),  # 高亮红色
        ColorEntry(QColor(0x54, 0xFF, 0x54), False),  # 高亮绿色
        ColorEntry(QColor(0xFF, 0xFF, 0x54), False),  # 高亮黄色
        ColorEntry(QColor(0x54, 0x54, 0xFF), False),  # 高亮蓝色
        ColorEntry(QColor(0xFF, 0x54, 0xFF), False),  # 高亮品红色
        ColorEntry(QColor(0x54, 0xFF, 0xFF), False),  # 高亮青色
        ColorEntry(QColor(0xFF, 0xFF, 0xFF), False),  # 高亮白色
    ]
    
    # 颜色名称 - 对应C++: const char* const ColorScheme::colorNames[TABLE_COLORS]
    colorNames = [
        "Foreground",
        "Background", 
        "Color0",
        "Color1",
        "Color2",
        "Color3",
        "Color4",
        "Color5",
        "Color6",
        "Color7",
        "ForegroundIntense",
        "BackgroundIntense",
        "Color0Intense",
        "Color1Intense",
        "Color2Intense",
        "Color3Intense",
        "Color4Intense",
        "Color5Intense",
        "Color6Intense",
        "Color7Intense"
    ]
    
    # 翻译的颜色名称 - 对应C++: const char* const ColorScheme::translatedColorNames[TABLE_COLORS]
    translatedColorNames = [
        "前景色",
        "背景色",
        "颜色 1",
        "颜色 2", 
        "颜色 3",
        "颜色 4",
        "颜色 5",
        "颜色 6",
        "颜色 7",
        "颜色 8",
        "前景色 (高亮)",
        "背景色 (高亮)",
        "颜色 1 (高亮)",
        "颜色 2 (高亮)",
        "颜色 3 (高亮)",
        "颜色 4 (高亮)",
        "颜色 5 (高亮)",
        "颜色 6 (高亮)",
        "颜色 7 (高亮)",
        "颜色 8 (高亮)"
    ]
    
    MAX_HUE = 340  # 对应C++: static const quint16 MAX_HUE = 340;
    
    class RandomizationRange:
        """
        指定特定颜色可以随机化的程度
        对应C++: class RandomizationRange
        """
        
        def __init__(self, hue: int = 0, saturation: int = 0, value: int = 0):
            """
            初始化随机化范围。
            
            Args:
                hue: 色相随机化范围
                saturation: 饱和度随机化范围  
                value: 亮度随机化范围
                
            对应C++: RandomizationRange() : hue(0) , saturation(0) , value(0) {}
            """
            self.hue = hue
            self.saturation = saturation
            self.value = value
        
        def isNull(self) -> bool:
            """
            检查是否为空（无随机化）
            对应C++: bool isNull() const
            """
            return self.hue == 0 and self.saturation == 0 and self.value == 0
    
    def __init__(self):
        """
        构造新的颜色方案，初始化为Konsole的默认颜色集。
        对应C++: ColorScheme::ColorScheme()
        """
        self._table: Optional[List[ColorEntry]] = None
        self._randomTable: Optional[List[ColorScheme.RandomizationRange]] = None
        self._opacity = 1.0
        self._description = ""
        self._name = ""
    
    def __init_copy__(self, other: 'ColorScheme'):
        """
        拷贝构造函数。
        对应C++: ColorScheme::ColorScheme(const ColorScheme& other)
        """
        self._opacity = other._opacity
        self._table = None
        self._randomTable = None
        
        self.setName(other.name())
        self.setDescription(other.description())
        
        if other._table is not None:
            for i in range(TABLE_COLORS):
                self.setColorTableEntry(i, other._table[i])
        
        if other._randomTable is not None:
            for i in range(TABLE_COLORS):
                range_obj = other._randomTable[i]
                self.setRandomizationRange(i, range_obj.hue, range_obj.saturation, range_obj.value)
    
    def setDescription(self, description: str):
        """
        设置颜色方案的描述性名称
        对应C++: void setDescription(const QString& description)
        """
        self._description = description
    
    def description(self) -> str:
        """
        返回颜色方案的描述性名称
        对应C++: QString description() const
        """
        return self._description
    
    def setName(self, name: str):
        """
        设置颜色方案的名称
        对应C++: void setName(const QString& name)
        """
        self._name = name
    
    def name(self) -> str:
        """
        返回颜色方案的名称
        对应C++: QString name() const
        """
        return self._name
    
    def setColorTableEntry(self, index: int, entry: ColorEntry):
        """
        设置调色板中的单个条目。
        
        Args:
            index: 颜色索引（0-19）
            entry: 颜色条目
            
        对应C++: void setColorTableEntry(int index , const ColorEntry& entry)
        """
        assert 0 <= index < TABLE_COLORS, f"颜色索引 {index} 超出范围"
        
        if self._table is None:
            self._table = self.defaultTable.copy()
        
        self._table[index] = entry
    
    def colorEntry(self, index: int) -> ColorEntry:
        """
        检索表中的单个颜色条目。
        
        Args:
            index: 颜色索引
            
        Returns:
            ColorEntry: 颜色条目
            
        对应C++: ColorEntry colorEntry(int index) const
        """
        assert 0 <= index < TABLE_COLORS, f"颜色索引 {index} 超出范围"
        
        entry = self.colorTable()[index]
        
        if (self._randomTable is not None and 
            not self._randomTable[index].isNull()):
            
            range_obj = self._randomTable[index]
            
            # 计算随机偏移 - 对应C++实现
            hue_difference = random.randint(-range_obj.hue//2, range_obj.hue//2) if range_obj.hue else 0
            saturation_difference = random.randint(-range_obj.saturation//2, range_obj.saturation//2) if range_obj.saturation else 0
            value_difference = random.randint(-range_obj.value//2, range_obj.value//2) if range_obj.value else 0
            
            color = QColor(entry.color)
            
            new_hue = abs((color.hue() + hue_difference) % self.MAX_HUE)
            new_value = min(abs(color.value() + value_difference), 255)
            new_saturation = min(abs(color.saturation() + saturation_difference), 255)
            
            color.setHsv(new_hue, new_saturation, new_value)
            entry.color = color
        
        return entry
    
    def getColorTable(self, table: List[ColorEntry]):
        """
        将颜色表复制到提供的数组中
        
        Args:
            table: 要填充的颜色表数组，必须至少有TABLE_COLORS个元素
            
        对应C++: void getColorTable(ColorEntry* table) const
        """
        for i in range(min(TABLE_COLORS, len(table))):
            table[i] = self.colorEntry(i)
    
    def randomizedBackgroundColor(self) -> bool:
        """
        返回背景色是否随机化
        对应C++: bool randomizedBackgroundColor() const
        """
        return False if self._randomTable is None else not self._randomTable[1].isNull()
    
    def setRandomizedBackgroundColor(self, randomize: bool):
        """
        启用背景色随机化。这将导致getColorTable()和colorEntry()
        返回的调色板根据随机种子参数进行调整。
        
        Args:
            randomize: 是否启用背景色随机化
            
        对应C++: void setRandomizedBackgroundColor(bool randomize)
        """
        if randomize:
            # 背景色的色相允许尽可能随机调整
            # 亮度和饱和度保持不变以维持可读性
            self.setRandomizationRange(1, self.MAX_HUE, 255, 0)  # 背景色索引
        else:
            if self._randomTable:
                self.setRandomizationRange(1, 0, 0, 0)  # 背景色索引
    
    def setRandomizationRange(self, index: int, hue: int, saturation: int, value: int):
        """
        设置调色板中特定颜色的随机化程度。
        
        Args:
            index: 颜色索引
            hue: 色相随机化范围
            saturation: 饱和度随机化范围
            value: 亮度随机化范围
            
        对应C++: void setRandomizationRange( int index , quint16 hue , quint8 saturation , quint8 value )
        """
        assert hue <= self.MAX_HUE, f"色相值 {hue} 超出最大值 {self.MAX_HUE}"
        assert 0 <= index < TABLE_COLORS, f"颜色索引 {index} 超出范围"
        
        if self._randomTable is None:
            self._randomTable = [self.RandomizationRange() for _ in range(TABLE_COLORS)]
        
        self._randomTable[index].hue = hue
        self._randomTable[index].value = value
        self._randomTable[index].saturation = saturation
    
    def colorTable(self) -> List[ColorEntry]:
        """
        返回活动颜色表。如果没有专门设置，则为默认颜色表。
        对应C++: const ColorEntry* colorTable() const
        """
        if self._table:
            return self._table
        else:
            return self.defaultTable
    
    def foregroundColor(self) -> QColor:
        """
        便捷方法。返回此方案的前景色，
        这是用于在此方案中绘制文本的主要颜色。
        
        Returns:
            QColor: 前景色
            
        对应C++: QColor foregroundColor() const
        """
        return self.colorTable()[0].color
    
    def backgroundColor(self) -> QColor:
        """
        便捷方法。返回此方案的背景色，
        这是用于在此方案中绘制终端背景的主要颜色。
        
        Returns:
            QColor: 背景色
            
        对应C++: QColor backgroundColor() const
        """
        return self.colorTable()[1].color
    
    def hasDarkBackground(self) -> bool:
        """
        如果此颜色方案具有深色背景，则返回True。
        如果背景色在HSV颜色空间中的值小于127，则认为背景是深色的。
        
        Returns:
            bool: 是否具有深色背景
            
        对应C++: bool hasDarkBackground() const
        """
        return self.backgroundColor().value() < 127
    
    def setOpacity(self, opacity: float):
        """
        设置显示背景的不透明度级别。
        
        Args:
            opacity: 不透明度，范围0（完全透明）到1（完全不透明）
            
        对应C++: void setOpacity(qreal opacity)
        """
        self._opacity = opacity
    
    def opacity(self) -> float:
        """
        返回此颜色方案的不透明度级别
        对应C++: qreal opacity() const
        """
        return self._opacity
    
    def read(self, fileName: str):
        """
        从指定配置源读取颜色方案。
        
        Args:
            fileName: 配置文件路径
            
        对应C++: void read(const QString & fileName)
        """
        settings = QSettings(fileName, QSettings.IniFormat)
        
        # 开始General组 - 对应C++实现
        settings.beginGroup("General")
        
        # 读取描述信息
        self._description = settings.value("Description", "Un-named Color Scheme")
        if self._description is None:
            self._description = "Un-named Color Scheme"
        else:
            self._description = str(self._description)
        
        # 读取不透明度
        opacity_value = settings.value("Opacity", 1.0)
        if opacity_value is not None:
            try:
                self._opacity = float(opacity_value)
            except (ValueError, TypeError):
                self._opacity = 1.0
        else:
            self._opacity = 1.0
        
        settings.endGroup()
        
        # 读取所有颜色条目
        for i in range(TABLE_COLORS):
            self.readColorEntry(settings, i)
    
    def readColorEntry(self, settings: QSettings, index: int):
        """
        从QSettings源读取单个颜色条目并设置调色板中索引处的条目。
        
        Args:
            settings: QSettings对象
            index: 颜色索引
            
        对应C++: void readColorEntry(QSettings * s , int index)
        """
        colorName = self.colorNameForIndex(index)
        settings.beginGroup(colorName)
        
        entry = ColorEntry()
        
        # 读取颜色值 - 对应C++实现逻辑
        colorValue = settings.value("Color")
        r, g, b = 0, 0, 0
        ok = False
        
        if colorValue is not None:
            if isinstance(colorValue, list):
                # QStringList格式：逗号分隔的RGB值
                if len(colorValue) == 3:
                    try:
                        r = int(colorValue[0])
                        g = int(colorValue[1])
                        b = int(colorValue[2])
                        ok = (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255)
                    except (ValueError, IndexError):
                        ok = False
            else:
                # 字符串格式：十六进制颜色
                colorStr = str(colorValue)
                if colorStr.startswith('#') and len(colorStr) == 7:
                    try:
                        r = int(colorStr[1:3], 16)
                        g = int(colorStr[3:5], 16)
                        b = int(colorStr[5:7], 16)
                        ok = True
                    except ValueError:
                        ok = False
        
        if not ok:
            print(f"警告：颜色值 {colorValue} 对于 {colorName} 无效。回退到黑色。")
            r = g = b = 0
        
        entry.color = QColor(r, g, b)
        
        # 读取透明度设置
        transparentValue = settings.value("Transparent", False)
        if isinstance(transparentValue, str):
            entry.transparent = transparentValue.lower() in ('true', '1', 'yes')
        else:
            entry.transparent = bool(transparentValue)
        
        # 读取Bold设置（已弃用，但为了兼容性保留）
        if settings.contains("Bold"):
            boldValue = settings.value("Bold")
            if isinstance(boldValue, str):
                isBold = boldValue.lower() in ('true', '1', 'yes')
            else:
                isBold = bool(boldValue)
            entry.fontWeight = (ColorEntry.FontWeight.Bold if isBold else 
                               ColorEntry.FontWeight.UseCurrentFormat)
        
        # 读取随机化设置
        hue = int(settings.value("MaxRandomHue", 0))
        value = int(settings.value("MaxRandomValue", 0))
        saturation = int(settings.value("MaxRandomSaturation", 0))
        
        self.setColorTableEntry(index, entry)
        
        if hue != 0 or value != 0 or saturation != 0:
            self.setRandomizationRange(index, hue, saturation, value)
        
        settings.endGroup()
    
    @staticmethod
    def colorNameForIndex(index: int) -> str:
        """
        返回指定索引的颜色名称。
        
        Args:
            index: 颜色索引
            
        Returns:
            str: 颜色名称
            
        对应C++: static QString colorNameForIndex(int index)
        """
        assert 0 <= index < TABLE_COLORS, f"颜色索引 {index} 超出范围"
        return ColorScheme.colorNames[index]
    
    @staticmethod
    def translatedColorNameForIndex(index: int) -> str:
        """
        返回指定索引的翻译颜色名称。
        
        Args:
            index: 颜色索引
            
        Returns:
            str: 翻译的颜色名称
            
        对应C++: static QString translatedColorNameForIndex(int index)
        """
        assert 0 <= index < TABLE_COLORS, f"颜色索引 {index} 超出范围"
        return ColorScheme.translatedColorNames[index]


class AccessibleColorScheme(ColorScheme):
    """
    使用标准KDE颜色调色板颜色的颜色方案。
    
    主要为使用特殊设计颜色的用户提供便利。
    
    对应C++: class AccessibleColorScheme : public ColorScheme
    """
    
    def __init__(self):
        """
        构造可访问的颜色方案
        对应C++: AccessibleColorScheme::AccessibleColorScheme()
        """
        super().__init__()
        
        # 基本属性
        self.setName("accessible")
        self.setDescription("可访问颜色方案")


class ColorSchemeManager:
    """
    管理可供终端显示使用的颜色方案。
    
    对应C++: class ColorSchemeManager
    """
    
    # 默认颜色方案 - 对应C++: static const ColorScheme _defaultColorScheme;
    _defaultColorScheme = ColorScheme()
    
    def __init__(self):
        """
        构造新的ColorSchemeManager并加载可用颜色方案列表。
        
        颜色方案本身在第一次通过findColorScheme()调用请求时才加载。
        
        Corresponds to C++: ColorSchemeManager::ColorSchemeManager()
        """
        self._colorSchemes: Dict[str, ColorScheme] = {}
        self._haveLoadedAll = False
    
    def __del__(self):
        """
        析构函数，保存任何修改的颜色方案到磁盘
        Corresponds to C++: ColorSchemeManager::~ColorSchemeManager()
        """
        # Python的垃圾回收会自动处理内存清理
        pass
    
    def defaultColorScheme(self) -> ColorScheme:
        """
        返回Konsole的默认颜色方案
        Corresponds to C++: const ColorScheme* defaultColorScheme() const
        """
        return self._defaultColorScheme
    
    def findColorScheme(self, name: str) -> Optional[ColorScheme]:
        """
        返回具有给定名称的颜色方案，如果不存在则返回None。
        如果name为空，返回默认颜色方案。
        
        First request for a specific named color scheme, load configuration information from disk.
        
        Args:
            name: 颜色方案名称
            
        Returns:
            Optional[ColorScheme]: 颜色方案对象
            
        Corresponds to C++: const ColorScheme* findColorScheme(const QString& name)
        """
        if not name:
            return self.defaultColorScheme()
        
        if name in self._colorSchemes:
            return self._colorSchemes[name]
        else:
            # 查找此颜色方案
            path = self.findColorSchemePath(name)
            if path and self.loadColorScheme(path):
                return self.findColorScheme(name)
            
            print(f"警告：找不到颜色方案 - {name}")
            return None
    
    def deleteColorScheme(self, name: str) -> bool:
        """
        删除颜色方案。成功删除返回True，否则返回False。
        
        Args:
            name: 要删除的颜色方案名称
            
        Returns:
            bool: 是否成功删除
            
        Corresponds to C++: bool deleteColorScheme(const QString& name)
        """
        assert name in self._colorSchemes, f"颜色方案 {name} 不存在"
        
        # 查找路径并删除
        path = self.findColorSchemePath(name)
        try:
            if path and os.path.exists(path):
                os.remove(path)
                del self._colorSchemes[name]
                return True
            else:
                print(f"失败删除颜色方案 - {path}")
                return False
        except OSError as e:
            print(f"删除颜色方案失败: {e}")
            return False
    
    def allColorSchemes(self) -> List[ColorScheme]:
        """
        返回所有可用颜色方案的列表。
        First call may be slow because must locate, read, and parse all color scheme resources on disk.
        
        Subsequent calls will be cheap.
        
        Returns:
            List[ColorScheme]: 所有颜色方案列表
            
        Corresponds to C++: QList<const ColorScheme*> allColorSchemes()
        """
        if not self._haveLoadedAll:
            self.loadAllColorSchemes()
        
        return list(self._colorSchemes.values())
    
    def loadCustomColorScheme(self, path: str) -> bool:
        """
        在给定路径下加载自定义颜色方案。
        
        Path can reference KDE 4 .colorscheme or KDE 3 .schema files
        
        If load succeeds, loaded color scheme can be obtained by subsequent calls to
        allColorSchemes() and findColorScheme() methods.
        
        Args:
            path: KDE 4 .colorscheme or KDE 3 .schema path
            
        Returns:
            bool: 是否成功加载颜色方案
            
        Corresponds to C++: bool loadCustomColorScheme(const QString& path)
        """
        if path.endswith(".colorscheme"):
            return self.loadColorScheme(path)
        
        return False
    
    def addCustomColorSchemeDir(self, customDir: str):
        """
        允许添加颜色方案的自定义位置。
        
        Args:
            customDir: 颜色方案的自定义位置（必须以/结尾）
            
        Corresponds to C++: void addCustomColorSchemeDir(const QString& custom_dir)
        """
        add_custom_color_scheme_dir(customDir)
    
    def loadAllColorSchemes(self):
        """
        加载所有颜色方案
        Corresponds to C++: void loadAllColorSchemes()
        """
        failed = 0
        
        nativeColorSchemes = self.listColorSchemes()
        for schemePath in nativeColorSchemes:
            if not self.loadColorScheme(schemePath):
                failed += 1
        
        if failed > 0:
            print(f"警告：加载 {failed} 个颜色方案失败。")
        
        self._haveLoadedAll = True
    
    def loadColorScheme(self, filePath: str) -> bool:
        """
        加载颜色方案。
        
        Args:
            filePath: 颜色方案文件路径
            
        Returns:
            bool: 是否成功加载
            
        Corresponds to C++: bool loadColorScheme(const QString& filePath)
        """
        if not filePath.endswith(".colorscheme") or not os.path.exists(filePath):
            return False
        
        info = QFileInfo(filePath)
        schemeName = info.baseName()
        
        scheme = ColorScheme()
        scheme.setName(schemeName)
        scheme.read(filePath)
        
        if not scheme.name():
            print(f"颜色方案 {filePath} 没有有效名称，未加载。")
            return False
        
        if schemeName not in self._colorSchemes:
            self._colorSchemes[schemeName] = scheme
        else:
            print(f"名为 {schemeName} 的颜色方案已经存在，忽略。")
        
        return True
    
    def listColorSchemes(self) -> List[str]:
        """
        返回颜色方案路径列表
        Corresponds to C++: QList<QString> listColorSchemes()
        """
        ret = []
        for schemeDir in get_color_schemes_dirs():
            dirObj = QDir(schemeDir)
            dirObj.setNameFilters(["*.colorscheme"])
            for fileName in dirObj.entryList(["*.colorscheme"]):
                ret.append(os.path.join(schemeDir, fileName))
        return ret
    
    def findColorSchemePath(self, name: str) -> Optional[str]:
        """
        查找颜色方案路径。
        
        Args:
            name: 颜色方案名称
            
        Returns:
            Optional[str]: 颜色方案文件路径
            
        Corresponds to C++: QString findColorSchemePath(const QString& name) const
        """
        dirs = get_color_schemes_dirs()
        if not dirs:
            return None
        
        # 查找.colorscheme文件
        for dirPath in dirs:
            path = os.path.join(dirPath, f"{name}.colorscheme")
            if os.path.exists(path):
                return path
        
        # 查找.schema文件（向后兼容）
        for dirPath in dirs:
            path = os.path.join(dirPath, f"{name}.schema")
            if os.path.exists(path):
                return path
        
        return None

    @staticmethod
    def instance() -> 'ColorSchemeManager':
        """
        获取全局ColorSchemeManager实例（静态方法）
        
        Returns:
            ColorSchemeManager: 全局实例
            
        Corresponds to C++: static ColorSchemeManager* instance()
        """
        return getColorSchemeManager()


# 全局单例实例 - 对应C++: Q_GLOBAL_STATIC(ColorSchemeManager, theColorSchemeManager)
_colorSchemeManagerInstance: Optional[ColorSchemeManager] = None


def getColorSchemeManager() -> ColorSchemeManager:
    """
    获取全局ColorSchemeManager实例。
    
    Returns:
        ColorSchemeManager: 全局实例
        
    Corresponds to C++: ColorSchemeManager* ColorSchemeManager::instance()
    """
    global _colorSchemeManagerInstance
    if _colorSchemeManagerInstance is None:
        _colorSchemeManagerInstance = ColorSchemeManager()
    return _colorSchemeManagerInstance 