"""MEGA 雲端關鍵字搜尋與下載服務。"""

import asyncio
import logging
import os
import shutil
import subprocess
import time

from ..config import get_settings

logger = logging.getLogger(__name__)

TEMP_FOLDER = "Temp_Search_Folder"
DOWNLOAD_DIR = "./downloads"


def _run_cmd(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def mega_search_and_download(should_fetch: bool, keywords: list[str]) -> str:
    """Synchronous MEGA search & download. Run via asyncio.to_thread."""
    public_url = get_settings().MEGA_PUBLIC_URL
    if not public_url:
        return "❌ MEGA_PUBLIC_URL 未設定"

    if not shutil.which("mega-cmd") and not shutil.which("mega-find"):
        return "❌ 找不到 MEGAcmd，請先安裝 (brew install megacmd)"

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    for kw in keywords:
        os.makedirs(os.path.join(DOWNLOAD_DIR, kw), exist_ok=True)

    if should_fetch:
        subprocess.run(["mega-rm", "-r", f"/{TEMP_FOLDER}"], capture_output=True)
        subprocess.run(["mega-mkdir", f"/{TEMP_FOLDER}"], capture_output=True)
        res = _run_cmd(["mega-import", public_url, f"/{TEMP_FOLDER}"])
        if res is None:
            return "❌ mega-import 失敗"
        time.sleep(3)

    all_files_str = _run_cmd(["mega-find", f"/{TEMP_FOLDER}"])
    if not all_files_str:
        return "⚠️ 暫存區沒有檔案"

    matched = []
    for line in all_files_str.split("\n"):
        line = line.strip()
        if not line:
            continue
        filename = line.split("/")[-1]
        if not keywords or any(kw.lower() in filename.lower() for kw in keywords):
            matched.append(line)

    if not matched:
        return f"⚠️ 找不到符合關鍵字 {keywords} 的檔案"

    downloaded, skipped = 0, 0
    for file_path in matched:
        filename = file_path.split("/")[-1]
        for kw in keywords:
            if kw.lower() in filename.lower():
                local_path = os.path.join(DOWNLOAD_DIR, kw, filename)
                if os.path.exists(local_path):
                    skipped += 1
                else:
                    _run_cmd(["mega-get", file_path, local_path])
                    downloaded += 1
                break

    return f"✅ 完成！下載 {downloaded} 個，跳過 {skipped} 個（共 {len(matched)} 個符合）"


async def mega_search_and_download_async(should_fetch: bool, keywords: list[str]) -> str:
    """Async wrapper."""
    return await asyncio.to_thread(mega_search_and_download, should_fetch, keywords)
