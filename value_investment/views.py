import os
import zipfile
import threading
from pathlib import Path
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse
from django.http import FileResponse


from value_investment.forms import InputForm
from value_investment.main.server_main import Individual_search, daily_run, run


# Create your views here.
def index(request):
    return render(request, "index.html")


def Individual(request):
    resultsPath = Path("results", "Individual", "Individual.txt")
    if request.method == "POST":
        form = InputForm(request.POST)
        if form.is_valid():
            if resultsPath.exists():
                resultsPath.unlink()
                resultsPath.with_name(resultsPath.stem + "_apple").with_suffix(
                    ".csv"
                ).unlink()
                resultsPath.with_name(resultsPath.stem + "_google").with_suffix(
                    ".csv"
                ).unlink()
                resultsPath.with_suffix(".csv").unlink()

            StockLists = form.cleaned_data["user_input"].split(" ")
            Individual_search(StockLists)
            result = ""
            with resultsPath.open("r", encoding="utf-8") as file:
                for line in file:
                    result += line
            return render(
                request, "Individual/Individual_result.html", {"user_input": result}
            )
    else:
        form = InputForm()

    return render(request, "Individual/Individual_input.html", {"form": form})


thread1 = None
thread2 = None


def force＿run(request):
    global thread2
    print("111")
    if "thread2" not in globals() or thread2 is None:
        # 线程已完成，可以重新启动
        thread2 = threading.Thread(target=run)
        thread2.start()
    else:
        print("Thread2 is already running.")
    return render(request, "Daily_run_Report.html")


def Daily_run_Report(request):
    global thread1
    if "thread1" not in globals() or thread1 is None:
        # 线程已完成，可以重新启动
        thread1 = threading.Thread(target=daily_run)
        thread1.start()
    else:
        print("Thread1 is already running.")

    return render(request, "Daily_run_Report.html")


def download_file_apple(request):
    # 設定檔案的路徑
    file_paths = [
        os.path.join(settings.BASE_DIR, "results", "Individual/0050_apple.csv"),
        os.path.join(settings.BASE_DIR, "results", "Individual/0051_apple.csv"),
        os.path.join(settings.BASE_DIR, "results", "Individual/006201_apple.csv"),
        os.path.join(settings.BASE_DIR, "results", "Individual/User_Choice_apple.csv"),
    ]

    # 創建一個內存中的 ZIP 文件
    response = HttpResponse(content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=result_apple.zip"

    with zipfile.ZipFile(response, "w") as zip_file:
        for file_path in file_paths:
            print(file_path)
            if os.path.isfile(file_path):
                zip_file.write(file_path, os.path.basename(file_path))

    return response


def download_file_Individual(request):
    # 設定檔案的路徑
    file_paths = [
        os.path.join(
            settings.BASE_DIR, "results", "Individual", "Individual_apple.csv"
        ),
        os.path.join(settings.BASE_DIR, "results", "Individual", "Individual.txt"),
        os.path.join(settings.BASE_DIR, "results", "Individual", "Individual.csv"),
        os.path.join(
            settings.BASE_DIR, "results", "Individual", "Individual_google.csv"
        ),
        os.path.join(
            settings.BASE_DIR, "results", "Individual", "User_Choice_google.csv"
        ),
    ]

    # 創建一個內存中的 ZIP 文件
    response = HttpResponse(content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=result_Individual.zip"

    with zipfile.ZipFile(response, "w") as zip_file:
        for file_path in file_paths:
            print(file_path)
            if os.path.isfile(file_path):
                zip_file.write(file_path, os.path.basename(file_path))

    return response


def download_file_txt(request):
    # 設定檔案的路徑
    file_paths = [
        os.path.join(settings.BASE_DIR, "results", "0050.txt"),
        os.path.join(settings.BASE_DIR, "results", "0051.txt"),
        os.path.join(settings.BASE_DIR, "results", "006201.txt"),
        os.path.join(settings.BASE_DIR, "results", "User_Choice.txt"),
    ]

    # 創建一個內存中的 ZIP 文件
    response = HttpResponse(content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=result_txt.zip"

    with zipfile.ZipFile(response, "w") as zip_file:
        for file_path in file_paths:
            if os.path.isfile(file_path):
                zip_file.write(file_path, os.path.basename(file_path))

    return response


def download_file_csv(request):
    # 設定檔案的路徑
    file_paths = [
        os.path.join(settings.BASE_DIR, "results", "0050.csv"),
        os.path.join(settings.BASE_DIR, "results", "0051.csv"),
        os.path.join(settings.BASE_DIR, "results", "006201.csv"),
        os.path.join(settings.BASE_DIR, "results", "User_Choice.csv"),
    ]

    # 創建一個內存中的 ZIP 文件
    response = HttpResponse(content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=result_csv.zip"

    with zipfile.ZipFile(response, "w") as zip_file:
        for file_path in file_paths:
            if os.path.isfile(file_path):
                zip_file.write(file_path, os.path.basename(file_path))

    return response


def download_file_google(request):
    # 設定檔案的路徑
    file_paths = [
        os.path.join(settings.BASE_DIR, "results", "0050_google.csv"),
        os.path.join(settings.BASE_DIR, "results", "0051_google.csv"),
        os.path.join(settings.BASE_DIR, "results", "006201_google.csv"),
        os.path.join(settings.BASE_DIR, "results", "User_Choice_google.csv"),
    ]

    # 創建一個內存中的 ZIP 文件
    response = HttpResponse(content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=result_google.zip"

    with zipfile.ZipFile(response, "w") as zip_file:
        for file_path in file_paths:
            if os.path.isfile(file_path):
                zip_file.write(file_path, os.path.basename(file_path))

    return response
