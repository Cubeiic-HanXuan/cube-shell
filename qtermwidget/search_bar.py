#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SearchBar - 搜索栏UI组件
从Konsole的SearchBar.cpp/h转换而来

Copyright 2013 Christian Surlykke
转换为Python PySide6版本
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeyEvent, QPalette, QColor, QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QToolButton, QLabel,
    QLineEdit, QMenu
)


class SearchBar(QWidget):
    """
    搜索栏组件 - 提供终端内容搜索功能的UI界面
    
    包含搜索文本框、前进/后退导航按钮、选项菜单等。
    支持大小写匹配、正则表达式、高亮所有匹配等功能。
    
    对应C++: class SearchBar : public QWidget
    """
    
    # 信号定义 - 与C++完全一致
    searchCriteriaChanged = Signal()           # 搜索条件改变
    highlightMatchesChanged = Signal(bool)     # 高亮匹配改变  
    findNext = Signal()                        # 查找下一个
    findPrevious = Signal()                    # 查找上一个
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        构造搜索栏
        
        Args:
            parent: 父窗口部件
            
        对应C++: SearchBar::SearchBar(QWidget *parent) : QWidget(parent)
        """
        super().__init__(parent)
        
        self._setupUi()
        self._connectSignals()
        self._setupOptionsMenu()
    
    def __del__(self):
        """
        析构函数
        
        对应C++: SearchBar::~SearchBar()
        """
        # Python中由垃圾回收自动处理
        pass
    
    def _setupUi(self):
        """
        设置UI布局
        
        对应C++: widget.setupUi(this);
        """
        # 设置背景总是不透明，特别是在半透明窗口内
        # 对应C++: setAutoFillBackground(true);
        self.setAutoFillBackground(True)
        
        # 创建水平布局
        self._layout = QHBoxLayout(self)
        
        # 关闭按钮
        # 对应C++: widget.closeButton
        self._closeButton = QToolButton()
        self._closeButton.setText("X")
        self._closeButton.setIcon(QIcon.fromTheme("dialog-close"))
        self._layout.addWidget(self._closeButton)
        
        # "查找:"标签
        # 对应C++: widget.findLabel
        self._findLabel = QLabel(self.tr("Find:"))
        self._layout.addWidget(self._findLabel)
        
        # 搜索文本编辑框
        # 对应C++: widget.searchTextEdit
        self._searchTextEdit = QLineEdit()
        self._layout.addWidget(self._searchTextEdit)
        
        # 查找上一个按钮
        # 对应C++: widget.findPreviousButton
        self._findPreviousButton = QToolButton()
        self._findPreviousButton.setText("<")
        self._findPreviousButton.setIcon(QIcon.fromTheme("go-previous"))
        self._layout.addWidget(self._findPreviousButton)
        
        # 查找下一个按钮
        # 对应C++: widget.findNextButton
        self._findNextButton = QToolButton()
        self._findNextButton.setText(">")
        self._findNextButton.setIcon(QIcon.fromTheme("go-next"))
        self._layout.addWidget(self._findNextButton)
        
        # 选项按钮
        # 对应C++: widget.optionsButton
        self._optionsButton = QToolButton()
        self._optionsButton.setText("...")
        self._optionsButton.setIcon(QIcon.fromTheme("preferences-system"))
        self._optionsButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._layout.addWidget(self._optionsButton)
        
        # 设置窗口属性
        self.setWindowTitle("SearchBar")
        self.resize(399, 40)
    
    def _connectSignals(self):
        """
        连接信号和槽
        
        对应C++构造函数中的connect语句
        """
        # 对应C++: connect(widget.closeButton, &QAbstractButton::clicked, this, &SearchBar::hide);
        self._closeButton.clicked.connect(self.hide)
        
        # 对应C++: connect(widget.searchTextEdit, SIGNAL(textChanged(QString)), this, SIGNAL(searchCriteriaChanged()));
        self._searchTextEdit.textChanged.connect(self.searchCriteriaChanged)
        
        # 对应C++: connect(widget.findPreviousButton, SIGNAL(clicked()), this, SIGNAL(findPrevious()));
        self._findPreviousButton.clicked.connect(self.findPrevious)
        
        # 对应C++: connect(widget.findNextButton, SIGNAL(clicked()), this, SIGNAL(findNext()));
        self._findNextButton.clicked.connect(self.findNext)
        
        # 对应C++: connect(this, SIGNAL(searchCriteriaChanged()), this, SLOT(clearBackgroundColor()));
        self.searchCriteriaChanged.connect(self.clearBackgroundColor)
    
    def _setupOptionsMenu(self):
        """
        设置选项菜单
        
        对应C++构造函数中的选项菜单设置
        """
        # 对应C++: QMenu *optionsMenu = new QMenu(widget.optionsButton);
        # widget.optionsButton->setMenu(optionsMenu);
        optionsMenu = QMenu(self._optionsButton)
        self._optionsButton.setMenu(optionsMenu)
        
        # 匹配大小写选项
        # 对应C++: m_matchCaseMenuEntry = optionsMenu->addAction(tr("Match case"));
        self._matchCaseMenuEntry = optionsMenu.addAction(self.tr("Match case"))
        self._matchCaseMenuEntry.setCheckable(True)
        self._matchCaseMenuEntry.setChecked(True)
        self._matchCaseMenuEntry.toggled.connect(self.searchCriteriaChanged)
        
        # 正则表达式选项
        # 对应C++: m_useRegularExpressionMenuEntry = optionsMenu->addAction(tr("Regular expression"));
        self._useRegularExpressionMenuEntry = optionsMenu.addAction(self.tr("Regular expression"))
        self._useRegularExpressionMenuEntry.setCheckable(True)
        self._useRegularExpressionMenuEntry.toggled.connect(self.searchCriteriaChanged)
        
        # 高亮所有匹配选项
        # 对应C++: m_highlightMatchesMenuEntry = optionsMenu->addAction(tr("Highlight all matches"));
        self._highlightMatchesMenuEntry = optionsMenu.addAction(self.tr("Highlight all matches"))
        self._highlightMatchesMenuEntry.setCheckable(True)
        self._highlightMatchesMenuEntry.setChecked(True)
        self._highlightMatchesMenuEntry.toggled.connect(self.highlightMatchesChanged)
    
    # ===============================
    # C++公开方法 (完全一致的API)
    # ===============================
    
    def searchText(self) -> str:
        """
        获取搜索文本
        
        Returns:
            str: 当前搜索文本
            
        对应C++: QString SearchBar::searchText()
        """
        # 对应C++: return widget.searchTextEdit->text();
        return self._searchTextEdit.text()
    
    def useRegularExpression(self) -> bool:
        """
        是否使用正则表达式
        
        Returns:
            bool: 是否启用正则表达式搜索
            
        对应C++: bool SearchBar::useRegularExpression()
        """
        # 对应C++: return m_useRegularExpressionMenuEntry->isChecked();
        return self._useRegularExpressionMenuEntry.isChecked()
    
    def matchCase(self) -> bool:
        """
        是否匹配大小写
        
        Returns:
            bool: 是否启用大小写匹配
            
        对应C++: bool SearchBar::matchCase()
        """
        # 对应C++: return m_matchCaseMenuEntry->isChecked();
        return self._matchCaseMenuEntry.isChecked()
    
    def highlightAllMatches(self) -> bool:
        """
        是否高亮所有匹配
        
        Returns:
            bool: 是否启用高亮所有匹配
            
        对应C++: bool SearchBar::highlightAllMatches()
        """
        # 对应C++: return m_highlightMatchesMenuEntry->isChecked();
        return self._highlightMatchesMenuEntry.isChecked()
    
    def show(self):
        """
        显示搜索栏并设置焦点
        
        对应C++: void SearchBar::show()
        """
        # 对应C++: QWidget::show();
        # widget.searchTextEdit->setFocus();
        # widget.searchTextEdit->selectAll();
        super().show()
        self._searchTextEdit.setFocus()
        self._searchTextEdit.selectAll()
    
    @Slot()
    def hide(self):
        """
        隐藏搜索栏并将焦点返回给父窗口部件
        
        对应C++: void SearchBar::hide()
        """
        # 对应C++: QWidget::hide();
        # if (QWidget *p = parentWidget())
        # {
        #     p->setFocus(Qt::OtherFocusReason);
        # }
        super().hide()
        if self.parentWidget():
            self.parentWidget().setFocus(Qt.FocusReason.OtherFocusReason)
    
    @Slot()
    def noMatchFound(self):
        """
        显示未找到匹配的视觉反馈
        
        对应C++: void SearchBar::noMatchFound()
        """
        # 对应C++: QPalette palette;
        # palette.setColor(widget.searchTextEdit->backgroundRole(), QColor(255, 128, 128));
        # widget.searchTextEdit->setPalette(palette);
        palette = QPalette()
        palette.setColor(self._searchTextEdit.backgroundRole(), QColor(255, 128, 128))
        self._searchTextEdit.setPalette(palette)
    
    # ===============================
    # 事件处理 (受保护的方法)
    # ===============================
    
    def keyReleaseEvent(self, keyEvent: QKeyEvent):
        """
        处理键盘释放事件
        
        Args:
            keyEvent: 键盘事件
            
        对应C++: void SearchBar::keyReleaseEvent(QKeyEvent* keyEvent)
        """
        # 对应C++完整实现:
        # if (keyEvent->key() == Qt::Key_Return || keyEvent->key() == Qt::Key_Enter)
        # {
        #     if (keyEvent->modifiers() == Qt::ShiftModifier)
        #     {
        #         Q_EMIT findPrevious();
        #     }
        #     else
        #     {
        #         Q_EMIT findNext();
        #     }
        # }
        # else if (keyEvent->key() == Qt::Key_Escape)
        # {
        #     hide();
        # }
        
        if keyEvent.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if keyEvent.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                self.findPrevious.emit()
            else:
                self.findNext.emit()
        elif keyEvent.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyReleaseEvent(keyEvent)
    
    # ===============================
    # 私有槽
    # ===============================
    
    @Slot()
    def clearBackgroundColor(self):
        """
        清除搜索框的背景色，恢复默认外观
        
        对应C++: void SearchBar::clearBackgroundColor()
        """
        # 对应C++: widget.searchTextEdit->setPalette(QWidget::window()->palette());
        if self.window():
            self._searchTextEdit.setPalette(self.window().palette())


# ===============================
# 工厂函数
# ===============================

def create_search_bar(parent: Optional[QWidget] = None) -> SearchBar:
    """
    创建搜索栏的工厂函数
    
    Args:
        parent: 父窗口部件
        
    Returns:
        SearchBar: 搜索栏对象
    """
    return SearchBar(parent) 