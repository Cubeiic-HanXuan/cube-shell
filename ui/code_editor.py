from PySide6.QtCore import Qt, QRect, QSize, QRegularExpression
from PySide6.QtGui import (QColor, QPainter, QSyntaxHighlighter, QTextCharFormat,
                           QFont, QTextCursor, QTextDocument)
from PySide6.QtWidgets import QPlainTextEdit, QWidget, QTextEdit


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.codeEditor = editor

    def sizeHint(self):
        return QSize(self.codeEditor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.codeEditor.lineNumberAreaPaintEvent(event)


class Highlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlightingRules = []

        # Keyword format
        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(QColor("#ff79c6"))  # Pink
        keywordFormat.setFontWeight(QFont.Bold)
        keywords = [
            "class", "const", "def", "delete", "elif", "else", "enum", "except", "explicit",
            "export", "extends", "false", "finally", "for", "from", "function", "if",
            "implements", "import", "in", "instanceof", "interface", "let", "new", "null",
            "package", "private", "protected", "public", "return", "static", "super",
            "switch", "this", "throw", "true", "try", "typeof", "var", "void", "while",
            "with", "yield", "async", "await"
        ]
        for pattern in keywords:
            self.highlightingRules.append((QRegularExpression(r"\b" + pattern + r"\b"), keywordFormat))

        # String format
        stringFormat = QTextCharFormat()
        stringFormat.setForeground(QColor("#f1fa8c"))  # Yellow
        self.highlightingRules.append((QRegularExpression(r"\".*\""), stringFormat))
        self.highlightingRules.append((QRegularExpression(r"'.*'"), stringFormat))

        # Function format
        functionFormat = QTextCharFormat()
        functionFormat.setForeground(QColor("#50fa7b"))  # Green
        self.highlightingRules.append((QRegularExpression(r"\b[A-Za-z0-9_]+(?=\()"), functionFormat))

        # Self format
        selfFormat = QTextCharFormat()
        selfFormat.setForeground(QColor("#ff5555"))  # Red
        selfFormat.setFontWeight(QFont.Bold)
        self.highlightingRules.append((QRegularExpression(r"\bself\b"), selfFormat))

        # Number format
        numberFormat = QTextCharFormat()
        numberFormat.setForeground(QColor("#bd93f9"))  # Purple
        self.highlightingRules.append((QRegularExpression(r"\b\d+\b"), numberFormat))

    def highlightBlock(self, text):
        # 1. 先应用所有语法高亮规则（关键字、字符串、数字等）
        for pattern, format in self.highlightingRules:
            expression = QRegularExpression(pattern)
            match = expression.match(text)
            while match.hasMatch():
                index = match.capturedStart()
                length = match.capturedLength()
                self.setFormat(index, length, format)
                match = expression.match(text, index + length)

        # 2. 最后应用注释规则，覆盖掉之前可能被高亮的关键字等
        # 这样注释中的 self, class 等关键字就会显示为注释颜色，而不是高亮颜色
        commentFormat = QTextCharFormat()
        commentFormat.setForeground(QColor("#6272a4"))  # Gray/Blue
        
        # Python style comments
        self.applyRule(text, QRegularExpression(r"#[^\n]*"), commentFormat)
        # C/Java style comments
        self.applyRule(text, QRegularExpression(r"//[^\n]*"), commentFormat)

    def applyRule(self, text, expression, format):
        match = expression.match(text)
        while match.hasMatch():
            index = match.capturedStart()
            length = match.capturedLength()
            self.setFormat(index, length, format)
            match = expression.match(text, index + length)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lineNumberArea = LineNumberArea(self)

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()

        # Set font
        font = QFont()
        font.setFamily("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(14)
        self.setFont(font)

        # Set tab width
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)

        # Bracket matching
        self.leftBracketFormat = QTextCharFormat()
        # self.leftBracketFormat.setBackground(QColor("#bd93f9"))
        self.leftBracketFormat.setForeground(QColor("#ff79c6"))
        self.rightBracketFormat = QTextCharFormat()
        # self.rightBracketFormat.setBackground(QColor("#bd93f9"))
        self.rightBracketFormat.setForeground(QColor("#ff79c6"))

    def lineNumberAreaWidth(self):
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        space = 3 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(0, rect.y(), self.lineNumberArea.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.lineNumberArea.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def highlightCurrentLine(self):
        extraSelections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            lineColor = QColor("#44475a")  # Dracula selection
            lineColor.setAlpha(50)
            selection.format.setBackground(lineColor)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)

        # Bracket matching
        self.matchBrackets(extraSelections)

        self.setExtraSelections(extraSelections)

    def matchBrackets(self, extraSelections):
        cursor = self.textCursor()
        block = cursor.block()
        text = block.text()
        pos = cursor.positionInBlock()

        if pos > 0 and pos <= len(text):
            char = text[pos - 1]
            if char in ")]}":
                self.matchLeftBracket(cursor, char, extraSelections)
            elif char in "([{":
                self.matchRightBracket(cursor, char, extraSelections)

    def matchLeftBracket(self, cursor, rightBracket, extraSelections):
        # Simplified bracket matching logic
        if rightBracket == ')':
            leftBracket = '('
        elif rightBracket == ']':
            leftBracket = '['
        elif rightBracket == '}':
            leftBracket = '{'

        doc = self.document()
        text = doc.toPlainText()
        pos = cursor.position() - 1
        count = 1

        while pos > 0:
            pos -= 1
            char = text[pos]
            if char == rightBracket:
                count += 1
            elif char == leftBracket:
                count -= 1
                if count == 0:
                    self.createBracketSelection(pos, extraSelections)
                    self.createBracketSelection(cursor.position() - 1, extraSelections)
                    break

    def matchRightBracket(self, cursor, leftBracket, extraSelections):
        # Simplified bracket matching logic
        if leftBracket == '(':
            rightBracket = ')'
        elif leftBracket == '[':
            rightBracket = ']'
        elif leftBracket == '{':
            rightBracket = '}'

        doc = self.document()
        text = doc.toPlainText()
        pos = cursor.position()
        count = 1
        limit = len(text)

        while pos < limit:
            char = text[pos]
            if char == leftBracket:
                count += 1
            elif char == rightBracket:
                count -= 1
                if count == 0:
                    self.createBracketSelection(pos, extraSelections)
                    self.createBracketSelection(cursor.position() - 1, extraSelections)
                    break
            pos += 1

    def createBracketSelection(self, pos, extraSelections):
        selection = QTextEdit.ExtraSelection()
        selection.format = self.leftBracketFormat  # Use same format for both
        selection.cursor = self.textCursor()
        selection.cursor.setPosition(pos)
        selection.cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        extraSelections.append(selection)

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.lineNumberArea)
        painter.fillRect(event.rect(), QColor("#282a36"))  # Background

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(blockNumber + 1)
                painter.setPen(QColor("#6272a4"))  # Line number color
                painter.setFont(self.font())
                painter.drawText(0, int(top), self.lineNumberArea.width(), self.fontMetrics().height(),
                                 Qt.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            blockNumber += 1

    def find_text(self, text, regex=False, case_sensitive=False, backward=False):
        """
        在文档中查找文本。
        
        Args:
            text: 要搜索的文本或模式。
            regex: 是否将 'text' 视为正则表达式。
            case_sensitive: 搜索是否区分大小写。
            backward: 是否向后搜索。
            
        Returns:
            bool: 如果找到则返回 True，否则返回 False。
        """
        cursor = self.textCursor()

        # 设置查找标志
        try:
            flags = QTextDocument.FindFlags(0)
        except TypeError:
            flags = QTextDocument.FindFlags()
            if flags is None:
                flags = QTextDocument.FindFlags(0)
        if case_sensitive:
            flags |= QTextDocument.FindCaseSensitively
        if backward:
            flags |= QTextDocument.FindBackward

        # 执行搜索
        if regex:
            reg = QRegularExpression(text)
            if not case_sensitive:
                reg.setPatternOptions(QRegularExpression.CaseInsensitiveOption)
            found = self.document().find(reg, cursor, flags)
        else:
            found = self.document().find(text, cursor, flags)

        # Handle not found (wrap around)
        if found.isNull():
            # 创建一个光标进行循环搜索
            temp_cursor = self.textCursor()
            temp_cursor.movePosition(QTextCursor.Start if not backward else QTextCursor.End)

            if regex:
                found = self.document().find(reg, temp_cursor, flags)
            else:
                found = self.document().find(text, temp_cursor, flags)

        # If found (either directly or after wrap)
        if not found.isNull():
            self.setTextCursor(found)
            return True

        return False

    def replace_text(self, text, new_text, regex=False, case_sensitive=False):
        cursor = self.textCursor()
        if cursor.hasSelection() and (cursor.selectedText() == text or regex):
            cursor.insertText(new_text)
            return True
        return self.find_text(text, regex, case_sensitive)

    def replace_all(self, text, new_text, regex=False, case_sensitive=False):
        """
        将所有出现的 'text' 替换为 'new_text'。
        
        Args:
            text: 要搜索的文本或模式。
            new_text: 替换后的文本。
            regex: 是否将 'text' 视为正则表达式。
            case_sensitive: 搜索是否区分大小写。
            
        Returns:
            int: 执行替换的次数。
        """
        count = 0
        cursor = self.textCursor()
        cursor.beginEditBlock()

        # 将光标移动到文档开头
        cursor.movePosition(QTextCursor.Start)
        self.setTextCursor(cursor)

        # 循环查找并替换所有出现的内容
        while True:
            # 关键修改：直接使用 document().find() 确保始终从当前光标位置向后查找
            # find_text 方法包含"循环查找"(wrap around)逻辑，这在 replace_all 中是致命的，会导致死循环
            
            # 设置查找标志
            try:
                flags = QTextDocument.FindFlags(0)
            except TypeError:
                flags = QTextDocument.FindFlags()
                if flags is None:
                    flags = QTextDocument.FindFlags(0)
            if case_sensitive:
                flags |= QTextDocument.FindCaseSensitively
            # 注意：replace_all 始终向前查找，不使用 FindBackward

            current_cursor = self.textCursor()
            
            if regex:
                reg = QRegularExpression(text)
                if not case_sensitive:
                    reg.setPatternOptions(QRegularExpression.CaseInsensitiveOption)
                # 从当前光标位置开始查找
                found_cursor = self.document().find(reg, current_cursor, flags)
            else:
                found_cursor = self.document().find(text, current_cursor, flags)

            # 如果未找到，跳出循环
            if found_cursor.isNull():
                break

            # 选中找到的文本并设置为主光标
            self.setTextCursor(found_cursor)
            
            # 执行替换
            self.textCursor().insertText(new_text)
            count += 1

            # 替换后，insertText 会自动将光标移动到插入文本的末尾
            # 下一次循环将从这个新位置继续查找，从而避免死循环

            # 安全检查：如果计数非常高，可能是无限循环（例如替换空字符串）
            if count > 100000:
                print("警告：由于替换次数过多（可能存在无限循环），已中止全部替换操作。")
                break

        cursor.endEditBlock()
        return count


from PySide6.QtGui import QTextFormat
