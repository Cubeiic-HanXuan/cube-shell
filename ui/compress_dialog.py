# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QComboBox, QDialogButtonBox, QFormLayout


class CompressDialog(QDialog):
    def __init__(self, parent=None, default_name="archive"):
        super().__init__(parent)
        self.setWindowTitle(self.tr("新建压缩"))
        self.setFixedSize(200, 150)  # 增加高度以适应调整

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.name_edit = QLineEdit(default_name)
        form_layout.addRow(self.tr("文件名:"), self.name_edit)

        self.format_combo = QComboBox()
        self.format_combo.addItems([".tar.gz", ".zip"])
        # 增加下拉框最小宽度，防止文字被截断
        self.format_combo.setMinimumWidth(100)
        form_layout.addRow(self.tr("格式:"), self.format_combo)

        layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_settings(self):
        return self.name_edit.text(), self.format_combo.currentText()
