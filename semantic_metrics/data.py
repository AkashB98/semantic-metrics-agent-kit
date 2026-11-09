import random
from datetime import date, timedelta
CHANNELS=["online","retail","partner"]
REGIONS=["north","south","east","west"]
def generate_rows(seed=42, days=90):
    rng=random.Random(seed)
    start=date(2026,1,1)
    rows=[]
    for offset in range(days):
        d=(start+timedelta(days=offset)).isoformat()
        for channel in CHANNELS:
            for region in REGIONS:
                sessions=rng.randint(100,1000)
                orders=int(sessions*rng.uniform(0.05,0.25))
                if orders<1: orders=1
                aov=rng.uniform(40.0,120.0)
                revenue=round(orders*aov,2)
                legacy=round(revenue*0.97,2)
                refunds=rng.randint(0,max(1,orders//10))
                tickets=rng.randint(0,20)
                active=rng.randint(50,800)
                gross=round(revenue*rng.uniform(0.3,0.6),2)
                churned=rng.randint(0,max(1,active//20))
                rows.append({"date":d,"channel":channel,"region":region,"revenue_amount":revenue,"revenue_legacy_amount":legacy,"orders_count":orders,"sessions_count":sessions,"refunds_count":refunds,"support_tickets_count":tickets,"active_users_count":active,"gross_profit_amount":gross,"churned_users_count":churned})
    return rows
