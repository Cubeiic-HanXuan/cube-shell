# -*- coding: utf-8 -*-
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import (QCoreApplication, QMetaObject, QRect,
                            QSize, Qt)
from PySide6.QtGui import (QCursor, QFont, QIcon)
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QTabWidget, QTableWidget,
                               QTextBrowser, QTreeWidget, QVBoxLayout, QWidget)

from style.style import DangerButtonStyle, PrimaryButtonStyle


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
        self.gridLayoutWidget = QWidget(self.splitter_3)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayout = QGridLayout(self.gridLayoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setVerticalSpacing(0)

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
        self.treeWidget.setRootIsDecorated(False)
        self.treeWidget.setIndentation(0)

        self.gridLayout.addWidget(self.treeWidget, 1, 0, 1, 1)

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

        self.splitter_3.addWidget(self.gridLayoutWidget)
        self.splitter_255 = QSplitter(self.splitter_3)
        self.splitter_255.setObjectName(u"splitter_255")
        self.splitter_255.setMinimumSize(QSize(0, 0))
        self.splitter_255.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        self.splitter_255.setMouseTracking(False)
        self.splitter_255.setOrientation(Qt.Orientation.Horizontal)
        self.gridLayoutWidget_2 = QWidget(self.splitter_255)
        self.gridLayoutWidget_2.setObjectName(u"gridLayoutWidget_2")
        self.gridLayout_4 = QGridLayout(self.gridLayoutWidget_2)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.gridLayout_4.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_3 = QVBoxLayout()
        self.verticalLayout_3.setSpacing(2)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_3.setContentsMargins(0, -1, -1, -1)
        self.search_box = QLineEdit(self.gridLayoutWidget_2)
        self.search_box.setFocusPolicy(Qt.ClickFocus)
        self.search_box.setObjectName(u"search_box")

        self.verticalLayout_3.addWidget(self.search_box)

        self.result = QTableWidget(self.gridLayoutWidget_2)
        self.result.setFocusPolicy(Qt.ClickFocus)
        # 去掉最左边的序号列
        self.result.verticalHeader().setVisible(False)
        self.result.setObjectName(u"result")

        self.verticalLayout_3.addWidget(self.result)

        self.gridLayout_4.addLayout(self.verticalLayout_3, 4, 0, 1, 2)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.horizontalLayout_5.setContentsMargins(3, -1, 3, -1)
        self.discButton = QPushButton(self.gridLayoutWidget_2)
        self.discButton.setEnabled(False)
        self.discButton.setTabletTracking(False)
        self.discButton.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.discButton.setStyleSheet(DangerButtonStyle)
        self.discButton.setCursor(QCursor(Qt.PointingHandCursor))
        self.discButton.setObjectName(u"discButton")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.discButton.sizePolicy().hasHeightForWidth())
        self.discButton.setSizePolicy(sizePolicy)

        self.horizontalLayout_5.addWidget(self.discButton)

        self.theme = QPushButton(self.gridLayoutWidget_2)
        self.theme.setTabletTracking(False)
        self.theme.setStyleSheet(PrimaryButtonStyle)
        self.theme.setCursor(QCursor(Qt.PointingHandCursor))
        self.theme.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.theme.setObjectName(u"theme")

        self.horizontalLayout_5.addWidget(self.theme)

        self.gridLayout_4.addLayout(self.horizontalLayout_5, 1, 0, 1, 2)

        self.gridLayout_8 = QGridLayout()
        self.gridLayout_8.setObjectName(u"gridLayout_8")
        self.gridLayout_8.setContentsMargins(3, -1, 3, -1)
        self.operatingSystem = QLineEdit(self.gridLayoutWidget_2)
        self.operatingSystem.setFocusPolicy(Qt.ClickFocus)
        self.operatingSystem.setObjectName(u"operatingSystem")
        self.operatingSystem.setReadOnly(True)

        self.gridLayout_8.addWidget(self.operatingSystem, 5, 1, 1, 1)

        self.label_5 = QLabel(self.gridLayoutWidget_2)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_8.addWidget(self.label_5, 4, 0, 1, 1)

        self.diskRate = QProgressBar(self.gridLayoutWidget_2)
        self.diskRate.setObjectName(u"diskRate")
        self.diskRate.setRange(0, 100)
        self.diskRate.setValue(0)

        self.gridLayout_8.addWidget(self.diskRate, 2, 1, 1, 1)

        self.label_2 = QLabel(self.gridLayoutWidget_2)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout_8.addWidget(self.label_2, 1, 0, 1, 1)

        self.kernelVersion = QLineEdit(self.gridLayoutWidget_2)
        self.kernelVersion.setFocusPolicy(Qt.ClickFocus)
        self.kernelVersion.setObjectName(u"kernelVersion")
        self.kernelVersion.setReadOnly(True)

        self.gridLayout_8.addWidget(self.kernelVersion, 7, 1, 1, 1)

        self.memRate = QProgressBar(self.gridLayoutWidget_2)
        self.memRate.setObjectName(u"memRate")
        self.memRate.setRange(0, 100)
        self.memRate.setValue(0)

        self.gridLayout_8.addWidget(self.memRate, 1, 1, 1, 1)

        self.cpuRate = QProgressBar(self.gridLayoutWidget_2)
        self.cpuRate.setObjectName(u"cpuRate")
        self.cpuRate.setRange(0, 100)
        self.cpuRate.setValue(0)

        self.gridLayout_8.addWidget(self.cpuRate, 0, 1, 1, 1)

        self.label_3 = QLabel(self.gridLayoutWidget_2)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_8.addWidget(self.label_3, 2, 0, 1, 1)

        self.label_4 = QLabel(self.gridLayoutWidget_2)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_8.addWidget(self.label_4, 5, 0, 1, 1)

        self.label_10 = QLabel(self.gridLayoutWidget_2)
        self.label_10.setObjectName(u"label_10")

        self.gridLayout_8.addWidget(self.label_10, 7, 0, 1, 1)

        self.label_6 = QLabel(self.gridLayoutWidget_2)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout_8.addWidget(self.label_6, 3, 0, 1, 1)

        self.label = QLabel(self.gridLayoutWidget_2)
        self.label.setObjectName(u"label")

        self.gridLayout_8.addWidget(self.label, 0, 0, 1, 1)

        self.kernel = QLineEdit(self.gridLayoutWidget_2)
        self.kernel.setFocusPolicy(Qt.ClickFocus)
        self.kernel.setObjectName(u"kernel")
        self.kernel.setReadOnly(True)

        self.gridLayout_8.addWidget(self.kernel, 6, 1, 1, 1)

        self.label_8 = QLabel(self.gridLayoutWidget_2)
        self.label_8.setObjectName(u"label_8")

        self.gridLayout_8.addWidget(self.label_8, 6, 0, 1, 1)

        self.networkUpload = QLineEdit(self.gridLayoutWidget_2)
        self.networkUpload.setFocusPolicy(Qt.ClickFocus)
        self.networkUpload.setObjectName(u"networkUpload")
        self.networkUpload.setReadOnly(True)

        self.gridLayout_8.addWidget(self.networkUpload, 3, 1, 1, 1)

        self.networkDownload = QLineEdit(self.gridLayoutWidget_2)
        self.networkDownload.setFocusPolicy(Qt.ClickFocus)
        self.networkDownload.setObjectName(u"networkDownload")
        self.networkDownload.setReadOnly(True)

        self.gridLayout_8.addWidget(self.networkDownload, 4, 1, 1, 1)

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

        self.ShellTab = QTabWidget(self.verticalLayoutWidget)
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

        self.verticalLayout.addWidget(self.ShellTab)

        self.splitter.addWidget(self.verticalLayoutWidget)
        self.verticalLayoutWidget_2 = QWidget(self.splitter)
        self.verticalLayoutWidget_2.setObjectName(u"verticalLayoutWidget_2")
        self.verticalLayout_2 = QVBoxLayout(self.verticalLayoutWidget_2)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.tabWidget = QTabWidget(self.verticalLayoutWidget_2)
        self.tabWidget.setCursor(QCursor(Qt.PointingHandCursor))
        font = QFont()
        font.setWeight(QFont.ExtraLight)
        self.tabWidget.setFont(font)
        self.tabWidget.setStyleSheet("""
            QTabBar::tab {
                border-top-left-radius: 10px; /* 左上角圆角 */
                border-top-right-radius: 10px; /* 右上角圆角 */
                min-width: 8ex;
                padding: 2px;
            }
            QTabBar::tab:selected {
                margin-bottom: 1px; /* 使选中的 tab 突出 */
            }
        """)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tab_docker_manager = QWidget()
        self.tab_docker_manager.setObjectName(u"tab_docker_manager")
        self.horizontalLayout_4 = QHBoxLayout(self.tab_docker_manager)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.horizontalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")

        self.treeWidgetDocker = QTreeWidget(self.tab_docker_manager)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.treeWidgetDocker.sizePolicy().hasHeightForWidth())
        self.treeWidgetDocker.setSizePolicy(sizePolicy)
        self.treeWidgetDocker.setCursor(QCursor(Qt.ArrowCursor))
        self.treeWidgetDocker.setFocusPolicy(QtCore.Qt.NoFocus)
        self.treeWidgetDocker.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.treeWidgetDocker.setObjectName(u"treeWidgetDocker")

        self.horizontalLayout_2.addWidget(self.treeWidgetDocker)

        self.horizontalLayout_4.addLayout(self.horizontalLayout_2)

        self.tabWidget.addTab(self.tab_docker_manager, "")
        self.tab_docker_soft = QWidget()
        self.tab_docker_soft.setObjectName(u"tab_docker_soft")
        self.horizontalLayout_8 = QHBoxLayout(self.tab_docker_soft)
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.horizontalLayout_8.setContentsMargins(0, 0, 0, 0)
        self.gridLayout_7 = QGridLayout()
        self.gridLayout_7.setObjectName(u"gridLayout_7")

        self.horizontalLayout_8.addLayout(self.gridLayout_7)

        self.tabWidget.addTab(self.tab_docker_soft, "")
        self.tab_ssh_manager = QWidget()
        self.tab_ssh_manager.setObjectName(u"tab_ssh_manager")
        self.formLayout = QFormLayout(self.tab_ssh_manager)
        self.formLayout.setObjectName(u"formLayout")
        self.formLayout.setHorizontalSpacing(0)
        self.formLayout.setVerticalSpacing(0)
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = QScrollArea(self.tab_ssh_manager)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setContentsMargins(0, 0, 0, 0)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 925, 109))
        self.gridLayout_11 = QGridLayout(self.scrollAreaWidgetContents)
        self.gridLayout_11.setObjectName(u"gridLayout_11")
        self.gridLayout_11.setContentsMargins(12, -1, -1, -1)
        self.gridLayout_tunnel_tabs = QGridLayout()
        self.gridLayout_tunnel_tabs.setObjectName(u"gridLayout_tunnel_tabs")

        self.gridLayout_11.addLayout(self.gridLayout_tunnel_tabs, 0, 0, 1, 1)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents)

        self.formLayout.setWidget(0, QFormLayout.SpanningRole, self.scrollArea)

        self.gridLayout_kill_all = QGridLayout()
        self.gridLayout_kill_all.setObjectName(u"gridLayout_kill_all")
        self.gridLayout_kill_all.setContentsMargins(0, 0, 0, 0)

        self.formLayout.setLayout(1, QFormLayout.SpanningRole, self.gridLayout_kill_all)

        self.tabWidget.addTab(self.tab_ssh_manager, "")

        self.NAT_traversal = QWidget()
        self.NAT_traversal.setObjectName(u"NAT_traversal")
        self.verticalLayout_4 = QVBoxLayout(self.NAT_traversal)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.gridLayout_10 = QGridLayout()
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.label_17 = QLabel(self.NAT_traversal)
        self.label_17.setObjectName(u"label_17")

        self.gridLayout_10.addWidget(self.label_17, 1, 2, 1, 1)

        self.lineEdit_3 = QLineEdit(self.NAT_traversal)
        self.lineEdit_3.setObjectName(u"lineEdit_3")

        self.gridLayout_10.addWidget(self.lineEdit_3, 1, 3, 1, 1)

        self.label_19 = QLabel(self.NAT_traversal)
        self.label_19.setObjectName(u"label_19")

        self.gridLayout_10.addWidget(self.label_19, 2, 2, 1, 1)

        self.comboBox = QComboBox(self.NAT_traversal)
        self.comboBox.setObjectName(u"comboBox")

        self.gridLayout_10.addWidget(self.comboBox, 1, 1, 1, 1)

        self.comboBox_3 = QComboBox(self.NAT_traversal)
        self.comboBox_3.addItem("")
        self.comboBox_3.addItem("")
        self.comboBox_3.addItem("")
        self.comboBox_3.setObjectName(u"comboBox_3")

        self.gridLayout_10.addWidget(self.comboBox_3, 2, 1, 1, 1)

        self.label_16 = QLabel(self.NAT_traversal)
        self.label_16.setObjectName(u"label_16")

        self.gridLayout_10.addWidget(self.label_16, 1, 0, 1, 1)

        self.lineEdit_2 = QLineEdit(self.NAT_traversal)
        self.lineEdit_2.setObjectName(u"lineEdit_2")

        self.gridLayout_10.addWidget(self.lineEdit_2, 2, 3, 1, 1)

        self.label_18 = QLabel(self.NAT_traversal)
        self.label_18.setObjectName(u"label_18")

        self.gridLayout_10.addWidget(self.label_18, 2, 0, 1, 1)

        self.label_20 = QLabel(self.NAT_traversal)
        self.label_20.setObjectName(u"label_20")

        self.gridLayout_10.addWidget(self.label_20, 3, 0, 1, 1)

        self.lineEdit = QLineEdit(self.NAT_traversal)
        self.lineEdit.setObjectName(u"lineEdit")
        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password)

        self.gridLayout_10.addWidget(self.lineEdit, 3, 1, 1, 1)

        self.pushButton = QPushButton(self.NAT_traversal)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setToolTip("启动/关闭")
        self.pushButton.setMaximumSize(QSize(50, 16777215))
        self.pushButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        icon1 = QIcon()
        icon1.addFile(u":open.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.pushButton.setIcon(icon1)
        self.pushButton.setIconSize(QSize(50, 20))
        self.pushButton.setFlat(True)

        self.gridLayout_10.addWidget(self.pushButton, 3, 3, 1, 1)

        self.verticalLayout_4.addLayout(self.gridLayout_10)

        self.tabWidget.addTab(self.NAT_traversal, "")

        self.verticalLayout_2.addWidget(self.tabWidget)

        self.splitter.addWidget(self.verticalLayoutWidget_2)

        self.gridLayout_6.addWidget(self.splitter, 0, 0, 1, 1)

        self.splitter_255.addWidget(self.gridLayoutWidget_3)
        self.splitter_3.addWidget(self.splitter_255)

        self.gridLayout_5.addWidget(self.splitter_3, 0, 0, 1, 1)

        MainWindow.setCentralWidget(self.centralwidget)
        self.action = QtGui.QAction(MainWindow)
        self.action.setObjectName("action")
        self.retranslateUi(MainWindow)

        self.ShellTab.setCurrentIndex(0)
        self.tabWidget.setCurrentIndex(2)

        QMetaObject.connectSlotsByName(MainWindow)

    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle("")
        ___qtreewidgetitem = self.treeWidget.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"\u8bbe\u5907\u5217\u8868", None));
        self.search_box.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u641c\u7d22...", None))
        self.discButton.setText(QCoreApplication.translate("MainWindow", u"\u65ad\u5f00\u8fde\u63a5", None))
        self.theme.setText(QCoreApplication.translate("MainWindow", u"\u5207\u6362\u4e3b\u9898", None))
        self.operatingSystem.setText("")
        self.label_5.setText(QCoreApplication.translate("MainWindow", u"\u7f51\u7edc\u4e0b\u884c", None))
        self.label_2.setText(QCoreApplication.translate("MainWindow", u"\u5185\u5b58\u76d1\u63a7", None))
        self.kernelVersion.setText("")
        self.label_3.setText(QCoreApplication.translate("MainWindow", u"\u78c1\u76d8\u76d1\u63a7", None))
        self.label_4.setText(QCoreApplication.translate("MainWindow", u"\u64cd\u4f5c\u7cfb\u7edf", None))
        self.label_10.setText(QCoreApplication.translate("MainWindow", u"\u5185\u6838\u7248\u672c", None))
        self.label_6.setText(QCoreApplication.translate("MainWindow", u"\u7f51\u7edc\u4e0a\u884c", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"CPU\u76d1\u63a7", None))
        self.kernel.setText(QCoreApplication.translate("MainWindow", u"Linux", None))
        self.label_8.setText(QCoreApplication.translate("MainWindow", u"\u5185\u6838", None))
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
        ___qtreewidgetitem1 = self.treeWidgetDocker.headerItem()
        ___qtreewidgetitem1.setText(0, QCoreApplication.translate("MainWindow", u"docker容器管理", None));
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_docker_manager),
                                  QCoreApplication.translate("MainWindow", u"\u5bb9\u5668\u7ba1\u7406", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_docker_soft),
                                  QCoreApplication.translate("MainWindow", u"\u5e38\u7528\u5bb9\u5668", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_ssh_manager),
                                  QCoreApplication.translate("MainWindow", u"SSH\u96a7\u9053", None))
        self.label_17.setText(
            QCoreApplication.translate("MainWindow", u"\u670d\u52a1\u7aef\u4ee3\u7406\u7aef\u53e3", None))
        self.lineEdit_3.setText(QCoreApplication.translate("MainWindow", u"80", None))
        self.label_19.setText(
            QCoreApplication.translate("MainWindow", u"\u5ba2\u6237\u7aef\u4ee3\u7406\u7aef\u53e3", None))
        self.comboBox_3.setItemText(0, QCoreApplication.translate("MainWindow", u"TCP", None))
        self.comboBox_3.setItemText(1, QCoreApplication.translate("MainWindow", u"HTTP", None))
        self.comboBox_3.setItemText(2, QCoreApplication.translate("MainWindow", u"UDP", None))

        self.label_16.setText(QCoreApplication.translate("MainWindow", u"\u670d\u52a1\u7aef", None))
        self.lineEdit_2.setText(QCoreApplication.translate("MainWindow", u"8080", None))
        self.label_18.setText(QCoreApplication.translate("MainWindow", u"\u4ee3\u7406\u7c7b\u578b", None))
        self.label_20.setText(QCoreApplication.translate("MainWindow", u"\u53cc\u5411\u8ba4\u8bc1\u5bc6\u94a5", None))
        # self.pushButton.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u542f", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.NAT_traversal),
                                  QCoreApplication.translate("MainWindow", u"\u5185\u7f51\u7a7f\u900f", None))
    # retranslateUi
