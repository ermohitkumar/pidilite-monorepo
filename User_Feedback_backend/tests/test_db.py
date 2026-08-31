from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import User, Base
from core.security import hash_password

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

u = User(email="test@test.com", password_hash=hash_password("test"), role="user", is_active=True, allowed_resources=[])
session.add(u)
session.commit()
print(repr(u.created_at))
print(type(u.created_at))
