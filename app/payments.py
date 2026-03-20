"""
MARKETPLACE PAYMENT INTEGRATION
===============================

Stripe integration for marketplace purchases and payouts.
Supports: One-time purchases, subscriptions, connected accounts.
"""

import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

# Stripe configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
MARKETPLACE_FEE_PERCENT = float(os.getenv("MARKETPLACE_FEE_PERCENT", "15"))  # 15% platform fee


class StripeMarketplace:
    """Stripe integration for marketplace payments."""
    
    def __init__(self):
        self._stripe = None
    
    @property
    def stripe(self):
        if self._stripe is None:
            try:
                import stripe
                stripe.api_key = STRIPE_SECRET_KEY
                self._stripe = stripe
            except ImportError:
                raise ImportError("stripe not installed. Run: pip install stripe")
        return self._stripe
    
    # ============== CONNECTED ACCOUNTS ==============
    
    async def create_connected_account(
        self,
        user_id: str,
        email: str,
        country: str = "US",
    ) -> Dict[str, Any]:
        """
        Create a Stripe Connect account for a publisher.
        This allows them to receive payouts.
        """
        try:
            account = self.stripe.Account.create(
                type="express",
                country=country,
                email=email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                metadata={
                    "user_id": user_id,
                    "platform": "resonant_genesis",
                },
            )
            
            return {
                "account_id": account.id,
                "details_submitted": account.details_submitted,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled,
            }
            
        except Exception as e:
            logger.error(f"Failed to create connected account: {e}")
            raise
    
    async def create_account_link(
        self,
        account_id: str,
        return_url: str,
        refresh_url: str,
    ) -> str:
        """Create an onboarding link for a connected account."""
        try:
            link = self.stripe.AccountLink.create(
                account=account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
            return link.url
            
        except Exception as e:
            logger.error(f"Failed to create account link: {e}")
            raise
    
    async def get_account_status(self, account_id: str) -> Dict[str, Any]:
        """Get connected account status."""
        try:
            account = self.stripe.Account.retrieve(account_id)
            return {
                "account_id": account.id,
                "details_submitted": account.details_submitted,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled,
                "requirements": account.requirements,
            }
        except Exception as e:
            logger.error(f"Failed to get account status: {e}")
            raise
    
    # ============== PRODUCTS & PRICES ==============
    
    async def create_product(
        self,
        listing_id: str,
        name: str,
        description: str = None,
    ) -> str:
        """Create a Stripe product for an agent listing."""
        try:
            product = self.stripe.Product.create(
                name=name,
                description=description,
                metadata={
                    "listing_id": listing_id,
                    "platform": "resonant_genesis_marketplace",
                },
            )
            return product.id
            
        except Exception as e:
            logger.error(f"Failed to create product: {e}")
            raise
    
    async def create_price(
        self,
        product_id: str,
        amount: int,  # In cents
        currency: str = "usd",
        recurring: bool = False,
        interval: str = "month",
    ) -> str:
        """Create a price for a product."""
        try:
            price_data = {
                "product": product_id,
                "unit_amount": amount,
                "currency": currency.lower(),
            }
            
            if recurring:
                price_data["recurring"] = {"interval": interval}
            
            price = self.stripe.Price.create(**price_data)
            return price.id
            
        except Exception as e:
            logger.error(f"Failed to create price: {e}")
            raise
    
    # ============== ONE-TIME PURCHASES ==============
    
    async def create_checkout_session(
        self,
        listing_id: str,
        price_id: str,
        buyer_id: str,
        publisher_account_id: str,
        success_url: str,
        cancel_url: str,
    ) -> Dict[str, Any]:
        """
        Create a checkout session for purchasing an agent.
        Uses Stripe Connect to split payment with publisher.
        """
        try:
            # Calculate platform fee
            price = self.stripe.Price.retrieve(price_id)
            amount = price.unit_amount
            fee = int(amount * (MARKETPLACE_FEE_PERCENT / 100))
            
            session = self.stripe.checkout.Session.create(
                mode="payment",
                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],
                payment_intent_data={
                    "application_fee_amount": fee,
                    "transfer_data": {
                        "destination": publisher_account_id,
                    },
                    "metadata": {
                        "listing_id": listing_id,
                        "buyer_id": buyer_id,
                    },
                },
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "listing_id": listing_id,
                    "buyer_id": buyer_id,
                    "type": "agent_purchase",
                },
            )
            
            return {
                "session_id": session.id,
                "url": session.url,
            }
            
        except Exception as e:
            logger.error(f"Failed to create checkout session: {e}")
            raise
    
    # ============== SUBSCRIPTIONS ==============
    
    async def create_subscription_checkout(
        self,
        listing_id: str,
        price_id: str,
        buyer_id: str,
        publisher_account_id: str,
        success_url: str,
        cancel_url: str,
    ) -> Dict[str, Any]:
        """Create a subscription checkout for recurring agent access."""
        try:
            session = self.stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],
                subscription_data={
                    "application_fee_percent": MARKETPLACE_FEE_PERCENT,
                    "transfer_data": {
                        "destination": publisher_account_id,
                    },
                    "metadata": {
                        "listing_id": listing_id,
                        "buyer_id": buyer_id,
                    },
                },
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "listing_id": listing_id,
                    "buyer_id": buyer_id,
                    "type": "agent_subscription",
                },
            )
            
            return {
                "session_id": session.id,
                "url": session.url,
            }
            
        except Exception as e:
            logger.error(f"Failed to create subscription checkout: {e}")
            raise
    
    async def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription."""
        try:
            self.stripe.Subscription.delete(subscription_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {e}")
            return False
    
    # ============== REFUNDS ==============
    
    async def refund_purchase(
        self,
        payment_intent_id: str,
        amount: int = None,  # None = full refund
        reason: str = "requested_by_customer",
    ) -> Dict[str, Any]:
        """Process a refund for a purchase."""
        try:
            refund_data = {
                "payment_intent": payment_intent_id,
                "reason": reason,
            }
            if amount:
                refund_data["amount"] = amount
            
            # Reverse the transfer to publisher
            refund_data["reverse_transfer"] = True
            refund_data["refund_application_fee"] = True
            
            refund = self.stripe.Refund.create(**refund_data)
            
            return {
                "refund_id": refund.id,
                "status": refund.status,
                "amount": refund.amount,
            }
            
        except Exception as e:
            logger.error(f"Failed to process refund: {e}")
            raise
    
    # ============== PAYOUTS ==============
    
    async def get_publisher_balance(self, account_id: str) -> Dict[str, Any]:
        """Get publisher's available balance."""
        try:
            balance = self.stripe.Balance.retrieve(
                stripe_account=account_id
            )
            
            available = sum(b.amount for b in balance.available)
            pending = sum(b.amount for b in balance.pending)
            
            return {
                "available": available,
                "pending": pending,
                "currency": balance.available[0].currency if balance.available else "usd",
            }
            
        except Exception as e:
            logger.error(f"Failed to get publisher balance: {e}")
            raise
    
    async def create_payout(
        self,
        account_id: str,
        amount: int,
        currency: str = "usd",
    ) -> Dict[str, Any]:
        """Create a payout to publisher's bank account."""
        try:
            payout = self.stripe.Payout.create(
                amount=amount,
                currency=currency,
                stripe_account=account_id,
            )
            
            return {
                "payout_id": payout.id,
                "status": payout.status,
                "amount": payout.amount,
                "arrival_date": payout.arrival_date,
            }
            
        except Exception as e:
            logger.error(f"Failed to create payout: {e}")
            raise
    
    # ============== WEBHOOKS ==============
    
    def verify_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """Verify and parse a Stripe webhook."""
        try:
            event = self.stripe.Webhook.construct_event(
                payload,
                signature,
                STRIPE_WEBHOOK_SECRET,
            )
            return {
                "type": event.type,
                "data": event.data.object,
            }
        except Exception as e:
            logger.error(f"Webhook verification failed: {e}")
            raise


# Singleton instance
_marketplace_stripe: Optional[StripeMarketplace] = None


def get_marketplace_stripe() -> StripeMarketplace:
    """Get or create marketplace Stripe instance."""
    global _marketplace_stripe
    if _marketplace_stripe is None:
        _marketplace_stripe = StripeMarketplace()
    return _marketplace_stripe
