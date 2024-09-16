# forms.py
from django import forms


class InputForm(forms.Form):
    user_input = forms.CharField(label="输入内容", max_length=100)
