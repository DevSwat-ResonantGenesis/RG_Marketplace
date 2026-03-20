"""
MARKETPLACE REVIEWS SERVICE
===========================

Review and rating system for marketplace agents.
Supports: Verified purchases, helpful votes, moderation.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from uuid import UUID, uuid4
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentReview, AgentPurchase, AgentListing

logger = logging.getLogger(__name__)


class ReviewStatus(Enum):
    PUBLISHED = "published"
    HIDDEN = "hidden"
    FLAGGED = "flagged"
    PENDING = "pending"


@dataclass
class ReviewStats:
    """Aggregated review statistics for a listing."""
    average_rating: float
    total_reviews: int
    rating_distribution: Dict[int, int]  # {5: 10, 4: 5, 3: 2, ...}
    verified_purchase_count: int


class ReviewService:
    """Service for managing agent reviews."""
    
    MIN_RATING = 1
    MAX_RATING = 5
    MIN_CONTENT_LENGTH = 10
    MAX_CONTENT_LENGTH = 5000
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    # ============== CREATE REVIEW ==============
    
    async def create_review(
        self,
        listing_id: UUID,
        reviewer_id: UUID,
        rating: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new review for an agent listing.
        
        Validates:
        - Rating within bounds
        - Content length
        - User hasn't already reviewed
        - Checks if verified purchase
        """
        # Validate rating
        if not self.MIN_RATING <= rating <= self.MAX_RATING:
            raise ValueError(f"Rating must be between {self.MIN_RATING} and {self.MAX_RATING}")
        
        # Validate content length
        if content and len(content) > self.MAX_CONTENT_LENGTH:
            raise ValueError(f"Content exceeds maximum length of {self.MAX_CONTENT_LENGTH}")
        
        # Check for existing review
        existing = await self.db.execute(
            select(AgentReview).where(
                and_(
                    AgentReview.listing_id == listing_id,
                    AgentReview.reviewer_id == reviewer_id,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("You have already reviewed this agent")
        
        # Check if verified purchase
        purchase = await self.db.execute(
            select(AgentPurchase).where(
                and_(
                    AgentPurchase.listing_id == listing_id,
                    AgentPurchase.buyer_id == reviewer_id,
                    AgentPurchase.status == "completed",
                )
            )
        )
        is_verified = purchase.scalar_one_or_none() is not None
        
        # Create review
        review = AgentReview(
            id=uuid4(),
            listing_id=listing_id,
            reviewer_id=reviewer_id,
            rating=rating,
            title=title,
            content=content,
            is_verified_purchase=is_verified,
            status=ReviewStatus.PUBLISHED.value,
        )
        
        self.db.add(review)
        await self.db.commit()
        await self.db.refresh(review)
        
        # Update listing stats
        await self._update_listing_stats(listing_id)
        
        return {
            "id": str(review.id),
            "listing_id": str(review.listing_id),
            "rating": review.rating,
            "title": review.title,
            "content": review.content,
            "is_verified_purchase": review.is_verified_purchase,
            "created_at": review.created_at.isoformat(),
        }
    
    # ============== UPDATE REVIEW ==============
    
    async def update_review(
        self,
        review_id: UUID,
        reviewer_id: UUID,
        rating: Optional[int] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing review."""
        review = await self.db.get(AgentReview, review_id)
        if not review:
            raise ValueError("Review not found")
        
        if review.reviewer_id != reviewer_id:
            raise ValueError("You can only edit your own reviews")
        
        if rating is not None:
            if not self.MIN_RATING <= rating <= self.MAX_RATING:
                raise ValueError(f"Rating must be between {self.MIN_RATING} and {self.MAX_RATING}")
            review.rating = rating
        
        if title is not None:
            review.title = title
        
        if content is not None:
            if len(content) > self.MAX_CONTENT_LENGTH:
                raise ValueError(f"Content exceeds maximum length")
            review.content = content
        
        await self.db.commit()
        await self.db.refresh(review)
        
        # Update listing stats
        await self._update_listing_stats(review.listing_id)
        
        return {
            "id": str(review.id),
            "rating": review.rating,
            "title": review.title,
            "content": review.content,
            "updated_at": review.updated_at.isoformat() if review.updated_at else None,
        }
    
    # ============== DELETE REVIEW ==============
    
    async def delete_review(
        self,
        review_id: UUID,
        reviewer_id: UUID,
    ) -> bool:
        """Delete a review (soft delete by setting status to hidden)."""
        review = await self.db.get(AgentReview, review_id)
        if not review:
            raise ValueError("Review not found")
        
        if review.reviewer_id != reviewer_id:
            raise ValueError("You can only delete your own reviews")
        
        review.status = ReviewStatus.HIDDEN.value
        await self.db.commit()
        
        # Update listing stats
        await self._update_listing_stats(review.listing_id)
        
        return True
    
    # ============== GET REVIEWS ==============
    
    async def get_reviews(
        self,
        listing_id: UUID,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "recent",  # recent, helpful, rating_high, rating_low
        verified_only: bool = False,
    ) -> Dict[str, Any]:
        """Get reviews for a listing with pagination and sorting."""
        query = select(AgentReview).where(
            and_(
                AgentReview.listing_id == listing_id,
                AgentReview.status == ReviewStatus.PUBLISHED.value,
            )
        )
        
        if verified_only:
            query = query.where(AgentReview.is_verified_purchase == True)
        
        # Sorting
        if sort_by == "helpful":
            query = query.order_by(AgentReview.helpful_count.desc())
        elif sort_by == "rating_high":
            query = query.order_by(AgentReview.rating.desc())
        elif sort_by == "rating_low":
            query = query.order_by(AgentReview.rating.asc())
        else:  # recent
            query = query.order_by(AgentReview.created_at.desc())
        
        # Count total
        count_query = select(func.count()).select_from(AgentReview).where(
            and_(
                AgentReview.listing_id == listing_id,
                AgentReview.status == ReviewStatus.PUBLISHED.value,
            )
        )
        if verified_only:
            count_query = count_query.where(AgentReview.is_verified_purchase == True)
        
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()
        
        # Fetch reviews
        query = query.offset(offset).limit(limit)
        result = await self.db.execute(query)
        reviews = result.scalars().all()
        
        return {
            "reviews": [
                {
                    "id": str(r.id),
                    "reviewer_id": str(r.reviewer_id),
                    "rating": r.rating,
                    "title": r.title,
                    "content": r.content,
                    "is_verified_purchase": r.is_verified_purchase,
                    "helpful_count": r.helpful_count,
                    "created_at": r.created_at.isoformat(),
                }
                for r in reviews
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    
    async def get_user_review(
        self,
        listing_id: UUID,
        reviewer_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Get a specific user's review for a listing."""
        result = await self.db.execute(
            select(AgentReview).where(
                and_(
                    AgentReview.listing_id == listing_id,
                    AgentReview.reviewer_id == reviewer_id,
                )
            )
        )
        review = result.scalar_one_or_none()
        
        if not review:
            return None
        
        return {
            "id": str(review.id),
            "rating": review.rating,
            "title": review.title,
            "content": review.content,
            "is_verified_purchase": review.is_verified_purchase,
            "helpful_count": review.helpful_count,
            "status": review.status,
            "created_at": review.created_at.isoformat(),
        }
    
    # ============== HELPFUL VOTES ==============
    
    async def mark_helpful(
        self,
        review_id: UUID,
        user_id: UUID,
    ) -> int:
        """Mark a review as helpful. Returns new helpful count."""
        # In production, track who voted to prevent duplicates
        review = await self.db.get(AgentReview, review_id)
        if not review:
            raise ValueError("Review not found")
        
        review.helpful_count += 1
        await self.db.commit()
        
        return review.helpful_count
    
    # ============== STATS ==============
    
    async def get_review_stats(self, listing_id: UUID) -> ReviewStats:
        """Get aggregated review statistics for a listing."""
        # Get all published reviews
        result = await self.db.execute(
            select(AgentReview).where(
                and_(
                    AgentReview.listing_id == listing_id,
                    AgentReview.status == ReviewStatus.PUBLISHED.value,
                )
            )
        )
        reviews = result.scalars().all()
        
        if not reviews:
            return ReviewStats(
                average_rating=0.0,
                total_reviews=0,
                rating_distribution={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                verified_purchase_count=0,
            )
        
        # Calculate stats
        total = len(reviews)
        rating_sum = sum(r.rating for r in reviews)
        verified_count = sum(1 for r in reviews if r.is_verified_purchase)
        
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in reviews:
            distribution[r.rating] += 1
        
        return ReviewStats(
            average_rating=round(rating_sum / total, 2),
            total_reviews=total,
            rating_distribution=distribution,
            verified_purchase_count=verified_count,
        )
    
    # ============== MODERATION ==============
    
    async def flag_review(
        self,
        review_id: UUID,
        reason: str,
        reporter_id: UUID,
    ) -> bool:
        """Flag a review for moderation."""
        review = await self.db.get(AgentReview, review_id)
        if not review:
            raise ValueError("Review not found")
        
        review.status = ReviewStatus.FLAGGED.value
        await self.db.commit()
        
        # In production, create a moderation queue entry
        logger.info(f"Review {review_id} flagged by {reporter_id}: {reason}")
        
        return True
    
    async def moderate_review(
        self,
        review_id: UUID,
        action: str,  # approve, hide, delete
        moderator_id: UUID,
    ) -> bool:
        """Moderate a flagged review (admin only)."""
        review = await self.db.get(AgentReview, review_id)
        if not review:
            raise ValueError("Review not found")
        
        if action == "approve":
            review.status = ReviewStatus.PUBLISHED.value
        elif action == "hide":
            review.status = ReviewStatus.HIDDEN.value
        elif action == "delete":
            await self.db.delete(review)
        else:
            raise ValueError(f"Invalid moderation action: {action}")
        
        await self.db.commit()
        
        # Update listing stats
        await self._update_listing_stats(review.listing_id)
        
        logger.info(f"Review {review_id} moderated ({action}) by {moderator_id}")
        
        return True
    
    # ============== INTERNAL ==============
    
    async def _update_listing_stats(self, listing_id: UUID):
        """Update listing's rating stats after review changes."""
        stats = await self.get_review_stats(listing_id)
        
        await self.db.execute(
            update(AgentListing).where(
                AgentListing.id == listing_id
            ).values(
                rating_average=stats.average_rating,
                rating_count=stats.total_reviews,
            )
        )
        await self.db.commit()


# ============== FACTORY ==============

def get_review_service(db_session: AsyncSession) -> ReviewService:
    """Create a review service instance."""
    return ReviewService(db_session)
