import os
from pm_app import create_app
print('DATABASE_URL env', os.getenv('DATABASE_URL'))
app = create_app()
print('app.config DATABASE_URL', app.config.get('SQLALCHEMY_DATABASE_URI'))
print('APP_ENV', app.config.get('APP_ENV'))
