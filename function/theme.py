import os

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout,
                               QLabel, QFrame, QPushButton, QWidget,
                               QFontComboBox, QSpinBox, QMessageBox
                               )

from function import util


class MainWindow(QMainWindow):
    def __init__(self, main_window=None):
        super().__init__()
        self._main_window = main_window

        self.setWindowTitle("主题设置")
        self.setMinimumWidth(350)

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)

        # Title Bar - 暗色/亮色切换
        self.title_bar = QFrame(self.central_widget)
        self.title_bar.setFixedHeight(50)

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 0, 10, 0)
        title_label = QLabel("终端主题", self.title_bar)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_layout.addWidget(title_label)

        title_layout.addStretch(1)
        self._btn_dark = QPushButton("暗色", self.title_bar)
        self._btn_light = QPushButton("亮色", self.title_bar)
        title_layout.addWidget(self._btn_dark)
        title_layout.addWidget(self._btn_light)
        self._btn_dark.clicked.connect(lambda: self._set_appearance("dark"))
        self._btn_light.clicked.connect(lambda: self._set_appearance("light"))

        self.main_layout.addWidget(self.title_bar)

        # 字体设置区域
        font_frame = QFrame(self.central_widget)
        font_frame.setFrameShape(QFrame.StyledPanel)
        font_layout = QVBoxLayout(font_frame)

        # 字体选择
        font_label = QLabel("终端字体", font_frame)
        font_label.setStyleSheet("font-weight: bold;")
        font_layout.addWidget(font_label)

        self.font_combobox = QFontComboBox(font_frame)
        self.font_combobox.setFontFilters(QFontComboBox.MonospacedFonts)  # 只显示等宽字体
        font_layout.addWidget(self.font_combobox)

        # 字体大小
        size_layout = QHBoxLayout()
        size_label = QLabel("字体大小:", font_frame)
        size_layout.addWidget(size_label)
        
        self.font_size_spinbox = QSpinBox(font_frame)
        self.font_size_spinbox.setRange(8, 32)
        self.font_size_spinbox.setValue(14)
        size_layout.addWidget(self.font_size_spinbox)
        size_layout.addStretch(1)
        font_layout.addLayout(size_layout)

        # 应用按钮
        self.apply_btn = QPushButton("应用字体设置", font_frame)
        self.apply_btn.clicked.connect(self.apply_font_settings)
        font_layout.addWidget(self.apply_btn)

        self.main_layout.addWidget(font_frame)
        self.main_layout.addStretch(1)

        # 加载当前配置
        self._load_current_settings()

    def _load_current_settings(self):
        """加载当前配置"""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, '../'))
            file_path = os.path.join(project_root, 'conf', 'theme.json')
            data = util.read_json(file_path)
            
            # 加载外观设置
            appearance = str(data.get("appearance") or "dark").lower()
            self._btn_light.setEnabled(appearance != "light")
            self._btn_dark.setEnabled(appearance == "light")
            
            # 加载字体设置
            saved_font = data.get('font', '')
            if saved_font:
                self.font_combobox.setCurrentFont(QFont(saved_font))
            
            # 加载字体大小
            font_size = data.get('font_size', 14)
            self.font_size_spinbox.setValue(font_size)
            
        except Exception as e:
            print(f"加载配置失败: {e}")

    def _set_appearance(self, appearance: str):
        """设置暗色/亮色主题"""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, '../'))
            file_path = os.path.join(project_root, 'conf', 'theme.json')
            data = util.read_json(file_path)
            data["appearance"] = str(appearance).lower()
            util.write_json(file_path, data)
            util.THEME = data
            if self._main_window and hasattr(self._main_window, "applyAppearance"):
                self._main_window.applyAppearance(data["appearance"])
            self._btn_light.setEnabled(data["appearance"] != "light")
            self._btn_dark.setEnabled(data["appearance"] == "light")
        except Exception as e:
            print(f"设置外观失败: {e}")

    def apply_font_settings(self):
        """应用字体设置到所有终端"""
        try:
            # 获取选择的字体和大小
            selected_font = self.font_combobox.currentFont()
            font_family = selected_font.family()
            font_size = self.font_size_spinbox.value()
            
            # 保存到配置文件
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, '../'))
            file_path = os.path.join(project_root, 'conf', 'theme.json')
            
            data = util.read_json(file_path)
            data['font'] = font_family
            data['font_size'] = font_size
            util.write_json(file_path, data)
            util.THEME = data
            
            # 应用到所有打开的终端
            if self._main_window:
                self._apply_font_to_terminals(font_family, font_size)
            
            QMessageBox.information(self, "字体设置", f"已应用字体: {font_family}, 大小: {font_size}")
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"应用字体失败: {e}")

    def _apply_font_to_terminals(self, font_family: str, font_size: int):
        """应用字体到所有终端标签页"""
        if not self._main_window:
            return
            
        try:
            # 获取主窗口的终端标签页控件 (ShellTab)
            shell_tab = getattr(self._main_window.ui, 'ShellTab', None)
            if not shell_tab:
                print("未找到 ShellTab")
                return
            
            new_font = QFont(font_family, font_size)
            
            # 遍历所有终端标签页
            for i in range(shell_tab.count()):
                # 使用主窗口的方法获取终端实例
                if hasattr(self._main_window, 'get_text_browser_from_tab'):
                    terminal = self._main_window.get_text_browser_from_tab(i)
                    if terminal and hasattr(terminal, 'setTerminalFont'):
                        terminal.setTerminalFont(new_font)
                        print(f"已应用字体到终端 {i}: {font_family}, {font_size}")
                    
        except Exception as e:
            print(f"应用字体到终端失败: {e}")
