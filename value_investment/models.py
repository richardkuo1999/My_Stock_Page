from django.db import models

class StringListModel(models.Model):
    class Meta:
        abstract = True

    def __str__(self):
        return getattr(self, self._field_name())

    def get_list(self):
        return getattr(self, self._field_name()).split() if getattr(self, self._field_name()) else []

    def add_items(self, items: list):
        item_list = self.get_list()
        add_success = ""
        for item in items:
            if item not in item_list:
                add_success += f"{item} "
                setattr(self, self._field_name(), getattr(self, self._field_name()) + f" {item}")
        all_itme = self.save()
        add_success = add_success.split()
        return add_success, all_itme

    def del_items(self, items: list):
        item_list = self.get_list()
        del_success = ""
        for item in items:
            if item in item_list:
                del_success += f"{item} "
                item_list.remove(item)
                setattr(self, self._field_name(), " ".join(item_list))
        all_itme = self.save()
        del_success = del_success.split()
        return del_success, all_itme

    def clear_items(self):
        setattr(self, self._field_name(), "")
        return self.save()

    def _field_name(self):
        raise NotImplementedError("Subclasses must implement _field_name()")

class DAILY_LIST(StringListModel):
    tag_str = models.TextField(default="")

    def _field_name(self):
        return "tag_str"

    def get_tag_list(self):
        return self.get_list()

    def add_tag(self, tags: list):
        return self.add_items(tags)

    def del_tag(self, tags: list):
        return self.del_items(tags)

    def clear_tags(self):
        return self.clear_items()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        return self.get_tag_list()

class USER_CHOICE(StringListModel):
    stock_str = models.TextField(default="")

    def _field_name(self):
        return "stock_str"

    def get_stock_list(self):
        return self.get_list()

    def add_stock(self, stocks: list):
        return self.add_items(stocks)

    def del_stock(self, stocks: list):
        return self.del_items(stocks)

    def sort_stocks(self):
        stock_list = self.get_stock_list()
        stock_list.sort()
        self.stock_str = " ".join(stock_list)

    def save(self, *args, **kwargs):
        self.sort_stocks()
        super().save(*args, **kwargs)
        return self.get_stock_list()

    def clear_stocks(self):
        return self.clear_items()

    def is_ordinary_stock(self, stock):
        if not stock or len(stock) < 4:
            return False
        if not stock.isdigit():
            return False
        return stock[0] in "123456780"