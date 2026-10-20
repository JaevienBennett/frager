from app import models  # noqa: F401
from app.database import Base, engine

Base.metadata.create_all(engine)
print("Tables created:", ", ".join(sorted(Base.metadata.tables)))
