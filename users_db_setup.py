from app import app
from models import db, User

with app.app_context():
    db.create_all()

with app.app_context():
    if not User.query.filter_by(email='test@example.com').first():
        test_user = User(email='userinitdbtest@example.com')
        test_user.set_password('testpassword') 
        db.session.add(test_user)
        db.session.commit()

print("Users database has been set up.")