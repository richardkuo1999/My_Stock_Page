import os
import sys
import csv
import requests
from pathlib import Path
from django.http import HttpResponse

from telegram import Bot
from telegram.error import TelegramError

sys.path.append(os.path.dirname(__file__)+"/..")

from utils.utils import logger, dict2list, get_profit, get_target, load_token, load_data


ROW_TITLE = [
    "名稱",
    "代號",
    "產業",
    "資訊",
    "交易所",
    "價格",
    "毛利率",
    # =========== 7
    "EPS(TTM)",
    "BPS",
    "PE(TTM)",
    "PB(TTM)",
    # =========== 11
    "yahooforwardEps",
    "Yahoo_1yTargetEst",
    # =========== 13
    "EPS(EST)",
    "PE(EST)",
    "Factest目標價",
    "資料時間",
    "ANUEurl",
    # =========== 18
    "往上機率",
    "區間震盪機率",
    "往下機率",
    "TL價",
    "保守做多期望值",
    "樂觀做多期望值",
    "樂觀做空期望值",
    # =========== 25
    "超極樂觀",
    "極樂觀",
    "樂觀",
    "趨勢",
    "悲觀",
    "極悲觀",
    "超極悲觀",
    # ===========
    "PE(25%)",
    "PE(50%)",
    "PE(75%)",
    "PE(平均)",
    "PE(TL+3SD)",
    "PE(TL+2SD)",
    "PE(TL+1SD)",
    "PE(TL)",
    "PE(TL-1SD)",
    "PE(TL-2SD)",
    "PE(TL-3SD)",
    # ===========
    "PB(25%)",
    "PB(50%)",
    "PB(75%)",
    "PB(平均)",
    "PB(TL+3SD)",
    "PB(TL+2SD)",
    "PB(TL+1SD)",
    "PB(TL)",
    "PB(TL-1SD)",
    "PB(TL-2SD)",
    "PB(TL-3SD)",
    # ===========
    "PEG",
]

def write2csv(result_path, csvdata):
    with result_path.open(mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(csvdata)

def write2txt(msg, filepath=None):
    with filepath.open(mode="a", encoding="utf-8") as file:
        file.write(f"{msg}\n")
    print(msg)

def csv_output(result_path, stock_datas):
    result_path = result_path.with_suffix(".csv")
    write2csv(result_path, ROW_TITLE)
    for stock_id, stock_data in stock_datas.items():
        csv_row = dict2list(stock_data)
        write2csv(result_path, csv_row)

def txt_output(result_path, stock_datas, eps_lists=None):
    result_path = result_path.with_suffix(".txt")
    texts = ""

    for idx, (stock_id, stock_data) in enumerate(stock_datas.items()):
        if not stock_data:
            logger.warning(f"Skipping empty stock data for {stock_id}")
            continue

        close_price = float(stock_data.get("價格"))
        if not close_price:
            logger.warning(f"Missing or invalid price for {stock_id}")
            continue

        # Select EPS
        eps_ttm = float(stock_data.get('EPS(TTM)'))
        eps_use = None
        if eps_lists and idx < len(eps_lists) and eps_lists[idx] is not None:
            eps_use = float(eps_lists[idx])
        else:
            eps_est = stock_data.get("EPS(EST)") or stock_data.get("yahooforwardEps")
            eps_use = float(eps_est) if eps_est else eps_ttm
        bps = float(stock_data.get("BPS"))

        text = ""
# Stock Overview
        text += f"""
============================================================================

股票名稱: {stock_data.get('名稱')}		股票代號: {stock_data.get('代號')}                    
公司產業: {stock_data.get('產業')}		交易所: {stock_data.get('交易所')}
公司資訊: {stock_data.get('資訊')}

目前股價: {close_price:>10.2f}		毛利率: {stock_data.get('毛利率')}
EPS(TTM): {eps_ttm:>10.2f}          BPS: {bps:>10.2f}
PE(TTM): {stock_data.get('PE(TTM)'):>10.2f}          PB(TTM): {stock_data.get('PB(TTM)'):>10.2f}
"""

# Yahoo Finance Target
        target_price = stock_data.get("Yahoo_1yTargetEst")
        forwardEps = stock_data.get("yahooforwardEps")
        if target_price:
            profit = get_profit(target_price, close_price)
            text += f"""
============================================================================
Yahoo Finance 1y Target Est....

預估eps: {forwardEps}
目標價位: {target_price:>10.2f}          潛在漲幅: {profit:>10.2f}%
"""
        else:
            logger.warning(f"{stock_id}: Missing Yahoo Finance Target")

# Mean Reversion
        try:
            prob = [stock_data[key] for key in ["往上機率", "區間震盪機率", "往下機率"]]
            expect = [stock_data[key] for key in ["保守做多期望值", "樂觀做多期望值", "樂觀做空期望值"]]
            tl_price = float(stock_data.get("TL價"))
            profit = get_profit(tl_price, close_price)
            expect_profit_rate = [e / close_price * 100 if close_price else 0.0 for e in expect]
            text += f"""
============================================================================
股價均值回歸......

均值回歸適合使用在穩定成長的股票上，如大盤or台積電等，高速成長及景氣循環股不適用，請小心服用。
偏離越多標準差越遠代表趨勢越強，請勿直接進場。

{stock_data["代號"]} 往上的機率為: {prob[0]:>10.2f}%, 維持在這個區間的機率為: {prob[1]:>10.2f}%, 往下的機率為: {prob[2]:>10.2f}%

目前股價: {close_price:>10.2f}, TL價: {tl_price:>10.2f}, TL價潛在漲幅: {profit:>10.2f}
做多評估：
期望值為: {expect[0]:>10.2f}, 期望報酬率為: {expect_profit_rate[0]:>10.2f}% (保守計算: 上檔TL，下檔歸零)
期望值為: {expect[1]:>10.2f}, 期望報酬率為: {expect_profit_rate[1]:>10.2f}% (樂觀計算: 上檔TL，下檔-3SD)

做空評估: 
期望值為: {expect[2]:>10.2f}, 期望報酬率為: {expect_profit_rate[2]:>10.2f}% (樂觀計算: 上檔+3SD，下檔TL)
"""
        except KeyError as e:
            logger.warning(f"{stock_id}: Missing Mean Reversion data: {e}")

# Five-Line Spectrum (樂活五線譜)
        try:
            target_prices = [stock_data[key] for key in ["超極樂觀","極樂觀", "樂觀", "趨勢", "悲觀", "極悲觀", "超極悲觀"]]
            profits = [get_profit(tp, close_price) for tp in target_prices]
            text += f"""
============================================================================
樂活五線譜......      


    超極樂觀價位: {target_prices[0]:>10.2f}, 潛在漲幅: {profits[0]:>10.2f}%
    極樂觀價位:   {target_prices[1]:>10.2f}, 潛在漲幅: {profits[1]:>10.2f}%
    樂觀價位:     {target_prices[2]:>10.2f}, 潛在漲幅: {profits[2]:>10.2f}%
    趨勢價位:     {target_prices[3]:>10.2f}, 潛在漲幅: {profits[3]:>10.2f}%
    悲觀價位:     {target_prices[4]:>10.2f}, 潛在漲幅: {profits[4]:>10.2f}%
    極悲觀價位:    {target_prices[5]:>10.2f}, 潛在漲幅: {profits[5]:>10.2f}%
    超極悲觀價位:  {target_prices[6]:>10.2f}, 潛在漲幅: {profits[6]:>10.2f}%
"""
        except KeyError as e:
            logger.warning(f"{stock_id}: Missing Five-Line Spectrum data: {e}")

# FactSet Estimates
        if stock_data.get("EPS(EST)"):
            eps_est = float(stock_data.get("EPS(EST)"))
            if eps_est:
                target_price = float(stock_data.get("Factest目標價"))
                profit = get_profit(target_price, close_price)
                text += f"""
============================================================================
Factest預估

估計EPS: {eps_est:>10.2f}  預估本益比：    {stock_data["PE(EST)"]:>10.2f}
Factest目標價: {target_price:>10.2f}  推算潛在漲幅為:  {profit:>10.2f}
資料日期: {stock_data["資料時間"]}  
url: {stock_data["ANUEurl"]}
"""
        else:
            logger.warning(f"{stock_id}: Missing FactSet Estimates")

        text += f"""
****************************************************************************
*                           以下資料使用的EPS, BPS                         *
*                        EPS: {eps_use:>10.2f} BPS: {bps:>10.2f}                   *    
****************************************************************************
"""

# PE Quartiles
        try:
            pe_rates = [stock_data[key] for key in ["PE(25%)", "PE(50%)", "PE(75%)", "PE(平均)"]]
            pe_target_prices = [get_target(rate, eps_use) for rate in pe_rates]
            pe_profits = [get_profit(tp, close_price) for tp in pe_target_prices]
            text += f"""
============================================================================
本益比四分位數與平均本益比......

PE 25% : {pe_rates[0]:>10.2f}          目標價位: {pe_target_prices[0]:>10.2f}          潛在漲幅: {pe_profits[0]:>10.2f}%
PE 50% : {pe_rates[1]:>10.2f}          目標價位: {pe_target_prices[1]:>10.2f}          潛在漲幅: {pe_profits[1]:>10.2f}%
PE 75% : {pe_rates[2]:>10.2f}          目標價位: {pe_target_prices[2]:>10.2f}          潛在漲幅: {pe_profits[2]:>10.2f}%
PE平均% : {pe_rates[3]:>10.2f}          目標價位: {pe_target_prices[3]:>10.2f}          潛在漲幅: {pe_profits[3]:>10.2f}%
"""
        except KeyError as e:
            logger.warning(f"{stock_id}: Missing PE Quartiles data: {e}")

# PE Standard Deviation
        try:
            pe_sd_rates = [stock_data[key] for key in ["PE(TL+3SD)", "PE(TL+2SD)", "PE(TL+1SD)", "PE(TL)", "PE(TL-1SD)", "PE(TL-2SD)", "PE(TL-3SD)"]]
            pe_sd_target_prices = [get_target(rate, eps_use) for rate in pe_sd_rates]
            pe_sd_profits = [get_profit(tp, close_price) for tp in pe_sd_target_prices]
            text += f"""
============================================================================
本益比標準差......

PE TL+3SD: {pe_sd_rates[0]:>10.2f}          目標價位: {pe_sd_target_prices[0]:>10.2f}          潛在漲幅: {pe_sd_profits[0]:>10.2f}%
PE TL+2SD: {pe_sd_rates[1]:>10.2f}          目標價位: {pe_sd_target_prices[1]:>10.2f}          潛在漲幅: {pe_sd_profits[1]:>10.2f}%
PE TL+1SD: {pe_sd_rates[2]:>10.2f}          目標價位: {pe_sd_target_prices[2]:>10.2f}          潛在漲幅: {pe_sd_profits[2]:>10.2f}%
PE TL    : {pe_sd_rates[3]:>10.2f}          目標價位: {pe_sd_target_prices[3]:>10.2f}          潛在漲幅: {pe_sd_profits[3]:>10.2f}%
PE TL-1SD: {pe_sd_rates[4]:>10.2f}          目標價位: {pe_sd_target_prices[4]:>10.2f}          潛在漲幅: {pe_sd_profits[4]:>10.2f}%
PE TL-2SD: {pe_sd_rates[5]:>10.2f}          目標價位: {pe_sd_target_prices[5]:>10.2f}          潛在漲幅: {pe_sd_profits[5]:>10.2f}%
PE TL-3SD: {pe_sd_rates[6]:>10.2f}          目標價位: {pe_sd_target_prices[6]:>10.2f}          潛在漲幅: {pe_sd_profits[6]:>10.2f}%
"""
        except KeyError as e:
            logger.warning(f"{stock_id}: Missing PE Standard Deviation data: {e}")

# PB Quartiles
        try:
            pb_rates = [stock_data[key] for key in ["PB(25%)", "PB(50%)", "PB(75%)", "PB(平均)"]]
            pb_target_prices = [get_target(rate, bps) for rate in pb_rates]
            pb_profits = [get_profit(tp, close_price) for tp in pb_target_prices]
            text += f"""
============================================================================
股價淨值比四分位數與平均本益比......

PB 25% : {pb_rates[0]:>10.2f}           目標價位: {pb_target_prices[0]:>10.2f}          潛在漲幅: {pb_profits[0]:>10.2f}%
PB 50% : {pb_rates[1]:>10.2f}           目標價位: {pb_target_prices[1]:>10.2f}          潛在漲幅: {pb_profits[1]:>10.2f}%
PB 75% : {pb_rates[2]:>10.2f}           目標價位: {pb_target_prices[2]:>10.2f}          潛在漲幅: {pb_profits[2]:>10.2f}%
PB 平均 : {pb_rates[3]:>10.2f}           目標價位: {pb_target_prices[3]:>10.2f}          潛在漲幅: {pb_profits[3]:>10.2f}%
"""
        except KeyError as e:
            logger.warning(f"{stock_id}: Missing PB Quartiles data: {e}")

# PB Standard Deviation
        try:
            pb_sd_rates = [stock_data[key] for key in ["PB(TL+3SD)", "PB(TL+2SD)", "PB(TL+1SD)", "PB(TL)", "PB(TL-1SD)", "PB(TL-2SD)", "PB(TL-3SD)"]]
            pb_sd_target_prices = [get_target(rate, bps) for rate in pb_sd_rates]
            pb_sd_profits = [get_profit(tp, close_price) for tp in pb_sd_target_prices]
            text += f"""
============================================================================
股價淨值比標準差......

PB TL+3SD : {pb_sd_rates[0]:>10.2f}           目標價位: {pb_sd_target_prices[0]:>10.2f}          潛在漲幅: {pb_sd_profits[0]:>10.2f}%
PB TL+2SD : {pb_sd_rates[1]:>10.2f}           目標價位: {pb_sd_target_prices[1]:>10.2f}          潛在漲幅: {pb_sd_profits[1]:>10.2f}%
PB TL+1SD : {pb_sd_rates[2]:>10.2f}           目標價位: {pb_sd_target_prices[2]:>10.2f}          潛在漲幅: {pb_sd_profits[2]:>10.2f}%
PB TL     : {pb_sd_rates[3]:>10.2f}           目標價位: {pb_sd_target_prices[3]:>10.2f}          潛在漲幅: {pb_sd_profits[3]:>10.2f}%
PB TL-1SD : {pb_sd_rates[4]:>10.2f}           目標價位: {pb_sd_target_prices[4]:>10.2f}          潛在漲幅: {pb_sd_profits[4]:>10.2f}%
PB TL-2SD : {pb_sd_rates[5]:>10.2f}           目標價位: {pb_sd_target_prices[5]:>10.2f}          潛在漲幅: {pb_sd_profits[5]:>10.2f}%
PB TL-3SD : {pb_sd_rates[6]:>10.2f}           目標價位: {pb_sd_target_prices[6]:>10.2f}          潛在漲幅: {pb_sd_profits[6]:>10.2f}%
"""
        except KeyError as e:
            logger.warning(f"{stock_id}: Missing PB Standard Deviation data: {e}")

# PEG Valuation
        peg = stock_data.get("PEG", None)
        if peg:
            if not peg and eps_use != eps_ttm:
                eps_growth = (eps_use / eps_ttm - 1) * 100
                peg = eps_ttm / eps_growth
                target_price = get_target(eps_growth, eps_ttm)
            else:
                eps_growth = get_target(1 / peg, eps_ttm)
                target_price = close_price / peg
            profit = get_profit(target_price, close_price)
            text += f"""
============================================================================
PEG估值......

PEG: {peg:>10.2f}           EPS成長率: {eps_growth :>10.2f}
目標價位: {target_price:>10.2f}          潛在漲幅: {profit:>10.2f}%
"""
        else:
            logger.warning(f"{stock_id}: Missing PEG Valuation")

        write2txt(text, result_path)
        texts = texts +f"""

{text}
"""
    return texts


def result_output(result_path, stock_datas, eps_lists=None):
    if not isinstance(result_path, Path):
        raise ValueError("result_path must be a pathlib.Path object")
    if not stock_datas:
        raise ValueError("stock_datas cannot be empty")

    try:
        csv_output(result_path, stock_datas)
    except Exception as e:
        logger.error(f"Failed to write CSV: {e}")

    try:
        return txt_output(result_path, stock_datas, eps_lists)
    except Exception as e:
        logger.error(f"Failed to write TXT: {e}")
        return HttpResponse("伺服器錯誤", status=500)

def telegram_print(msg, token_path="token.yaml"):
    try:
        tokens = load_token(token_path)
        token = tokens.get("TelegramToken")
        chat_id = tokens.get("TelegramchatID")
        if not token or not chat_id:
            logger.error("Missing TelegramToken or TelegramchatID in token file")
            return False  
        url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text={msg}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        print(msg)
        return True
    except (requests.RequestException, KeyError) as e:
        logger.error(f"Telegram 發送失敗: {e}")
        return False

async def send_zip_TG(zip_name, token_path="token.yaml"):
    try:
        tokens = load_token(token_path)
        token = tokens.get("TelegramToken")
        chat_id = tokens.get("TelegramchatID")
        if not token or not chat_id:
            logger.error("Missing TelegramToken or TelegramchatID in token file")
            return False  
        
        bot = Bot(token=token)

        with open(zip_name, 'rb') as zip_file:
            await bot.send_document(chat_id=chat_id, document=zip_file, filename=zip_name)

    except TelegramError as te:
        print(f"Telegram error: {te}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

class UnderEST:
    @staticmethod
    async def get_underestimated(result_path: Path) -> dict:
        last_data = await load_data(result_path)
        unders_est_data = {stock_id: data \
                            for stock_id, data in last_data.items()
                            if UnderEST.is_underestimated(data)
                        }
        return unders_est_data

    @staticmethod
    def notify_unders_est(underestimated_dict: dict) -> str:
        msg = "Under Stimated\n"
        unsorted_list = []
        for stock_id, data in underestimated_dict.items():
            name = data.get("名稱")
            business = data.get('產業')
            profit = UnderEST.get_expected_profit(data)
            unsorted_list.append([stock_id, name, business, profit])
        sorted_list = sorted(unsorted_list, key=lambda x: x[3], reverse=True)
        for stock_id, name, business, profit in sorted_list:
            stock_id = str(stock_id).split('.')[0]
            msg += f"{stock_id:<5} {name:<6} {business:<6} {profit:>5.1f}%\n"
        telegram_print(msg)
        return msg

    @staticmethod
    def is_underestimated(StockData):
        return UnderEST.get_expected_profit(StockData) > 0.0

    @staticmethod
    def get_expected_profit(data: dict) -> float:
        eps = data.get("EPS(EST)") or data.get("EPS(TTM)")
        price = data.get("價格")
        target = get_target(data.get("PE(TL-1SD)"), eps)
        
        return get_profit(target, price) if(eps > 0) else -1