# """
# QTermWidget Python包 - PySide6版本
#
# 这个包提供了QTermWidget的Python绑定和工具函数。
# 从Qt C++代码转换而来。
# """
#
# from .tools import (
#     getKbLayoutDir,
#     addCustomColorSchemeDir,
#     getColorSchemesDirs,
#     clearCustomColorSchemeDirs,
#     getCustomColorSchemeDirs,
#     qtermwidgetLogger,  # C++风格的名称
#     KB_LAYOUT_DIR,
#     COLORSCHEMES_DIR,
# )
#
# from .block_array import (
#     Block,
#     BlockArray,
#     QTERMWIDGET_BLOCKSIZE,
#     ENTRIES,
# )
#
# from .character_color import (
#     ColorEntry, CharacterColor, color256, base_color_table,
#     BASE_COLORS, INTENSITIES, TABLE_COLORS,
#     DEFAULT_FORE_COLOR, DEFAULT_BACK_COLOR,
#     COLOR_SPACE_UNDEFINED, COLOR_SPACE_DEFAULT, COLOR_SPACE_SYSTEM,
#     COLOR_SPACE_256, COLOR_SPACE_RGB
# )
#
# from .character import (
#     Character, ExtendedCharTable, extended_char_table_instance,
#     LineProperty, vt100_graphics,
#     LINE_DEFAULT, LINE_WRAPPED, LINE_DOUBLEWIDTH, LINE_DOUBLEHEIGHT,
#     DEFAULT_RENDITION, RE_BOLD, RE_BLINK, RE_UNDERLINE, RE_REVERSE,
#     RE_INTENSIVE, RE_ITALIC, RE_CURSOR, RE_EXTENDED_CHAR, RE_FAINT,
#     RE_STRIKEOUT, RE_CONCEAL, RE_OVERLINE
# )
#
# from .color_scheme import (
#     ColorScheme, AccessibleColorScheme, ColorSchemeManager,
#     getColorSchemeManager
# )
#
# from .history import (
#     HistoryFile, HistoryType, HistoryScroll,
#     HistoryScrollFile, HistoryScrollBuffer, HistoryScrollNone, HistoryScrollBlockArray,
#     HistoryTypeNone, HistoryTypeBlockArray, HistoryTypeFile, HistoryTypeBuffer,
#     CompactHistoryType, CharacterFormat
# )
#
# from .wcwidth import (
#     konsole_wcwidth, string_width, clear_width_cache, get_cache_size,
#     is_wide_char, is_printable_char, truncate_string, pad_string
# )
#
# from .keyboard_translator import (
#     KeyboardTranslatorState,
#     KeyboardTranslatorCommand,
#     KeyboardTranslatorEntry,
#     KeyboardTranslator,
#     KeyboardTranslatorReader,
#     KeyboardTranslatorWriter,
#     KeyboardTranslatorManager,
#     getKeyboardTranslatorManager,
#     # 兼容性别名
#     States,
#     Commands,
#     Entry
# )
#
# # 导入KProcess相关类和函数
# from .kprocess import (
#     KProcess,
#     OutputChannelMode,
#     execute,
#     execute_argv,
#     start_detached,
#     start_detached_argv
# )
#
# # 导入TerminalCharacterDecoder相关类
# from .terminal_character_decoder import (
#     TerminalCharacterDecoder,
#     PlainTextDecoder,
#     HTMLDecoder
# )
#
# # 导入工具模块
# from . import tools
#
# # 导入Screen相关类
# from .screen import (
#     Screen, SavedState, loc,
#     MODE_Origin, MODE_Wrap, MODE_Insert, MODE_Screen, MODE_Cursor, MODE_NewLine, MODES_SCREEN
# )
#
# # 导入ScreenWindow相关类
# from .screen_window import (
#     ScreenWindow
# )
#
# # 导入ShellCommand相关类
# from .shell_command import (
#     ShellCommand
# )
#
# # 导入Filter相关类
# from .filter import (
#     Filter, RegExpFilter, UrlFilter, FilterChain,
#     TerminalImageFilterChain, FilterObject
# )
#
# # 导入KPty相关类
# from .kpty import (
#     KPty, create_pty_pair, get_pty_slave_name
# )
#
# # 导入KPtyDevice相关类
# from .kpty_device import (
#     KPtyDevice, KRingBuffer, create_pty_device
# )
#
# # 导入KPtyProcess相关类
# from .kptyprocess import (
#     KPtyProcess, PtyChannelFlag, KPtyDevice
# )
#
# # 导入Pty相关类
# from .pty import (
#     Pty, createPty, createPtyWithMasterFd
# )
#
# # 导入TerminalDisplay相关类
# from .terminal_display import (
#     TerminalDisplay, MotionAfterPasting, BackgroundMode,
#     BellMode, TripleClickMode, ScrollBar, AutoScrollHandler
# )
#
# # 导入Session相关类
# from .session import (
#     Session, SessionGroup,
#     NOTIFYNORMAL, NOTIFYBELL, NOTIFYACTIVITY, NOTIFYSILENCE,
#     VIEW_LINES_THRESHOLD, VIEW_COLUMNS_THRESHOLD
# )
#
# # 导入HistorySearch相关类
# from .history_search import (
#     HistorySearch, EmulationPtr, createHistorySearch
# )
#
# # 导入SearchBar相关类
# from .search_bar import (
#     SearchBar, create_search_bar
# )
#
# # 导入QTermWidget版本信息
# from .qtermwidget_version import (
#     QTERMWIDGET_VERSION_MAJOR, QTERMWIDGET_VERSION_MINOR, QTERMWIDGET_VERSION_PATCH,
#     QTERMWIDGET_VERSION, get_version, get_version_tuple, get_version_info,
#     version_check, VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH, VERSION
# )
#
# # 导入QTermWidget接口定义
# from .qtermwidget_interface import (
#     QTermWidgetInterface, ScrollBarPosition, QTERMWIDGET_INTERFACE_IID
# )
#
# # 导入QTermWidget主类
# from .qtermwidget import (
#     QTermWidget, TermWidgetImpl, createTermWidget, create_term_widget,
#     DEFAULT_FONT_FAMILY, STEP_ZOOM
# )
#
# # VT102 Emulation
# from .vt102_emulation import (
#     Vt102Emulation,
#     MODE_AppScreen, MODE_AppCuKeys, MODE_AppKeyPad,
#     MODE_Mouse1000, MODE_Mouse1001, MODE_Mouse1002, MODE_Mouse1003,
#     MODE_Mouse1005, MODE_Mouse1006, MODE_Mouse1015,
#     MODE_Ansi, MODE_132Columns, MODE_Allow132Columns, MODE_BracketedPaste,
#     MODE_total,
#     CharCodes, TerminalState,
#     TY_CHR, TY_CTL, TY_ESC, TY_ESC_CS, TY_ESC_DE,
#     TY_CSI_PS, TY_CSI_PN, TY_CSI_PR, TY_CSI_PS_SP,
#     TY_VT52, TY_CSI_PG, TY_CSI_PE,
#     vt100_graphics,
#     COLOR_SPACE_RGB, COLOR_SPACE_256, COLOR_SPACE_SYSTEM, COLOR_SPACE_DEFAULT
# )
#
# __version__ = "1.0.0"
# __author__ = "转换自Qt C++代码"
#
# __all__ = [
#     # 工具函数
#     # "get_kb_layout_dir",
#     # "add_custom_color_scheme_dir",
#     # "get_color_schemes_dirs",
#     # "clear_custom_color_scheme_dirs",
#     # "get_custom_color_scheme_dirs",
#     "qtermwidgetLogger",  # 主要的日志记录器（C++风格）
#     # "qtermwidget_logger",     # 别名（Python风格）
#     "KB_LAYOUT_DIR",
#     "COLORSCHEMES_DIR",
#
#     # 块数组相关
#     "Block",
#     "BlockArray",
#     "QTERMWIDGET_BLOCKSIZE",
#     "ENTRIES",
#
#     # 字符颜色相关
#     "ColorEntry", "CharacterColor", "color256", "base_color_table",
#     "BASE_COLORS", "INTENSITIES", "TABLE_COLORS",
#     "DEFAULT_FORE_COLOR", "DEFAULT_BACK_COLOR",
#     "COLOR_SPACE_UNDEFINED", "COLOR_SPACE_DEFAULT", "COLOR_SPACE_SYSTEM",
#     "COLOR_SPACE_256", "COLOR_SPACE_RGB",
#
#     # 字符相关
#     "Character", "ExtendedCharTable", "extended_char_table_instance",
#     "LineProperty", "vt100_graphics",
#     "LINE_DEFAULT", "LINE_WRAPPED", "LINE_DOUBLEWIDTH", "LINE_DOUBLEHEIGHT",
#     "DEFAULT_RENDITION", "RE_BOLD", "RE_BLINK", "RE_UNDERLINE", "RE_REVERSE",
#     "RE_INTENSIVE", "RE_ITALIC", "RE_CURSOR", "RE_EXTENDED_CHAR", "RE_FAINT",
#     "RE_STRIKEOUT", "RE_CONCEAL", "RE_OVERLINE",
#
#     # 颜色方案相关
#     "ColorScheme", "AccessibleColorScheme", "ColorSchemeManager",
#     "getColorSchemeManager",
#
#     # 历史记录相关
#     "HistoryFile", "HistoryType", "HistoryScroll",
#     "HistoryScrollFile", "HistoryScrollBuffer", "HistoryScrollNone", "HistoryScrollBlockArray",
#     "HistoryTypeNone", "HistoryTypeBlockArray", "HistoryTypeFile", "HistoryTypeBuffer",
#     "CompactHistoryType", "CharacterFormat",
#
#     # Unicode字符宽度计算相关
#     "konsole_wcwidth", "string_width", "clear_width_cache", "get_cache_size",
#     "is_wide_char", "is_printable_char", "truncate_string", "pad_string",
#
#     # 键盘翻译器
#     'KeyboardTranslatorState',
#     'KeyboardTranslatorCommand',
#     'KeyboardTranslatorEntry',
#     'KeyboardTranslator',
#     'KeyboardTranslatorReader',
#     'KeyboardTranslatorWriter',
#     'KeyboardTranslatorManager',
#     'getKeyboardTranslatorManager',
#     # 兼容性别名
#     'States',
#     'Commands',
#     'Entry',
#
#     # KProcess
#     'KProcess',
#     'OutputChannelMode',
#     'execute',
#     'execute_argv',
#     'start_detached',
#     'start_detached_argv',
#
#     # TerminalCharacterDecoder
#     'TerminalCharacterDecoder',
#     'PlainTextDecoder',
#     'HTMLDecoder',
#
#     # 工具
#     'tools',
#
#     # Screen
#     'Screen',
#     'SavedState',
#     'loc',
#     'MODE_Origin',
#     'MODE_Wrap',
#     'MODE_Insert',
#     'MODE_Screen',
#     'MODE_Cursor',
#     'MODE_NewLine',
#     'MODES_SCREEN',
#
#     # ScreenWindow
#     'ScreenWindow',
#
#     # ShellCommand
#     'ShellCommand',
#
#     # Filter
#     'Filter',
#     'RegExpFilter',
#     'UrlFilter',
#     'FilterChain',
#     'TerminalImageFilterChain',
#     'FilterObject',
#
#     # KPty
#     'KPty',
#     'create_pty_pair',
#     'get_pty_slave_name',
#
#     # KPtyDevice
#     'KPtyDevice',
#     'KRingBuffer',
#     'create_pty_device',
#
#     # KPtyProcess
#     'KPtyProcess',
#     'PtyChannelFlag',
#
#     # Pty
#     'Pty',
#     'createPty',
#     'createPtyWithMasterFd',
#
#     # TerminalDisplay
#     'TerminalDisplay',
#     'MotionAfterPasting',
#     'BackgroundMode',
#     'BellMode',
#     'TripleClickMode',
#     'ScrollBar',
#     'AutoScrollHandler',
#
#     # VT102 Emulation
#     'Vt102Emulation',
#     'MODE_AppScreen', 'MODE_AppCuKeys', 'MODE_AppKeyPad',
#     'MODE_Mouse1000', 'MODE_Mouse1001', 'MODE_Mouse1002', 'MODE_Mouse1003',
#     'MODE_Mouse1005', 'MODE_Mouse1006', 'MODE_Mouse1015',
#     'MODE_Ansi', 'MODE_132Columns', 'MODE_Allow132Columns', 'MODE_BracketedPaste',
#     'MODE_total',
#     'MODE_NewLine', 'MODE_Insert', 'MODE_Origin', 'MODE_Wrap', 'MODE_Screen', 'MODE_Cursor',
#     'CharCodes', 'TerminalState',
#     'TY_CHR', 'TY_CTL', 'TY_ESC', 'TY_ESC_CS', 'TY_ESC_DE',
#     'TY_CSI_PS', 'TY_CSI_PN', 'TY_CSI_PR', 'TY_CSI_PS_SP',
#     'TY_VT52', 'TY_CSI_PG', 'TY_CSI_PE',
#     'vt100_graphics',
#     'COLOR_SPACE_RGB', 'COLOR_SPACE_256', 'COLOR_SPACE_SYSTEM', 'COLOR_SPACE_DEFAULT',
#
#     # Session
#     'Session',
#     'SessionGroup',
#     'NOTIFYNORMAL',
#     'NOTIFYBELL',
#     'NOTIFYACTIVITY',
#     'NOTIFYSILENCE',
#     'VIEW_LINES_THRESHOLD',
#     'VIEW_COLUMNS_THRESHOLD',
#
#     # HistorySearch
#     'HistorySearch',
#     'EmulationPtr',
#     'createHistorySearch',
#
#     # SearchBar
#     'SearchBar',
#     'create_search_bar',
#
#     # QTermWidget版本信息
#     'QTERMWIDGET_VERSION_MAJOR',
#     'QTERMWIDGET_VERSION_MINOR',
#     'QTERMWIDGET_VERSION_PATCH',
#     'QTERMWIDGET_VERSION',
#     'get_version',
#     'get_version_tuple',
#     'get_version_info',
#     'version_check',
#     'VERSION_MAJOR',
#     'VERSION_MINOR',
#     'VERSION_PATCH',
#     'VERSION',
#
#     # QTermWidget接口定义
#     'QTermWidgetInterface',
#     'ScrollBarPosition',
#     'QTERMWIDGET_INTERFACE_IID',
#
#     # QTermWidget主类
#     'QTermWidget',
#     'TermWidgetImpl',
#     'createTermWidget',
#     'create_term_widget',
#     'DEFAULT_FONT_FAMILY',
#     'STEP_ZOOM'
# ]
