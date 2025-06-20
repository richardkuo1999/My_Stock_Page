import asyncio
from pathlib import Path
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler

from value_investment.value_investment.server_main import daily_run
from value_investment.views import UserChoiceView, DailyListView

URL = settings.ALLOWED_HOSTS[0]
LOG_PATH = settings.LOG_PATH

def sync_daily_run(run_lists, user_choice, url):
    if Path.exists(LOG_PATH):
        LOG_PATH.unlink()
    asyncio.run(daily_run(run_lists, user_choice, url))

scheduler = BackgroundScheduler()
try:
    daily_list = DailyListView.get_tag_list()
    user_choice = UserChoiceView.get_stock_list()
    scheduler.add_job(sync_daily_run, 'cron', args=(daily_list, user_choice, URL),
                            hour=20, minute=0, misfire_grace_time=30, id='test', 
                            replace_existing=True, timezone='Asia/Taipei')
    scheduler.start()
except Exception as e:
    print(e)
    scheduler.shutdown()