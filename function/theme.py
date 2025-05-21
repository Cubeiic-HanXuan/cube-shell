import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, Qt
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout,
                               QLabel, QFrame, QStackedWidget, QPushButton, QWidget, QTableWidget, QTableWidgetItem,
                               QAbstractItemView, QFontComboBox, QHeaderView, QMessageBox
                               )

from function import util


class ColorThemeButton(QPushButton):
    def __init__(self, name, color, parent=None):
        super().__init__(name, parent)
        self.name = name
        self.color = color
        self.setStyleSheet(f"background-color: {color};")


class ColorThemeList(QTableWidget):
    def __init__(self, themes, parent=None):
        super().__init__(len(themes), 1, parent)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setHorizontalHeaderLabels([""])
        self.verticalHeader().hide()  # 隐藏垂直表头
        self.horizontalHeader().setDefaultSectionSize(100)  # 设置默认列宽
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setWordWrap(True)
        self.setSortingEnabled(False)

        self.themes = themes
        self.buttons = []
        self.selected_row = None

        for i, (theme_name, theme_color) in enumerate(self.themes.items()):
            button = ColorThemeButton(theme_name, theme_color)
            button.clicked.connect(lambda _, idx=i: self.onThemeClick(idx, parent))
            self.buttons.append(button)
            # 将 QPushButton 放置在一个 QTableWidgetItem 中
            item = QTableWidgetItem()
            self.setItem(i, 0, item)
            self.setCellWidget(i, 0, button)
            # 设置项的可选中
            item.setFlags(item.flags() | Qt.ItemIsSelectable)
            item.setData(Qt.UserRole, i)  # 存储索引以便后续使用

        self.itemSelectionChanged.connect(self.handleItemSelectionChanged)

        # 设置水平头的大小调整模式
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 设置样式表来控制选中行的颜色和边框
        self.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: yellow;
                border: 2px solid green;
            }
            QTableWidget::item {
                background-color: white;
            }
        """)

    def handleItemSelectionChanged(self):
        current_row = self.currentRow()
        if current_row != self.selected_row:
            self.deselectRow(self.selected_row)
            self.selectRow(current_row)
            self.selected_row = current_row
            # 鼠标移上去触发
            # self.onThemeClick(current_row)

    def deselectRow(self, row):
        if row is not None:
            self.item(row, 0).setBackground(QColor("#FFFFFF"))  # 设置背景色为白色

    def selectRow(self, row):
        if row is not None:
            self.item(row, 0).setBackground(QColor("#FFFF00"))  # 设置背景色为黄色
            self.item(row, 0).setForeground(QColor("#FF0000"))  # 设置文本颜色为红色

    def onThemeClick(self, index, parent):
        # 打印当前选择的主题信息
        theme_name, theme_color = list(self.themes.items())[index]
        print(theme_name, theme_color)

        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, '../'))
        file_path = os.path.join(project_root, 'conf', 'theme.json')

        # 读取 JSON 文件内容
        data = util.read_json(file_path)
        data['theme'] = theme_name
        data['theme_color'] = theme_color

        # 将修改后的数据写回 JSON 文件
        util.write_json(file_path, data)

        util.THEME = data
        QMessageBox.information(self, "切换主题", "主题切换成功")

        # 关闭窗口
        parent.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("主题切换")

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)

        # Title Bar
        self.title_bar = QFrame(self.central_widget)
        self.title_bar.setFixedHeight(50)

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 0, 0, 0)  # 设置左边距
        title_label = QLabel("终端主题", self.title_bar)
        title_label.setStyleSheet("font-size: 20px;")
        title_label.setAlignment(Qt.AlignCenter)  # 居中文本
        title_layout.addWidget(title_label)

        # Sidebar
        self.sidebar = QFrame(self.central_widget)

        self.sidebar_layout = QVBoxLayout(self.sidebar)

        # 添加 “色彩主题” 标签
        self.sidebar_layout.addWidget(QLabel("字体", self.sidebar))

        # 字体选择框及其相关控件
        font_group_box = QFrame(self.sidebar)
        font_group_box.setFrameShape(QFrame.StyledPanel)
        font_group_box_layout = QVBoxLayout(font_group_box)

        self.font_combobox = QFontComboBox(font_group_box)
        font_group_box_layout.addWidget(self.font_combobox)

        # 连接 currentFontChanged 信号到槽函数
        self.font_combobox.currentFontChanged.connect(self.print_selected_font)
        self.sidebar_layout.addWidget(font_group_box)  # 添加字体选择框组

        # 添加 “彩色主题” 标签
        self.sidebar_layout.addWidget(QLabel("彩色主题", self.sidebar))

        # 创建一个 widget 来容纳 `ColorThemeList` 表格
        theme_list_widget = QWidget(self.sidebar)
        self.sidebar_layout.addWidget(theme_list_widget)  # 添加 widget 到 sidebar 布局
        theme_list_layout = QVBoxLayout(theme_list_widget)  # widget 内部的布局
        theme_list_layout.setContentsMargins(0, 0, 0, 0)  # 移除边距

        self.color_theme_list = ColorThemeList({
            "rrt": "#000000",
            "paraiso-light": "#E7E9DA",
            "staroffice": "#FFFFFF",
            "paraiso-dark": "#321D2F",
            "native": "#202020",
            "monokai": "#272821",
            "lightbulb": "#1B2332",
            "xcode": "#FFFFFF",
            "fruity": "#000000",
            "inkpot": "#1E1E28",
            "material": "#233239",
            "one-dark": "#272C35",
            "zenburn": "#3F3F3F",
            "solarized-dark": "#002C37",
            "tango": "#F8F8F8"
        }, self)  # 传递 MainWindow 实例作为父对象

        theme_list_layout.addWidget(self.color_theme_list)  # 将 ColorThemeList 添加到布局

        self.stacked_widget = QStackedWidget(self.central_widget)

        self.main_layout.addWidget(self.title_bar)
        self.main_layout.addWidget(self.sidebar)
        self.main_layout.addWidget(self.stacked_widget)

    def print_selected_font(self, font):
        # 当前选择的字体改变时，打印字体名称
        file_path = 'conf/theme.json'
        print("Selected Font:", font.family())
        # 读取 JSON 文件内容
        data = util.read_json(file_path)
        data['font'] = font.family()

        # 将修改后的数据写回 JSON 文件
        util.write_json(file_path, data)

        util.THEME = data
        QMessageBox.information(self, "切换字体", "字体切换成功")
