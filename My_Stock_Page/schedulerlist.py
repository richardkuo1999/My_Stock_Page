import asyncio
from pathlib import Path
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler

from value_investment.value_investment.server_main import daily_run

RUN_LISTS = settings.DAILY_RUN_LISTS
URL = settings.ALLOWED_HOSTS[0]
LOG_PATH = settings.LOG_PATH

def sync_daily_run(run_lists, url):
    if Path.exists(LOG_PATH):
        LOG_PATH.unlink()
    asyncio.run(daily_run(run_lists, url))

scheduler = BackgroundScheduler()
try:
    scheduler.add_job(sync_daily_run, 'cron', args=(RUN_LISTS, URL),
                            hour=20, minute=0, misfire_grace_time=30, id='test', 
                            replace_existing=True, timezone='Asia/Taipei')
    scheduler.start()
except Exception as e:
    print(e)
    scheduler.shutdown()