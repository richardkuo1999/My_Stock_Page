import os
import sys
from pathlib import Path
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse
from django.core.exceptions import ValidationError


sys.path.append(os.path.dirname(__file__)+"/..")

from value_investment.utils import zip_response
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

async def force_run_input(request):
    if request.method == "POST":
        form = ForceRun_Input(request.POST)
        if form.is_valid():
            run_lists = form.cleaned_data["ETF_input"].split()
            if Path.exists(LOG_PATH):
                LOG_PATH.unlink()
            _ = await force_run(run_lists, DAILY_RUN_LISTS, IP_ADDR)
    else:
        form = ForceRun_Input()

    return render(request, "Daily_run/Force_run.html", {"form": form})

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
