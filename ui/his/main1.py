# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main1.ui'
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
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSplitter,
    QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1524, 510)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.gridLayout_5 = QGridLayout(self.centralwidget)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.splitter_3 = QSplitter(self.centralwidget)
        self.splitter_3.setObjectName(u"splitter_3")
        self.splitter_3.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        self.splitter_3.setMouseTracking(False)
        self.splitter_3.setOrientation(Qt.Orientation.Horizontal)
        self.gridLayoutWidget = QWidget(self.splitter_3)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayout = QGridLayout(self.gridLayoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.treeWidget = QTreeWidget(self.gridLayoutWidget)
        self.treeWidget.setObjectName(u"treeWidget")
        self.treeWidget.setMinimumSize(QSize(200, 0))

        self.gridLayout.addWidget(self.treeWidget, 1, 0, 1, 1)

        self.lineEdit = QLineEdit(self.gridLayoutWidget)
        self.lineEdit.setObjectName(u"lineEdit")

        self.gridLayout.addWidget(self.lineEdit, 0, 0, 1, 1)

        self.splitter_3.addWidget(self.gridLayoutWidget)
        self.splitter_255 = QSplitter(self.splitter_3)
        self.splitter_255.setObjectName(u"splitter_255")
        self.splitter_255.setMinimumSize(QSize(0, 0))
        self.splitter_255.setMaximumSize(QSize(16777215, 16777215))
        self.splitter_255.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        self.splitter_255.setMouseTracking(False)
        self.splitter_255.setOrientation(Qt.Orientation.Horizontal)
        self.gridLayoutWidget_2 = QWidget(self.splitter_255)
        self.gridLayoutWidget_2.setObjectName(u"gridLayoutWidget_2")
        self.gridLayout_4 = QGridLayout(self.gridLayoutWidget_2)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.gridLayout_4.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.horizontalLayout_3.setContentsMargins(3, -1, 3, -1)
        self.webview = QPushButton(self.gridLayoutWidget_2)
        self.webview.setObjectName(u"webview")

        self.horizontalLayout_3.addWidget(self.webview)

        self.iport = QLineEdit(self.gridLayoutWidget_2)
        self.iport.setObjectName(u"iport")

        self.horizontalLayout_3.addWidget(self.iport)

        self.seeOnline = QPushButton(self.gridLayoutWidget_2)
        self.seeOnline.setObjectName(u"seeOnline")

        self.horizontalLayout_3.addWidget(self.seeOnline)

        self.showPort = QPushButton(self.gridLayoutWidget_2)
        self.showPort.setObjectName(u"showPort")

        self.horizontalLayout_3.addWidget(self.showPort)


        self.gridLayout_4.addLayout(self.horizontalLayout_3, 3, 0, 1, 2)

        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.gridLayout_2.setContentsMargins(-1, -1, 3, -1)
        self.label_5 = QLabel(self.gridLayoutWidget_2)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_2.addWidget(self.label_5, 1, 0, 1, 1)

        self.label_4 = QLabel(self.gridLayoutWidget_2)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_2.addWidget(self.label_4, 0, 0, 1, 1)

        self.lanIP = QLineEdit(self.gridLayoutWidget_2)
        self.lanIP.setObjectName(u"lanIP")

        self.gridLayout_2.addWidget(self.lanIP, 0, 1, 1, 1)

        self.wanIP = QLineEdit(self.gridLayoutWidget_2)
        self.wanIP.setObjectName(u"wanIP")

        self.gridLayout_2.addWidget(self.wanIP, 1, 1, 1, 1)

        self.label_6 = QLabel(self.gridLayoutWidget_2)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout_2.addWidget(self.label_6, 2, 0, 1, 1)

        self.gateway = QLineEdit(self.gridLayoutWidget_2)
        self.gateway.setObjectName(u"gateway")

        self.gridLayout_2.addWidget(self.gateway, 2, 1, 1, 1)


        self.gridLayout_4.addLayout(self.gridLayout_2, 0, 1, 1, 1)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(3, -1, 3, -1)
        self.initKey = QPlainTextEdit(self.gridLayoutWidget_2)
        self.initKey.setObjectName(u"initKey")
        self.initKey.setMinimumSize(QSize(260, 50))

        self.horizontalLayout.addWidget(self.initKey)

        self.init = QPushButton(self.gridLayoutWidget_2)
        self.init.setObjectName(u"init")

        self.horizontalLayout.addWidget(self.init)


        self.gridLayout_4.addLayout(self.horizontalLayout, 2, 0, 1, 2)

        self.verticalLayout_3 = QVBoxLayout()
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.progressBar = QProgressBar(self.gridLayoutWidget_2)
        self.progressBar.setObjectName(u"progressBar")
        self.progressBar.setValue(24)

        self.verticalLayout_3.addWidget(self.progressBar)

        self.result = QTextBrowser(self.gridLayoutWidget_2)
        self.result.setObjectName(u"result")

        self.verticalLayout_3.addWidget(self.result)


        self.gridLayout_4.addLayout(self.verticalLayout_3, 4, 0, 1, 2)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.horizontalLayout_5.setContentsMargins(3, -1, 3, -1)
        self.discButton = QPushButton(self.gridLayoutWidget_2)
        self.discButton.setObjectName(u"discButton")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.discButton.sizePolicy().hasHeightForWidth())
        self.discButton.setSizePolicy(sizePolicy)

        self.horizontalLayout_5.addWidget(self.discButton)

        self.timezoneButton = QPushButton(self.gridLayoutWidget_2)
        self.timezoneButton.setObjectName(u"timezoneButton")

        self.horizontalLayout_5.addWidget(self.timezoneButton)

        self.setWan = QPushButton(self.gridLayoutWidget_2)
        self.setWan.setObjectName(u"setWan")

        self.horizontalLayout_5.addWidget(self.setWan)

        self.setLan = QPushButton(self.gridLayoutWidget_2)
        self.setLan.setObjectName(u"setLan")

        self.horizontalLayout_5.addWidget(self.setLan)


        self.gridLayout_4.addLayout(self.horizontalLayout_5, 1, 0, 1, 2)

        self.gridLayout_8 = QGridLayout()
        self.gridLayout_8.setObjectName(u"gridLayout_8")
        self.gridLayout_8.setContentsMargins(3, -1, 3, -1)
        self.diskRate = QProgressBar(self.gridLayoutWidget_2)
        self.diskRate.setObjectName(u"diskRate")
        self.diskRate.setValue(24)

        self.gridLayout_8.addWidget(self.diskRate, 2, 1, 1, 1)

        self.cpuRate = QProgressBar(self.gridLayoutWidget_2)
        self.cpuRate.setObjectName(u"cpuRate")
        self.cpuRate.setValue(24)

        self.gridLayout_8.addWidget(self.cpuRate, 0, 1, 1, 1)

        self.label_2 = QLabel(self.gridLayoutWidget_2)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout_8.addWidget(self.label_2, 1, 0, 1, 1)

        self.label = QLabel(self.gridLayoutWidget_2)
        self.label.setObjectName(u"label")

        self.gridLayout_8.addWidget(self.label, 0, 0, 1, 1)

        self.memRate = QProgressBar(self.gridLayoutWidget_2)
        self.memRate.setObjectName(u"memRate")
        self.memRate.setValue(24)

        self.gridLayout_8.addWidget(self.memRate, 1, 1, 1, 1)

        self.label_3 = QLabel(self.gridLayoutWidget_2)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_8.addWidget(self.label_3, 2, 0, 1, 1)


        self.gridLayout_4.addLayout(self.gridLayout_8, 0, 0, 1, 1)

        self.splitter_255.addWidget(self.gridLayoutWidget_2)
        self.gridLayoutWidget_3 = QWidget(self.splitter_255)
        self.gridLayoutWidget_3.setObjectName(u"gridLayoutWidget_3")
        self.gridLayout_6 = QGridLayout(self.gridLayoutWidget_3)
        self.gridLayout_6.setObjectName(u"gridLayout_6")
        self.gridLayout_6.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(self.gridLayoutWidget_3)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setEnabled(True)
        self.splitter.setMinimumSize(QSize(888, 0))
        self.splitter.setSizeIncrement(QSize(0, 0))
        self.splitter.setBaseSize(QSize(0, 0))
        self.splitter.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        self.splitter.setMouseTracking(False)
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.verticalLayoutWidget = QWidget(self.splitter)
        self.verticalLayoutWidget.setObjectName(u"verticalLayoutWidget")
        self.verticalLayout = QVBoxLayout(self.verticalLayoutWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.Shell = QTextBrowser(self.verticalLayoutWidget)
        self.Shell.setObjectName(u"Shell")
        self.Shell.setMinimumSize(QSize(234, 338))
        self.Shell.setSizeIncrement(QSize(0, 0))
        self.Shell.setMouseTracking(True)
        self.Shell.setReadOnly(True)
        self.Shell.setCursorWidth(5)
        self.Shell.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        self.verticalLayout.addWidget(self.Shell)

        self.splitter.addWidget(self.verticalLayoutWidget)
        self.verticalLayoutWidget_2 = QWidget(self.splitter)
        self.verticalLayoutWidget_2.setObjectName(u"verticalLayoutWidget_2")
        self.verticalLayout_2 = QVBoxLayout(self.verticalLayoutWidget_2)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.treeWidget333 = QTreeWidget(self.verticalLayoutWidget_2)
        self.treeWidget333.setObjectName(u"treeWidget333")

        self.verticalLayout_2.addWidget(self.treeWidget333)

        self.splitter.addWidget(self.verticalLayoutWidget_2)

        self.gridLayout_6.addWidget(self.splitter, 0, 0, 1, 1)

        self.splitter_255.addWidget(self.gridLayoutWidget_3)
        self.splitter_3.addWidget(self.splitter_255)

        self.gridLayout_5.addWidget(self.splitter_3, 0, 0, 1, 1)

        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        ___qtreewidgetitem = self.treeWidget.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"\u8bbe\u5907\u5217\u8868", None));
        self.webview.setText(QCoreApplication.translate("MainWindow", u"\u6253\u5f00\u63a7\u5236\u53f0", None))
        self.iport.setText(QCoreApplication.translate("MainWindow", u"192.168.137.0/24", None))
        self.seeOnline.setText(QCoreApplication.translate("MainWindow", u"\u67e5\u770b\u5728\u7ebf\u8bbe\u5907", None))
        self.showPort.setText(QCoreApplication.translate("MainWindow", u"\u626b\u63cfip\u7aef\u53e3", None))
        self.label_5.setText(QCoreApplication.translate("MainWindow", u"\u516c\u7f51IP", None))
        self.label_4.setText(QCoreApplication.translate("MainWindow", u"\u5185\u7f51IP", None))
        self.lanIP.setText(QCoreApplication.translate("MainWindow", u"192.168.137.100/24", None))
        self.wanIP.setText(QCoreApplication.translate("MainWindow", u"192.168.1.250/24", None))
        self.label_6.setText(QCoreApplication.translate("MainWindow", u"\u7f51\u5173", None))
        self.gateway.setText(QCoreApplication.translate("MainWindow", u"192.168.1.1", None))
        self.initKey.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u8bf7\u590d\u5236\u670d\u52a1\u7aef\u79d8\u94a5\uff0c\u6216\u952e\u5165\u9700\u8981\u8fd0\u884c\u7684\u547d\u4ee4\uff0c\u8bf7\u6ce8\u610f\u662f\u5426\u9700\u8981\u589e\u52a0sudo", None))
        self.init.setText(QCoreApplication.translate("MainWindow", u"\u521d\u59cb\u5316\n"
"\uff08\u8fd0\u884c\u547d\u4ee4\uff09", None))
        self.discButton.setText(QCoreApplication.translate("MainWindow", u"\u65ad\u5f00\u8fde\u63a5", None))
        self.timezoneButton.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u65f6\u533a", None))
        self.setWan.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u516c\u7f51", None))
        self.setLan.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u5185\u7f51", None))
        self.label_2.setText(QCoreApplication.translate("MainWindow", u"\u5185\u5b58\u4f7f\u7528\u7387", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"CPU\u4f7f\u7528\u7387", None))
        self.label_3.setText(QCoreApplication.translate("MainWindow", u"\u78c1\u76d8\u4f7f\u7528\u7387", None))
        self.Shell.setMarkdown("")
        self.Shell.setHtml(QCoreApplication.translate("MainWindow", u"<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n"
"<html><head><meta name=\"qrichtext\" content=\"1\" /><meta charset=\"utf-8\" /><style type=\"text/css\">\n"
"p, li { white-space: pre-wrap; }\n"
"hr { height: 1px; border-width: 0; }\n"
"li.unchecked::marker { content: \"\\2610\"; }\n"
"li.checked::marker { content: \"\\2612\"; }\n"
"</style></head><body style=\" font-family:'.AppleSystemUIFont'; font-size:13pt; font-weight:400; font-style:normal;\">\n"
"<p style=\"-qt-paragraph-type:empty; margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\"><br /></p></body></html>", None))
        ___qtreewidgetitem1 = self.treeWidget333.headerItem()
        ___qtreewidgetitem1.setText(0, QCoreApplication.translate("MainWindow", u"\u8bbe\u5907\u5217\u8868", None));
    # retranslateUi

