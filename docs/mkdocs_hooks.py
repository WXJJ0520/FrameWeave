"""只处理文档站构建：过滤排除项，复制并链接仓库原始许可证。"""

import posixpath
import re
from pathlib import Path

from mkdocs.plugins import event_priority
from mkdocs.structure.files import File, Files, InclusionLevel


@event_priority(1000)
def on_files(files, *, config):
    """遵循 MkDocs 的 exclude_docs，不改动源文件或扩大排除范围。"""
    # i18n 会先比较所有页面路径，再处理 inclusion 标记；排除的旧图库也会冲突。
    # 提前过滤已经标记排除的文件，保留 GitHub 原路径与中英文站点的独立页面。
    included = Files(file for file in files if not file.inclusion.is_excluded())
    # GitHub 文档可指向仓库根许可证；静态站点必须有自己的原文副本。
    # 只复制明确的两个公开声明，不复制配置、运行记录或其他仓库文件。
    root = Path(config.config_file_path).parent
    for name in ("LICENSE", "NOTICE"):
        included.append(File.generated(
            config,
            f"legal/{name}",
            abs_src_path=str(root / name),
            inclusion=InclusionLevel.INCLUDED,
        ))
    return included


def on_page_markdown(markdown, *, page, config, files):
    """仅构建期重写指向根许可证的相对链接，源 Markdown 保持 GitHub 可用。"""
    root = Path(config.config_file_path).parent.resolve()
    source_dir = Path(page.file.abs_src_path).parent

    def legal_link(match):
        target, name = match.group(1), match.group(2)
        if (source_dir / target).resolve() != root / name:
            return match.group(0)
        relative = posixpath.relpath(f"legal/{name}", posixpath.dirname(page.file.src_uri))
        return f"]({relative})"

    return re.sub(r"\]\(((?:\.\./)+(LICENSE|NOTICE))\)", legal_link, markdown)
