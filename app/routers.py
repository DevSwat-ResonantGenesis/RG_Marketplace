"""Marketplace Service API routers."""

import httpx
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import (
    AgentListing, AgentVersion, AgentPurchase, AgentReview,
    AgentUsageStats, PublisherProfile, MarketplaceCategory,
)
from .config import settings

logger = logging.getLogger(__name__)

BLOCKCHAIN_SERVICE_URL = os.getenv("BLOCKCHAIN_SERVICE_URL", "http://blockchain_service:8000")
CRYPTO_SERVICE_URL = os.getenv("CRYPTO_SERVICE_URL", "http://crypto_service:8000")

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ============== Request/Response Models ==============

class CreateListingRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    tagline: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    price_type: str = "free"
    price_amount: float = 0.0
    agent_config: Optional[Dict[str, Any]] = None
    required_tools: Optional[List[str]] = None


class UpdateListingRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    tagline: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    price_type: Optional[str] = None
    price_amount: Optional[float] = None
    agent_config: Optional[Dict[str, Any]] = None


class ListingResponse(BaseModel):
    id: str
    publisher_id: str
    name: str
    slug: str
    tagline: Optional[str]
    description: Optional[str]
    category: Optional[str]
    tags: Optional[List[str]]
    price_type: str
    price_amount: float
    downloads: int
    rating_average: float
    rating_count: int
    status: str
    is_featured: bool
    is_verified: bool


class CreateReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = Field(None, max_length=2000)


class ReviewResponse(BaseModel):
    id: str
    listing_id: str
    reviewer_id: str
    rating: int
    title: Optional[str]
    content: Optional[str]
    is_verified_purchase: bool
    helpful_count: int
    created_at: str


class PublisherProfileRequest(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=255)
    bio: Optional[str] = None
    website_url: Optional[str] = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
    icon: Optional[str]
    agent_count: int


# ============== Helper Functions ==============

def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from name."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


# ============== Listing Endpoints ==============

@router.post("/listings", response_model=ListingResponse, status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: CreateListingRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a new agent listing."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Generate unique slug
    base_slug = generate_slug(payload.name)
    slug = base_slug
    counter = 1
    
    while True:
        result = await session.execute(
            select(AgentListing).where(AgentListing.slug == slug)
        )
        if not result.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    listing = AgentListing(
        publisher_id=user_id,
        name=payload.name,
        slug=slug,
        tagline=payload.tagline,
        description=payload.description,
        category=payload.category,
        tags=payload.tags,
        price_type=payload.price_type,
        price_amount=payload.price_amount,
        agent_config=payload.agent_config,
        required_tools=payload.required_tools,
        status="draft",
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing)

    return ListingResponse(
        id=str(listing.id),
        publisher_id=str(listing.publisher_id),
        name=listing.name,
        slug=listing.slug,
        tagline=listing.tagline,
        description=listing.description,
        category=listing.category,
        tags=listing.tags,
        price_type=listing.price_type,
        price_amount=listing.price_amount,
        downloads=listing.downloads,
        rating_average=listing.rating_average,
        rating_count=listing.rating_count,
        status=listing.status,
        is_featured=listing.is_featured,
        is_verified=listing.is_verified,
    )


@router.get("/listings", response_model=List[ListingResponse])
async def list_listings(
    category: Optional[str] = None,
    item_type: Optional[str] = None,
    search: Optional[str] = None,
    price_type: Optional[str] = None,
    sort_by: str = "downloads",  # downloads, rating, newest, price
    limit: int = Query(20, le=100),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List published agent listings."""
    stmt = select(AgentListing).where(AgentListing.status == "published")

    # Support both category and item_type params (frontend sends item_type)
    cat = category or item_type
    if cat:
        stmt = stmt.where(AgentListing.category == cat)
    
    if price_type:
        stmt = stmt.where(AgentListing.price_type == price_type)

    if search:
        search_filter = or_(
            AgentListing.name.ilike(f"%{search}%"),
            AgentListing.description.ilike(f"%{search}%"),
            AgentListing.tagline.ilike(f"%{search}%"),
        )
        stmt = stmt.where(search_filter)

    # Sorting
    if sort_by == "downloads":
        stmt = stmt.order_by(AgentListing.downloads.desc())
    elif sort_by == "rating":
        stmt = stmt.order_by(AgentListing.rating_average.desc())
    elif sort_by == "newest":
        stmt = stmt.order_by(AgentListing.published_at.desc())
    elif sort_by == "price":
        stmt = stmt.order_by(AgentListing.price_amount.asc())

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    listings = result.scalars().all()

    return [
        ListingResponse(
            id=str(l.id),
            publisher_id=str(l.publisher_id),
            name=l.name,
            slug=l.slug,
            tagline=l.tagline,
            description=l.description,
            category=l.category,
            tags=l.tags,
            price_type=l.price_type,
            price_amount=l.price_amount,
            downloads=l.downloads,
            rating_average=l.rating_average,
            rating_count=l.rating_count,
            status=l.status,
            is_featured=l.is_featured,
            is_verified=l.is_verified,
        )
        for l in listings
    ]


@router.get("/listings/featured", response_model=List[ListingResponse])
async def get_featured_listings(
    limit: int = Query(10, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Get featured agent listings."""
    stmt = (
        select(AgentListing)
        .where(AgentListing.status == "published")
        .where(AgentListing.is_featured == True)
        .order_by(AgentListing.downloads.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    listings = result.scalars().all()

    return [
        ListingResponse(
            id=str(l.id),
            publisher_id=str(l.publisher_id),
            name=l.name,
            slug=l.slug,
            tagline=l.tagline,
            description=l.description,
            category=l.category,
            tags=l.tags,
            price_type=l.price_type,
            price_amount=l.price_amount,
            downloads=l.downloads,
            rating_average=l.rating_average,
            rating_count=l.rating_count,
            status=l.status,
            is_featured=l.is_featured,
            is_verified=l.is_verified,
        )
        for l in listings
    ]


@router.get("/listings/{listing_id}", response_model=ListingResponse)
async def get_listing(
    listing_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a specific listing by ID or slug."""
    # Try UUID first
    try:
        uuid.UUID(listing_id)
        stmt = select(AgentListing).where(AgentListing.id == listing_id)
    except ValueError:
        # Assume it's a slug
        stmt = select(AgentListing).where(AgentListing.slug == listing_id)

    result = await session.execute(stmt)
    listing = result.scalar_one_or_none()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    return ListingResponse(
        id=str(listing.id),
        publisher_id=str(listing.publisher_id),
        name=listing.name,
        slug=listing.slug,
        tagline=listing.tagline,
        description=listing.description,
        category=listing.category,
        tags=listing.tags,
        price_type=listing.price_type,
        price_amount=listing.price_amount,
        downloads=listing.downloads,
        rating_average=listing.rating_average,
        rating_count=listing.rating_count,
        status=listing.status,
        is_featured=listing.is_featured,
        is_verified=listing.is_verified,
    )


@router.put("/listings/{listing_id}", response_model=ListingResponse)
async def update_listing(
    listing_id: str,
    payload: UpdateListingRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Update a listing (publisher only)."""
    user_id = request.headers.get("x-user-id")
    
    result = await session.execute(
        select(AgentListing).where(AgentListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if str(listing.publisher_id) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update fields
    if payload.name is not None:
        listing.name = payload.name
    if payload.tagline is not None:
        listing.tagline = payload.tagline
    if payload.description is not None:
        listing.description = payload.description
    if payload.category is not None:
        listing.category = payload.category
    if payload.tags is not None:
        listing.tags = payload.tags
    if payload.price_type is not None:
        listing.price_type = payload.price_type
    if payload.price_amount is not None:
        listing.price_amount = payload.price_amount
    if payload.agent_config is not None:
        listing.agent_config = payload.agent_config

    await session.commit()
    await session.refresh(listing)

    return ListingResponse(
        id=str(listing.id),
        publisher_id=str(listing.publisher_id),
        name=listing.name,
        slug=listing.slug,
        tagline=listing.tagline,
        description=listing.description,
        category=listing.category,
        tags=listing.tags,
        price_type=listing.price_type,
        price_amount=listing.price_amount,
        downloads=listing.downloads,
        rating_average=listing.rating_average,
        rating_count=listing.rating_count,
        status=listing.status,
        is_featured=listing.is_featured,
        is_verified=listing.is_verified,
    )


@router.post("/listings/{listing_id}/publish")
async def publish_listing(
    listing_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Publish a draft listing."""
    user_id = request.headers.get("x-user-id")
    
    result = await session.execute(
        select(AgentListing).where(AgentListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if str(listing.publisher_id) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if listing.status not in ["draft", "pending_review"]:
        raise HTTPException(status_code=400, detail="Listing cannot be published")

    listing.status = "published"
    listing.published_at = datetime.utcnow()
    await session.commit()

    return {"status": "published", "listing_id": str(listing.id)}


# ============== Purchase Endpoints ==============

@router.post("/listings/{listing_id}/purchase")
async def purchase_listing(
    listing_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Purchase/acquire an agent."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await session.execute(
        select(AgentListing).where(AgentListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if listing.status != "published":
        raise HTTPException(status_code=400, detail="Listing not available")

    # Check if already purchased
    existing = await session.execute(
        select(AgentPurchase)
        .where(AgentPurchase.listing_id == listing_id)
        .where(AgentPurchase.buyer_id == user_id)
        .where(AgentPurchase.status == "completed")
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already purchased")

    # For free agents, complete immediately
    if listing.price_type == "free" or listing.price_amount == 0:
        purchase = AgentPurchase(
            listing_id=listing_id,
            buyer_id=user_id,
            price_paid=0,
            status="completed",
        )
        session.add(purchase)
        
        # Increment download count
        listing.downloads += 1
        await session.commit()

        # Record purchase on internal blockchain
        try:
            async with httpx.AsyncClient(timeout=3.0) as bc_client:
                await bc_client.post(
                    f"{BLOCKCHAIN_SERVICE_URL}/blockchain/transactions",
                    json={
                        "tx_type": "marketplace_purchase",
                        "payload": {
                            "listing_id": listing_id,
                            "listing_name": listing.name,
                            "buyer_id": user_id,
                            "publisher_id": str(listing.publisher_id) if listing.publisher_id else None,
                            "price_paid": 0,
                            "price_type": "free",
                        },
                    },
                )
        except Exception as bc_err:
            logger.debug("Blockchain tx for free purchase skipped: %s", bc_err)

        return {
            "status": "completed",
            "purchase_id": str(purchase.id),
            "agent_config": listing.agent_config,
        }

    # For paid agents, create Stripe checkout session
    from .payments import get_marketplace_stripe
    stripe_mp = get_marketplace_stripe()

    # Get publisher's Stripe account
    pub_result = await session.execute(
        select(PublisherProfile).where(PublisherProfile.user_id == listing.publisher_id)
    )
    publisher = pub_result.scalar_one_or_none()
    stripe_account = publisher.stripe_account_id if publisher else None

    if not stripe_account:
        # No Stripe account — use platform credits instead
        purchase = AgentPurchase(
            listing_id=listing_id,
            buyer_id=user_id,
            price_paid=listing.price_amount,
            status="completed",
        )
        session.add(purchase)
        listing.downloads += 1
        await session.commit()

        # Credit creator wallet via agent_engine_service
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"http://agent_engine_service:8000/api/v1/wallets/{listing.publisher_id}/credit",
                    params={
                        "amount": float(listing.price_amount * 0.85),
                        "description": f"Marketplace sale: {listing.name}",
                    },
                    headers={"x-user-id": "system", "x-user-role": "system"},
                )
        except Exception as e:
            logger.warning(f"Failed to credit creator wallet: {e}")

        # Record purchase on internal blockchain
        try:
            async with httpx.AsyncClient(timeout=3.0) as bc_client:
                await bc_client.post(
                    f"{BLOCKCHAIN_SERVICE_URL}/blockchain/transactions",
                    json={
                        "tx_type": "marketplace_purchase",
                        "payload": {
                            "listing_id": listing_id,
                            "listing_name": listing.name,
                            "buyer_id": user_id,
                            "publisher_id": str(listing.publisher_id) if listing.publisher_id else None,
                            "price_paid": float(listing.price_amount),
                            "price_type": "paid",
                        },
                    },
                )
        except Exception as bc_err:
            logger.debug("Blockchain tx for paid purchase skipped: %s", bc_err)

        # Award RGT tokens to publisher as marketplace reward
        if listing.publisher_id:
            try:
                async with httpx.AsyncClient(timeout=5.0) as rgt_client:
                    rgt_reward = max(1.0, float(listing.price_amount) * 10)
                    await rgt_client.post(
                        f"{CRYPTO_SERVICE_URL}/crypto/wallet/reward",
                        json={
                            "user_id": str(listing.publisher_id),
                            "amount": rgt_reward,
                            "reason": f"Marketplace sale: {listing.name}",
                            "source": "marketplace",
                        },
                        headers={"x-user-id": "system", "x-user-role": "system"},
                    )
                    logger.info("Awarded %.1f RGT to publisher %s", rgt_reward, listing.publisher_id)
            except Exception as rgt_err:
                logger.debug("RGT reward skipped: %s", rgt_err)

        return {
            "status": "completed",
            "purchase_id": str(purchase.id),
            "agent_config": listing.agent_config,
        }

    # Stripe checkout flow
    try:
        base_url = settings.FRONTEND_URL if hasattr(settings, "FRONTEND_URL") else "https://dev-swat.com"
        product_id = await stripe_mp.create_product(
            listing_id=listing_id,
            name=listing.name,
            description=listing.description,
        )
        price_id = await stripe_mp.create_price(
            product_id=product_id,
            amount=int(listing.price_amount * 100),
            currency=listing.price_currency or "usd",
        )
        checkout = await stripe_mp.create_checkout_session(
            listing_id=listing_id,
            price_id=price_id,
            buyer_id=user_id,
            publisher_account_id=stripe_account,
            success_url=f"{base_url}/marketplace/purchase-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/marketplace/{listing_id}",
        )
        return {
            "status": "payment_required",
            "price": listing.price_amount,
            "currency": listing.price_currency,
            "checkout_url": checkout["url"],
            "checkout_session_id": checkout["session_id"],
        }
    except Exception as e:
        logger.warning(f"Stripe checkout failed, falling back to credit purchase: {e}")
        return {
            "status": "payment_required",
            "price": listing.price_amount,
            "currency": listing.price_currency,
            "error": "Payment processing unavailable",
        }


@router.get("/purchases")
async def list_purchases(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """List user's purchased agents."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await session.execute(
        select(AgentPurchase)
        .where(AgentPurchase.buyer_id == user_id)
        .order_by(AgentPurchase.purchased_at.desc())
    )
    purchases = result.scalars().all()

    return {
        "purchases": [
            {
                "id": str(p.id),
                "listing_id": str(p.listing_id),
                "price_paid": p.price_paid,
                "status": p.status,
                "purchased_at": p.purchased_at.isoformat(),
            }
            for p in purchases
        ]
    }


# ============== Stripe Webhook (P3.3 Agent Economy) ==============

@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Handle Stripe webhook events for marketplace purchases."""
    import httpx
    from .payments import get_marketplace_stripe

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        stripe_mp = get_marketplace_stripe()
        event = stripe_mp.verify_webhook(payload, signature)
    except Exception as e:
        logger.error(f"Stripe webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        checkout_data = event["data"]
        listing_id = checkout_data.get("metadata", {}).get("listing_id")
        buyer_id = checkout_data.get("metadata", {}).get("buyer_id")
        amount_total = checkout_data.get("amount_total", 0)

        if listing_id and buyer_id:
            # Record purchase
            purchase = AgentPurchase(
                listing_id=listing_id,
                buyer_id=buyer_id,
                price_paid=amount_total / 100,  # cents → dollars
                status="completed",
                stripe_payment_id=checkout_data.get("payment_intent"),
            )
            session.add(purchase)

            # Increment download count
            listing_result = await session.execute(
                select(AgentListing).where(AgentListing.id == listing_id)
            )
            listing = listing_result.scalar_one_or_none()
            if listing:
                listing.downloads += 1

                # Credit creator wallet (85% after 15% platform fee)
                creator_amount = float(amount_total / 100) * 0.85
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            f"http://agent_engine_service:8000/api/v1/wallets/{listing.publisher_id}/credit",
                            params={
                                "amount": creator_amount,
                                "description": f"Marketplace sale: {listing.name} (buyer: {buyer_id})",
                            },
                            headers={"x-user-id": "system", "x-user-role": "system"},
                        )
                    logger.info(f"Credited {creator_amount} to creator {listing.publisher_id}")
                except Exception as e:
                    logger.warning(f"Failed to credit creator wallet: {e}")

            await session.commit()
            logger.info(f"Purchase completed: {listing_id} by {buyer_id}")

    elif event["type"] == "charge.refunded":
        # Handle refund — debit creator wallet
        logger.info(f"Refund processed: {event['data'].get('id')}")

    return {"status": "ok"}


# ============== Review Endpoints ==============

@router.post("/listings/{listing_id}/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    listing_id: str,
    payload: CreateReviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a review for an agent."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if listing exists
    result = await session.execute(
        select(AgentListing).where(AgentListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Check if already reviewed
    existing = await session.execute(
        select(AgentReview)
        .where(AgentReview.listing_id == listing_id)
        .where(AgentReview.reviewer_id == user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already reviewed")

    # Check if verified purchase
    purchase = await session.execute(
        select(AgentPurchase)
        .where(AgentPurchase.listing_id == listing_id)
        .where(AgentPurchase.buyer_id == user_id)
        .where(AgentPurchase.status == "completed")
    )
    is_verified = purchase.scalar_one_or_none() is not None

    review = AgentReview(
        listing_id=listing_id,
        reviewer_id=user_id,
        rating=payload.rating,
        title=payload.title,
        content=payload.content,
        is_verified_purchase=is_verified,
    )
    session.add(review)

    # Update listing rating
    result = await session.execute(
        select(func.avg(AgentReview.rating), func.count(AgentReview.id))
        .where(AgentReview.listing_id == listing_id)
    )
    avg_rating, count = result.one()
    listing.rating_average = float(avg_rating or 0)
    listing.rating_count = count + 1

    await session.commit()
    await session.refresh(review)

    return ReviewResponse(
        id=str(review.id),
        listing_id=str(review.listing_id),
        reviewer_id=str(review.reviewer_id),
        rating=review.rating,
        title=review.title,
        content=review.content,
        is_verified_purchase=review.is_verified_purchase,
        helpful_count=review.helpful_count,
        created_at=review.created_at.isoformat(),
    )


@router.get("/listings/{listing_id}/reviews", response_model=List[ReviewResponse])
async def list_reviews(
    listing_id: str,
    limit: int = Query(20, le=100),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List reviews for an agent."""
    result = await session.execute(
        select(AgentReview)
        .where(AgentReview.listing_id == listing_id)
        .where(AgentReview.status == "published")
        .order_by(AgentReview.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    reviews = result.scalars().all()

    return [
        ReviewResponse(
            id=str(r.id),
            listing_id=str(r.listing_id),
            reviewer_id=str(r.reviewer_id),
            rating=r.rating,
            title=r.title,
            content=r.content,
            is_verified_purchase=r.is_verified_purchase,
            helpful_count=r.helpful_count,
            created_at=r.created_at.isoformat(),
        )
        for r in reviews
    ]


# ============== Category Endpoints ==============

@router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(
    session: AsyncSession = Depends(get_session),
):
    """List marketplace categories."""
    result = await session.execute(
        select(MarketplaceCategory)
        .where(MarketplaceCategory.is_active == True)
        .order_by(MarketplaceCategory.sort_order)
    )
    categories = result.scalars().all()

    return [
        CategoryResponse(
            id=str(c.id),
            name=c.name,
            slug=c.slug,
            description=c.description,
            icon=c.icon,
            agent_count=c.agent_count,
        )
        for c in categories
    ]


# ============== Publisher Endpoints ==============

@router.post("/publisher/profile")
async def create_publisher_profile(
    payload: PublisherProfileRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create or update publisher profile."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await session.execute(
        select(PublisherProfile).where(PublisherProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if profile:
        profile.display_name = payload.display_name
        profile.bio = payload.bio
        profile.website_url = payload.website_url
    else:
        profile = PublisherProfile(
            user_id=user_id,
            display_name=payload.display_name,
            bio=payload.bio,
            website_url=payload.website_url,
        )
        session.add(profile)

    await session.commit()
    await session.refresh(profile)

    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "display_name": profile.display_name,
        "bio": profile.bio,
        "website_url": profile.website_url,
        "is_verified": profile.is_verified,
        "total_earnings": profile.total_earnings,
        "total_sales": profile.total_sales,
    }


@router.get("/publisher/{user_id}")
async def get_publisher_profile(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a publisher's public profile."""
    result = await session.execute(
        select(PublisherProfile).where(PublisherProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(status_code=404, detail="Publisher not found")

    # Get publisher's listings
    listings_result = await session.execute(
        select(AgentListing)
        .where(AgentListing.publisher_id == user_id)
        .where(AgentListing.status == "published")
        .order_by(AgentListing.downloads.desc())
        .limit(10)
    )
    listings = listings_result.scalars().all()

    return {
        "profile": {
            "id": str(profile.id),
            "display_name": profile.display_name,
            "bio": profile.bio,
            "website_url": profile.website_url,
            "is_verified": profile.is_verified,
            "total_sales": profile.total_sales,
        },
        "listings": [
            {
                "id": str(l.id),
                "name": l.name,
                "slug": l.slug,
                "downloads": l.downloads,
                "rating_average": l.rating_average,
            }
            for l in listings
        ],
    }


# ============== Trends Endpoint ==============

@router.get("/trends")
async def get_market_trends(
    session: AsyncSession = Depends(get_session),
):
    """Get marketplace trends and analytics."""
    # Trending items (top downloads in last period)
    trending_result = await session.execute(
        select(AgentListing)
        .where(AgentListing.status == "published")
        .order_by(AgentListing.downloads.desc())
        .limit(10)
    )
    trending = trending_result.scalars().all()

    # Top sellers
    sellers_result = await session.execute(
        select(PublisherProfile)
        .order_by(PublisherProfile.total_sales.desc())
        .limit(10)
    )
    sellers = sellers_result.scalars().all()

    # Category stats
    cat_result = await session.execute(
        select(
            AgentListing.category,
            func.count(AgentListing.id).label("item_count"),
            func.sum(AgentListing.downloads).label("total_downloads"),
            func.avg(AgentListing.price_amount).label("average_price"),
        )
        .where(AgentListing.status == "published")
        .where(AgentListing.category.isnot(None))
        .group_by(AgentListing.category)
    )
    categories = cat_result.all()

    # Total transactions (purchases)
    tx_count = await session.execute(select(func.count(AgentPurchase.id)))
    total_tx = tx_count.scalar() or 0

    tx_volume = await session.execute(
        select(func.sum(AgentPurchase.price_paid))
    )
    total_vol = tx_volume.scalar() or 0

    return {
        "trending_items": [
            {
                "id": str(l.id),
                "publisher_id": str(l.publisher_id),
                "name": l.name,
                "slug": l.slug,
                "tagline": l.tagline,
                "description": l.description,
                "category": l.category,
                "tags": l.tags,
                "price_type": l.price_type,
                "price_amount": l.price_amount,
                "downloads": l.downloads,
                "rating_average": l.rating_average,
                "rating_count": l.rating_count,
                "status": l.status,
                "is_featured": l.is_featured,
                "is_verified": l.is_verified,
            }
            for l in trending
        ],
        "top_sellers": [
            {
                "seller_id": str(s.user_id),
                "seller_name": s.display_name,
                "avatar_url": s.avatar_url,
                "total_sales": s.total_sales,
                "total_revenue": s.total_earnings,
                "average_rating": 0,
                "total_reviews": 0,
                "items_count": 0,
                "verified": s.is_verified,
                "joined_at": s.created_at.isoformat() if s.created_at else "",
            }
            for s in sellers
        ],
        "category_stats": [
            {
                "category": c.category or "uncategorized",
                "item_count": c.item_count or 0,
                "total_downloads": c.total_downloads or 0,
                "average_price": float(c.average_price or 0),
                "growth_percentage": 0.0,
            }
            for c in categories
        ],
        "price_trends": [],
        "total_transactions_24h": total_tx,
        "total_volume_24h": float(total_vol),
    }


# ============== Dashboard Endpoint ==============

@router.get("/dashboard")
async def get_user_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Get user's marketplace dashboard."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Owned items (purchased)
    purchases_result = await session.execute(
        select(AgentPurchase)
        .where(AgentPurchase.buyer_id == user_id)
        .where(AgentPurchase.status == "completed")
    )
    purchases = purchases_result.scalars().all()
    purchased_ids = [str(p.listing_id) for p in purchases]

    owned_items = []
    if purchased_ids:
        items_result = await session.execute(
            select(AgentListing).where(AgentListing.id.in_(purchased_ids))
        )
        owned_listings = items_result.scalars().all()
        owned_items = [
            {
                "id": str(l.id),
                "name": l.name,
                "description": l.description,
                "item_type": l.category or "agent",
                "category": l.category,
                "tags": l.tags or [],
                "price": l.price_amount,
                "is_free": l.price_type == "free" or l.price_amount == 0,
                "currency": "USD",
                "publisher_org_id": str(l.publisher_id),
                "status": l.status,
                "version": "1.0.0",
                "download_count": l.downloads,
                "purchase_count": l.downloads,
                "average_rating": l.rating_average,
                "review_count": l.rating_count,
                "created_at": l.created_at.isoformat() if l.created_at else "",
                "updated_at": (l.updated_at or l.created_at or datetime.utcnow()).isoformat(),
            }
            for l in owned_listings
        ]

    # Sales history (items the user published that were purchased)
    user_listings_result = await session.execute(
        select(AgentListing.id).where(AgentListing.publisher_id == user_id)
    )
    user_listing_ids = [str(r[0]) for r in user_listings_result.all()]

    sales_history = []
    total_earnings = 0.0
    if user_listing_ids:
        sales_result = await session.execute(
            select(AgentPurchase)
            .where(AgentPurchase.listing_id.in_(user_listing_ids))
            .where(AgentPurchase.status == "completed")
            .order_by(AgentPurchase.purchased_at.desc())
            .limit(50)
        )
        sales = sales_result.scalars().all()
        total_earnings = sum(float(s.price_paid or 0) for s in sales)
        for s in sales:
            sales_history.append({
                "sale_id": str(s.id),
                "item_id": str(s.listing_id),
                "item_name": "",
                "buyer_id": str(s.buyer_id),
                "buyer_name": "User",
                "price": float(s.price_paid or 0),
                "sale_type": "purchase",
                "timestamp": s.purchased_at.isoformat() if s.purchased_at else "",
            })

    total_spent = sum(float(p.price_paid or 0) for p in purchases)

    return {
        "owned_items": owned_items,
        "rented_items": [],
        "sales_history": sales_history,
        "purchase_history": [
            {
                "purchase_id": str(p.id),
                "item_id": str(p.listing_id),
                "item_name": "",
                "item_type": "agent",
                "price": float(p.price_paid or 0),
                "currency": "USD",
                "purchase_date": p.purchased_at.isoformat() if p.purchased_at else "",
                "status": p.status,
            }
            for p in purchases
        ],
        "total_earnings": total_earnings,
        "total_spent": total_spent,
        "active_listings": [],
        "pending_transactions": [],
    }


# ============== Execution Ledger Endpoint ==============

@router.get("/items/{item_id}/executions")
async def get_execution_ledger(
    item_id: str,
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get execution ledger for a marketplace item."""
    # Query usage stats as a proxy for execution records
    result = await session.execute(
        select(AgentUsageStats)
        .where(AgentUsageStats.listing_id == item_id)
        .order_by(AgentUsageStats.last_used_at.desc().nullslast())
        .limit(limit)
    )
    stats = result.scalars().all()

    return [
        {
            "entry_id": str(s.id),
            "item_id": str(s.listing_id),
            "item_name": "",
            "user_id": str(s.user_id),
            "execution_type": "agent_run",
            "input_hash": "",
            "output_hash": "",
            "gas_used": None,
            "execution_time_ms": s.total_duration_ms or 0,
            "status": "success",
            "timestamp": (s.last_used_at or s.created_at or datetime.utcnow()).isoformat(),
            "tx_hash": None,
        }
        for s in stats
    ]


# ============== NFT Listing Endpoint ==============

@router.post("/nft/list")
async def list_nft(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """List an item as NFT on the blockchain marketplace."""
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    body = await request.json()
    item_id = body.get("item_id")
    listing_type = body.get("listing_type", "sale")
    price = body.get("price", 0)

    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")

    # Verify item exists
    result = await session.execute(
        select(AgentListing).where(AgentListing.id == item_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Record NFT listing on internal blockchain
    nft_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=5.0) as bc_client:
            await bc_client.post(
                f"{BLOCKCHAIN_SERVICE_URL}/blockchain/transactions",
                json={
                    "tx_type": "nft_listing",
                    "payload": {
                        "nft_id": nft_id,
                        "item_id": item_id,
                        "item_name": listing.name,
                        "owner_id": user_id,
                        "listing_type": listing_type,
                        "price": price,
                    },
                },
            )
    except Exception as e:
        logger.debug("Blockchain NFT listing tx skipped: %s", e)

    return {
        "nft_id": nft_id,
        "item_id": item_id,
        "token_id": nft_id[:16],
        "contract_address": "0x" + nft_id.replace("-", "")[:40],
        "chain": "polygon",
        "owner_address": user_id,
        "price": price,
        "currency": "USD",
        "listing_type": listing_type,
        "rent_price_per_day": body.get("rent_price_per_day"),
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
    }


# ============== Stats Endpoints ==============

@router.get("/stats")
async def get_marketplace_stats(
    session: AsyncSession = Depends(get_session),
):
    """Get marketplace statistics."""
    # Total listings
    listings_count = await session.execute(
        select(func.count(AgentListing.id)).where(AgentListing.status == "published")
    )
    total_listings = listings_count.scalar()

    # Total downloads
    downloads_sum = await session.execute(
        select(func.sum(AgentListing.downloads))
    )
    total_downloads = downloads_sum.scalar() or 0

    # Total publishers
    publishers_count = await session.execute(
        select(func.count(PublisherProfile.id))
    )
    total_publishers = publishers_count.scalar()

    return {
        "total_listings": total_listings,
        "total_downloads": total_downloads,
        "total_publishers": total_publishers,
    }


# ============== Health Endpoint ==============

@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"service": "marketplace", "status": "ok"}
