"""
Celery configuration for async task processing.
"""

import os
from celery import Celery

# Create Celery instance
celery = Celery(
    'pm_app',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    include=['pm_app.tasks']
)

# Celery configuration
celery.conf.update(
    # Task serialization
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,

    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,

    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,

    # Result backend
    result_expires=3600,  # 1 hour

    # Task routing
    task_routes={
        'pm_app.tasks.send_async_email': {'queue': 'email'},
        'pm_app.tasks.generate_pdf_report': {'queue': 'reports'},
    },
)

# Auto-discover tasks from installed apps
celery.autodiscover_tasks(['pm_app'])

def init_celery(app):
    """Initialize Celery with Flask app context."""
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
