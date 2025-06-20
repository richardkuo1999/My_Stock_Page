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

from value_investment.models import USER_CHOICE

from value_investment.forms import Individual_Input, ForceRun_Input

from value_investment.value_investment.utils.utils import logger_create
from value_investment.value_investment.server_main import individual_search, force_run


logger = logger_create(__name__)

DAILY_RUN_LISTS = settings.DAILY_RUN_LISTS
IP_ADDR = settings.ALLOWED_HOSTS[0]
LOG_PATH = settings.LOG_PATH

def index(request):
    return render(request, "index.html")

from concurrent.futures import ThreadPoolExecutor

async def individual_input(request):
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
        form = Individual_Input(request.POST)
        if form.is_valid():
            try:
                stock_list, eps_list = process_stock_input(
                    form.cleaned_data["Stock_input"], form.cleaned_data["EPS_input"]
                )
                parms = [int(form.cleaned_data["level_input"]),float(form.cleaned_data["year_input"])]

                result = await individual_search(stock_list, eps_list, parms)
                
                return render(
                    request,
                    "Individual/Individual_result.html",
                    {"Stock_input": result[1]},
                )
            except ValidationError as e:
                form.add_error(None, str(e))
            except Exception as e:
                logger.error(f"個股查詢錯誤: {str(e)}")
                return HttpResponse("伺服器錯誤", status=500)
    else:
        form = Individual_Input()

    return render(request, "Individual/Individual_input.html", {"form": form})

def daily_run_report(request):
    return render(request, "Daily_run/Daily_run_Report.html")

def force_run_input(request):
    if request.method == "POST":
        form = ForceRun_Input(request.POST)
        if form.is_valid():
            run_lists = form.cleaned_data["ETF_input"].split()
            USER_CHOICE = UserChoiceView.get_stock_list()
            if Path.exists(LOG_PATH):
                LOG_PATH.unlink()
            _ = asyncio.run(force_run(run_lists, DAILY_RUN_LISTS, USER_CHOICE, IP_ADDR))
    else:
        form = ForceRun_Input()

    return render(request, "Daily_run/Force_run.html", {"form": form})

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

def download_file_Individual(request):
    file_paths = [
        os.path.join(settings.RESULT_PATHS["individual_report_path"], f"{name}")
        for name in ["Individual.txt", "Individual.csv"]
    ]
    return zip_response(file_paths, "result_Individual.zip")

def download_file_txt(request):
    file_paths = [
        os.path.join(settings.RESULT_PATHS["daliy_report_path"], f"{name}.txt")
        for name in settings.DAILY_RUN_LISTS + ["Understimated", "Institutional_TOP50"]
    ]
    return zip_response(file_paths, "result_txt.zip")

def download_file_csv(request):
    file_paths = [
        os.path.join(settings.RESULT_PATHS["daliy_report_path"], f"{name}.csv")
        for name in settings.DAILY_RUN_LISTS + ["Understimated", "Institutional_TOP50"]
    ]
    return zip_response(file_paths, "result_csv.zip")

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
        if request.method == "POST":
            add_success = []
            if stock_input:
                add_success, user_choices = obj.add_stock(stock_input.split())
            else:
                user_choices = obj.get_stock_list()
            return UserChoiceView.index(request, user_choices, add_success, [])
        return HttpResponse("Invalid request", status=400)

    @staticmethod
    def del_stock(request, obj, stock_input):
        if request.method == "POST":
            del_success = []
            if stock_input:
                del_success, user_choices = obj.del_stock(stock_input.split())
            else:
                user_choices = obj.get_stock_list()
            return UserChoiceView.index(request, user_choices, [], del_success)
        return HttpResponse("Invalid request", status=400)

    @staticmethod
    def clear_stocks(request, obj):
        user_choices  = obj.clear_stocks()
        return UserChoiceView.index(request, user_choices, [], [])
    
    @staticmethod
    def index(request, user_choices, add_success, del_success):
        return render(request, "UserChoice/UserChoiceSetting.html", locals())
