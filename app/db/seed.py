import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app.db.database import SessionLocal
from app.db.models.plan import Plan


def seed_plans():
    db = SessionLocal()
    try:
        free_plan = db.query(Plan).filter(Plan.id == "free").first()
        if not free_plan:
            free_plan = Plan(
                id="free",
                name="Free Plan",
                api_call_limit=1000,
                ai_token_limit=100000
            )
            db.add(free_plan)
            print("Created Free Plan.")

        pro_plan = db.query(Plan).filter(Plan.id == "pro").first()
        if not pro_plan:
            pro_plan = Plan(
                id="pro",
                name="Pro Plan",
                api_call_limit=50000,
                ai_token_limit=5000000
            )
            db.add(pro_plan)
            print("Created Pro Plan.")

        db.commit()
        print("Database seeding completed successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed_plans()
