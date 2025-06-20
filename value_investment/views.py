import os
import sys
import asyncio
import zipfile
from pathlib import Path
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse
from django.core.exceptions import ValidationError


sys.path.append(os.path.dirname(__file__)+"/..")

from value_investment.models import USER_CHOICE, DAILY_LIST

from value_investment.value_investment.utils.utils import logger_create
from value_investment.value_investment.server_main import individual_search, force_run


logger = logger_create(__name__)

IP_ADDR = settings.ALLOWED_HOSTS[0]
LOG_PATH = settings.LOG_PATH


def index(request):
    return render(request, "index.html")

def config_index(request):
    return render(request, "ConfigSet/Config.html")
class InvestmentView:
    @staticmethod
    def daily_run(request):
        return render(request, "Daily_run/Daily_run_Report.html")

    @staticmethod
    def force_run(request):
        daily_list = " ".join(DailyListView.get_tag_list())
        context = { "default_dailylist_input": daily_list }
        if request.method == "POST":
            user_choice = UserChoiceView.get_stock_list()
            run_lists = request.POST.get("stock_input", "").splite()
            if Path.exists(LOG_PATH):
                LOG_PATH.unlink()
            _ = asyncio.run(force_run(run_lists, daily_list, user_choice, IP_ADDR))
        return render(request, "Daily_run/Force_run.html", context)

    @staticmethod
    def individual(request):
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
                parms = [int(level_input),float(year_input)]

                result = asyncio.run(individual_search(stock_list, eps_list, parms))
                
                return render(
                    request,
                    "Individual/Individual_result.html",
                    {"Stock_input": result[1]},
                )
            except Exception as e:
                logger.error(f"個股查詢錯誤: {str(e)}")
                return HttpResponse("伺服器錯誤", status=500)

        context = { "default_level": 4 ,"default_year":4.5}
        return render(request, "Individual/Individual_input.html", context)


class DownloadFileView:
    @staticmethod
    def individual(request):
        file_paths = [
            os.path.join(settings.RESULT_PATHS["individual_report_path"], f"{name}")
            for name in ["Individual.txt", "Individual.csv"]
        ]
        return DownloadFileView.zip_response(file_paths, "result_Individual.zip")

    @staticmethod
    def daily_txt(request):
        daily_list = DailyListView.get_tag_list()
        file_paths = [
            os.path.join(settings.RESULT_PATHS["daliy_report_path"], f"{name}.txt")
            for name in daily_list + ["Understimated", "Institutional_TOP50"]
        ]
        return DownloadFileView.zip_response(file_paths, "result_txt.zip")

    @staticmethod
    def daily_csv(request):
        daily_list = DailyListView.get_tag_list()
        file_paths = [
            os.path.join(settings.RESULT_PATHS["daliy_report_path"], f"{name}.csv")
            for name in daily_list + ["Understimated", "Institutional_TOP50"]
        ]
        return DownloadFileView.zip_response(file_paths, "result_csv.zip")
    
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
