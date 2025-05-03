def createButtonStyle(def_bg_color="#409eff", h_bg_color="#66b1ff",
                      c_bg_color="#66b1ff", p_bg_color="#3a8ee6",
                      radius='3px', font_color="#fff"):
    QB = "QPushButton{"
    QBH = "}QPushButton:hover{"
    QBC = "}QPushButton:checked{"
    QBP = "}QPushButton:pressed{"
    END = "}"
    style = f"""{QB}color:{font_color};background-color:{def_bg_color};border: 1px solid {def_bg_color};border-radius: {radius};
{QBH}color:{font_color};border-color:{h_bg_color};background-color:{h_bg_color};
{QBC}color:{font_color};border-color:{c_bg_color};background-color: {c_bg_color};
{QBP}color:{font_color};border-color: {p_bg_color};background-color: {p_bg_color};
{END}"""
    return style


DefaultButtonStyle = """
QPushButton{
    color: #606266; 
    background-color: #fff; 
    border: 1px solid #dcdfe6;
    border-radius: 10px;
}
QPushButton:hover{
    color: #409eff;
    border-color: #c6e2ff;
    background-color: #ecf5ff
}
QPushButton:checked{
    color: #409eff;
    border-color: #c6e2ff;
    background-color: #ecf5ff;
}
QPushButton:pressed{
    color: #3a8ee6;
    border-color: #3a8ee6;
    background-color: #ecf5ff;}
"""
PrimaryButtonStyle = createButtonStyle()
SuccessButtonStyle = createButtonStyle(def_bg_color="#67c23a", h_bg_color="#85ce61",
                                       c_bg_color="#85ce61", p_bg_color="#5daf34")
InfoButtonStyle = createButtonStyle(def_bg_color="#909399", h_bg_color="#a6a9ad",
                                    c_bg_color="#a6a9ad", p_bg_color="#82848a")
WarningButtonStyle = createButtonStyle(def_bg_color="#e6a23c", h_bg_color="#ebb563",
                                       c_bg_color="#ebb563", p_bg_color="#cf9236")
DangerButtonStyle = createButtonStyle(def_bg_color="#f56c6c", h_bg_color="#f78989",
                                      c_bg_color="#f78989", p_bg_color="#dd6161")

InstallButtonStyle = """
    QPushButton {
                    color: white;         /* 设置字体颜色 */
                    background-color: #007BFF; /* 可选：设置背景色提高对比度 */
                    border-radius: 5px;   /* 可选：圆角效果 */
                    padding: 8px 16px;    /* 可选：内边距 */
                }
                
                /* 设置不同状态下的颜色 */
                QPushButton:hover {
                    background-color: #0056b3;
                }
                
                QPushButton:pressed {
                    background-color: #003d80;
                }
"""

InstalledButtonStyle = """
    QPushButton {
                    color: white;         /* 设置字体颜色 */
                    background-color: #00f260; /* 可选：设置背景色提高对比度 */
                    border-radius: 5px;   /* 可选：圆角效果 */
                    padding: 8px 16px;    /* 可选：内边距 */
                }
                
                /* 设置不同状态下的颜色 */
                QPushButton:hover {
                    background-color: #0056b3;
                }
                
                QPushButton:pressed {
                    background-color: #003d80;
                }
"""


def createDisabledButtonStyle(style_color='#a0cfff', color='#fff', radius='10px'):
    QP = 'QPushButton{'
    END = '}'
    style = f"""{QP}color:{color};background-color:{style_color};border: 1px solid{style_color};border-radius:{radius};{END}"""
    return style


DisabledDefaultButtonStyle = """
QPushButton{color: #c0c4cc;background-color: #fff;border: 1px solid #ebeef5;border-radius: 10px;
}
"""
DisabledPrimaryButtonStyle = createDisabledButtonStyle()
DisabledSuccessButtonStyle = createDisabledButtonStyle(style_color='#b3e19d')
DisabledInfoButtonStyle = createDisabledButtonStyle(style_color='#c8c9cc')
DisabledWarningButtonStyle = createDisabledButtonStyle(style_color='#f3d19e')
DisabledDangerButtonStyle = createDisabledButtonStyle(style_color='#fab6b6')


def updateColor(value):
    if value < 50:
        return "QProgressBar::chunk:horizontal { background-color: green; }"
    elif value < 80:
        return "QProgressBar::chunk:horizontal { background-color: orange; }"
    else:
        return "QProgressBar::chunk:horizontal { background-color: red; }"
