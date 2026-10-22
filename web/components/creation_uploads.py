"""创作页共用的上传缓存，避免步骤切换重复落盘或让同名文件互相覆盖。"""

import hashlib
import uuid
from pathlib import Path

import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile


def persist_uploaded_files(uploaded_files: list, *, key: str) -> list[str]:
    """按上传身份快速复用当前会话文件，首次上传和通用对象仍按名称与内容去重。"""
    if not uploaded_files:
        return []
    state_key = f"creation_upload_{key}"
    cache = st.session_state.get(state_key)
    if cache is None:
        cache = {
            "directory": str((Path("temp") / f"assets_{uuid.uuid4().hex[:12]}").absolute()),
            "files": {},
        }
        st.session_state[state_key] = cache
    directory = Path(cache["directory"])
    directory.mkdir(parents=True, exist_ok=True)
    # Streamlit 每次新上传分配 file_id，rerun 重建对象仍保留该 ID。
    # 仅保存身份到内容摘要的索引，不复制大文件字节；兼容早期会话没有此索引。
    upload_identities = cache.setdefault("upload_identities", {})
    asset_paths = []
    for uploaded_file in uploaded_files:
        # 同名替换产生新内容路径；只使用文件名，避免上传名称带出缓存目录。
        name = Path(uploaded_file.name).name
        identity = None
        if isinstance(uploaded_file, UploadedFile) and uploaded_file.file_id:
            identity = (uploaded_file.file_id, uploaded_file.name, uploaded_file.size)
            cached_digest = upload_identities.get(identity)
            cached_path = cache["files"].get(cached_digest)
            if cached_path and Path(cached_path).is_file():
                # 长素材切换步骤时不再 getbuffer/hash 整个文件；不存在则走原流程恢复。
                asset_paths.append(cached_path)
                continue
        contents = uploaded_file.getbuffer()
        checksum = hashlib.sha256(name.encode("utf-8") + b"\0")
        checksum.update(contents)
        digest = checksum.hexdigest()
        file_path = Path(cache["files"].get(digest, directory / f"{digest[:16]}_{name}"))
        if not file_path.is_file():
            file_path.write_bytes(contents)
        cache["files"][digest] = str(file_path)
        if identity is not None:
            upload_identities[identity] = digest
        asset_paths.append(str(file_path))
    # 删除上传项只改变返回列表，不删除仍可能被历史任务引用的本地素材。
    return asset_paths
