from __future__ import annotations
import csv, random, secrets
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, func
from .db import User, Zone, Vendor, Product, Campaign, CampaignSnapshot, BasketItem, Order, OrderItem, VendorQuote, session_scope, utcnow
from .security import hash_password

ROOT=Path(__file__).resolve().parents[1]
CATEGORIES=["Rice & Grains","Flour & Staples","Pulses & Dals","Oil & Ghee","Pantry Essentials","Tea & Coffee","Spices","Home Care","Personal Care"]

def load_catalog():
    with open(ROOT/"data"/"products.csv",newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))

def seed_sample_data():
    with session_scope() as s:
        if s.scalar(select(func.count(User.id)))>0:
            return
        random.seed(42)
        zones=s.scalars(select(Zone).order_by(Zone.city,Zone.pincode)).all()
        for z in zones:
            z.active=True
        admin=User(name="RUBY Administrator",email="admin@ruby.local",password_hash=hash_password("RubyAdmin#2026"),role="admin")
        s.add(admin); s.flush()
        vendor_users=[]; vendors=[]
        vendor_password_hash=hash_password("RubyVendor#2026")
        for i,name in enumerate(["Bharat Wholesale Co.","Metro Staples Supply", "FreshRoute Essentials", "Daily Needs Distributors"]):
            u=User(name=f"{name} Team",email=f"vendor{i+1}@ruby.local",password_hash=vendor_password_hash,role="vendor")
            s.add(u); s.flush(); vendor_users.append(u)
            v=Vendor(user_id=u.id,business_name=name,gstin=None,status="APPROVED")
            s.add(v); vendors.append(v)
        s.flush()
        products=[]
        for i,r in enumerate(load_catalog()):
            p=Product(vendor_id=vendors[i%len(vendors)].id,sku=r["sku"],name=r["name"],category=r["category"],pack_size=r["pack_size"],unit=r["unit"],mrp=float(r["mrp"]),reference_cost=float(r["cost"]),image_path=f"assets/products/{r['image']}",description=r["description"],active=True,approved=True)
            s.add(p); products.append(p)
        s.flush()
        # Create a named customer for walkthrough and a broad fictional history for analytics screens.
        customers=[]
        customer_password_hash=hash_password("RubyCustomer#2026")
        for i in range(140):
            zone=zones[0] if i==0 else zones[(i*7+3)%len(zones)]
            u=User(name=f"Customer {i+1:03d}",email=f"customer{i+1}@ruby.local",password_hash=customer_password_hash,role="customer",zone_id=zone.id)
            s.add(u); customers.append(u)
        s.flush()
        now=utcnow()
        # Historical campaign outcomes create a reproducible, explicitly illustrative training set.
        historical=[]
        for j in range(48):
            z=zones[(j*11)%len(zones)]
            target=random.choice([60,80,100,120,150,180])
            success=(j%5 not in (0,1))
            initial=random.randint(5,40)
            final=random.randint(int(target*.78),int(target*1.65)) if success else random.randint(int(target*.18),int(target*.92))
            participants=max(5,int(final/random.randint(2,5)))
            c=Campaign(zone_id=z.id,title=f"{z.city} Community Basket {j+1:02d}",target_units=target,
                cutoff_at=now-timedelta(days=random.randint(1,8)),status="COMPLETED" if success else "CLOSED",
                initial_units=initial,final_units=final,reached_moq=success,participant_count=participants,
                product_mix=";".join(random.sample(CATEGORIES,k=2)),created_at=now-timedelta(days=random.randint(35,180)))
            s.add(c); historical.append(c)
        s.flush()
        for c in historical:
            mix_count=len([x for x in (c.product_mix or "").split(";") if x])
            s.add(CampaignSnapshot(campaign_id=c.id,snapshot_at=c.cutoff_at-timedelta(days=2),
                demand_units=c.initial_units,participants=max(2,int(c.participant_count*.65)),
                days_to_cutoff=2,product_count=max(1,mix_count)))
        # Recent open campaigns are spread across key cities; PIN code selection is still editable by users.
        for idx in range(28):
            z=zones[idx*10]
            s.add(Campaign(zone_id=z.id,title=f"{z.city} Weekly Essentials",target_units=100,
                cutoff_at=now+timedelta(days=5),status="OPEN",initial_units=12,final_units=0,reached_moq=None,
                participant_count=8,min_participants=10,product_mix="Rice & Grains;Pulses & Dals;Home Care"))
        s.flush()
        for j in range(560):
            customer=customers[j%len(customers)]
            hist=historical[j%len(historical)]
            # A paid order with 1-4 items; values are illustrative but shaped like RUBY's workflow.
            order=Order(order_number=f"RB-{j+1:06d}",customer_id=customer.id,campaign_id=hist.id,zone_id=customer.zone_id,
                status=random.choice(["FULFILLED","FULFILLED","FULFILLED","PROCESSING"]),payment_status="PAID",
                total_amount=0,created_at=now-timedelta(days=random.randint(1,180)))
            s.add(order); s.flush()
            chosen=random.sample(products,k=random.randint(1,4))
            total=0
            for p in chosen:
                qty=random.randint(1,5)
                price=round(p.mrp*random.uniform(.82,.97),2)
                cost=round(p.reference_cost*random.uniform(.98,1.06),2)
                s.add(OrderItem(order_id=order.id,product_id=p.id,quantity=qty,unit_price=price,unit_cost=cost))
                total+=qty*price
            order.total_amount=round(total,2)
        # Quotes: multiple vendor offers allow basic supplier comparison.
        for p in products:
            base=p.reference_cost
            for vi,v in enumerate(vendors):
                s.add(VendorQuote(vendor_id=v.id,product_id=p.id,min_qty=10+vi*15,capacity=200+vi*50,
                    unit_cost=round(base*(1+vi*.025+random.uniform(-.03,.03)),2),lead_days=2+vi))
        s.flush()
