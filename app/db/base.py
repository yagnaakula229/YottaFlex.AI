from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata base for domain mappings added in later phases."""