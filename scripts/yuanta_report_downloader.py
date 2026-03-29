#!/usr/bin/env python3
"""
元大投顧研究報告自動下載腳本

登入元大投顧網站，下載每日最新研究報告。
需先安裝: pip install -r scripts/requirements-yuanta.txt
並執行: playwright install chromium
驗證碼 OCR 需安裝: brew install tesseract (macOS)

驗證碼：腳本會截圖驗證碼並用 OCR 自動辨識，失敗時改為手動輸入。

使用方式:
    python scripts/yuanta_report_downloader.py
    python scripts/yuanta_report_downloader.py --headless
"""

import asyncio
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime

# 從專案根目錄載入 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ============ 可調整的設定（依實際網站結構修改） ============
# 若登入/報告頁網址不同，請在 .env 設定 YT_LOGIN_URL、YT_REPORT_URL
YT_LOGIN_URL = os.getenv("YT_LOGIN_URL", "https://www.yuanta-consulting.com.tw/")
YT_REPORT_URL = os.getenv("YT_REPORT_URL", "https://www.yuanta-consulting.com.tw/")
OUTPUT_DIR = Path(os.getenv("YT_REPORT_OUTPUT_DIR", "") or str(Path(__file__).resolve().parent.parent / "reports" / "yuanta"))
# ============================================================


def _ocr_captcha(image_path: Path) -> str:
    """從驗證碼圖片讀取文字，失敗回傳空字串。"""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance

        img = Image.open(image_path).convert("RGB")
        # 嘗試多種預處理
        config = "--psm 7 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

        for proc_img in [_preprocess_captcha(img), img.convert("L")]:
            code = pytesseract.image_to_string(proc_img, config=config)
            code = re.sub(r"\s+", "", code).strip()
            if len(code) >= 4:  # 驗證碼通常 4–6 碼
                return code[:8]  # 最多取 8 碼
        return ""
    except Exception as e:
        print(f"  OCR 失敗: {e}")
        return ""


def _preprocess_captcha(img):  # PIL.Image
    """灰階、增強對比、二值化。"""
    from PIL import ImageEnhance

    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(2.0)
    threshold = 128
    return gray.point(lambda p: 255 if p > threshold else 0, mode="1")


async def download_yuanta_reports(headless: bool = False) -> None:
    """登入元大投顧並下載每日最新報告。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("請先安裝 Playwright: pip install playwright && playwright install chromium")
        return

    account = os.getenv("YT_ACCOUNT", "").strip().strip('"')
    password = os.getenv("YT_PASSWORD", "").strip().strip('"')

    if not account or not password:
        print("錯誤: 請在 .env 設定 YT_ACCOUNT 和 YT_PASSWORD")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        try:
            page = await context.new_page()

            # 1. 前往首頁
            print(f"前往: {YT_LOGIN_URL}")
            await page.goto(YT_LOGIN_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # 2. 先點擊「登入」按鈕，開啟登入表單（可能是 modal 或展開區塊）
            login_opened = False
            for loc in [
                page.get_by_text("登入", exact=True),
                page.get_by_role("link", name="登入"),
                page.get_by_role("button", name="登入"),
                page.locator('a[href*="login"]'),
                page.locator('a[href*="Login"]'),
            ]:
                try:
                    if await loc.count() > 0:
                        await loc.first.click()
                        print("  已點擊登入按鈕")
                        login_opened = True
                        break
                except Exception:
                    continue
            if not login_opened:
                print("  警告: 無法找到登入按鈕，嘗試直接填寫表單...")

            await asyncio.sleep(2)  # 等待登入表單出現

            # 3. 填寫帳號
            account_selectors = [
                'input[name="account"]',
                'input[name="id"]',
                'input[name="username"]',
                'input[name="user"]',
                'input[id="account"]',
                'input[id="id"]',
                'input[placeholder*="帳號"]',
                'input[placeholder*="身分證"]',
                'input[type="text"]',
            ]
            account_filled = False
            for sel in account_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=2000)
                    if el:
                        await el.fill(account)
                        account_filled = True
                        print(f"  已填寫帳號 (選擇器: {sel})")
                        break
                except Exception:
                    continue
            if not account_filled:
                print("  警告: 無法找到帳號輸入框")
                if not headless:
                    await page.pause()

            # 4. 填寫密碼
            password_selectors = [
                'input[name="password"]',
                'input[name="pwd"]',
                'input[id="password"]',
                'input[type="password"]',
            ]
            password_filled = False
            for sel in password_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(password)
                        password_filled = True
                        print(f"  已填寫密碼 (選擇器: {sel})")
                        break
                except Exception:
                    continue
            if not password_filled:
                print("  警告: 無法找到密碼輸入框")

            # 5. 驗證碼：截圖 → OCR 辨識，失敗則手動輸入
            captcha_input_selectors = [
                'input[name="captcha"]',
                'input[name="verify"]',
                'input[name="code"]',
                'input[name="verification"]',
                'input[placeholder*="驗證碼"]',
                'input[id*="captcha"]',
                'input[id*="verify"]',
                'input[id*="code"]',
            ]
            captcha_img_selectors = [
                'img[src*="captcha"]',
                'img[src*="verify"]',
                'img[src*="code"]',
                'img[alt*="驗證碼"]',
                'img[alt*="captcha"]',
                'canvas',
                '[class*="captcha"] img',
                '[class*="verify"] img',
                '[id*="captcha"] img',
            ]
            captcha_filled = False
            captcha_input_el = None
            for sel in captcha_input_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        captcha_input_el = el
                        break
                except Exception:
                    continue

            if captcha_input_el:
                code = ""
                img_el = None
                for img_sel in captcha_img_selectors:
                    try:
                        el = await page.query_selector(img_sel)
                        if el and await el.is_visible():
                            img_el = el
                            break
                    except Exception:
                        continue
                # 備援：在表單內找 img（驗證碼圖常與輸入框同 form）
                if not img_el:
                    form = await page.query_selector("form")
                    if form:
                        img_el = await form.query_selector("img")

                if img_el:
                    try:
                        captcha_path = Path(tempfile.gettempdir()) / "yuanta_captcha.png"
                        await img_el.screenshot(path=str(captcha_path))
                        code = _ocr_captcha(captcha_path)
                        captcha_path.unlink(missing_ok=True)
                        if code:
                            print(f"  OCR 辨識驗證碼: {code}")
                    except Exception as e:
                        print(f"  截圖/OCR 失敗: {e}")

                if not code and not headless:
                    print("\n  ═══ OCR 無法辨識，請手動輸入驗證碼（看瀏覽器畫面）═══")
                    code = input("  驗證碼: ").strip()

                if code:
                    await captcha_input_el.fill(code)
                    captcha_filled = True
                    print("  已填寫驗證碼")
            else:
                print("  未找到驗證碼輸入框。")

            # 6. 點擊送出登入（submit）
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("登入")',
                'input[value="登入"]',
                'a:has-text("登入")',
                '[class*="login"] button',
                '[class*="submit"]',
            ]
            for sel in submit_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        print(f"  已點擊送出登入 (選擇器: {sel})")
                        break
                except Exception:
                    continue

            await asyncio.sleep(3)  # 等待登入完成

            # 7. 檢查是否登入成功
            current_url = page.url
            print(f"  目前 URL: {current_url}")

            # 8. 前往報告頁面
            if YT_REPORT_URL != YT_LOGIN_URL:
                print(f"前往報告頁: {YT_REPORT_URL}")
                await page.goto(YT_REPORT_URL, wait_until="networkidle", timeout=30000)

            # 9. 尋找並下載報告連結（PDF 或 報告下載連結）
            report_links = await page.query_selector_all(
                'a[href*=".pdf"], a[href*="report"], a[href*="研究"], '
                'a[href*="download"], a[href*="Report"]'
            )

            downloaded = 0
            for i, link in enumerate(report_links[:10]):
                try:
                    href = await link.get_attribute("href")
                    text = (await link.inner_text()).strip()[:50]
                    if not href or (".pdf" not in href.lower() and "report" not in href.lower() and "研究" not in text):
                        continue
                    async with page.expect_download(timeout=15000) as download_info:
                        await link.click()
                    download = await download_info.value
                    fname = download.suggested_filename or f"report_{i}.pdf"
                    save_path = OUTPUT_DIR / f"{today}_{fname}"
                    await download.save_as(save_path)
                    print(f"✓ 已下載: {save_path}")
                    downloaded += 1
                    await asyncio.sleep(1)
                except Exception as e:
                    continue

            if downloaded == 0:
                print("  未找到或無法下載報告連結。")
                print("  請使用無 --headless 參數執行，手動操作並檢查頁面結構。")
                if not headless:
                    input("  按 Enter 關閉瀏覽器...")

            await asyncio.sleep(1)

        finally:
            await browser.close()

    print(f"報告儲存於: {OUTPUT_DIR}")


def main():
    import sys
    headless = "--headless" in sys.argv or "-h" in sys.argv
    asyncio.run(download_yuanta_reports(headless=headless))


if __name__ == "__main__":
    main()
