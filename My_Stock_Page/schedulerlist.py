import asyncio
from pathlib import Path
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler

from value_investment.views import UserChoiceView, DailyListView, InvestmentView

URL = settings.ALLOWED_HOSTS[0]
LOG_PATH = settings.LOG_PATH

def async_daily_run(run_lists, daily_list, user_choice, url):
    asyncio.run(InvestmentView.daily_run(run_lists, daily_list, user_choice, url))

scheduler = BackgroundScheduler()
try:
    daily_list = DailyListView.get_tag_list()
    user_choice = UserChoiceView.get_stock_list()
    scheduler.add_job(async_daily_run, 'cron', args=(daily_list, daily_list, user_choice, URL),
                            hour=20, minute=0, misfire_grace_time=30, id='test', 
                            replace_existing=True, timezone='Asia/Taipei')
    scheduler.start()
except Exception as e:
    print(e)
    scheduler.shutdown()