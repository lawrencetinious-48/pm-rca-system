from pm_app.legacy_app import create_app
from model import db
app = create_app()
print('SQLALCHEMY_DATABASE_URI=', app.config.get('SQLALCHEMY_DATABASE_URI'))
with app.app_context():
    db.drop_all()
    db.create_all()
    print('DB recreated')
