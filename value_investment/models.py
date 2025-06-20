from django.db import models

# Create your models here.

class USER_CHOICE(models.Model):
    stock_str = models.TextField(default="")

    def __str__(self):
        return self.stock_str

    def get_stock_list(self):
        return self.stock_str.split() if self.stock_str else []

    def add_stock(self, stocks: list):
        stock_list = self.get_stock_list()
        add_success = ""
        for stock in stocks:
            if stock not in stock_list:
                add_success += f"{stock} "
                self.stock_str += f" {stock}"
        user_choices = self.save()
        add_success  = add_success.split()
        return add_success, user_choices

    def del_stock(self, stocks: list):
        stock_list = self.get_stock_list()
        del_success = ""
        for stock in stocks:
            if stock in stock_list:
                del_success += f"{stock} "
                stock_list.remove(stock)
                self.stock_str = " ".join(stock_list)
        user_choices = self.save()
        del_success  = del_success.split()
        return del_success, user_choices

    def sort_stocks(self):
        stock_list = self.get_stock_list()
        stock_list.sort()
        self.stock_str = " ".join(stock_list)

    def save(self, *args, **kwargs):
        self.sort_stocks()
        super().save(*args, **kwargs)
        return self.get_stock_list()

    def clear_stocks(self):
        self.stock_str = ""
        return self.save()

    def is_ordinary_stock(self, stock):
        if not stock or len(stock) < 4:
            return False
        if not stock.isdigit():
            return False
        return stock[0] in "123456780"