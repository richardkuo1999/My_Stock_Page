from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler

from value_investment.value_investment.server_main import daily_run

RUN_LISTS = settings.DAILY_RUN_LISTS
URL = settings.ALLOWED_HOSTS[0]

scheduler = BackgroundScheduler()
try:
    scheduler.add_job(daily_run, 'cron', args=(RUN_LISTS, URL),
                            hour=20, minute=0, id='test', 
                            replace_existing=True, timezone='Asia/Taipei')
    scheduler.start()
except Exception as e:
    print(e)
    scheduler.shutdown()