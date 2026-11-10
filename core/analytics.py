from __future__ import annotations
from collections import Counter
import itertools
import numpy as np
import pandas as pd
from sqlalchemy import select
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score, silhouette_score
from .db import User, Zone, Product, Campaign, CampaignSnapshot, Order, OrderItem, VendorQuote, Vendor, utcnow

def frames(session):
    orders=session.scalars(select(Order)).all()
    items=session.scalars(select(OrderItem)).all()
    users={u.id:u for u in session.scalars(select(User)).all()}
    zones={z.id:z for z in session.scalars(select(Zone)).all()}
    products={p.id:p for p in session.scalars(select(Product)).all()}
    order_rows=[]; line_rows=[]
    item_by_order={}
    for it in items:
        item_by_order.setdefault(it.order_id,[]).append(it)
    for o in orders:
        u=users.get(o.customer_id); z=zones.get(o.zone_id)
        order_rows.append({"order_id":o.id,"order_number":o.order_number,"customer_id":o.customer_id,
            "city":z.city if z else "Unknown","state":z.state if z else "Unknown","pincode":z.pincode if z else "",
            "status":o.status,"payment_status":o.payment_status,"revenue":o.total_amount,"created_at":o.created_at})
        for it in item_by_order.get(o.id,[]):
            p=products.get(it.product_id)
            if p:
                line_rows.append({"order_id":o.id,"customer_id":o.customer_id,"city":z.city if z else "Unknown",
                    "pincode":z.pincode if z else "","product":p.name,"sku":p.sku,"category":p.category,
                    "quantity":it.quantity,"unit_price":it.unit_price,"unit_cost":it.unit_cost,
                    "revenue":it.quantity*it.unit_price,"margin":it.quantity*(it.unit_price-it.unit_cost),
                    "created_at":o.created_at})
    return pd.DataFrame(order_rows),pd.DataFrame(line_rows)

def customer_segments(orders: pd.DataFrame):
    if orders.empty: return None,"No order history yet."
    df=orders[orders.payment_status=="PAID"].copy()
    if len(df.customer_id.unique())<12: return None,"At least 12 paying customers are needed for a stable three-group segmentation."
    ref=df.created_at.max()
    r=df.groupby("customer_id").agg(recency_days=("created_at",lambda x:(ref-x.max()).days),frequency=("order_id","count"),monetary=("revenue","sum")).reset_index()
    features=np.log1p(r[["recency_days","frequency","monetary"]].clip(lower=0))
    scaled=StandardScaler().fit_transform(features)
    model=KMeans(n_clusters=3,random_state=42,n_init=10)
    r["segment_id"]=model.fit_predict(scaled)
    profile=r.groupby("segment_id").agg(customers=("customer_id","count"),avg_recency=("recency_days","mean"),avg_orders=("frequency","mean"),avg_spend=("monetary","mean")).reset_index()
    names={}
    # More spend and frequency, lower recency is a stronger repeat/value segment.
    score=profile.set_index("segment_id")["avg_orders"]*profile.set_index("segment_id")["avg_spend"]/(profile.set_index("segment_id")["avg_recency"]+7)
    sorted_ids=list(score.sort_values(ascending=False).index)
    labels=["Core community","Growing customers","Occasional buyers"]
    names={sid:labels[i] for i,sid in enumerate(sorted_ids)}
    r["segment"]=r.segment_id.map(names)
    profile["segment"]=profile.segment_id.map(names)
    return (r,profile),None

def campaign_classification(session, campaigns, open_features=None):
    hist=[c for c in campaigns if c.reached_moq is not None and c.status in {"COMPLETED","CLOSED"}]
    if len(hist)<30: return None,"At least 30 completed campaigns with recorded MOQ outcomes are needed."
    snapshots=session.scalars(select(CampaignSnapshot).order_by(CampaignSnapshot.snapshot_at)).all()
    campaign_by_id={c.id:c for c in hist}
    latest={}
    for snap in snapshots:
        campaign=campaign_by_id.get(snap.campaign_id)
        if campaign and snap.snapshot_at < campaign.cutoff_at:
            latest[snap.campaign_id]=snap
    hist=[c for c in hist if c.id in latest]
    hist=sorted(hist,key=lambda c:c.created_at)
    if len(hist)<30: return None,"At least 30 completed campaigns with a saved pre-cutoff demand snapshot and recorded MOQ outcome are needed."
    y=np.array([int(c.reached_moq) for c in hist])
    if len(set(y))<2: return None,"Historical data currently contains only one campaign outcome class."
    rows=[]
    for c in hist:
        snap=latest[c.id]
        rows.append([snap.demand_units,c.target_units,snap.participants,snap.days_to_cutoff,snap.product_count])
    X=np.array(rows,dtype=float)
    split=max(1,int(len(X)*.8))
    X_train,X_test=X[:split],X[split:]
    y_train,y_test=y[:split],y[split:]
    def build_model():
        return Pipeline([("scale",StandardScaler()),("model",LogisticRegression(max_iter=1000,class_weight="balanced",random_state=42))])
    holdout_accuracy=None
    if len(X_test)>=4 and len(set(y_train))==2 and len(set(y_test))==2:
        validation=build_model().fit(X_train,y_train)
        holdout_accuracy=float(accuracy_score(y_test,validation.predict(X_test)))
    model=build_model().fit(X,y)
    result={"model":model,"accuracy_holdout":holdout_accuracy,"n":len(hist),"success_rate":float(y.mean())}
    if open_features is not None:
        result["probability"]=float(model.predict_proba(np.array(open_features,dtype=float).reshape(1,-1))[0][1])
    return result,None

def demand_regression(lines: pd.DataFrame):
    if lines.empty or len(lines)<60: return None,"At least 60 historical paid order lines are needed before fitting a demand model."
    data=lines.copy().sort_values("created_at")
    data["month"]=pd.to_datetime(data.created_at).dt.month
    def build_model():
        pre=ColumnTransformer([("cat",OneHotEncoder(handle_unknown="ignore"),["city","category"]),
                               ("num",StandardScaler(),["unit_price","month"])])
        return Pipeline([("features",pre),("model",RandomForestRegressor(n_estimators=120,min_samples_leaf=2,random_state=42,n_jobs=1))])
    X=data[["city","category","unit_price","month"]]
    y=data.quantity.astype(float)
    split=max(1,int(len(data)*.8))
    holdout_mae=None;holdout_r2=None
    if len(data)-split>=10:
        validation=build_model().fit(X.iloc[:split],y.iloc[:split])
        pred=validation.predict(X.iloc[split:])
        holdout_mae=float(mean_absolute_error(y.iloc[split:],pred))
        holdout_r2=float(r2_score(y.iloc[split:],pred)) if y.iloc[split:].nunique()>1 else None
    model=build_model().fit(X,y)
    return {"model":model,"n":len(data),"mae_holdout":holdout_mae,"r2_holdout":holdout_r2},None

def market_basket(lines: pd.DataFrame, min_pair_count=3):
    if lines.empty: return pd.DataFrame()
    baskets=lines.groupby("order_id")["product"].apply(lambda s:sorted(set(s))).tolist()
    counts=Counter(); singles=Counter()
    for b in baskets:
        for p in b: singles[p]+=1
        for a,c in itertools.combinations(b,2): counts[(a,c)]+=1
    rows=[]; n=max(1,len(baskets))
    for (a,b),v in counts.items():
        if v>=min_pair_count:
            rows.append({"Product A":a,"Product B":b,"Orders together":v,"Support %":round(v/n*100,1),
                         "Confidence A→B %":round(v/max(1,singles[a])*100,1),"Confidence B→A %":round(v/max(1,singles[b])*100,1)})
    return pd.DataFrame(rows).sort_values("Orders together",ascending=False) if rows else pd.DataFrame()

def quote_anomalies(session):
    qs=session.scalars(select(VendorQuote)).all(); products={p.id:p.name for p in session.scalars(select(Product)).all()}; vendors={v.id:v.business_name for v in session.scalars(select(Vendor)).all()}
    rows=[]
    by={}
    for q in qs: by.setdefault(q.product_id,[]).append(q)
    for pid,arr in by.items():
        vals=np.array([q.unit_cost for q in arr],dtype=float)
        med=float(np.median(vals)); mad=float(np.median(np.abs(vals-med)))
        for q in arr:
            if len(vals)>=4 and mad>0 and abs(q.unit_cost-med)>3*1.4826*mad:
                rows.append({"Product":products.get(pid,"—"),"Vendor":vendors.get(q.vendor_id,"—"),"Quote (₹)":q.unit_cost,"Median (₹)":round(med,2),"Signal":"Review quote"})
    return pd.DataFrame(rows)
