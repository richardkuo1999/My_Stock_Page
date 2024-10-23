# forms.py
from django import forms


class InputForm(forms.Form):
    Stock_input = forms.CharField(label="输入内容", max_length=1024)
    EPS_input = forms.CharField(label="EPS(無請用 n)", max_length=1024)
