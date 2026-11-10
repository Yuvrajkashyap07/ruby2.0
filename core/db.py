from __future__ import annotations
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, CheckConstraint, create_engine, select, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def read_setting(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    try:
        import streamlit as st
        value = st.secrets.get(name, value)
    except Exception:
        pass
    return str(value)

def database_url() -> str:
    url = read_setting("DATABASE_URL", "").strip()
    if not url:
        Path("data").mkdir(exist_ok=True)
        return "sqlite:///./data/ruby.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

_ENGINE = None
_FACTORY = None

def get_engine():
    global _ENGINE, _FACTORY
    if _ENGINE is None:
        url = database_url()
        sqlite = url.startswith("sqlite")
        args = {"pool_pre_ping": True, "future": True}
        if sqlite:
            args["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            args.update(pool_size=5, max_overflow=5, pool_timeout=30, pool_recycle=1800)
        _ENGINE = create_engine(url, **args)
        if sqlite:
            from sqlalchemy import event
            @event.listens_for(_ENGINE, "connect")
            def _sqlite_setup(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        _FACTORY = sessionmaker(bind=_ENGINE, expire_on_commit=False, autoflush=False)
    return _ENGINE

@contextmanager
def session_scope():
    if _FACTORY is None:
        get_engine()
    session = _FACTORY()
    try:
        yield session
        session.commit()
    except BaseException as exc:
        if exc.__class__.__name__ == "RerunException":
            session.commit()
        else:
            session.rollback()
        raise
    finally:
        session.close()

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer", index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pincode: Mapped[str] = mapped_column(String(6), index=True, nullable=False)
    locality: Mapped[str] = mapped_column(String(140), nullable=False)
    hub_name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("pincode", name="uq_zone_pin"), CheckConstraint("length(pincode)=6", name="ck_zone_pin_len"))

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    business_name: Mapped[str] = mapped_column(String(180), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    sku: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    pack_size: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="pack")
    mrp: Mapped[float] = mapped_column(Float, nullable=False)
    reference_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    target_units: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    min_participants: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True, nullable=False)
    initial_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    final_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reached_moq: Mapped[bool | None] = mapped_column(Boolean)
    participant_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_mix: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

class CampaignSnapshot(Base):
    __tablename__ = "campaign_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True, nullable=False)
    demand_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    participants: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    days_to_cutoff: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class BasketItem(Base):
    __tablename__ = "basket_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("customer_id", "campaign_id", "product_id", name="uq_basket_line"), CheckConstraint("quantity > 0", name="ck_basket_qty"))

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PLACED", index=True, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(24), default="UNPAID", nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)

class VendorQuote(Base):
    __tablename__ = "vendor_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))
    min_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    lead_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


def init_db():
    Base.metadata.create_all(get_engine())
