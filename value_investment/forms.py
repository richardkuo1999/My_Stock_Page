# forms.py
from django import forms
from django.conf import settings

class Individual_Input(forms.Form):
    Stock_input = forms.CharField(
        label="输入内容",
        max_length=1024,
        initial=""  # 預設值為空字串
    )
    level_input = forms.CharField(
        label="Factset EPS level: 1-high, 2-low, 3-average, 4-medium",
        max_length=4,
        initial="4"  # 預設為 4 (medium)
    )
    EPS_input = forms.CharField(
        label="自行輸入EPS(無請用 n)",
        max_length=1024,
        initial="n"  # 預設為 "n"
    )
    year_input = forms.CharField(
        label="要使用過去幾年的資料: ",
        max_length=1024,
        initial="4.5"  # 預設為 4.5 年
    )

class ForceRun_Input(forms.Form):
    ETF_input = forms.CharField(
        label="输入内容",
        max_length=1024,
        initial=" ".join(settings.DAILY_RUN_LISTS)  # 預設值為全部
    )
