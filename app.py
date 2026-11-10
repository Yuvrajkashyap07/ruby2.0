from __future__ import annotations
import os, re, secrets
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select, func, desc, or_

from core.db import (init_db, session_scope, read_setting, utcnow, User, Zone, Vendor,
                     Product, Campaign, CampaignSnapshot, BasketItem, Order, OrderItem, VendorQuote)
from core.security import hash_password, verify_password
from core.seed import seed_sample_data
from core.analytics import (frames, customer_segments, campaign_classification,
                            demand_regression, market_basket, quote_anomalies)

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title="RUBY | Community Buying Network",page_icon="🛍️",layout="wide",initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root{--ink:#17251f;--muted:#68756e;--green:#1e704b;--line:#e4ebe5;--soft:#f5f8f4;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;color:var(--ink)}
.stApp{background:linear-gradient(180deg,#f6f9f4 0%,#fff 260px)}
[data-testid="stSidebar"]{background:#102b22}
[data-testid="stSidebar"] *{color:#edf5ef!important}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *{color:#b5cabe!important}
.block-container{padding-top:1.4rem;padding-bottom:3rem;max-width:1450px}
h1,h2,h3{font-family:'Manrope',sans-serif!important;letter-spacing:-.035em}
h1{font-weight:800!important}
.hero{background:linear-gradient(120deg,#102b22,#1e704b);color:#fff;padding:27px 30px;border-radius:21px;margin:4px 0 20px;position:relative;overflow:hidden}
.hero h1{color:#fff;margin:0;font-size:2rem}.hero p{color:#d7e7dc;margin:.45rem 0 0;max-width:800px}
.eyebrow{text-transform:uppercase;letter-spacing:.15em;font-size:.69rem;color:#d5eead;font-weight:700}
.metric-card{border:1px solid var(--line);background:#fff;border-radius:15px;padding:15px 17px;min-height:92px;box-shadow:0 3px 14px rgba(15,43,34,.035)}
.metric-label{font-size:.76rem;color:var(--muted);font-weight:600}.metric-value{font-family:'Manrope',sans-serif;font-size:1.55rem;font-weight:800;color:var(--ink);margin-top:5px}.metric-note{color:var(--muted);font-size:.72rem;margin-top:2px}
.product-card{border:1px solid var(--line);border-radius:16px;background:#fff;padding:12px;height:100%;box-shadow:0 4px 16px rgba(14,42,32,.035)}
.product-card h4{font:800 1rem Manrope,sans-serif;margin:.2rem 0}.product-card p{font-size:.78rem;color:#68756e;margin:.1rem 0}
.pill{display:inline-block;border-radius:99px;padding:4px 9px;background:#edf6e4;color:#35623d;font-weight:700;font-size:.68rem}
.notice{padding:12px 15px;border:1px solid #dce9dc;background:#f3f8ef;border-radius:12px;color:#345344;font-size:.85rem}
.warning{padding:12px 15px;border:1px solid #f0dfb4;background:#fff9e9;border-radius:12px;color:#6b511b;font-size:.84rem}
.stButton>button,.stFormSubmitButton>button{border-radius:10px;font-weight:700}
div[data-testid="stForm"]{border:1px solid #e2eae2;border-radius:14px;padding:14px;background:#fff}
[data-testid="stDataFrame"]{border:1px solid #e5ece6;border-radius:12px;overflow:hidden}
footer{visibility:hidden}
</style>
""",unsafe_allow_html=True)


def boot():
    init_db()
    ensure_postal_catalog()
    if read_setting("SEED_SAMPLE_DATA","true").lower() in {"1","true","yes","on"}:
        seed_sample_data()
    bootstrap_admin()

@st.cache_resource(show_spinner=False)
def boot_once():
    boot(); return True


def ensure_postal_catalog():
    import csv
    file=ROOT/"data"/"city_pincodes.csv"
    with session_scope() as s:
        if s.scalar(select(func.count(Zone.id)))>0: return
        with file.open(newline="",encoding="utf-8") as f:
            for r in csv.DictReader(f):
                s.add(Zone(city=r["city"],state=r["state"],pincode=r["pincode"],locality=r["locality"],
                           hub_name=f"{r['city']} Community Collection Hub",active=False))


def bootstrap_admin():
    email=read_setting("BOOTSTRAP_ADMIN_EMAIL","").strip().lower()
    password=read_setting("BOOTSTRAP_ADMIN_PASSWORD","")
    name=read_setting("BOOTSTRAP_ADMIN_NAME","Platform Administrator")
    if not email or not password: return
    with session_scope() as s:
        user=s.scalar(select(User).where(User.email==email))
        if not user:
            s.add(User(name=name,email=email,password_hash=hash_password(password),role="admin"))

boot_once()


def metric(label,value,note=""):
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',unsafe_allow_html=True)

def hero(kicker,title,subtitle):
    st.markdown(f'<div class="hero"><div class="eyebrow">{kicker}</div><h1>{title}</h1><p>{subtitle}</p></div>',unsafe_allow_html=True)

def rupees(v): return f"₹{float(v):,.0f}"
def local_time(v): return v.strftime("%d %b %Y, %I:%M %p") if v else "—"
def product_image(path):
    raw=str(path or "").strip()
    if raw.startswith("https://") or raw.startswith("http://"):
        return raw
    p=Path(raw)
    if not p.is_absolute(): p=ROOT/p
    return str(p) if p.exists() else None

def get_user():
    uid=st.session_state.get("user_id")
    if not uid:return None
    with session_scope() as s:
        u=s.get(User,uid)
        return {"id":u.id,"name":u.name,"email":u.email,"role":u.role,"zone_id":u.zone_id} if u and u.is_active else None

def record_campaign_snapshot(session, campaign, demand_units: int, participants: int):
    if campaign.status != "OPEN":
        return
    latest=session.scalar(select(CampaignSnapshot).where(CampaignSnapshot.campaign_id==campaign.id).order_by(CampaignSnapshot.snapshot_at.desc()).limit(1))
    now=utcnow()
    if latest and (now-latest.snapshot_at).total_seconds()<20*60*60:
        return
    products_count=len([x for x in (campaign.product_mix or "").split(";") if x])
    session.add(CampaignSnapshot(campaign_id=campaign.id,snapshot_at=now,demand_units=int(demand_units),
        participants=int(participants),days_to_cutoff=max(0,(campaign.cutoff_at-now).days),product_count=max(1,products_count)))


def login_page():
    left,right=st.columns([1.1,.9],gap="large")
    with left:
        hero("RUBY · COMMUNITY BUYING NETWORK","Your community buys smarter.","Bring neighbourhood demand together, unlock supplier volume, and make everyday buying more efficient.")
        st.markdown("### Demand → Aggregate → Negotiate → Save")
        st.write("RUBY brings customers in the same PIN-code area together around shared buying campaigns. Instead of everyone purchasing separately, the community combines its requirements and gives suppliers a clearer demand picture.")
        st.markdown('<div class="notice">Browse products, join local campaigns, track pooled demand and understand how supplier prices change with order volume.</div>',unsafe_allow_html=True)
        st.write("")
        st.markdown("**Three connected workspaces**")
        c1,c2,c3=st.columns(3)
        c1.markdown("**Customer**\n\nBrowse products and join campaigns.")
        c2.markdown("**Vendor**\n\nSubmit prices and manage supply.")
        c3.markdown("**Operations**\n\nManage locations, campaigns and insights.")
    with right:
        st.markdown("### Welcome to RUBY")
        sign,register,vendor=st.tabs(["Sign in","Create account","Vendor application"])
        with sign:
            with st.form("login_form"):
                email=st.text_input("Email",placeholder="you@example.com")
                password=st.text_input("Password",type="password")
                go=st.form_submit_button("Sign in",type="primary",use_container_width=True)
            if go:
                with session_scope() as s:
                    u=s.scalar(select(User).where(User.email==email.strip().lower(),User.is_active.is_(True)))
                    if u and verify_password(password,u.password_hash):
                        st.session_state.user_id=u.id;st.rerun()
                    else: st.error("Email or password is incorrect.")
            if read_setting("SEED_SAMPLE_DATA","true").lower() in {"1","true","yes","on"}:
                st.caption("Sample access")
                st.code("Admin: admin@ruby.local / RubyAdmin#2026\nCustomer: customer1@ruby.local / RubyCustomer#2026\nVendor: vendor1@ruby.local / RubyVendor#2026")
        with register:
            with session_scope() as s:
                zones=s.scalars(select(Zone).where(Zone.active.is_(True)).order_by(Zone.city,Zone.pincode)).all()
            zmap={f"{z.city} · {z.locality} · {z.pincode}":z.id for z in zones}
            with st.form("customer_register"):
                name=st.text_input("Full name")
                email=st.text_input("Email address",key="customer_email")
                password=st.text_input("Password (10+ characters)",type="password",key="customer_password")
                zone_label=st.selectbox("City / PIN code",list(zmap) or ["No service areas are active"])
                submit=st.form_submit_button("Create customer account",type="primary",use_container_width=True)
            if submit:
                if not zmap: st.error("No service areas are active yet.")
                elif not name.strip() or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$",email.strip()) or len(password)<10:
                    st.error("Enter a name, valid email and password of at least 10 characters.")
                else:
                    with session_scope() as s:
                        if s.scalar(select(User).where(User.email==email.strip().lower())): st.error("This email is already registered.")
                        else:
                            u=User(name=name.strip(),email=email.strip().lower(),password_hash=hash_password(password),role="customer",zone_id=zmap[zone_label]);s.add(u);s.flush();st.session_state.user_id=u.id;st.rerun()
        with vendor:
            with st.form("vendor_apply"):
                contact=st.text_input("Contact person")
                business=st.text_input("Business name")
                email=st.text_input("Business email",key="vendor_email")
                password=st.text_input("Password (10+ characters)",type="password",key="vendor_password")
                gstin=st.text_input("GSTIN (optional)")
                submit=st.form_submit_button("Submit vendor application",type="primary",use_container_width=True)
            if submit:
                if not contact.strip() or not business.strip() or "@" not in email or len(password)<10: st.error("Complete the required fields and use a 10+ character password.")
                else:
                    with session_scope() as s:
                        if s.scalar(select(User).where(User.email==email.strip().lower())): st.error("This email is already registered.")
                        else:
                            u=User(name=contact.strip(),email=email.strip().lower(),password_hash=hash_password(password),role="vendor");s.add(u);s.flush()
                            s.add(Vendor(user_id=u.id,business_name=business.strip(),gstin=gstin.strip() or None,status="PENDING"));st.success("Application received. Operations will review your business details.")


def customer_portal(user):
    with session_scope() as s:
        u=s.get(User,user["id"]); zone=s.get(Zone,u.zone_id) if u.zone_id else None
        active_zones=s.scalars(select(Zone).where(Zone.active.is_(True)).order_by(Zone.city,Zone.pincode)).all()
        products=s.scalars(select(Product).where(Product.active.is_(True),Product.approved.is_(True)).order_by(Product.category,Product.name)).all()
        campaigns=s.scalars(select(Campaign).where(Campaign.status=="OPEN").order_by(Campaign.cutoff_at)).all()
        my_orders=s.scalars(select(Order).where(Order.customer_id==u.id).order_by(Order.created_at.desc())).all()
        hero("CUSTOMER WORKSPACE","Shop your community basket.","Choose a local campaign, add products and follow the combined demand in your PIN-code area.")
        if not active_zones:
            st.info("RUBY has not activated any service areas yet. Please check again once your city is available.");return
        zone_labels={f"{z.city} · {z.locality} · {z.pincode}":z.id for z in active_zones}
        default_label=next((k for k,v in zone_labels.items() if zone and v==zone.id),list(zone_labels)[0])
        selected=st.selectbox("Your service area",list(zone_labels),index=list(zone_labels).index(default_label))
        selected_zone_id=zone_labels[selected]
        campaigns_here=[c for c in campaigns if c.zone_id==selected_zone_id]
        st.divider()
        if not campaigns_here:
            st.info("There is no open campaign in this service area right now. Browse the product catalogue below and check back for the next buying cycle.")
        else:
            clabels={f"{c.title} · cutoff {c.cutoff_at.strftime('%d %b')} · target {c.target_units} units":c.id for c in campaigns_here}
            chosen=st.selectbox("Open buying campaign",list(clabels))
            campaign_id=clabels[chosen]; campaign=s.get(Campaign,campaign_id)
            # Demand and participation are derived from the basket table.
            baskets=s.scalars(select(BasketItem).where(BasketItem.campaign_id==campaign_id)).all()
            total_units=sum(b.quantity for b in baskets); households=len(set(b.customer_id for b in baskets))
            record_campaign_snapshot(s,campaign,total_units,households)
            c1,c2,c3=st.columns(3)
            with c1: metric("Pooled quantities",f"{total_units:,}","Units added by customers")
            with c2: metric("Households",f"{households:,}","Participating customers")
            with c3: metric("MOQ progress",f"{min(100,total_units/max(1,campaign.target_units)*100):.0f}%",f"Target {campaign.target_units} units")
            st.progress(min(1,total_units/max(1,campaign.target_units)))
            st.caption(f"Collection point: {zone.hub_name if zone else 'Assigned hub'} · Campaign closes {local_time(campaign.cutoff_at)}")
            st.subheader("Products in this campaign")
            cat=st.selectbox("Filter by category",["All categories"]+sorted({p.category for p in products}),key="shop_category")
            search=st.text_input("Search products",placeholder="Search rice, dal, oil…",key="product_search")
            filtered=[p for p in products if (cat=="All categories" or p.category==cat) and (search.lower() in p.name.lower() or search.lower() in p.category.lower())]
            own={b.product_id:b.quantity for b in baskets if b.customer_id==u.id}
            demand_by_product={}
            for basket_row in baskets:
                demand_by_product[basket_row.product_id]=demand_by_product.get(basket_row.product_id,0)+basket_row.quantity
            for start in range(0,len(filtered),3):
                cols=st.columns(3,gap="medium")
                for col,p in zip(cols,filtered[start:start+3]):
                    with col:
                        img=product_image(p.image_path)
                        if img: st.image(img,use_container_width=True)
                        st.markdown(f"<span class='pill'>{p.category}</span>",unsafe_allow_html=True)
                        st.markdown(f"**{p.name}**")
                        st.caption(f"{p.pack_size} · {p.sku}")
                        st.markdown(f"### {rupees(p.mrp)}")
                        pooled=demand_by_product.get(p.id,0)
                        quote_rows=s.scalars(select(VendorQuote).where(VendorQuote.product_id==p.id,or_(VendorQuote.campaign_id==campaign_id,VendorQuote.campaign_id.is_(None)))).all()
                        eligible=[q for q in quote_rows if q.min_qty<=pooled and q.capacity>=pooled and pooled>0]
                        if eligible:
                            best=min(eligible,key=lambda q:q.unit_cost)
                            vendor_record=s.get(Vendor,best.vendor_id)
                            st.success(f"Indicative supplier quote: {rupees(best.unit_cost)} · {vendor_record.business_name if vendor_record else 'Supplier'}")
                        else:
                            next_tier=min((q.min_qty for q in quote_rows if q.min_qty>pooled),default=None)
                            if next_tier:
                                st.caption(f"Next supplier tier: {next_tier} units · {max(0,next_tier-pooled)} more needed")
                            else:
                                st.caption("Supplier quotation not available yet")
                        with st.form(f"basket_{campaign_id}_{p.id}"):
                            qty=st.number_input("Your quantity",min_value=0,max_value=100,value=int(own.get(p.id,0)),step=1,key=f"qty_{campaign_id}_{p.id}")
                            save=st.form_submit_button("Update basket",use_container_width=True)
                        if save:
                            existing=s.scalar(select(BasketItem).where(BasketItem.customer_id==u.id,BasketItem.campaign_id==campaign.id,BasketItem.product_id==p.id))
                            if qty==0:
                                if existing:s.delete(existing)
                            elif existing: existing.quantity=int(qty);existing.updated_at=utcnow()
                            else:s.add(BasketItem(customer_id=u.id,campaign_id=campaign.id,product_id=p.id,quantity=int(qty)))
                            st.success(f"{p.name} basket updated.");st.rerun()
            # Local popularity is a light recommendation signal based on paid orders in the selected city.
            st.divider();st.subheader(f"Popular in {s.get(Zone,selected_zone_id).city}")
            popular=s.execute(select(Product,func.sum(OrderItem.quantity).label("units"))
                .join(OrderItem,OrderItem.product_id==Product.id)
                .join(Order,Order.id==OrderItem.order_id)
                .join(Zone,Zone.id==Order.zone_id)
                .where(Zone.city==s.get(Zone,selected_zone_id).city,Order.payment_status=="PAID")
                .group_by(Product.id).order_by(desc("units")).limit(3)).all()
            if popular:
                rec_cols=st.columns(3)
                for rec_col,(recommended,units) in zip(rec_cols,popular):
                    with rec_col:
                        rec_img=product_image(recommended.image_path)
                        if rec_img: st.image(rec_img,use_container_width=True)
                        st.markdown(f"**{recommended.name}**")
                        st.caption(f"{recommended.category} · {int(units)} units ordered in this city")
            else:
                st.caption("Local purchase history is still building. City-based suggestions will appear after completed paid orders.")
            st.divider();st.subheader("Your campaign basket")
            own_rows=[b for b in baskets if b.customer_id==u.id]
            if own_rows:
                basket_data=[]
                for b in own_rows:
                    p=s.get(Product,b.product_id);basket_data.append({"Product":p.name,"Pack":p.pack_size,"Quantity":b.quantity,"Indicative value":b.quantity*p.mrp})
                st.dataframe(pd.DataFrame(basket_data),use_container_width=True,hide_index=True)
                approx=sum(x["Indicative value"] for x in basket_data)
                st.markdown(f"**Reference basket value: {rupees(approx)}**")
                if st.button("Submit group-buy commitment",type="primary"):
                    existing=s.scalar(select(Order).where(Order.customer_id==u.id,Order.campaign_id==campaign.id,Order.status.in_(["REQUESTED","AWAITING_PRICE"])))
                    if existing: st.warning("You already have a commitment in this campaign.")
                    else:
                        order=Order(order_number="RB-"+secrets.token_hex(4).upper(),customer_id=u.id,campaign_id=campaign.id,zone_id=selected_zone_id,status="REQUESTED",payment_status="NOT_COLLECTED",total_amount=round(approx,2))
                        s.add(order);s.flush()
                        for b in own_rows:
                            p=s.get(Product,b.product_id);s.add(OrderItem(order_id=order.id,product_id=p.id,quantity=b.quantity,unit_price=p.mrp,unit_cost=p.reference_cost))
                        st.success("Your commitment has been recorded. The supplier-backed price and payment step will follow the campaign review.");st.rerun()
            else: st.caption("Your basket is empty. Add products above to start.")
        st.divider();st.subheader("Your orders")
        if my_orders:
            rows=[]
            for o in my_orders:
                c=s.get(Campaign,o.campaign_id);rows.append({"Order":o.order_number,"Campaign":c.title if c else "—","Date":local_time(o.created_at),"Amount":rupees(o.total_amount),"Status":o.status.replace("_"," ").title(),"Payment":o.payment_status.replace("_"," ").title()})
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        else: st.caption("Your submitted commitments and confirmed orders will appear here.")


def vendor_portal(user):
    with session_scope() as s:
        vendor=s.scalar(select(Vendor).where(Vendor.user_id==user["id"]))
        hero("VENDOR WORKSPACE","Supply to growing communities.","Submit competitive volume quotations, manage your product proposals and track orders awarded to your business.")
        if not vendor: st.error("Vendor profile not found.");return
        a,b=st.columns(2);a.metric("Business",vendor.business_name);b.metric("Approval status",vendor.status)
        if vendor.status!="APPROVED": st.warning("Your account is under review. Quote submission is available after approval.");return
        tab1,tab2=st.tabs(["Submit a quotation","Your quotations"])
        products=s.scalars(select(Product).where(Product.active.is_(True),Product.approved.is_(True)).order_by(Product.name)).all()
        campaigns=s.scalars(select(Campaign).where(Campaign.status=="OPEN").order_by(Campaign.cutoff_at)).all()
        with tab1:
            if not products or not campaigns: st.info("No products or open campaigns are available.")
            else:
                pmap={f"{p.name} · {p.sku}":p.id for p in products}; cmap={f"{c.title} · closes {c.cutoff_at.strftime('%d %b')}":c.id for c in campaigns}
                with st.form("vendor_quote"):
                    pl=st.selectbox("Product",list(pmap));cl=st.selectbox("Campaign",list(cmap))
                    c1,c2,c3=st.columns(3)
                    with c1: minq=st.number_input("Minimum quantity",min_value=1,value=25,step=5)
                    with c2: cap=st.number_input("Available capacity",min_value=1,value=250,step=10)
                    with c3: cost=st.number_input("Your unit cost (₹)",min_value=.01,value=100.0,step=1.0)
                    lead=st.number_input("Lead time (days)",min_value=1,max_value=90,value=3)
                    sub=st.form_submit_button("Submit quotation",type="primary")
                if sub:
                    if cap<minq: st.error("Capacity must be greater than or equal to minimum quantity.")
                    else:
                        s.add(VendorQuote(vendor_id=vendor.id,product_id=pmap[pl],campaign_id=cmap[cl],min_qty=int(minq),capacity=int(cap),unit_cost=float(cost),lead_days=int(lead)))
                        st.success("Quotation submitted for operations review.");st.rerun()
        with tab2:
            quotes=s.scalars(select(VendorQuote).where(VendorQuote.vendor_id==vendor.id).order_by(VendorQuote.created_at.desc())).all()
            if quotes:
                rows=[]
                for q in quotes:
                    p=s.get(Product,q.product_id);c=s.get(Campaign,q.campaign_id) if q.campaign_id else None
                    rows.append({"Product":p.name if p else "—","Campaign":c.title if c else "General","MOQ":q.min_qty,"Capacity":q.capacity,"Unit cost":rupees(q.unit_cost),"Lead days":q.lead_days})
                st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
            else: st.caption("No quotations submitted yet.")


def admin_overview(s):
    hero("OPERATIONS OVERVIEW","See what is happening across RUBY.","A single view of communities, pooled buying activity, suppliers and commercial performance.")
    users=s.scalar(select(func.count(User.id)).where(User.role=="customer")) or 0
    vendors=s.scalar(select(func.count(Vendor.id)).where(Vendor.status=="APPROVED")) or 0
    zones=s.scalar(select(func.count(Zone.id)).where(Zone.active.is_(True))) or 0
    orders=s.scalars(select(Order).where(Order.payment_status=="PAID")).all()
    revenue=sum(o.total_amount for o in orders)
    cols=st.columns(5)
    vals=[("Customers",f"{users:,}","Registered accounts"),("Approved vendors",f"{vendors:,}","Supply partners"),("Service PIN codes",f"{zones:,}","Active coverage records"),("Paid orders",f"{len(orders):,}","Verified sample / recorded orders"),("Gross paid",rupees(revenue),"Recorded order value")]
    for col,(a,b,c) in zip(cols,vals):
        with col: metric(a,b,c)
    campaigns=s.scalars(select(Campaign).order_by(Campaign.created_at.desc()).limit(15)).all()
    if campaigns:
        data=[]
        for c in campaigns:
            z=s.get(Zone,c.zone_id)
            req=s.scalar(select(func.coalesce(func.sum(BasketItem.quantity),0)).where(BasketItem.campaign_id==c.id)) or 0
            people=s.scalar(select(func.count(func.distinct(BasketItem.customer_id))).where(BasketItem.campaign_id==c.id)) or 0
            data.append({"Campaign":c.title,"City":z.city if z else "—","PIN":z.pincode if z else "—","Status":c.status,"Pooled units":req or c.final_units,"Participants":people or c.participant_count,"MOQ target":c.target_units})
        st.subheader("Campaign monitor");st.dataframe(pd.DataFrame(data),use_container_width=True,hide_index=True)
    st.markdown('<div class="notice">Use the service-area page to activate only PIN codes where RUBY has a confirmed collection and fulfilment arrangement. Postal presence does not automatically mean delivery serviceability.</div>',unsafe_allow_html=True)


def admin_geography(s):
    hero("MARKET COVERAGE","Manage the city and PIN-code network.","The catalogue includes 28 cities with 10 candidate PIN codes per city. Activate a location only after local serviceability and collection capacity are confirmed.")
    zones=s.scalars(select(Zone).order_by(Zone.city,Zone.pincode)).all()
    df=pd.DataFrame([{"City":z.city,"State":z.state,"PIN code":z.pincode,"Locality":z.locality,"Hub":z.hub_name,"Active":z.active,"ID":z.id} for z in zones])
    if not df.empty:
        a,b,c=st.columns(3)
        with a: metric("Cities",str(df.City.nunique()),"Curated launch markets")
        with b: metric("PIN records",f"{len(df):,}","10 candidates per city")
        with c: metric("Active PIN codes",str(int(df.Active.sum())),"Admin-enabled service areas")
        show=df.groupby(["City","State"]).agg(PIN_codes=("PIN code","count"),Active=("Active","sum")).reset_index()
        st.dataframe(show,use_container_width=True,hide_index=True)
        city=st.selectbox("Choose a city",sorted(df.City.unique()))
        city_rows=[z for z in zones if z.city==city]
        with st.form("zone_update"):
            selected=st.multiselect("PIN codes to activate",[f"{z.pincode} · {z.locality}" for z in city_rows],default=[f"{z.pincode} · {z.locality}" for z in city_rows if z.active])
            hub=st.text_input("Collection hub name",value=f"{city} Community Collection Hub")
            save=st.form_submit_button("Save serviceability settings",type="primary")
        if save:
            active_pins={v.split(" · ")[0] for v in selected}
            for z in city_rows:
                z.active=z.pincode in active_pins
                if hub.strip():z.hub_name=hub.strip()
            st.success(f"Updated serviceability for {city}.");st.rerun()
        with st.expander("Review all PIN records"):
            st.dataframe(df.drop(columns=["ID"]),use_container_width=True,hide_index=True)
            st.download_button("Download service-area CSV",df.drop(columns=["ID"]).to_csv(index=False).encode("utf-8-sig"),file_name="ruby_service_areas.csv",mime="text/csv")


def admin_products(s):
    hero("PRODUCT CATALOGUE","Manage the products communities can buy.","Maintain a clean catalogue with product imagery, pack sizes, retail references and vendor ownership.")
    products=s.scalars(select(Product).order_by(Product.category,Product.name)).all()
    st.write(f"**{len(products)} catalogue products** across **{len(set(p.category for p in products))} categories**")
    search=st.text_input("Search catalogue",placeholder="Search by product, SKU or category")
    filtered=[p for p in products if search.lower() in f"{p.name} {p.sku} {p.category}".lower()]
    for i in range(0,len(filtered),4):
        cols=st.columns(4)
        for col,p in zip(cols,filtered[i:i+4]):
            with col:
                img=product_image(p.image_path)
                if img:st.image(img,use_container_width=True)
                st.markdown(f"**{p.name}**")
                st.caption(f"{p.category} · {p.pack_size} · {p.sku}")
                st.markdown(f"**{rupees(p.mrp)}**")
                with st.expander("Edit product"):
                    with st.form(f"edit_product_{p.id}"):
                        name=st.text_input("Product name",p.name)
                        mrp=st.number_input("Retail reference (₹)",min_value=0.0,value=float(p.mrp),step=1.0)
                        active=st.checkbox("Available in catalogue",value=p.active)
                        image=st.text_input("Image path or URL",p.image_path)
                        save=st.form_submit_button("Save changes")
                    if save:
                        p.name=name.strip() or p.name;p.mrp=mrp;p.active=active;p.image_path=image.strip() or p.image_path
                        st.success("Product updated.");st.rerun()
    st.divider();st.subheader("Add a product")
    vendors=s.scalars(select(Vendor).where(Vendor.status=="APPROVED")).all()
    if not vendors: st.info("Approve a vendor before adding a vendor-owned product.")
    else:
        vmap={v.business_name:v.id for v in vendors}
        with st.form("add_product"):
            a,b=st.columns(2)
            with a: name=st.text_input("Product name");sku=st.text_input("SKU")
            with b: category=st.selectbox("Category",["Rice & Grains","Flour & Staples","Pulses & Dals","Oil & Ghee","Pantry Essentials","Tea & Coffee","Spices","Home Care","Personal Care","Other"]);pack=st.text_input("Pack size",placeholder="1 kg pack")
            vendor=st.selectbox("Vendor",list(vmap));mrp=st.number_input("Reference retail price (₹)",min_value=0.0,value=100.0);cost=st.number_input("Reference supply cost (₹)",min_value=0.0,value=80.0)
            image=st.text_input("Image file path or HTTPS image URL",placeholder="assets/products/rice.webp")
            description=st.text_area("Product details")
            submit=st.form_submit_button("Add product",type="primary")
        if submit:
            if not name.strip() or not sku.strip() or not pack.strip() or s.scalar(select(Product).where(Product.sku==sku.strip().upper())): st.error("Enter the required fields and a unique SKU.")
            else:
                s.add(Product(vendor_id=vmap[vendor],sku=sku.strip().upper(),name=name.strip(),category=category,pack_size=pack.strip(),mrp=mrp,reference_cost=cost,image_path=image.strip(),description=description.strip(),active=True,approved=True));st.success("Product added.");st.rerun()


def admin_campaigns(s):
    hero("CAMPAIGN OPERATIONS","Create and monitor community buying cycles.","Run campaigns around a confirmed service area, set a clear minimum order quantity and watch demand build before the cutoff.")
    campaigns=s.scalars(select(Campaign).order_by(Campaign.created_at.desc())).all()
    if campaigns:
        rows=[]
        for c in campaigns:
            z=s.get(Zone,c.zone_id);demand=s.scalar(select(func.coalesce(func.sum(BasketItem.quantity),0)).where(BasketItem.campaign_id==c.id)) or 0
            rows.append({"Campaign":c.title,"City":z.city if z else "—","PIN":z.pincode if z else "—","Status":c.status,"Current units":demand or c.final_units,"MOQ":c.target_units,"Cutoff":local_time(c.cutoff_at)})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    st.divider();st.subheader("Create a campaign")
    zones=s.scalars(select(Zone).where(Zone.active.is_(True)).order_by(Zone.city,Zone.pincode)).all()
    products=s.scalars(select(Product).where(Product.active.is_(True),Product.approved.is_(True)).order_by(Product.name)).all()
    if not zones or not products: st.warning("Activate at least one service area and approve one product before creating a campaign.");return
    zmap={f"{z.city} · {z.locality} · {z.pincode}":z.id for z in zones};pmap={f"{p.name} · {p.sku}":p.id for p in products}
    with st.form("create_campaign"):
        title=st.text_input("Campaign name",placeholder="Weekend pantry buying group")
        zone=st.selectbox("Service area",list(zmap))
        selected_products=st.multiselect("Products included",list(pmap),default=list(pmap)[:5])
        a,b,c=st.columns(3)
        with a: target=st.number_input("MOQ target (total units)",min_value=10,value=100,step=10)
        with b: min_orders=st.number_input("Minimum households",min_value=2,value=10,step=1)
        with c: days=st.number_input("Days until cutoff",min_value=1,max_value=30,value=7)
        save=st.form_submit_button("Create buying campaign",type="primary")
    if save:
        if not title.strip() or not selected_products:st.error("Enter a campaign name and choose at least one product.")
        else:
            s.add(Campaign(zone_id=zmap[zone],title=title.strip(),target_units=int(target),min_participants=int(min_orders),cutoff_at=utcnow()+timedelta(days=int(days)),status="OPEN",initial_units=0,final_units=0,reached_moq=None,participant_count=0,product_mix=";".join([x.split(" · ")[0] for x in selected_products])))
            st.success("Campaign created.");st.rerun()
    st.divider();st.subheader("Record a campaign outcome")
    history_candidates=s.scalars(select(Campaign).where(Campaign.status.in_(["OPEN","CLOSED","COMPLETED"])).order_by(Campaign.created_at.desc())).all()
    if history_candidates:
        cmap={f"{c.title} · {c.status}":c.id for c in history_candidates}
        chosen_campaign=st.selectbox("Campaign to close / update",list(cmap),key="outcome_campaign")
        selected_campaign=s.get(Campaign,cmap[chosen_campaign])
        a,b=st.columns(2)
        with a: final_units=st.number_input("Final pooled units",min_value=0,value=int(selected_campaign.final_units or selected_campaign.initial_units),step=5)
        with b: outcome=st.selectbox("Outcome",["Completed - MOQ reached","Closed - MOQ not reached"],index=0 if selected_campaign.reached_moq is True else 1 if selected_campaign.reached_moq is False else 0)
        if st.button("Save campaign outcome",type="primary"):
            selected_campaign.final_units=int(final_units)
            selected_campaign.reached_moq=outcome.startswith("Completed")
            selected_campaign.status="COMPLETED" if selected_campaign.reached_moq else "CLOSED"
            st.success("Campaign outcome saved for reporting and future model training.");st.rerun()
    st.divider();st.subheader("Supplier quotations")
    quotes=s.scalars(select(VendorQuote).order_by(VendorQuote.created_at.desc()).limit(100)).all()
    if quotes:
        data=[]
        for q in quotes:
            p=s.get(Product,q.product_id);v=s.get(Vendor,q.vendor_id);c=s.get(Campaign,q.campaign_id) if q.campaign_id else None
            data.append({"Product":p.name if p else "—","Vendor":v.business_name if v else "—","Campaign":c.title if c else "General","MOQ":q.min_qty,"Capacity":q.capacity,"Unit cost":q.unit_cost,"Lead days":q.lead_days})
        qdf=pd.DataFrame(data);st.dataframe(qdf,use_container_width=True,hide_index=True)
        compare=qdf.groupby("Product")["Unit cost"].agg(["min","median","max"]).reset_index().rename(columns={"min":"Lowest quote","median":"Median quote","max":"Highest quote"})
        st.caption("Quote comparison by product");st.dataframe(compare,use_container_width=True,hide_index=True)


def admin_orders(s):
    hero("ORDER CONTROL","Track customer commitments and fulfilment.","A basket is not a confirmed purchase. Review commitments, confirm supplier pricing and update order status only when the relevant step is complete.")
    orders=s.scalars(select(Order).order_by(Order.created_at.desc())).all()
    if not orders:st.info("No orders recorded yet.");return
    data=[]
    for o in orders:
        u=s.get(User,o.customer_id);z=s.get(Zone,o.zone_id);c=s.get(Campaign,o.campaign_id)
        data.append({"Order":o.order_number,"Customer":u.name if u else "—","City":z.city if z else "—","Campaign":c.title if c else "—","Amount":rupees(o.total_amount),"Status":o.status,"Payment":o.payment_status,"Date":local_time(o.created_at)})
    st.dataframe(pd.DataFrame(data),use_container_width=True,hide_index=True)
    chosen=st.selectbox("Select an order",{o.order_number:o.id for o in orders})
    order=s.get(Order,{o.order_number:o.id for o in orders}[chosen])
    a,b=st.columns(2)
    with a: status=st.selectbox("Order status",["REQUESTED","AWAITING_PRICE","CONFIRMED","PROCESSING","FULFILLED","CANCELLED"],index=["REQUESTED","AWAITING_PRICE","CONFIRMED","PROCESSING","FULFILLED","CANCELLED"].index(order.status) if order.status in ["REQUESTED","AWAITING_PRICE","CONFIRMED","PROCESSING","FULFILLED","CANCELLED"] else 0)
    with b: payment=st.selectbox("Payment status",["NOT_COLLECTED","PENDING","PAID","REFUND_PENDING","REFUNDED"],index=["NOT_COLLECTED","PENDING","PAID","REFUND_PENDING","REFUNDED"].index(order.payment_status) if order.payment_status in ["NOT_COLLECTED","PENDING","PAID","REFUND_PENDING","REFUNDED"] else 0)
    if st.button("Update selected order",type="primary"):
        order.status=status;order.payment_status=payment;st.success("Order record updated.");st.rerun()
    lines=s.scalars(select(OrderItem).where(OrderItem.order_id==order.id)).all()
    if lines:
        st.subheader("Order line items")
        st.dataframe(pd.DataFrame([{"Product":s.get(Product,x.product_id).name,"Quantity":x.quantity,"Unit price":rupees(x.unit_price),"Line value":rupees(x.quantity*x.unit_price)} for x in lines]),use_container_width=True,hide_index=True)


def admin_vendors(s):
    hero("SUPPLIER NETWORK","Review vendors and build supply depth.","Vendor applications and quotations are managed here. Competitive pricing is only one part of supplier selection; reliability and capacity matter too.")
    vendors=s.scalars(select(Vendor).order_by(Vendor.created_at.desc())).all()
    rows=[]
    for v in vendors:
        u=s.get(User,v.user_id);rows.append({"Business":v.business_name,"Contact":u.name if u else "—","Email":u.email if u else "—","GSTIN":v.gstin or "Not supplied","Status":v.status})
    if rows:st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    if vendors:
        vmap={v.business_name:v.id for v in vendors};chosen=st.selectbox("Select vendor",list(vmap));v=s.get(Vendor,vmap[chosen])
        status=st.selectbox("Vendor status",["PENDING","APPROVED","SUSPENDED"],index=["PENDING","APPROVED","SUSPENDED"].index(v.status))
        if st.button("Save vendor status"):
            v.status=status;st.success("Vendor status updated.");st.rerun()


def admin_analytics(s):
    hero("DATA INTELLIGENCE","Understand demand before making the next move.","The analytics below are connected to RUBY order, campaign, customer and quotation records. Predictive models remain gated by the amount of usable history.")
    od,ld=frames(s)
    campaigns=s.scalars(select(Campaign)).all()
    if od.empty:
        st.info("There is not enough transactional data yet. Descriptive reporting will appear as customers place orders.");return
    paid=od[od.payment_status=="PAID"].copy()
    paid_lines=ld[ld.order_id.isin(paid.order_id)].copy() if not paid.empty and not ld.empty else pd.DataFrame()
    t1,t2,t3,t4,t5=st.tabs(["Business overview","Customer clusters","Campaign classification","Demand regression","Product & vendor mining"])
    with t1:
        st.subheader("Recorded trading activity")
        revenue=paid.revenue.sum() if not paid.empty else 0
        margin=ld[ld.order_id.isin(paid.order_id)].margin.sum() if not paid.empty and not ld.empty else 0
        a,b,c,d=st.columns(4)
        with a:metric("Paid orders",f"{len(paid):,}","Only records marked paid")
        with b:metric("Gross order value",rupees(revenue),"Recorded order values")
        with c:metric("Estimated line margin",rupees(margin),"Price less reference cost")
        with d:metric("Products purchased",str(ld.sku.nunique() if not ld.empty else 0),"Distinct SKUs")
        if not paid.empty:
            left,right=st.columns(2)
            with left:
                cat=ld[ld.order_id.isin(paid.order_id)].groupby("category",as_index=False).agg(units=("quantity","sum"),sales=("revenue","sum")).sort_values("sales",ascending=False)
                st.plotly_chart(px.bar(cat,x="category",y="sales",color="units",title="Sales by product category",labels={"category":"Category","sales":"Sales (₹)"}),use_container_width=True)
            with right:
                city=paid.groupby("city",as_index=False).agg(orders=("order_id","count"),sales=("revenue","sum")).sort_values("sales",ascending=False).head(15)
                st.plotly_chart(px.bar(city,x="city",y="orders",color="sales",title="Order activity by city",labels={"city":"City","orders":"Paid orders"}),use_container_width=True)
            trend=paid.assign(week=pd.to_datetime(paid.created_at).dt.to_period("W").astype(str)).groupby("week",as_index=False).agg(orders=("order_id","count"),sales=("revenue","sum"))
            st.plotly_chart(px.line(trend,x="week",y="sales",markers=True,title="Weekly recorded sales trend",labels={"week":"Week","sales":"Sales (₹)"}),use_container_width=True)
            top=ld.groupby(["product","category"],as_index=False).agg(units=("quantity","sum"),sales=("revenue","sum")).sort_values("units",ascending=False).head(12)
            st.subheader("Most purchased products");st.dataframe(top,use_container_width=True,hide_index=True)
    with t2:
        st.subheader("Customer segmentation (RFM + K-Means)")
        result,err=customer_segments(paid)
        if err:st.info(err)
        else:
            customer_df,profile=result
            a,b=st.columns(2)
            with a:st.plotly_chart(px.scatter(customer_df,x="frequency",y="monetary",color="segment",size="frequency",hover_data=["recency_days"],title="Customer segments by order frequency and spend",labels={"frequency":"Paid orders","monetary":"Total spend (₹)"}),use_container_width=True)
            with b:st.dataframe(profile[["segment","customers","avg_recency","avg_orders","avg_spend"]].rename(columns={"segment":"Segment","customers":"Customers","avg_recency":"Avg days since order","avg_orders":"Avg orders","avg_spend":"Avg spend (₹)"}).round(1),use_container_width=True,hide_index=True)
            st.caption("RFM means recency, frequency and monetary value. K-Means groups customers with similar purchase patterns; the labels are operational descriptions, not personal traits.")
    with t3:
        st.subheader("Campaign MOQ achievement classification")
        # Find an active campaign and current live features for an illustrative scoring candidate.
        active=next((c for c in campaigns if c.status=="OPEN"),None)
        features=None;label=None
        if active:
            req=s.scalar(select(func.coalesce(func.sum(BasketItem.quantity),0)).where(BasketItem.campaign_id==active.id)) or 0
            people=s.scalar(select(func.count(func.distinct(BasketItem.customer_id))).where(BasketItem.campaign_id==active.id)) or 0
            days=max(1,(active.cutoff_at-utcnow()).days)
            features=[req,active.target_units,people,max(1,(active.cutoff_at-utcnow()).days),len((active.product_mix or "").split(";"))]
            label=active.title
        model,err=campaign_classification(s,campaigns,features)
        if err:st.info(err)
        else:
            a,b,c=st.columns(3)
            with a:metric("Historical campaigns",str(model["n"]),"Completed with recorded outcomes")
            with b:metric("Historical MOQ success",f"{model['success_rate']*100:.1f}%","Outcome share in training data")
            with c:metric("Holdout accuracy",f"{model['accuracy_holdout']*100:.1f}%" if model["accuracy_holdout"] is not None else "Not available","Chronological holdout")
            if active:
                prob=model.get("probability",0)
                st.markdown(f"**Current candidate:** {label}")
                st.metric("Estimated MOQ achievement probability",f"{prob*100:.1f}%")
                st.progress(prob)
                st.caption("This is a decision-support estimate, not a guarantee. The reported holdout uses earlier campaigns for training and the latest 20% for testing; keep monitoring performance as real campaign history grows.")
            else:st.info("No open campaign available to score.")
    with t4:
        st.subheader("Expected product demand")
        model,err=demand_regression(paid_lines)
        if err:st.info(err)
        else:
            a,b=st.columns(2)
            with a:metric("Historical order lines",f"{model['n']:,}","Training observations")
            with b:metric("Holdout MAE",f"{model['mae_holdout']:.2f} units" if model["mae_holdout"] is not None else "Not available","Latest 20% of paid line records")
            cities=sorted(ld.city.unique());categories=sorted(ld.category.unique())
            x,y,z=st.columns(3)
            with x:city=st.selectbox("City",cities)
            with y:category=st.selectbox("Category",categories)
            with z:price=st.number_input("Reference unit price (₹)",min_value=1.0,value=float(ld.unit_price.median()))
            month=st.selectbox("Forecast month",list(range(1,13)),index=(utcnow().month-1))
            prediction=float(model["model"].predict(pd.DataFrame([{"city":city,"category":category,"unit_price":price,"month":month}]))[0])
            st.metric("Estimated units per order line",f"{max(0,prediction):.1f}")
            st.caption("This model estimates typical line quantity from historical transaction patterns. It is not an aggregate city-demand forecast. The latest 20% of paid line records are held out by time for evaluation.")
    with t5:
        st.subheader("Market basket analysis")
        pairs=market_basket(paid_lines)
        if pairs.empty:st.info("More multi-product orders are needed to discover stable product combinations.")
        else:st.dataframe(pairs.head(20),use_container_width=True,hide_index=True)
        st.caption("The table finds products appearing together in the same order. It can support bundle design and complementary campaign suggestions.")
        st.divider();st.subheader("Supplier quote outliers")
        anomalies=quote_anomalies(s)
        if anomalies.empty:st.success("No obvious price outliers were detected with the current median-deviation rule.")
        else:st.dataframe(anomalies,use_container_width=True,hide_index=True)
        st.caption("An outlier is a review signal, not proof of a bad quote. Differences in product grade, brand, tax, delivery and validity still need human review.")


def admin_financials(s):
    hero("UNIT ECONOMICS","Track margin, not only order value.","Understand whether a dense community buying cycle can cover procurement, payment and fulfilment costs.")
    od,ld=frames(s)
    if od.empty:st.info("No order activity is recorded yet.");return
    paid=od[od.payment_status=="PAID"]
    lines=ld[ld.order_id.isin(paid.order_id)] if not paid.empty else pd.DataFrame()
    a,b,c,d=st.columns(4)
    gross=paid.revenue.sum() if not paid.empty else 0
    margin=lines.margin.sum() if not lines.empty else 0
    with a:metric("Paid GMV",rupees(gross),"Recorded gross order value")
    with b:metric("Product contribution",rupees(margin),"Before delivery and overhead")
    with c:metric("Contribution rate",f"{(margin/gross*100 if gross else 0):.1f}%","Simplified product margin")
    with d:metric("Average order value",rupees(paid.revenue.mean() if not paid.empty else 0),"Paid orders only")
    st.markdown('<div class="warning">This view uses order-line unit cost and price. It does not yet allocate all tax, delivery, payment gateway, refunds, labour or fixed overhead costs. Do not treat it as audited profit.</div>',unsafe_allow_html=True)
    if not lines.empty:
        by=lines.groupby("city",as_index=False).agg(sales=("revenue","sum"),margin=("margin","sum"),units=("quantity","sum"))
        st.plotly_chart(px.bar(by.sort_values("margin",ascending=False).head(15),x="city",y="margin",color="sales",title="Product contribution by city",labels={"city":"City","margin":"Product contribution (₹)"}),use_container_width=True)


def admin_portal(user):
    with session_scope() as s:
        pages=["Overview","Geographic coverage","Product catalogue","Campaigns & quotes","Order management","Data intelligence","Unit economics","Vendor approvals"]
        selected=st.sidebar.radio("Operations workspace",pages)
        if selected=="Overview":admin_overview(s)
        elif selected=="Geographic coverage":admin_geography(s)
        elif selected=="Product catalogue":admin_products(s)
        elif selected=="Campaigns & quotes":admin_campaigns(s)
        elif selected=="Order management":admin_orders(s)
        elif selected=="Data intelligence":admin_analytics(s)
        elif selected=="Unit economics":admin_financials(s)
        elif selected=="Vendor approvals":admin_vendors(s)


def main():
    user=get_user()
    if not user:
        if "user_id" in st.session_state:st.session_state.pop("user_id",None)
        login_page();return
    with st.sidebar:
        st.markdown("<div style='font:800 1.7rem Manrope;color:#d6f29a'>RUBY<span style='color:white'>.</span></div><div style='font-size:.72rem;color:#b5cabe;margin-bottom:16px'>COMMUNITY BUYING NETWORK</div>",unsafe_allow_html=True)
        st.markdown(f"**{user['name']}**")
        st.caption(f"{user['role'].title()} workspace")
        if read_setting("SEED_SAMPLE_DATA","true").lower() in {"1","true","yes","on"}:
            st.caption("Illustrative sample records are active. Disable sample seeding and use PostgreSQL before handling live customer orders.")
        if st.button("Sign out",use_container_width=True):st.session_state.clear();st.rerun()
        st.divider()
    if user["role"]=="admin":admin_portal(user)
    elif user["role"]=="vendor":vendor_portal(user)
    else:customer_portal(user)
    st.sidebar.caption("RUBY · Demand · Aggregate · Negotiate · Save")

main()
