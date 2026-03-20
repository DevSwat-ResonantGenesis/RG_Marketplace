"""Marketplace Service database models."""

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, Boolean, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func

from .db import Base


class AgentListing(Base):
    """Published agent in the marketplace."""
    __tablename__ = "agent_listings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    tagline = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    
    category = Column(String(64), index=True, nullable=True)  # coding, writing, research, etc.
    tags = Column(ARRAY(String), nullable=True)
    
    icon_url = Column(String(512), nullable=True)
    banner_url = Column(String(512), nullable=True)
    screenshots = Column(ARRAY(String), nullable=True)
    
    # Pricing
    price_type = Column(String(32), default="free")  # free, one_time, subscription
    price_amount = Column(Float, default=0.0)
    price_currency = Column(String(3), default="USD")
    stripe_price_id = Column(String(128), nullable=True)
    
    # Agent configuration
    agent_config = Column(JSON, nullable=True)  # System prompt, tools, etc.
    required_tools = Column(ARRAY(String), nullable=True)
    
    # Stats
    downloads = Column(Integer, default=0)
    rating_average = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)
    
    # Status
    status = Column(String(32), default="draft")  # draft, pending_review, published, suspended
    is_featured = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AgentVersion(Base):
    """Version history for agents."""
    __tablename__ = "agent_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    version = Column(String(32), nullable=False)  # semver: 1.0.0
    changelog = Column(Text, nullable=True)
    
    agent_config = Column(JSON, nullable=True)
    is_current = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentPurchase(Base):
    """Record of agent purchases."""
    __tablename__ = "agent_purchases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    buyer_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    price_paid = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    
    stripe_payment_id = Column(String(128), nullable=True)
    stripe_subscription_id = Column(String(128), nullable=True)
    
    status = Column(String(32), default="completed")  # pending, completed, refunded, cancelled
    
    purchased_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # For subscriptions


class AgentReview(Base):
    """User reviews for agents."""
    __tablename__ = "agent_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    rating = Column(Integer, nullable=False)  # 1-5
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)
    
    is_verified_purchase = Column(Boolean, default=False)
    helpful_count = Column(Integer, default=0)
    
    status = Column(String(32), default="published")  # published, hidden, flagged
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AgentUsageStats(Base):
    """Usage statistics for agents."""
    __tablename__ = "agent_usage_stats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    total_runs = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_duration_ms = Column(Integer, default=0)
    
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PublisherProfile(Base):
    """Publisher/developer profiles."""
    __tablename__ = "publisher_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), unique=True, index=True, nullable=False)
    
    display_name = Column(String(255), nullable=False)
    bio = Column(Text, nullable=True)
    website_url = Column(String(512), nullable=True)
    avatar_url = Column(String(512), nullable=True)
    
    stripe_account_id = Column(String(128), nullable=True)  # Connected account for payouts
    
    is_verified = Column(Boolean, default=False)
    total_earnings = Column(Float, default=0.0)
    total_sales = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class MarketplaceCategory(Base):
    """Categories for organizing agents."""
    __tablename__ = "marketplace_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    name = Column(String(64), unique=True, nullable=False)
    slug = Column(String(64), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(64), nullable=True)
    
    parent_id = Column(UUID(as_uuid=True), nullable=True)
    sort_order = Column(Integer, default=0)
    
    is_active = Column(Boolean, default=True)
    agent_count = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
