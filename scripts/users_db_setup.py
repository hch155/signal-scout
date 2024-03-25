from app import app
from models import User
from database import db

with app.app_context():
    db.create_all()

with app.app_context():
    if not User.query.filter_by(email='test@example.com').first():
        test_user = User(email='initdbtest@example.com')
        test_user.set_password('Test2024$') 
        db.session.add(test_user)
        db.session.commit()

print("Users database has been set up.")