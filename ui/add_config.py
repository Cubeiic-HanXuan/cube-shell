# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'add_config.ui'
##
## Created by: Qt User Interface Compiler version 6.7.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
                            QMetaObject, QObject, QPoint, QRect,
                            QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
                           QFont, QFontDatabase, QGradient, QIcon,
                           QImage, QKeySequence, QLinearGradient, QPainter,
                           QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QWidget)

from style.style import PrimaryButtonStyle


class Ui_addConfig(object):
    def setupUi(self, addConfig):
        if not addConfig.objectName():
            addConfig.setObjectName(u"addConfig")
        addConfig.resize(360, 476)
        self.horizontalLayout = QHBoxLayout(addConfig)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.gridLayout = QGridLayout()
        self.gridLayout.setObjectName(u"gridLayout")
        self.label_5 = QLabel(addConfig)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout.addWidget(self.label_5, 5, 0, 1, 1)

        self.pushButton_3 = QPushButton(addConfig)
        self.pushButton_3.setObjectName(u"pushButton_3")

        self.gridLayout.addWidget(self.pushButton_3, 6, 2, 1, 1)

        self.configName = QLineEdit(addConfig)
        self.configName.setObjectName(u"configName")
        self.configName.setTabletTracking(False)
        self.configName.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.gridLayout.addWidget(self.configName, 0, 1, 1, 2)

        self.passwordEdit = QLineEdit(addConfig)
        self.passwordEdit.setObjectName(u"passwordEdit")
        self.passwordEdit.setTabletTracking(False)
        self.passwordEdit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.passwordEdit.setEchoMode(QLineEdit.EchoMode.Password)

        self.gridLayout.addWidget(self.passwordEdit, 2, 1, 1, 2)

        self.ipEdit = QLineEdit(addConfig)
        self.ipEdit.setObjectName(u"ipEdit")
        self.ipEdit.setTabletTracking(False)
        self.ipEdit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.gridLayout.addWidget(self.ipEdit, 3, 1, 1, 2)

        self.label = QLabel(addConfig)
        self.label.setObjectName(u"label")
        self.label.setTabletTracking(False)

        self.gridLayout.addWidget(self.label, 1, 0, 1, 1)

        self.usernamEdit = QLineEdit(addConfig)
        self.usernamEdit.setObjectName(u"usernamEdit")
        self.usernamEdit.setTabletTracking(False)
        self.usernamEdit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.gridLayout.addWidget(self.usernamEdit, 1, 1, 1, 2)

        self.comboBox = QComboBox(addConfig)
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.setObjectName(u"comboBox")

        self.gridLayout.addWidget(self.comboBox, 5, 1, 1, 2)

        self.lineEdit = QLineEdit(addConfig)
        self.lineEdit.setObjectName(u"lineEdit")

        self.gridLayout.addWidget(self.lineEdit, 6, 1, 1, 1)

        self.label_3 = QLabel(addConfig)
        self.label_3.setObjectName(u"label_3")
        self.label_3.setTabletTracking(False)

        self.gridLayout.addWidget(self.label_3, 3, 0, 1, 1)

        self.label_6 = QLabel(addConfig)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout.addWidget(self.label_6, 6, 0, 1, 1)

        self.label_4 = QLabel(addConfig)
        self.label_4.setObjectName(u"label_4")
        self.label_4.setTabletTracking(False)

        self.gridLayout.addWidget(self.label_4, 0, 0, 1, 1)

        self.pushButton = QPushButton(addConfig)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setStyleSheet(PrimaryButtonStyle)
        self.pushButton.setCursor(QCursor(Qt.PointingHandCursor))
        self.gridLayout.addWidget(self.pushButton, 7, 0, 1, 2)

        self.label_2 = QLabel(addConfig)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setTabletTracking(False)

        self.gridLayout.addWidget(self.label_2, 2, 0, 1, 1)

        self.pushButton_2 = QPushButton(addConfig)
        self.pushButton_2.setCursor(QCursor(Qt.PointingHandCursor))
        self.pushButton_2.setObjectName(u"pushButton_2")

        self.gridLayout.addWidget(self.pushButton_2, 7, 2, 1, 1)

        self.label_7 = QLabel(addConfig)
        self.label_7.setObjectName(u"label_7")

        self.gridLayout.addWidget(self.label_7, 4, 0, 1, 1)

        self.protEdit = QLineEdit(addConfig)
        self.protEdit.setObjectName(u"protEdit")

        self.gridLayout.addWidget(self.protEdit, 4, 1, 1, 2)

        self.horizontalLayout.addLayout(self.gridLayout)

        self.retranslateUi(addConfig)
        QMetaObject.connectSlotsByName(addConfig)

        addConfig.setTabOrder(self.configName, self.usernamEdit)
        addConfig.setTabOrder(self.usernamEdit, self.passwordEdit)
        addConfig.setTabOrder(self.passwordEdit, self.ipEdit)
        addConfig.setTabOrder(self.ipEdit, self.protEdit)
    # setupUi

    def retranslateUi(self, addConfig):
        addConfig.setWindowTitle(QCoreApplication.translate("addConfig", u"\u6dfb\u52a0\u8bbe\u5907", None))
        self.label_5.setText(QCoreApplication.translate("addConfig", u"\u79c1\u94a5\u767b\u5f55", None))
        self.pushButton_3.setText(QCoreApplication.translate("addConfig", u"+", None))
        self.configName.setText("")
        self.configName.setPlaceholderText(
            QCoreApplication.translate("addConfig", u"\u8bf7\u8f93\u5165\u914d\u7f6e\u540d\u79f0", None))
        self.passwordEdit.setText("")
        self.passwordEdit.setPlaceholderText(
            QCoreApplication.translate("addConfig", u"\u7ec8\u7aef\u5bc6\u7801\u53ef\u4ee5\u4e0d\u8f93\u5165", None))
        self.ipEdit.setText("")
        self.ipEdit.setPlaceholderText(
            QCoreApplication.translate("addConfig", u"\u8bf7\u8f93\u5165IP\u5730\u5740\uff08\u652f\u6301IPv6\uff09", None))
        self.label.setText(QCoreApplication.translate("addConfig", u"\u7528\u6237\u540d\uff1a", None))
        self.usernamEdit.setText("")
        self.usernamEdit.setPlaceholderText(
            QCoreApplication.translate("addConfig", u"\u8bf7\u8f93\u5165\u7ec8\u7aef\u7528\u6237\u540d", None))
        self.comboBox.setItemText(0, "")
        self.comboBox.setItemText(1, QCoreApplication.translate("addConfig", u"Ed25519Key", None))
        self.comboBox.setItemText(2, QCoreApplication.translate("addConfig", u"RSAKey", None))
        self.comboBox.setItemText(3, QCoreApplication.translate("addConfig", u"ECDSAKey", None))
        self.comboBox.setItemText(4, QCoreApplication.translate("addConfig", u"DSSKey", None))

        self.label_3.setText(QCoreApplication.translate("addConfig", u"IP\u5730\u5740\uff1a", None))
        self.label_6.setText(QCoreApplication.translate("addConfig", u"\u79c1\u94a5\u6587\u4ef6", None))
        self.label_4.setText(QCoreApplication.translate("addConfig", u"\u914d\u7f6e\u540d\uff1a", None))
        self.pushButton.setText(QCoreApplication.translate("addConfig", u"\u786e\u8ba4", None))
        self.label_2.setText(QCoreApplication.translate("addConfig", u"\u5bc6  \u7801\uff1a", None))
        self.pushButton_2.setText(QCoreApplication.translate("addConfig", u"\u53d6\u6d88", None))
        self.label_7.setText(QCoreApplication.translate("addConfig", u"\u7aef\u53e3", None))
        self.protEdit.setText(QCoreApplication.translate("addConfig", u"22", None))
    # retranslateUi
