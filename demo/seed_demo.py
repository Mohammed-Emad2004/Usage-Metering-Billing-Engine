"""
Deterministic demo seed for the FlyRank capstone final presentation.

Creates demo tenants with small, human-readable quota limits:
  - demo_free: Free plan  (api_call_limit=10, ai_token_limit=100)
  - demo_pro:  Pro plan   (api_call_limit=1000, ai_token_limit=10000)

Usage:
    python -m demo.seed_demo          # from project root
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.database import SessionLocal
from app.db.models.plan import Plan
from app.db.models.tenant import Tenant
from app.db.models.subscription import Subscription


def seed_demo():
    db = SessionLocal()
    try:
        # --- Plans (small limits for demo) ---
        free_plan = db.query(Plan).filter(Plan.id == "free").first()
        if not free_plan:
            free_plan = Plan(
                id="free", name="Free Plan",
                api_call_limit=10, ai_token_limit=100,
            )
            db.add(free_plan)
            print("  Created free plan (api=10, ai=100)")

        pro_plan = db.query(Plan).filter(Plan.id == "pro").first()
        if not pro_plan:
            pro_plan = Plan(
                id="pro", name="Pro Plan",
                api_call_limit=1000, ai_token_limit=10000,
            )
            db.add(pro_plan)
            print("  Created pro plan (api=1000, ai=10000)")

        # --- Tenants ---
        for tenant_id, name, plan_id, sub_status in [
            ("demo_free", "Demo Free Tenant", "free", "active"),
            ("demo_pro",  "Demo Pro Tenant",  "pro",  "active"),
        ]:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant:
                tenant = Tenant(id=tenant_id, name=name)
                db.add(tenant)
                print(f"  Created tenant {tenant_id}")

            sub = db.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()
            if not sub:
                sub = Subscription(
                    id=f"sub_{tenant_id}", tenant_id=tenant_id,
                    plan_id=plan_id, status=sub_status,
                    stripe_customer_id=None, stripe_subscription_id=None,
                )
                db.add(sub)
                print(f"  Created subscription {tenant_id} -> {plan_id} ({sub_status})")

        db.commit()
        print("\nDemo seed complete.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding demo data: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding demo data ...")
    seed_demo()
