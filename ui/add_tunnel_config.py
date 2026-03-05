# -*- coding: utf-8 -*-
import os
import pickle

from PySide6.QtCore import (QCoreApplication, QMetaObject, QSize, Qt)
from PySide6.QtGui import (QIcon, QCursor)
from PySide6.QtWidgets import (QComboBox, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit,
                               QSizePolicy, QSpacerItem, QDialogButtonBox)

from style.style import PrimaryButtonStyle
import icons.icons


class Ui_AddTunnelConfig(object):
    def setupUi(self, TunnelConfig):
        if not TunnelConfig.objectName():
            TunnelConfig.setObjectName(u"TunnelConfig")
        TunnelConfig.resize(386, 257)
        self.gridLayout = QGridLayout(TunnelConfig)
        self.gridLayout.setObjectName(u"gridLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalSpacer = QSpacerItem(188, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.add_tunnel = QDialogButtonBox(TunnelConfig)
        self.add_tunnel.setObjectName(u"add_tunnel")
        self.add_tunnel.setOrientation(Qt.Orientation.Horizontal)
        self.add_tunnel.setStandardButtons(QDialogButtonBox.StandardButton.Save)
        # 更改按钮文本
        ok_button = self.add_tunnel.button(QDialogButtonBox.StandardButton.Save)
        ok_button.setText(QCoreApplication.translate("TunnelConfig", u"保存", None))
        ok_button.setStyleSheet(PrimaryButtonStyle)
        ok_button.setCursor(QCursor(Qt.PointingHandCursor))

        self.horizontalLayout.addWidget(self.add_tunnel)

        self.gridLayout.addLayout(self.horizontalLayout, 9, 0, 1, 3)

        self.comboBox_ssh = QComboBox(TunnelConfig)
        self.comboBox_ssh.setObjectName(u"comboBox_ssh")

        self.gridLayout.addWidget(self.comboBox_ssh, 1, 1, 1, 2)

        self.label_browser_open = QLabel(TunnelConfig)
        self.label_browser_open.setObjectName(u"label_browser_open")

        self.gridLayout.addWidget(self.label_browser_open, 7, 0, 1, 1)

        self.local_bind_address_edit = QLineEdit(TunnelConfig)
        self.local_bind_address_edit.setObjectName(u"local_bind_address_edit")

        self.gridLayout.addWidget(self.local_bind_address_edit, 6, 1, 1, 2)

        self.label_remote_bind_address_edit = QLabel(TunnelConfig)
        self.label_remote_bind_address_edit.setObjectName(u"label_remote_bind_address_edit")

        self.gridLayout.addWidget(self.label_remote_bind_address_edit, 3, 0, 1, 1)

        self.label = QLabel(TunnelConfig)
        self.label.setObjectName(u"label")

        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)

        self.label_local_bind_address_edit = QLabel(TunnelConfig)
        self.label_local_bind_address_edit.setObjectName(u"label_local_bind_address_edit")

        self.gridLayout.addWidget(self.label_local_bind_address_edit, 6, 0, 1, 1)

        self.label_ssh_port_edit = QLabel(TunnelConfig)
        self.label_ssh_port_edit.setObjectName(u"label_ssh_port_edit")

        self.gridLayout.addWidget(self.label_ssh_port_edit, 1, 0, 1, 1)

        self.comboBox_tunnel_type = QComboBox(TunnelConfig)
        icon = QIcon()
        icon.addFile(u":Localhost.png", QSize(), QIcon.Mode.Selected, QIcon.State.On)
        self.comboBox_tunnel_type.addItem(icon, "")
        icon1 = QIcon()
        icon1.addFile(u":remote.png", QSize(), QIcon.Mode.Selected, QIcon.State.On)
        self.comboBox_tunnel_type.addItem(icon1, "")
        icon2 = QIcon()
        icon2.addFile(u":dynamic.png", QSize(), QIcon.Mode.Selected, QIcon.State.On)
        self.comboBox_tunnel_type.addItem(icon2, "")
        self.comboBox_tunnel_type.setObjectName(u"comboBox_tunnel_type")

        self.gridLayout.addWidget(self.comboBox_tunnel_type, 0, 1, 1, 1)

        self.browser_open = QLineEdit(TunnelConfig)
        self.browser_open.setObjectName(u"browser_open")

        self.gridLayout.addWidget(self.browser_open, 7, 1, 1, 2)

        self.remote_bind_address_edit = QLineEdit(TunnelConfig)
        self.remote_bind_address_edit.setObjectName(u"remote_bind_address_edit")

        self.gridLayout.addWidget(self.remote_bind_address_edit, 3, 1, 1, 2)

        self.label_tunnel_name = QLabel(TunnelConfig)
        self.label_tunnel_name.setObjectName(u"label_tunnel_name")

        self.gridLayout.addWidget(self.label_tunnel_name, 2, 0, 1, 1)

        self.ssh_tunnel_name = QLineEdit(TunnelConfig)
        self.ssh_tunnel_name.setObjectName(u"ssh__tunnel_name")
        self.ssh_tunnel_name.setReadOnly(False)

        self.gridLayout.addWidget(self.ssh_tunnel_name, 2, 1, 1, 2)

        self.retranslateUi(TunnelConfig)

        QMetaObject.connectSlotsByName(TunnelConfig)

    # setupUi

    def retranslateUi(self, TunnelConfig):
        TunnelConfig.setWindowTitle(QCoreApplication.translate("TunnelConfig", u"添加SSH隧道", None))
        # self.add_tunnel.setText(QCoreApplication.translate("TunnelConfig", u"\u65b0\u589e", None))
        self.label_browser_open.setText(
            QCoreApplication.translate("TunnelConfig", u"\u6d4f\u89c8\u5668\u6253\u5f00", None))
        self.local_bind_address_edit.setPlaceholderText(QCoreApplication.translate("TunnelConfig",
                                                                                   u"\u8bf7\u8f93\u5165\u672c\u5730\u7ed1\u5b9a\u5730\u5740\uff0c\u4f8b\u5982:localhost:8080",
                                                                                   None))
        self.label_remote_bind_address_edit.setText(
            QCoreApplication.translate("TunnelConfig", u"\u8fdc\u7a0b\u7ed1\u5b9a\u5730\u5740", None))
        self.label.setText(QCoreApplication.translate("TunnelConfig", u"\u8f6c\u53d1\u6a21\u5f0f", None))
        self.label_local_bind_address_edit.setText(
            QCoreApplication.translate("TunnelConfig", u"\u672c\u5730\u7ed1\u5b9a\u5730\u5740", None))
        self.label_ssh_port_edit.setText(QCoreApplication.translate("TunnelConfig", u"SSH \u670d\u52a1\u5668", None))
        self.comboBox_tunnel_type.setItemText(0, QCoreApplication.translate("TunnelConfig", u"\u672c\u5730", None))
        self.comboBox_tunnel_type.setItemText(1, QCoreApplication.translate("TunnelConfig", u"\u8fdc\u7a0b", None))
        self.comboBox_tunnel_type.setItemText(2, QCoreApplication.translate("TunnelConfig", u"\u52a8\u6001", None))

        self.browser_open.setPlaceholderText(QCoreApplication.translate("TunnelConfig", u"https://127.0.0.1:80", None))
        self.remote_bind_address_edit.setPlaceholderText(QCoreApplication.translate("TunnelConfig",
                                                                                    u"\u8bf7\u8f93\u5165\u8fdc\u7a0b\u7ed1\u5b9a\u5730\u5740\uff0c\u4f8b\u5982:localhost:8080",
                                                                                    None))
        self.label_tunnel_name.setText(QCoreApplication.translate("TunnelConfig", u"\u96a7\u9053\u540d\u79f0", None))
        self.ssh_tunnel_name.setPlaceholderText(QCoreApplication.translate("TunnelConfig", u"\u5982:nginx", None))
    # retranslateUi
