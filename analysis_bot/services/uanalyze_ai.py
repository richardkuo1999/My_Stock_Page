"""UAnalyze AI 股票分析服務。"""

import asyncio
import logging
import random
import urllib.parse
from datetime import datetime

from ..config import get_settings
from .http import create_session

logger = logging.getLogger(__name__)

MAX_CONCURRENT_REQUESTS = 5
RANDOM_TIME_WINDOW = 10

PROMPT_LIST = [
    "近況發展",
    "產業趨勢",
    "❤️產品線分析",
    "長短期展望",
    "供需分析",
    "觀察重點",
    "利多因素",
    "利空因素",
    "接單狀況",
    "資本支出",
    "新產品",
    "時間表",
    "相關公司",
    "同業競爭",
    "護城河分析",
    "併購分析",
    "重要數字",
    "公司概覽",
    "銷售地區",
    "描述庫存",
    "驅動銷售金額(營收)成長或衰退的來源有哪些，詳細且完整的敍述原因(敍述時請用數據佐證你的論點(若有數據的話))，分為短期(意為持續性不強)、長期(意為持續不斷的動能)",
    "驅動獲利(盈餘)成長或衰退的因子有哪些，詳細且完整的敍述原因(敍述時請用數據佐證你的論點(若有數據的話))，分為短期(意為持續性不強)、長期(意為持續不斷的動能)",
    "驅動毛利率(成本)上升或下降的因素有哪些，詳細且完整的敍述原因，可以的話用數據佐證你的論點，分為短期長期。如果資料不足允許提供較少內容，如果資料中找不到原因可以不提供。備註，業外不會影響毛利率，ASP與毛利率不一定相關",
    "根據資料，將有提到(營收)或(銷售)的資訊取出，重新改寫(改寫程度大)，理為時間線(依時間排序)(去除相同內容)(排除匯兌收益、EPS、毛利率相關資訊)",
    "法人或公司有展望上下修原因是什麼?請注意要有明確看法變化|調整的意思才算。以多層結構顯示，第1層先[[展望上修(正向調整)]]再<<展望下修(負向調整)>>，第2層 - 時間(例如2025年第一季)、 - 第3層類型(例如<<毛利率下修>>、[[出貨量上修]]以及其他類型)。注意，有上下修的才算，維持不變的不用顯示。如果沒有上下修相關資料，請回答『無相關資料』",
    "請你幫我做2件事，第一、我提供的資料中是否有提到關稅、貿易戰、或相關細節內容(這很重要一定要找出來)...； 第二、提供公司的生產基地、工廠地點、據點的相關細節內容...",
    "請檢查提供的資料中是否有提到『供應鏈如何重組』、『美國製造基地資訊』、『關稅影響利潤及價格上漲議題』或者『對等關稅影響』的相關內容...如果回答時有相似內容請將其整合為一句，儘量提供具體數據以及具體案例來輔助說明...",
    "台幣兌美元升貶值對公司成本或競爭力(產業競爭程度如何)的影響(再分為升值 and 貶值)公司說明(如果有的話)及分析並綜合評估影響明顯程度，台幣兌美元升貶值對匯兌損益影響...。輸出：台幣升值情境分析：... 台幣貶值情境分析：...。記得標示正面和負面標記",
    "請檢查我提供的資料中是否有提到『AI』『邊緣AI』『人工智慧』『人工智能』或相關內容...如果回答時有相似內容請將其整合為一句，可以提供具體數據以及具體案例來輔助說明...",
    "有新產品嗎，進度如何，最後條列出新產品詳細數字",
    "詳述資本支出或擴產計劃，包含前因後果、項目、產能、金額、時間點、地點，若無資本支出或擴產，請回答『無資本支出相關資料』",
    "描述該公司的庫存情形，並在每一段敘述之後標註資料來源日期。我想更加了解該公司自身的庫存水位以及終端需求或客戶的庫存水位，接著想利用公司的接單情況來預判未來庫存循環方向",
]


async def fetch_completion(session, prompt: str, stock: str, semaphore, results: list):
    """Fetch AI completion for a prompt+stock pair."""
    url_template = get_settings().UANALYZE_AI_URL_TEMPLATE
    if not url_template:
        results.append({"prompt": prompt, "response": "Error: UANALYZE_AI_URL_TEMPLATE not set"})
        return

    await asyncio.sleep(random.uniform(0, RANDOM_TIME_WINDOW))

    async with semaphore:
        url = url_template.format(
            prompt=urllib.parse.quote(prompt),
            stock=urllib.parse.quote(stock),
        )
        try:
            async with session.get(url, timeout=300) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                            text = data["data"].get("text", str(data))
                        else:
                            text = str(data)
                    except Exception:
                        text = await resp.text()
                    results.append({"prompt": prompt, "response": text})
                else:
                    results.append({"prompt": prompt, "response": f"Error: Status {resp.status}"})
        except Exception as e:
            results.append({"prompt": prompt, "response": f"Exception: {e}"})


async def analyze_stock(stock: str, prompts: list[str] | None = None) -> str:
    """Run full analysis for a stock, return markdown string."""
    prompts = prompts or PROMPT_LIST
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    results: list[dict] = []

    async with create_session() as session:
        tasks = [fetch_completion(session, p, stock, semaphore, results) for p in prompts]
        await asyncio.gather(*tasks)

    # Sort by original prompt order
    prompt_order = {p: i for i, p in enumerate(prompts)}
    results.sort(key=lambda x: prompt_order.get(x["prompt"], 0))

    lines = [
        f"# AI Analysis: {stock}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
    ]
    for r in results:
        lines.append(f"## {r['prompt']}\n\n{r['response']}\n\n---\n")
    return "\n".join(lines)
