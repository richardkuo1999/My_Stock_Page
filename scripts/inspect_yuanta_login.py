#!/usr/bin/env python3
"""檢查元大登入頁面的 HTML 結構，找出正確的選擇器"""
import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

async def inspect():
    from playwright.async_api import async_playwright
    url = "https://www.yuanta-consulting.com.tw/"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)  # 等待動態內容
        # 取得所有 input 的屬性
        inputs = await page.query_selector_all("input")
        print(f"\n找到 {len(inputs)} 個 input 元素:\n")
        for i, inp in enumerate(inputs):
            attrs = await inp.evaluate("""
                el => ({
                    tag: el.tagName,
                    type: el.type,
                    name: el.name,
                    id: el.id,
                    placeholder: el.placeholder,
                    className: el.className,
                })
            """)
            print(f"  [{i}] {attrs}")
        # 取得登入按鈕
        buttons = await page.query_selector_all("button, a, input[type=submit]")
        print(f"\n找到 {len(buttons)} 個按鈕/連結:\n")
        for i, btn in enumerate(buttons[:15]):
            text = await btn.inner_text()
            tag = await btn.evaluate("el => el.tagName")
            href = await btn.get_attribute("href") or ""
            print(f"  [{i}] <{tag}> text={text[:30]!r} href={href[:50]!r}")
        # 儲存完整 HTML 供檢查
        html = await page.content()
        out = Path(__file__).parent / "yuanta_page_dump.html"
        out.write_text(html, encoding="utf-8")
        print(f"\n完整 HTML 已儲存至: {out}")
        input("按 Enter 關閉瀏覽器...")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
