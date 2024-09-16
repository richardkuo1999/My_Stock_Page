from django.shortcuts import render
from value_investment.forms import InputForm


# Create your views here.
def input_view(request):
    if request.method == "POST":
        form = InputForm(request.POST)
        if form.is_valid():
            user_input = form.cleaned_data["user_input"]
            return render(request, "success.html", {"user_input": user_input})
    else:
        form = InputForm()

    return render(request, "input_form.html", {"form": form})
