"""工作台的公共视觉层；不参与生成、网络请求或配置保存。"""

from pathlib import Path
import streamlit as st

from web.i18n import get_language


def studio_text(chinese: str, english: str) -> str:
    """随当前会话语言呈现简短界面文案。"""
    return chinese if get_language().startswith("zh") else english


def apply_studio_theme():
    """从 UTF-8 样式文件加载主题，避免外部字体与脚本依赖。"""
    css = (Path(__file__).resolve().parent.parent / "assets" / "studio.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


def render_studio_sidebar():
    """使用真实页面链接，保留 Streamlit 的导航与键盘可访问性。"""
    with st.sidebar:
        # 品牌名保留 Pixelle，描述性文字随语言切换，中文界面不夹杂英文宣传语。
        brand_caption = studio_text("创作工作台", "CREATIVE STUDIO")
        st.html(f'''<div class="studio-brand"><span class="studio-mark" aria-hidden="true">P<span></span></span>
<div>pixelle<span class="brand-caption">{brand_caption}</span></div></div>''')
        st.html(f'<div class="sidebar-eyebrow">{studio_text("工作空间", "WORKSPACE")}</div>')
        st.page_link("pages/1_🎬_Home.py", label=studio_text("创作工作台", "Create"), icon=":material/space_dashboard:")
        st.page_link("pages/2_📚_History.py", label=studio_text("作品与记录", "Library"), icon=":material/video_library:")
        st.html(f'''<div class="sidebar-note"><span class="studio-status-dot"></span> {studio_text("本地工作空间", "LOCAL WORKSPACE")}
<p>{studio_text("从一个想法，到一段好故事。", "A small idea. A story worth sharing.")}</p></div>''')


def render_studio_intro():
    """紧凑的创作引导，步骤仅作说明，不伪装成可点击控件。"""
    title = studio_text("让灵感，成为下一帧。", "Your next frame starts here.")
    subtitle = studio_text("写下想法，选择画面与声音，把故事交给镜头。", "Shape the story. Set the look and sound. Make it yours.")
    steps = [("01", studio_text("构思脚本", "Write")), ("02", studio_text("画面与声音", "Style")), ("03", studio_text("生成与导出", "Export"))]
    step_html = "".join(f'<span><b>{number}</b>{label}</span>' for number, label in steps)
    st.html(f'''<section class="studio-intro"><div class="studio-eyebrow">{studio_text("从灵感开始创作", "MAKE SOMETHING THAT MOVES")}</div>
<h1>{title}</h1><p>{subtitle}</p><div class="studio-steps">{step_html}</div></section>''')
