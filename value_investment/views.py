import os, sys
import zipfile
import logging
import threading
import asyncio, aiohttp
from pathlib import Path
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from asgiref.sync import sync_to_async


sys.path.append(os.path.dirname(__file__)+"/..")

from value_investment.models import USER_CHOICE, DAILY_LIST

from value_investment.value_investment.utils.output import UnderEST, result_output, telegram_print
from value_investment.value_investment.calculator.calculator import calculator
from value_investment.value_investment.utils.utils import logger, load_token, load_data
from value_investment.value_investment.calculator.Index import notify_macro_indicators
from value_investment.value_investment.calculator.stock_select import fetch_etf_constituents, fetch_institutional_top50


IP_ADDR = settings.ALLOWED_HOSTS[0]
RESULT_PATHS = settings.RESULT_PATHS
LOG_PATH = settings.LOG_PATH / "value_investment.log"

level = 4       # EPS level: 1-high, 2-low, 3-average, 4-medium
year = 4.5      # Calculation period (years)
daily_run_lock = threading.Lock()

def index(request):
    return render(request, "index.html")

def config_index(request):
    return render(request, "ConfigSet/Config.html")

def daily_run_index(request):
    return render(request, "Daily_run/Daily_run_Report.html")
class InvestmentView:
    @staticmethod
    async def daily_run(run_lists, daily_list, user_choice, IP_ADDR):
        async def __daily_run(run_lists, daily_list, user_choice):
            result_path = RESULT_PATHS["daliy_report_path"]
            backup_path = RESULT_PATHS["daliy_report_backup_path"]
            tokens = load_token()
            params = [level, year]

            catchs = await load_data(RESULT_PATHS["result_path"])

            stock_groups = {}

            for file in result_path.rglob("*"):
                if file.is_file() and (file.stem in run_lists or file.stem == "Understimated"):
                    file.replace(backup_path / file.name)

            stock_groups = {}
            async with aiohttp.ClientSession() as session:
                for etf in daily_list:
                    if etf in run_lists:
                        stock_groups[etf] = user_choice if etf == "User_Choice" else await fetch_etf_constituents(session, etf)

                # TODO 評估要不要異步化
                for title, stocklist in stock_groups.items():
                    if title != "Institutional_TOP50":
                        telegram_print(f"Start Run\n{title}: {len(stocklist)}")
                        resultdata = await calculator(session, stocklist, params, tokens, catchs)
                        result_output(result_path / Path(title), resultdata)

                unders_est_data = {}
                try:
                    unders_est_data = await UnderEST.get_underestimated(result_path)
                    result_output(result_path / Path("Understimated"), unders_est_data)
                except Exception as e:
                    logger.error(f"Error in getting underestimated stocks: {e}")

                if "Institutional_TOP50" in run_lists:
                    try:
                        last_data = await load_data(result_path)
                        stock_list = await fetch_institutional_top50(session)
                        telegram_print(f"Start Run\nInstitutional_TOP50: {len(stock_list)}")

                        existing_data = {sid: last_data[sid] for sid in stock_list if sid in last_data}
                        missing_ids = [sid for sid in stock_list if sid not in last_data]

                        resultdata = await calculator(session, missing_ids, params, tokens, catchs)

                        resultdata.update(existing_data)
                        result_output(result_path / Path("Institutional_TOP50"), resultdata)
                    except Exception as e:
                        logger.error(f"Error in getting institutional data: {e}")

                try:
                    UnderEST.notify_unders_est(unders_est_data)
                except Exception as e:
                    logger.error(f"Error in Notify underestimated stocks: {e}")
                    logger.error(f"unders_est_data: {unders_est_data}")

                try:
                    await notify_macro_indicators(tokens, session)
                except Exception as e:
                    logger.error(f"Error in notifying macro indicators: {e}")

        if daily_run_lock.acquire(blocking=False):
            if Path.exists(LOG_PATH):
                with open(LOG_PATH, 'w') as f:
                    f.truncate(0)  # 清空文件内容

            try:
                telegram_print("Start Run")
                await __daily_run(run_lists, daily_list, user_choice)
                telegram_print("Run Finished")
            except Exception as e:
                logger.error(f"Run error: {e}")
                telegram_print(f"Run error: {e}")
            finally:
                telegram_print(
                    f"Download link:\nCSV: http://{IP_ADDR}:8000/download/csv\n" \
                    f"TXT: http://{IP_ADDR}:8000/download/txt"
                )
                daily_run_lock.release()
                logging.shutdown()

    @staticmethod
    async def force_run(request):
        daily_list = await sync_to_async(DailyListView.get_tag_list)()
        daily_str = " ".join(daily_list)
        context = { "default_dailylist_input": daily_str }
        if request.method == "POST":
            user_choice = await sync_to_async(UserChoiceView.get_stock_list)()
            run_lists = request.POST.get("tag_input", "").split()
            await InvestmentView.daily_run(run_lists, daily_list, user_choice, IP_ADDR)
        return render(request, "Daily_run/Force_run.html", context)

    @staticmethod
    async def individual(request):
        result_path = RESULT_PATHS["individual_report_path"]
        result_path.mkdir(parents=True, exist_ok=True)
        tokens = load_token()
        catchs = await load_data(RESULT_PATHS["result_path"])

        def process_stock_input(stock_input, eps_input):
            try:
                stock_list = stock_input.split()
                if eps_input == "n":
                    eps_list = None
                else:
                    eps_list = [float(eps) for eps in eps_input.split()]
                return stock_list, eps_list
            except ValueError:
                raise ValidationError("EPS 輸入格式錯誤")
        
        if request.method == "POST":
            try:
                stock_input = request.POST.get("stock_input", None)
                level_input = request.POST.get("level_input", 4)
                EPS_input = request.POST.get("EPS_input", "n")
                year_input = request.POST.get("year_input", 4.5)
                stock_list, eps_list = process_stock_input(stock_input, EPS_input)
                params = [int(level_input),float(year_input)]
    
                for file in result_path.rglob("*"):
                    if file.is_file() and file.stem == "Individual":
                        file.unlink()

                if Path.exists(LOG_PATH):
                    with open(LOG_PATH, 'w') as f:
                        f.truncate(0)  # 清空文件内容

                async with aiohttp.ClientSession() as session:
                    stock_datas = await calculator(session, stock_list, params, tokens, catchs)
                stock_texts = result_output(result_path / Path("Individual"), stock_datas, eps_list)

                return render(
                    request,
                    "Individual/Individual_result.html",
                    {"Stock_input": stock_texts},
                )
            except Exception as e:
                logger.error(f"個股查詢錯誤: {str(e)}")
                return HttpResponse("伺服器錯誤", status=500)
            finally:
                logging.shutdown()

        context = { "default_level": 4 ,"default_year":4.5}
        return render(request, "Individual/Individual_input.html", context)


class DownloadFileView:
    @staticmethod
    def individual(request):
        file_paths = [
            RESULT_PATHS["individual_report_path"]/f"{name}"
            for name in ["Individual.txt", "Individual.csv"]
        ]
        return DownloadFileView.zip_response(file_paths, "result_Individual.zip")

    @staticmethod
    def daily_txt(request):
        daily_list = DailyListView.get_tag_list()
        file_paths = [
            RESULT_PATHS["daliy_report_path"]/f"{name}.txt"
            for name in daily_list + ["Understimated", "Institutional_TOP50"]
        ]
        return DownloadFileView.zip_response(file_paths, "result_txt.zip")

    @staticmethod
    def daily_csv(request):
        daily_list = DailyListView.get_tag_list()
        file_paths = [
            RESULT_PATHS["daliy_report_path"]/f"{name}.csv"
            for name in daily_list + ["Understimated", "Institutional_TOP50"]
        ]
        return DownloadFileView.zip_response(file_paths, "result_csv.zip")

    @staticmethod
    def download_log(request):
        file_paths = [
           file for file in settings.LOG_PATH.rglob("*")
        ]
        return DownloadFileView.zip_response(file_paths, "log.zip")
    
    @staticmethod
    def zip_response(file_paths, zip_name):
        response = HttpResponse(content_type="application/zip")
        response["Content-Disposition"] = f"attachment; filename={zip_name}"

        try:
            with zipfile.ZipFile(response, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                for path in file_paths:
                    if Path(path).is_file():
                        zip_file.write(path, Path(path).name)
                        logger.info(f"壓縮檔案: {path}")
                    else:
                        logger.warning(f"檔案不存在: {path}")
            return response
        except Exception as e:
            logger.error(f"壓縮檔案失敗: {str(e)}")
            return HttpResponse("壓縮檔案失敗", status=500)


class DailyListView:
    @staticmethod
    def get_tag_list():
        obj = DAILY_LIST.objects.first()
        if obj is None:
            obj = DAILY_LIST.objects.create(tag_str="")
        return obj.get_tag_list()

    @staticmethod
    def daily_list_index(request):
        obj = DAILY_LIST.objects.first()
        if obj is None:
            obj = DAILY_LIST.objects.create(tag_str="")
        if request.method == "POST":
            action = request.POST.get("action")
            tag_input = request.POST.get("tag_input", None)
            tag_input = tag_input.strip() if tag_input else ""
            if action == "add":
                return DailyListView.add_tag(request, obj, tag_input)
            elif action == "delete":
                return DailyListView.del_tag(request, obj, tag_input)
            elif action == "clear":
                return DailyListView.clear_tags(request, obj)
        else:
            daily_tags = obj.get_tag_list()
        return DailyListView.index(request, daily_tags, [], [])

    @staticmethod
    def add_tag(request, obj, tag_input):
        add_success = []
        if tag_input:
            add_success, daily_tags = obj.add_tag(tag_input.split())
        else:
            daily_tags = obj.get_tag_list()
        return DailyListView.index(request, daily_tags, add_success, [])

    @staticmethod
    def del_tag(request, obj, tag_input):
        del_success = []
        if tag_input:
            del_success, daily_tags = obj.del_tag(tag_input.split())
        else:
            daily_tags = obj.get_tag_list()
        return DailyListView.index(request, daily_tags, [], del_success)

    @staticmethod
    def clear_tags(request, obj):
        daily_tags  = obj.clear_tags()
        return DailyListView.index(request, daily_tags, [], [])
    
    @staticmethod
    def index(request, daily_list, add_success, del_success):
        return render(request, "ConfigSet/DailyListSetting.html", locals())


class UserChoiceView:
    @staticmethod
    def get_stock_list():
        obj = USER_CHOICE.objects.first()
        if obj is None:
            obj = USER_CHOICE.objects.create(stock_str="")
        return obj.get_stock_list()

    @staticmethod
    def user_choice_index(request):
        obj = USER_CHOICE.objects.first()
        if obj is None:
            obj = USER_CHOICE.objects.create(stock_str="")
        if request.method == "POST":
            action = request.POST.get("action")
            stock_input = request.POST.get("stock_input", None)
            stock_input = stock_input.strip() if stock_input else ""
            if action == "add":
                return UserChoiceView.add_stock(request, obj, stock_input)
            elif action == "delete":
                return UserChoiceView.del_stock(request, obj, stock_input)
            elif action == "clear":
                return UserChoiceView.clear_stocks(request, obj)
        else:
            user_choices = obj.get_stock_list()
        return UserChoiceView.index(request, user_choices, [], [])

    @staticmethod
    def add_stock(request, obj, stock_input):
        add_success = []
        if stock_input:
            add_success, user_choices = obj.add_stock(stock_input.split())
        else:
            user_choices = obj.get_stock_list()
        return UserChoiceView.index(request, user_choices, add_success, [])

    @staticmethod
    def del_stock(request, obj, stock_input):
        del_success = []
        if stock_input:
            del_success, user_choices = obj.del_stock(stock_input.split())
        else:
            user_choices = obj.get_stock_list()
        return UserChoiceView.index(request, user_choices, [], del_success)

    @staticmethod
    def clear_stocks(request, obj):
        user_choices  = obj.clear_stocks()
        return UserChoiceView.index(request, user_choices, [], [])
    
    @staticmethod
    def index(request, user_choices, add_success, del_success):
        return render(request, "ConfigSet/UserChoiceSetting.html", locals())
