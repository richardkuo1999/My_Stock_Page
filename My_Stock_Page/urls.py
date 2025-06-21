"""
URL configuration for My_Stock_Page project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from value_investment.views import *
from My_Stock_Page.schedulerlist import *

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", index),
    
    path("Individual", InvestmentView.individual),
    path("Daily_run_Report", daily_run_index),
    path("Force_run", InvestmentView.force_run),
    path("download/Individual", DownloadFileView.individual, name="Individual"),
    path("download/txt", DownloadFileView.daily_txt, name="txt"),
    path("download/csv", DownloadFileView.daily_csv, name="csv"),

    path("ConfigSetting", config_index),
    path("UserChoice", UserChoiceView.user_choice_index),
    path("DailyList", DailyListView.daily_list_index),
]
