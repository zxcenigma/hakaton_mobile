from celery import Celery

from monoapi.core import settings

celery_app = Celery(main="monoapi", 
                    broker=settings.redis_settings.redis_url, 
                    backend=settings.redis_settings.redis_url)

celery_app.autodiscover_tasks(packages=["monoapi"])