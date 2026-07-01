# -*- coding: utf-8 -*-
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import (QCoreApplication, QMetaObject,
                            QSize, Qt)
from PySide6.QtGui import (QCursor)
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout,
                               QLabel,
                               QProgressBar,
                               QSplitter, QTabWidget,
                               QTreeWidget, QVBoxLayout, QWidget)


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1370, 777)
        self.centralwidget = QWidget(MainWindow)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.centralwidget.sizePolicy().hasHeightForWidth())
        self.centralwidget.setSizePolicy(sizePolicy)
        self.centralwidget.setObjectName(u"centralwidget")

        self.gridLayout_5 = QGridLayout(self.centralwidget)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.splitter_3 = QSplitter(self.centralwidget)
        self.splitter_3.setObjectName(u"splitter_3")
        self.splitter_3.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        self.splitter_3.setMouseTracking(False)
        self.splitter_3.setOrientation(Qt.Orientation.Horizontal)

        # ── 左侧面板 ──────────────────────────────────────────────────────────
        self.gridLayoutWidget = QWidget(self.splitter_3)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayout = QGridLayout(self.gridLayoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setVerticalSpacing(0)

        # 行 1：文件树（占满剩余高度）
        self.treeWidget = QTreeWidget(self.gridLayoutWidget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.treeWidget.sizePolicy().hasHeightForWidth())
        self.treeWidget.setSizePolicy(sizePolicy)
        self.treeWidget.setCursor(QCursor(Qt.ArrowCursor))
        self.treeWidget.setFocusPolicy(QtCore.Qt.NoFocus)
        self.treeWidget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.treeWidget.setObjectName(u"treeWidget")
        self.treeWidget.setRootIsDecorated(True)
        self.treeWidget.setIndentation(20)

        self.gridLayout.addWidget(self.treeWidget, 1, 0, 1, 1)
        self.gridLayout.setRowStretch(1, 1)

        # 行 2：下载进度条 + 下载布局
        self.download_with_resume1 = QProgressBar(self.gridLayoutWidget)
        self.download_with_resume1.setObjectName(u"download_with_resume")
        self.download_with_resume1.setVisible(False)
        self.download_with_resume1.setMaximumSize(QSize(16777215, 10))
        self.download_with_resume1.setValue(0)

        self.gridLayout.addWidget(self.download_with_resume1, 2, 0, 1, 1)

        self.download_with_resume = QVBoxLayout()
        self.download_with_resume.setObjectName(u"download_with_resume")
        self.download_with_resume.setContentsMargins(0, 0, 0, 0)

        self.gridLayout.addLayout(self.download_with_resume, 2, 0, 1, 1)

        # 行 3：跟随终端文件夹复选框 + 远程监控复选框（水平布局）
        self.follow_folder = QCheckBox(self.gridLayoutWidget)
        self.follow_folder.setObjectName("follow_folder")
        self.follow_folder.setCursor(QCursor(Qt.ArrowCursor))
        self.follow_folder.setText("")
        self.follow_folder.setChecked(False)

        self.remote_monitoring = QCheckBox(self.gridLayoutWidget)
        self.remote_monitoring.setObjectName("remote_monitoring")
        self.remote_monitoring.setCursor(QCursor(Qt.ArrowCursor))
        self.remote_monitoring.setText("")
        self.remote_monitoring.setChecked(False)

        self.checkbox_row_layout = QHBoxLayout()
        self.checkbox_row_layout.setContentsMargins(0, 0, 0, 0)
        self.checkbox_row_layout.setSpacing(15)
        self.checkbox_row_layout.addWidget(self.follow_folder)
        self.checkbox_row_layout.addWidget(self.remote_monitoring)
        self.checkbox_row_layout.addStretch()

        self.gridLayout.addLayout(self.checkbox_row_layout, 3, 0, 1, 1)

        self.splitter_3.addWidget(self.gridLayoutWidget)

        # ── 右侧面板（仅包含 ShellTab）────────────────────────────────────────
        self.gridLayoutWidget_right = QWidget(self.splitter_3)
        self.gridLayoutWidget_right.setObjectName(u"gridLayoutWidget_right")
        self.gridLayout_right = QGridLayout(self.gridLayoutWidget_right)
        self.gridLayout_right.setObjectName(u"gridLayout_right")
        self.gridLayout_right.setContentsMargins(0, 0, 0, 0)

        self.ShellTab = QTabWidget(self.gridLayoutWidget_right)
        # 允许标签可移动
        self.ShellTab.setMovable(True)
        self.ShellTab.setObjectName(u"ShellTab")
        self.ShellTab.tabBar().setCursor(QCursor(Qt.PointingHandCursor))
        self.ShellTab.setStyleSheet(u"QTabWidget::tab-bar { left: 0px; }")

        self.index = QWidget()
        self.index.setObjectName(u"index")
        self.verticalLayout_5 = QVBoxLayout(self.index)
        self.verticalLayout_5.setSpacing(0)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.verticalLayout_5.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_6 = QVBoxLayout()
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")

        self.widget = QWidget(self.index)
        self.widget.setObjectName(u"widget")
        self.gridLayout_2 = QGridLayout(self.widget)
        self.gridLayout_2.setSpacing(0)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.gridLayout_2.setContentsMargins(0, 117, 0, 117)
        self.label_11 = QLabel(self.widget)
        self.label_11.setObjectName(u"label_11")

        self.gridLayout_2.addWidget(self.label_11, 2, 0, 1, 1)

        self.label_13 = QLabel(self.widget)
        self.label_13.setObjectName(u"label_13")

        self.gridLayout_2.addWidget(self.label_13, 6, 0, 1, 1)

        self.label_7 = QLabel(self.widget)
        self.label_7.setObjectName(u"label_7")

        self.gridLayout_2.addWidget(self.label_7, 0, 0, 1, 1)

        self.label_12 = QLabel(self.widget)
        self.label_12.setObjectName(u"label_12")

        self.gridLayout_2.addWidget(self.label_12, 4, 0, 1, 1)

        self.label_15 = QLabel(self.widget)
        self.label_15.setObjectName(u"label_15")

        self.gridLayout_2.addWidget(self.label_15, 8, 0, 1, 1)

        self.label_14 = QLabel(self.widget)
        self.label_14.setObjectName(u"label_14")

        self.gridLayout_2.addWidget(self.label_14, 7, 0, 1, 1)

        self.label_9 = QLabel(self.widget)
        self.label_9.setObjectName(u"label_9")

        self.gridLayout_2.addWidget(self.label_9, 1, 0, 1, 1)

        self.verticalLayout_6.addWidget(self.widget, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self.verticalLayout_5.addLayout(self.verticalLayout_6)

        self.ShellTab.addTab(self.index, "")

        self.gridLayout_right.addWidget(self.ShellTab, 0, 0, 1, 1)

        self.splitter_3.addWidget(self.gridLayoutWidget_right)
        self.splitter_3.setSizes([280, 1090])

        self.gridLayout_5.addWidget(self.splitter_3, 0, 0, 1, 1)

        MainWindow.setCentralWidget(self.centralwidget)
        self.action = QtGui.QAction(MainWindow)
        self.action.setObjectName("action")
        self.retranslateUi(MainWindow)

        self.ShellTab.setCurrentIndex(0)

        QMetaObject.connectSlotsByName(MainWindow)

    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle("")
        ___qtreewidgetitem = self.treeWidget.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"\u8bbe\u5907\u5217\u8868", None));
        self.follow_folder.setText(QCoreApplication.translate("MainWindow", u"\u8ddf\u968f\u7ec8\u7aef\u76ee\u5f55", None))
        self.remote_monitoring.setText(QCoreApplication.translate("MainWindow", u"\u8fdc\u7a0b\u76d1\u63a7", None))
        self.label_11.setText(QCoreApplication.translate("MainWindow", u"\u5e2e\u52a9 Shift+Command+P", None))
        self.label_13.setText(
            QCoreApplication.translate("MainWindow", u"\u67e5\u627e\u547d\u4ee4\u884c Shift+Command+C", None))
        self.label_7.setText(
            QCoreApplication.translate("MainWindow", u"\u6dfb\u52a0\u914d\u7f6e Shift+Command+A", None))
        self.label_12.setText(QCoreApplication.translate("MainWindow", u"\u5173\u4e8e Shift+Command+B", None))
        self.label_15.setText(
            QCoreApplication.translate("MainWindow", u"\u5bfc\u51fa\u914d\u7f6e Shift+Command+E", None))
        self.label_14.setText(
            QCoreApplication.translate("MainWindow", u"\u5bfc\u5165\u914d\u7f6e Shift+Command+I", None))
        self.label_9.setText(
            QCoreApplication.translate("MainWindow", u"\u6dfb\u52a0\u96a7\u9053 Shift+Command+S", None))
        self.ShellTab.setTabText(self.ShellTab.indexOf(self.index),
                                 QCoreApplication.translate("MainWindow", u"\u9996\u9875", None))

    # retranslateUi
