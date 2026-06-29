import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json, io, base64
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(
    page_title="RC Inventory Dashboard",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

FOLDER_ID = "1n2MfzEAcQegvJ8djT4_ZKNRbKEMG7kq6"  # RC inventory folder

# ── Flipkart Email Login (no password) ───────────────────────────────────────
def check_access():
    if "authenticated" not in st.session_state:
        st.markdown("""
        <style>
        body{background:#f4f6f9}
        .block-container{padding-top:60px!important}
        </style>
        <div style="display:flex;flex-direction:column;align-items:center;padding:20px">
          <div style="background:#fff;border-radius:16px;padding:36px 44px;border:1px solid #e2e8f0;
                      text-align:center;max-width:420px;width:100%">
            <div style="font-size:44px;margin-bottom:10px">📦</div>
            <div style="color:#0f2557;font-size:20px;font-weight:700;margin-bottom:4px">
              RC Inventory Dashboard
            </div>
            <div style="color:#64748b;font-size:12px;margin-bottom:20px">
              Flipkart Internal Tool · RC Operations Analytics
            </div>
            <div style="color:#94a3b8;font-size:11px;border-top:1px solid #f1f5f9;
                        padding-top:14px;margin-top:4px">
              Enter your @flipkart.com email to continue
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            email = st.text_input(
                "Flipkart Email",
                placeholder="yourname@flipkart.com",
                label_visibility="collapsed"
            ).strip().lower()

            if st.button("Continue →", use_container_width=True, type="primary"):
                if email.endswith("@flipkart.com"):
                    st.session_state["authenticated"] = True
                    st.session_state["user_email"]    = email
                    st.rerun()
                elif "@" in email and not email.endswith("@flipkart.com"):
                    st.error("❌ Only @flipkart.com email accounts are allowed.")
                else:
                    st.error("❌ Please enter a valid @flipkart.com email.")

            st.markdown(
                "<p style='text-align:center;color:#94a3b8;font-size:11px;margin-top:6px'>"
                "Only @flipkart.com accounts are allowed</p>",
                unsafe_allow_html=True
            )
        st.stop()

    # Sidebar
    with st.sidebar:
        st.markdown(f"👤 **{st.session_state.get('user_email','')}**")
        st.markdown("✅ Flipkart Employee")
        if st.button("Logout"):
            del st.session_state["authenticated"]
            del st.session_state["user_email"]
            st.rerun()

check_access()

AGEING_ORDER = ["<=7 days", "8-15 days", "16-30 days", ">30 days"]

# ── Auth ──────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_drive_service():
    creds = Credentials(
        token=None,
        refresh_token=st.secrets["oauth"]["refresh_token"],
        client_id=st.secrets["oauth"]["client_id"],
        client_secret=st.secrets["oauth"]["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds)

# ── List all CSV files ─────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def list_files():
    svc = get_drive_service()
    res = svc.files().list(
        q=f"'{FOLDER_ID}' in parents and mimeType='text/csv' and trashed=false",
        fields="files(id,name)",
        orderBy="name desc"
    ).execute()
    return res.get("files", [])

# ── Load one file ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_file(file_id):
    svc = get_drive_service()
    buf = io.BytesIO()
    req = svc.files().get_media(fileId=file_id)
    dl  = MediaIoBaseDownload(buf, req, chunksize=10*1024*1024)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return pd.read_csv(buf, low_memory=False)

# ── Build week → file map ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def build_week_map(file_ids_names):
    svc = get_drive_service()
    week_map = {}
    for fid, fname in file_ids_names:
        buf = io.BytesIO()
        req = svc.files().get_media(fileId=fid)
        dl  = MediaIoBaseDownload(buf, req, chunksize=2*1024*1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)
        try:
            sample = pd.read_csv(buf, nrows=3, low_memory=False)
            sample.columns = sample.columns.str.strip()
            if "Calculation_Week" in sample.columns:
                week = str(sample["Calculation_Week"].iloc[0]).strip()
                date = str(sample["Calculation_Date"].iloc[0]).strip() if "Calculation_Date" in sample.columns else fname
                week_map[week] = {"file_id": fid, "file_name": fname, "date": date}
        except Exception:
            pass
    return week_map

def clean(df):
    df.columns = df.columns.str.strip()
    df["quantity"]                = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    df["product_listing_dim_fsp"] = pd.to_numeric(df["product_listing_dim_fsp"], errors="coerce").fillna(0)
    df["atp_flag"]                = pd.to_numeric(df["atp_flag"], errors="coerce").fillna(0).astype(int)
    for c in ["Calculation_Week","warehouse_id","Zone","Alpha/MP Flag",
              "Mapped_Storage_Location","Ageing_Bucket","Calculation_Date"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    return df

def fmt_n(v):
    if v >= 1e7: return f"{v/1e7:.2f}Cr"
    if v >= 1e5: return f"{v/1e5:.2f}L"
    if v >= 1e3: return f"{v/1e3:.1f}K"
    return str(int(v))

def fmt_f(v):
    if v >= 1e7: return f"₹{v/1e7:.2f}Cr"
    if v >= 1e5: return f"₹{v/1e5:.2f}L"
    if v >= 1e3: return f"₹{v/1e3:.1f}K"
    return f"₹{int(v)}"

# ── Load files ─────────────────────────────────────────────────────────────────
with st.spinner("Scanning Google Drive..."):
    all_files = list_files()

if not all_files:
    st.error("No CSV files found in the Google Drive folder.")
    st.stop()

with st.spinner("Building week index..."):
    week_map = build_week_map(tuple([(f["id"], f["name"]) for f in all_files]))

if not week_map:
    st.error("Could not read week data from files.")
    st.stop()

all_weeks = sorted(week_map.keys(), reverse=True)

# ── Week selector ──────────────────────────────────────────────────────────────
selected_week = st.selectbox(
    "📅 Select Week",
    options=all_weeks,
    index=0,
    help="Each week loads its own file from Google Drive"
)

wk_info = week_map[selected_week]
with st.spinner(f"Loading {selected_week}..."):
    df = clean(load_file(wk_info["file_id"]))

# ── Aggregate ─────────────────────────────────────────────────────────────────
GROUP_COLS = ["warehouse_id", "Zone", "Mapped_Storage_Location", "Alpha/MP Flag", "Ageing_Bucket"]

rows = []
for keys, grp in df.groupby(GROUP_COLS, dropna=False):
    d = dict(zip(GROUP_COLS, [str(k) for k in keys]))
    d["qty"]  = int(grp["quantity"].sum())
    d["fsp"]  = round(float(grp["product_listing_dim_fsp"].sum()), 2)
    d["atp1"] = int(grp[grp["atp_flag"]==1]["quantity"].sum())
    d["atp0"] = int(grp[grp["atp_flag"]==0]["quantity"].sum())
    rows.append(d)

summary_json = json.dumps(rows)

# Overall
total_qty  = int(df["quantity"].sum())
total_fsp  = round(float(df["product_listing_dim_fsp"].sum()), 2)
total_atp1 = int(df[df["atp_flag"]==1]["quantity"].sum())
total_atp0 = int(df[df["atp_flag"]==0]["quantity"].sum())
total_aged = int(df[(df["atp_flag"]==1) & (df["Ageing_Bucket"]==">30 days")]["quantity"].sum())
wh_count   = int(df["warehouse_id"].nunique())
total_rec  = len(df)
latest_date = wk_info["date"]

all_wh    = sorted(df["warehouse_id"].unique())
all_zones = sorted(df["Zone"].unique())
all_alpha = sorted(df["Alpha/MP Flag"].unique())
all_locs  = sorted(df["Mapped_Storage_Location"].unique())

def opts(vals):
    return "".join(f'<option value="{v}">{v}</option>' for v in vals)

def zone_rows():
    html = ""
    for zone, zg in df.groupby("Zone"):
        qty  = int(zg["quantity"].sum())
        a0   = int(zg[zg["atp_flag"]==0]["quantity"].sum())
        a1   = int(zg[zg["atp_flag"]==1]["quantity"].sum())
        v1   = int(zg[(zg["atp_flag"]==1)&(zg["Ageing_Bucket"]=="<=7 days")]["quantity"].sum())
        v2   = int(zg[(zg["atp_flag"]==1)&(zg["Ageing_Bucket"]=="8-15 days")]["quantity"].sum())
        v3   = int(zg[(zg["atp_flag"]==1)&(zg["Ageing_Bucket"]=="16-30 days")]["quantity"].sum())
        v4   = int(zg[(zg["atp_flag"]==1)&(zg["Ageing_Bucket"]==">30 days")]["quantity"].sum())
        p    = a1/qty*100 if qty > 0 else 0
        pc   = "rr" if p >= 30 else ("rw" if p >= 15 else "rg")
        if v4 > 0 or p >= 30: st_pill = '<span class="pill r">🔴 Critical</span>'
        elif p >= 15: st_pill = '<span class="pill y">🟡 Watch</span>'
        else: st_pill = '<span class="pill g">🟢 OK</span>'
        html += f"""<tr>
          <td style="text-align:left;font-weight:500;padding:6px 10px">{zone}</td>
          <td style="padding:6px 10px">{fmt_n(qty)}</td>
          <td style="padding:6px 10px" class="rg">{fmt_n(a0)}</td>
          <td style="padding:6px 10px" class="{pc}">{fmt_n(a1)}</td>
          <td style="padding:6px 10px" class="{pc}">{p:.1f}%</td>
          <td style="padding:6px 10px;background:#ecfdf5;color:#065f46;border-left:3px solid #2563eb">{fmt_n(v1)}</td>
          <td style="padding:6px 10px;background:#fffbeb;color:#92400e">{fmt_n(v2)}</td>
          <td style="padding:6px 10px;background:#fff7ed;color:#9a3412">{fmt_n(v3)}</td>
          <td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:600">{fmt_n(v4)}</td>
          <td style="padding:6px 10px">{st_pill}</td>
        </tr>"""
    # Pan India total
    p = total_atp1/total_qty*100 if total_qty > 0 else 0
    tv1 = int(df[(df["atp_flag"]==1)&(df["Ageing_Bucket"]=="<=7 days")]["quantity"].sum())
    tv2 = int(df[(df["atp_flag"]==1)&(df["Ageing_Bucket"]=="8-15 days")]["quantity"].sum())
    tv3 = int(df[(df["atp_flag"]==1)&(df["Ageing_Bucket"]=="16-30 days")]["quantity"].sum())
    tv4 = int(df[(df["atp_flag"]==1)&(df["Ageing_Bucket"]==">30 days")]["quantity"].sum())
    html += f"""<tr class="rt">
      <td style="text-align:left;padding:6px 10px">Pan India Total</td>
      <td style="padding:6px 10px">{fmt_n(total_qty)}</td>
      <td style="padding:6px 10px" class="rg">{fmt_n(total_atp0)}</td>
      <td style="padding:6px 10px" class="rr">{fmt_n(total_atp1)}</td>
      <td style="padding:6px 10px" class="rr">{p:.1f}%</td>
      <td style="padding:6px 10px;background:#ecfdf5;color:#065f46;border-left:3px solid #2563eb">{fmt_n(tv1)}</td>
      <td style="padding:6px 10px;background:#fffbeb;color:#92400e">{fmt_n(tv2)}</td>
      <td style="padding:6px 10px;background:#fff7ed;color:#9a3412">{fmt_n(tv3)}</td>
      <td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:700">{fmt_n(tv4)}</td>
      <td style="padding:6px 10px"><span class="pill r">🔴 Critical</span></td>
    </tr>"""
    return html

def fc_rows():
    html = ""
    for wh, wg in sorted(df.groupby("warehouse_id"), key=lambda x: -x[1]["quantity"].sum()):
        zone  = str(wg["Zone"].iloc[0])
        qty   = int(wg["quantity"].sum())
        a0    = int(wg[wg["atp_flag"]==0]["quantity"].sum())
        a1    = int(wg[wg["atp_flag"]==1]["quantity"].sum())
        v1    = int(wg[(wg["atp_flag"]==1)&(wg["Ageing_Bucket"]=="<=7 days")]["quantity"].sum())
        v2    = int(wg[(wg["atp_flag"]==1)&(wg["Ageing_Bucket"]=="8-15 days")]["quantity"].sum())
        v3    = int(wg[(wg["atp_flag"]==1)&(wg["Ageing_Bucket"]=="16-30 days")]["quantity"].sum())
        v4    = int(wg[(wg["atp_flag"]==1)&(wg["Ageing_Bucket"]==">30 days")]["quantity"].sum())
        p     = a1/qty*100 if qty > 0 else 0
        pc    = "rr" if p >= 30 else ("rw" if p >= 15 else "rg")
        if v4 > 0 or p >= 30:
            st_pill = '<span class="pill r">🔴 Critical</span>'
        elif p >= 15:
            st_pill = '<span class="pill y">🟡 Watch</span>'
        else:
            st_pill = '<span class="pill g">🟢 OK</span>'
        html += f"""<tr>
          <td style="text-align:left;font-weight:500;padding:6px 10px">{wh}</td>
          <td style="text-align:left;padding:6px 10px;color:#475569">{zone}</td>
          <td style="padding:6px 10px">{fmt_n(qty)}</td>
          <td style="padding:6px 10px" class="rg">{fmt_n(a0)}</td>
          <td style="padding:6px 10px" class="{pc}">{fmt_n(a1)}</td>
          <td style="padding:6px 10px" class="{pc}">{p:.1f}%</td>
          <td style="padding:6px 10px;background:#ecfdf5;color:#065f46;border-left:3px solid #2563eb">{fmt_n(v1)}</td>
          <td style="padding:6px 10px;background:#fffbeb;color:#92400e">{fmt_n(v2)}</td>
          <td style="padding:6px 10px;background:#fff7ed;color:#9a3412">{fmt_n(v3)}</td>
          <td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:600">{fmt_n(v4)}</td>
          <td style="padding:6px 10px">{st_pill}</td>
        </tr>"""
    return html

# ── Build HTML ─────────────────────────────────────────────────────────────────
atp1_pct = f"{total_atp1/total_qty*100:.1f}%" if total_qty > 0 else "0%"
atp0_pct = f"{total_atp0/total_qty*100:.1f}%" if total_qty > 0 else "0%"

html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;font-family:'Inter',sans-serif}}
body{{background:#f4f6f9;color:#1a1a2e;font-size:13px}}
.hdr{{background:linear-gradient(135deg,#0f2557,#1a3a7c);padding:14px 20px;display:flex;justify-content:space-between;align-items:center}}
.ht{{color:#fff;font-size:16px;font-weight:600}}
.hs{{color:#93b4e8;font-size:11px;margin-top:3px}}
.lv{{background:rgba(16,185,129,.2);border:1px solid rgba(16,185,129,.4);color:#34d399;font-size:10px;font-weight:600;padding:4px 12px;border-radius:20px;display:flex;align-items:center;gap:5px}}
.pulse{{width:6px;height:6px;border-radius:50%;background:#34d399;animation:pu 1.5s infinite}}
@keyframes pu{{0%{{box-shadow:0 0 0 0 rgba(52,211,153,.5)}}70%{{box-shadow:0 0 0 6px rgba(52,211,153,0)}}100%{{box-shadow:0 0 0 0 rgba(52,211,153,0)}}}}
.fb{{background:#fff;padding:12px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 10px 10px;margin-bottom:14px}}
.fg{{display:flex;flex-direction:column;gap:3px}}
.fl{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#94a3b8}}
.fg select{{font-size:12px;padding:7px 28px 7px 10px;border-radius:8px;border:1.5px solid #e2e8f0;background:#f8fafc;color:#1e293b;min-width:130px;cursor:pointer}}
.whs{{border:2px solid #3b82f6!important;background:#eff6ff!important;font-weight:500;min-width:210px!important}}
.wi{{margin-left:auto;text-align:right;line-height:1.8;font-size:11px;color:#64748b}}
.wi strong{{font-size:16px;font-weight:700;color:#0f2557}}
.wrap{{padding:0 20px 32px}}
.sec{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#3b82f6;border-left:3px solid #3b82f6;padding-left:9px;margin:14px 0 8px}}
.kr{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:14px}}
.kc{{background:#fff;border-radius:10px;padding:14px 16px;border:1px solid #e2e8f0}}
.kc.b{{border-top:3px solid #3b82f6}}.kc.g{{border-top:3px solid #10b981}}.kc.r{{border-top:3px solid #ef4444}}.kc.o{{border-top:3px solid #f59e0b}}
.kl{{font-size:9.5px;color:#64748b;font-weight:500;text-transform:uppercase;letter-spacing:.3px}}
.kv{{font-size:22px;font-weight:700;margin:5px 0 2px}}
.kv.r{{color:#dc2626}}.kv.g{{color:#059669}}.kv.a{{color:#d97706}}.kv.b{{color:#2563eb}}
.ksb{{font-size:10px;color:#94a3b8}}
.tw{{background:#fff;border-radius:10px;border:1px solid #e2e8f0;overflow:hidden;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:11.5px}}
.rh1 th{{background:#0f2557;color:#fff;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.4px;padding:9px 10px;text-align:center;border-right:1px solid rgba(255,255,255,.1);white-space:nowrap}}
.rh1 th:first-child,.rh1 th:nth-child(2){{text-align:left}}
.rh1 th.tth{{background:#1e3a7c;color:#bfdbfe}}
.rh1 th.ath{{background:#064e3b;color:#6ee7b7}}
.rh1 th.bth{{background:#7f1d1d;color:#fecaca}}
.rh1 th.cth{{background:#7c2d12;color:#fed7aa}}
.rh2 th{{background:#f1f5f9;color:#475569;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.4px;padding:6px 10px;border-bottom:2px solid #e2e8f0;border-right:1px solid #e8edf2;text-align:center;white-space:nowrap}}
.rh2 th.ok{{background:#ecfdf5;color:#065f46}}
.rh2 th.w1{{background:#fffbeb;color:#92400e}}
.rh2 th.w2{{background:#fff7ed;color:#9a3412}}
.rh2 th.cr{{background:#fef2f2;color:#991b1b;font-weight:700}}
tbody tr{{border-bottom:1px solid #f1f5f9}}
tbody tr:hover{{background:#f8fafc}}
tbody td{{padding:7px 10px;text-align:center;color:#334155;border-right:1px solid #f1f5f9}}
tbody td:first-child{{text-align:left;font-weight:500;color:#1e293b}}
tbody td:nth-child(2){{text-align:center;color:#475569}}
.lh td{{background:linear-gradient(90deg,#eff6ff,#f8fafc);color:#1d4ed8;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;padding:0!important;border-right:none!important}}
.rs td{{background:#f8fafc;font-weight:600;color:#374151}}
.rt td{{background:linear-gradient(90deg,#eff6ff,#fff);font-weight:700;color:#1e3a7c;border-top:2px solid #bfdbfe}}
.sep td{{padding:3px!important;background:#f4f6f9;border:none!important}}
.rr{{color:#dc2626;font-weight:600}}.rw{{color:#d97706;font-weight:500}}.rg{{color:#059669;font-weight:500}}
.pill{{display:inline-flex;font-size:9px;font-weight:600;padding:2px 8px;border-radius:20px}}
.pill.r{{background:#fef2f2;color:#dc2626;border:1px solid #fecaca}}
.pill.g{{background:#f0fdf4;color:#166534;border:1px solid #bbf7d0}}
.pill.y{{background:#fffbeb;color:#b45309;border:1px solid #fde68a}}
.ac{{background:#fef2f2;color:#dc2626;font-weight:600}}
.aw{{background:#fff7ed;color:#c2410c}}.am{{background:#fffbeb;color:#b45309}}.ag{{background:#f0fdf4;color:#166534}}
.note{{font-size:10px;color:#94a3b8;padding:8px 14px;border-top:1px solid #f1f5f9;background:#f8fafc;display:flex;gap:14px;flex-wrap:wrap}}
.dot{{width:7px;height:7px;border-radius:50%;display:inline-block}}
.nl{{display:flex;align-items:center;gap:4px}}
.divider{{height:1px;background:#e2e8f0;margin:6px 0 16px}}
</style></head><body>

<div class="hdr">
  <div>
    <div class="ht">📦 RC Inventory Dashboard — Pan India</div>
    <div class="hs">Week: {selected_week} · {latest_date} · {fmt_n(total_rec)} records · {wh_count} warehouses</div>
  </div>
  <div class="lv"><span class="pulse"></span> LIVE · {latest_date}</div>
</div>

<div class="fb">
  <div class="fg"><div class="fl" style="color:#3b82f6">🏭 Warehouse</div>
    <select id="fWH" class="whs" onchange="render()"><option value="">All Warehouses (Pan India)</option>{opts(all_wh)}</select></div>
  <div class="fg"><div class="fl">Zone</div>
    <select id="fZone" onchange="render()"><option value="">All Zones</option>{opts(all_zones)}</select></div>
  <div class="fg"><div class="fl">Alpha / MP</div>
    <select id="fAlpha" onchange="render()"><option value="">All</option>{opts(all_alpha)}</select></div>
  <div class="fg"><div class="fl">Storage Type</div>
    <select id="fLoc" onchange="render()"><option value="">All Locations</option>{opts(all_locs)}</select></div>
  <div class="wi">
    <div id="wiLine">All warehouses · {selected_week}</div>
    <strong id="wiTot">{fmt_n(total_qty)}</strong> &nbsp;units · {latest_date}
  </div>
</div>

<div class="wrap">

<div class="sec">🌏 Pan India Overview — Week {selected_week}</div>
<div class="kr" style="grid-template-columns:repeat(6,1fr)">
  <div class="kc b"><div class="kl">Total inventory</div><div class="kv b" id="ovQ">{fmt_n(total_qty)}</div><div class="ksb">{wh_count} warehouses · all zones</div></div>
  <div class="kc g"><div class="kl">✅ Booked (ATP=0)</div><div class="kv g" id="ovA0">{fmt_n(total_atp0)}</div><div class="ksb" id="ovA0s">{atp0_pct} · packed, will move</div></div>
  <div class="kc r"><div class="kl">⚠️ On shelf (ATP=1)</div><div class="kv r" id="ovA1">{fmt_n(total_atp1)}</div><div class="ksb" id="ovA1s">{atp1_pct} · idle, action needed</div></div>
  <div class="kc r"><div class="kl">🔴 Aged &gt;30d qty</div><div class="kv r" id="ovAg">{fmt_n(total_aged)}</div><div class="ksb" id="ovAgPct">— % of on shelf</div></div>
  <div class="kc r"><div class="kl">🔴 Aged &gt;30d FSP</div><div class="kv r" id="ovAgF">—</div><div class="ksb">FSP value at risk</div></div>
  <div class="kc o"><div class="kl">💰 Total FSP value</div><div class="kv a" id="ovFS">{fmt_f(total_fsp)}</div><div class="ksb">overall inventory value</div></div>
</div>

<div class="tw">
<table>
  <thead>
    <tr class="rh1">
      <th style="text-align:left">Zone</th>
      <th class="tth">Total</th>
      <th class="ath">Booked<br><span style="font-size:8px;opacity:.8">ATP=0</span></th>
      <th class="bth">On shelf<br><span style="font-size:8px;opacity:.8">ATP=1</span></th>
      <th class="bth">On shelf<br><span style="font-size:8px;opacity:.8">%</span></th>
      <th colspan="4" class="cth" style="text-align:center">Ageing — On Shelf qty</th>
      <th class="bth">Status</th>
    </tr>
    <tr class="rh2">
      <th style="text-align:left"></th>
      <th></th><th></th><th></th><th></th>
      <th class="ok" style="font-size:9px;border-left:3px solid #2563eb">&#8592; &lt;=7d</th>
      <th class="w1" style="font-size:9px">8-15d</th>
      <th class="w2" style="font-size:9px">16-30d</th>
      <th class="cr" style="font-size:9px">&gt;30d🔴</th>
      <th></th>
    </tr>
  </thead>
  <tbody id="zoneBody">{zone_rows()}</tbody>
</table>
</div>

<div class="divider"></div>
<div class="sec">📦 Mapped Location Inventory View</div>
<div class="tw">
<table style="table-layout:fixed;width:100%">
  <colgroup>
    <col style="width:55px"><col style="width:140px"><col style="width:80px">
    <col style="width:80px"><col style="width:80px"><col style="width:70px">
    <col style="width:68px"><col style="width:68px"><col style="width:68px">
    <col style="width:72px"><col style="width:72px">
  </colgroup>
  <thead>
    <tr class="rh1">
      <th colspan="2" style="text-align:left">Mapped Location / Alpha-MP</th>
      <th class="tth">Total</th>
      <th class="ath">Booked<br><span style="font-size:8px;opacity:.8">ATP=0</span></th>
      <th class="bth">On shelf<br><span style="font-size:8px;opacity:.8">ATP=1</span></th>
      <th class="bth">On shelf<br><span style="font-size:8px;opacity:.8">%</span></th>
      <th colspan="4" class="cth" style="text-align:center">Ageing — On Shelf qty</th>
      <th class="bth">Status</th>
    </tr>
    <tr class="rh2">
      <th colspan="2" style="text-align:left"></th>
      <th></th><th></th><th></th><th></th>
      <th class="ok" style="font-size:9px;border-left:3px solid #2563eb">&#8592; &lt;=7d</th>
      <th class="w1" style="font-size:9px">8-15d</th>
      <th class="w2" style="font-size:9px">16-30d</th>
      <th class="cr" style="font-size:9px">&gt;30d🔴</th>
      <th></th>
    </tr>
  </thead>
  <tbody id="mainBody"></tbody>
</table>
<div class="note">
  <span class="nl"><span class="dot" style="background:#059669"></span> Booked (ATP=0) = packed, will move — good</span>
  <span class="nl"><span class="dot" style="background:#dc2626"></span> On shelf (ATP=1) = idle, needs action — bad</span>
  <span class="nl"><span class="dot" style="background:#dc2626"></span> &gt;30 days always critical</span>
  <span class="nl"><span class="dot" style="background:#f59e0b"></span> Ageing = On Shelf qty only</span>
</div>
</div>
<div class="divider"></div>
<div class="sec">🏭 FC / Warehouse-wise Summary</div>
<div class="tw">
<table>
  <thead>
    <tr class="rh1">
      <th style="text-align:left;min-width:160px">Warehouse (FC)</th>
      <th style="text-align:left">Zone</th>
      <th class="tth">Total</th>
      <th class="ath">Booked<br><span style="font-size:8px;opacity:.8">ATP=0</span></th>
      <th class="bth">On shelf<br><span style="font-size:8px;opacity:.8">ATP=1</span></th>
      <th class="bth">On shelf<br><span style="font-size:8px;opacity:.8">%</span></th>
      <th colspan="4" class="cth" style="text-align:center">Ageing — On Shelf qty</th>
      <th class="bth">Status</th>
    </tr>
    <tr class="rh2">
      <th colspan="2" style="text-align:left"></th>
      <th></th><th></th><th></th><th></th>
      <th class="ok" style="font-size:9px;border-left:3px solid #2563eb">&#8592; &lt;=7d</th>
      <th class="w1" style="font-size:9px">8-15d</th>
      <th class="w2" style="font-size:9px">16-30d</th>
      <th class="cr" style="font-size:9px">&gt;30d🔴</th>
      <th></th>
    </tr>
  </thead>
  <tbody id="fcBody">{fc_rows()}</tbody>
</table>
</div>

</div>

<script>
var DATA={summary_json};

function fN(v){{if(v>=1e7)return(v/1e7).toFixed(2)+'Cr';if(v>=1e5)return(v/1e5).toFixed(2)+'L';if(v>=1e3)return(v/1e3).toFixed(1)+'K';return Math.round(v)+'';}}
function fF(v){{if(v>=1e7)return'₹'+(v/1e7).toFixed(2)+'Cr';if(v>=1e5)return'₹'+(v/1e5).toFixed(2)+'L';if(v>=1e3)return'₹'+(v/1e3).toFixed(1)+'K';return'₹'+Math.round(v);}}
function pt(a,b){{return b>0?(a/b*100).toFixed(1)+'%':'0%';}}
function cc(p){{return p>=30?'rr':p>=15?'rw':'rg';}}
function pill(p,a4){{if(p>=30||a4>0)return'<span class="pill r">🔴 Critical</span>';if(p>=15)return'<span class="pill y">🟡 Watch</span>';return'<span class="pill g">🟢 OK</span>';}}
function s(id,v){{var e=document.getElementById(id);if(e)e.innerHTML=v;}}

function render(){{
  var fWH=document.getElementById('fWH').value;
  var fZ=document.getElementById('fZone').value;
  var fA=document.getElementById('fAlpha').value;
  var fL=document.getElementById('fLoc').value;

  var d=DATA.filter(function(r){{
    return(!fWH||r.warehouse_id===fWH)&&(!fZ||r.Zone===fZ)&&
           (!fA||r['Alpha/MP Flag']===fA)&&(!fL||r.Mapped_Storage_Location===fL);
  }});

  var tQ=d.reduce(function(s,r){{return s+r.qty;}},0);
  var a0=d.reduce(function(s,r){{return s+r.atp0;}},0);
  var a1=d.reduce(function(s,r){{return s+r.atp1;}},0);
  var ag=d.filter(function(r){{return r.Ageing_Bucket==='>30 days';}}).reduce(function(s,r){{return s+r.atp1;}},0);
  var tF=d.reduce(function(s,r){{return s+r.fsp;}},0);

  ['ovQ'].forEach(function(id){{s(id,fN(tQ));}});
  s('ovA0',fN(a0));s('ovA1',fN(a1));s('ovAg',fN(ag));s('ovFS',fF(tF));
  s('ovA0s',pt(a0,tQ)+' · packed, will move');
  s('ovA1s',pt(a1,tQ)+' · idle, needs action');
  var agPct=a1>0?(ag/a1*100).toFixed(1)+'% of on shelf':'0% of on shelf';
  s('ovAgPct',agPct);
  var agFsp=d.filter(function(r){{return r.Ageing_Bucket==='>30 days';}}).reduce(function(s,r){{return s+r.fsp;}},0);
  s('ovAgF',fF(agFsp));
  s('wiTot',fN(tQ));
  s('wiLine',(fWH||'All warehouses')+' · {selected_week}'+(fZ?' · '+fZ:'')+(fA?' · '+fA:'')+(fL?' · '+fL:''));

  // Zone table
  var zm={{}};
  d.forEach(function(r){{
    if(!zm[r.Zone])zm[r.Zone]={{qty:0,a0:0,a1:0,ag:0,fsp:0}};
    zm[r.Zone].qty+=r.qty;zm[r.Zone].a0+=r.atp0;zm[r.Zone].a1+=r.atp1;zm[r.Zone].fsp+=r.fsp;
    if(r.Ageing_Bucket==='>30 days')zm[r.Zone].ag+=r.atp1;
  }});
  var zH=Object.keys(zm).sort(function(a,b){{return zm[b].qty-zm[a].qty;}}).map(function(z){{
    var zd=zm[z];var p=zd.qty>0?zd.a1/zd.qty*100:0;var pc=cc(p);
    return'<tr><td style="text-align:left;font-weight:500;padding:6px 10px">'+z+'</td>'+
      '<td style="padding:6px 10px">'+fN(zd.qty)+'</td>'+
      '<td style="padding:6px 10px" class="rg">'+fN(zd.a0)+'</td>'+
      '<td style="padding:6px 10px" class="'+pc+'">'+fN(zd.a1)+'</td>'+
      '<td style="padding:6px 10px" class="'+pc+'">'+pt(zd.a1,zd.qty)+'</td>'+
      '<td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:600">'+fN(zd.ag)+'</td>'+
      '<td style="padding:6px 10px;color:#d97706;font-weight:500">'+fF(zd.fsp)+'</td></tr>';
  }}).join('');
  zH+='<tr class="rt"><td style="text-align:left;padding:6px 10px">Pan India Total</td>'+
    '<td style="padding:6px 10px">'+fN(tQ)+'</td><td style="padding:6px 10px" class="rg">'+fN(a0)+'</td>'+
    '<td style="padding:6px 10px" class="rr">'+fN(a1)+'</td><td style="padding:6px 10px" class="rr">'+pt(a1,tQ)+'</td>'+
    '<td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:700">'+fN(ag)+'</td>'+
    '<td style="padding:6px 10px;color:#d97706;font-weight:600">'+fF(tF)+'</td></tr>';
  s('zoneBody',zH);

  // FC table
  var fm={{}};
  d.forEach(function(r){{
    if(!fm[r.warehouse_id])fm[r.warehouse_id]={{z:r.Zone,qty:0,a0:0,a1:0,ag:0,fsp:0}};
    fm[r.warehouse_id].qty+=r.qty;fm[r.warehouse_id].a0+=r.atp0;fm[r.warehouse_id].a1+=r.atp1;fm[r.warehouse_id].fsp+=r.fsp;
    if(r.Ageing_Bucket==='>30 days')fm[r.warehouse_id].ag+=r.atp1;
  }});
  var fcH=Object.keys(fm).sort(function(a,b){{return fm[b].qty-fm[a].qty;}}).map(function(wh){{
    var fd=fm[wh];var p=fd.qty>0?fd.a1/fd.qty*100:0;var ap=fd.qty>0?fd.ag/fd.qty*100:0;
    return'<tr>'+
      '<td style="text-align:left;font-weight:500;padding:6px 10px">'+wh+'</td>'+
      '<td style="text-align:left;padding:6px 10px;color:#475569">'+fd.z+'</td>'+
      '<td style="padding:6px 10px">'+fN(fd.qty)+'</td>'+
      '<td style="padding:6px 10px" class="rg">'+fN(fd.a0)+'</td>'+
      '<td style="padding:6px 10px" class="'+cc(p)+'">'+fN(fd.a1)+'</td>'+
      '<td style="padding:6px 10px" class="'+cc(p)+'">'+p.toFixed(1)+'%</td>'+
      '<td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:600">'+fN(fd.ag)+'</td>'+
      '<td style="padding:6px 10px" class="'+(ap>15?'rr':ap>8?'rw':'rg')+'">'+ap.toFixed(1)+'%</td>'+
      '<td style="padding:6px 10px;color:#d97706;font-weight:500">'+fF(fd.fsp)+'</td>'+
      '<td style="padding:6px 10px">'+pill(p,fd.ag)+'</td></tr>';
  }}).join('');
  fcH+='<tr class="rt"><td colspan="2" style="text-align:left;padding:6px 10px">Grand Total</td>'+
    '<td style="padding:6px 10px">'+fN(tQ)+'</td><td style="padding:6px 10px" class="rg">'+fN(a0)+'</td>'+
    '<td style="padding:6px 10px" class="rr">'+fN(a1)+'</td><td style="padding:6px 10px" class="rr">'+pt(a1,tQ)+'</td>'+
    '<td style="padding:6px 10px;background:#fef2f2;color:#991b1b;font-weight:700">'+fN(ag)+'</td>'+
    '<td style="padding:6px 10px" class="rr">'+pt(ag,tQ)+'</td>'+
    '<td style="padding:6px 10px;color:#d97706;font-weight:600">'+fF(tF)+'</td>'+
    '<td style="padding:6px 10px">'+pill(a1/Math.max(tQ,1)*100,ag)+'</td></tr>';
  s('fcBody',fcH);

  // Storage type breakdown
  var tree={{}};
  d.forEach(function(r){{
    if(!tree[r.Mapped_Storage_Location])tree[r.Mapped_Storage_Location]={{}};
    if(!tree[r.Mapped_Storage_Location][r['Alpha/MP Flag']])
      tree[r.Mapped_Storage_Location][r['Alpha/MP Flag']]={{qty:0,a0:0,a1:0,v:{{}}}};
    var n=tree[r.Mapped_Storage_Location][r['Alpha/MP Flag']];
    n.qty+=r.qty;n.a0+=r.atp0;n.a1+=r.atp1;
    n.v[r.Ageing_Bucket]=(n.v[r.Ageing_Bucket]||0)+r.atp1;
  }});
  var slC={{'disposal_area':'#dc2626','main_storage':'#2563eb','processing_area':'#059669','qc_hold_area':'#d97706'}};
  var slI={{'disposal_area':'🗑️','main_storage':'📦','processing_area':'🔧','qc_hold_area':'🔍'}};
  var slKeys=Object.keys(tree).sort(function(a,b){{
    return Object.values(tree[b]).reduce(function(s,n){{return s+n.qty;}},0)-
           Object.values(tree[a]).reduce(function(s,n){{return s+n.qty;}},0);
  }});
  var mH='';
  var gt={{qty:0,a0:0,a1:0,v1:0,v2:0,v3:0,v4:0}};
  slKeys.forEach(function(sl,idx){{
    var c=slC[sl]||'#3b82f6';var ic=slI[sl]||'📋';
    mH+='<tr class="lh" style="border-top:3px solid '+c+'">'+
      '<td colspan="11" style="padding:8px 14px;border-left:5px solid '+c+';background:linear-gradient(90deg,rgba(255,255,255,.95),#f8fafc)">'+
        '<span style="font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:'+c+'">'+ic+' '+sl+'</span>'+
      '</td></tr>';
    var st={{qty:0,a0:0,a1:0,v1:0,v2:0,v3:0,v4:0}};
    Object.keys(tree[sl]).sort().forEach(function(am){{
      var n=tree[sl][am];
      var v1=n.v['<=7 days']||0,v2=n.v['8-15 days']||0,v3=n.v['16-30 days']||0,v4=n.v['>30 days']||0;
      var p=n.qty>0?n.a1/n.qty*100:0;
      st.qty+=n.qty;st.a0+=n.a0;st.a1+=n.a1;st.v1+=v1;st.v2+=v2;st.v3+=v3;st.v4+=v4;
      gt.qty+=n.qty;gt.a0+=n.a0;gt.a1+=n.a1;gt.v1+=v1;gt.v2+=v2;gt.v3+=v3;gt.v4+=v4;
      var amB=am==='alpha'?
        '<span style="background:#dbeafe;color:#1d4ed8;font-size:9px;font-weight:600;padding:1px 6px;border-radius:20px">Alpha</span>':
        '<span style="background:#fce7f3;color:#9d174d;font-size:9px;font-weight:600;padding:1px 6px;border-radius:20px">MP</span>';
      mH+='<tr>'+
        '<td style="padding:6px 4px 6px 8px;text-align:center;border-left:5px solid '+c+'">'+amB+'</td>'+
        '<td style="padding-left:8px;font-weight:400;color:#64748b;font-size:11px">'+sl+'</td>'+
        '<td>'+fN(n.qty)+'</td><td class="rg">'+fN(n.a0)+'</td>'+
        '<td class="'+cc(p)+'">'+fN(n.a1)+'</td><td class="'+cc(p)+'">'+p.toFixed(1)+'%</td>'+
        '<td class="ag" style="border-left:3px solid #2563eb">'+fN(v1)+'</td>'+
        '<td class="am">'+fN(v2)+'</td><td class="aw">'+fN(v3)+'</td>'+
        '<td class="ac">'+fN(v4)+'</td><td>'+pill(p,v4)+'</td></tr>';
    }});
    var sp=st.qty>0?st.a1/st.qty*100:0;
    mH+='<tr class="rs">'+
      '<td colspan="2" style="text-align:left;padding-left:14px;font-size:11px;border-left:5px solid '+c+'">Subtotal</td>'+
      '<td>'+fN(st.qty)+'</td><td class="rg">'+fN(st.a0)+'</td>'+
      '<td class="'+cc(sp)+'">'+fN(st.a1)+'</td><td class="'+cc(sp)+'">'+sp.toFixed(1)+'%</td>'+
      '<td style="border-left:3px solid #2563eb">'+fN(st.v1)+'</td>'+
      '<td>'+fN(st.v2)+'</td><td>'+fN(st.v3)+'</td>'+
      '<td class="ac">'+fN(st.v4)+'</td><td>'+pill(sp,st.v4)+'</td></tr>';
  }});
  var gp=gt.qty>0?gt.a1/gt.qty*100:0;
  var tot1=gt.a1||1;
  var c1=(gt.v1/tot1*100).toFixed(1),c2=(gt.v2/tot1*100).toFixed(1),c3=(gt.v3/tot1*100).toFixed(1),c4=(gt.v4/tot1*100).toFixed(1);
  mH+='<tr><td colspan="11" style="padding:0;border-top:2px solid #e2e8f0"></td></tr>'+
    '<tr class="rt">'+
    '<td colspan="2" style="text-align:left">Grand Total</td>'+
    '<td>'+fN(gt.qty)+'</td><td class="rg">'+fN(gt.a0)+'</td>'+
    '<td class="'+cc(gp)+'">'+fN(gt.a1)+'</td><td class="'+cc(gp)+'">'+gp.toFixed(1)+'%</td>'+
    '<td class="ag" style="border-left:3px solid #2563eb">'+fN(gt.v1)+'</td>'+
    '<td class="am">'+fN(gt.v2)+'</td><td class="aw">'+fN(gt.v3)+'</td>'+
    '<td class="ac" style="font-size:13px">'+fN(gt.v4)+'</td><td>'+pill(gp,gt.v4)+'</td></tr>'+
    '<tr style="background:#f0f4ff;border-top:2px dashed #bfdbfe">'+
      '<td colspan="2" style="text-align:left;padding:6px 10px;font-size:10px;font-weight:700;color:#1d4ed8;text-transform:uppercase;letter-spacing:.5px">% Contribution by Ageing</td>'+

      '<td colspan="4" style="padding:6px 10px;font-size:10px;color:#64748b;text-align:center">— of total on shelf (ATP=1) qty —</td>'+
      '<td style="padding:6px 10px;text-align:center;background:#ecfdf5;color:#065f46;font-weight:700;font-size:12px;border-left:3px solid #2563eb">'+c1+'%</td>'+
      '<td style="padding:6px 10px;text-align:center;background:#fffbeb;color:#92400e;font-weight:700;font-size:12px">'+c2+'%</td>'+
      '<td style="padding:6px 10px;text-align:center;background:#fff7ed;color:#9a3412;font-weight:700;font-size:12px">'+c3+'%</td>'+
      '<td style="padding:6px 10px;text-align:center;background:#fef2f2;color:#991b1b;font-weight:700;font-size:14px">'+c4+'%</td>'+
      '<td style="padding:6px 10px;text-align:center;font-size:10px;color:#64748b">of on shelf</td></tr>'+
    '<tr style="background:#f0f4ff">'+
      '<td colspan="6" style="padding:4px 10px;font-size:10px;color:#64748b;border-top:none"></td>'+
      '<td colspan="4" style="padding:3px 0">'+
        '<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin:0 8px">'+
          '<div style="width:'+c1+'%;background:#059669;transition:width .4s"></div>'+
          '<div style="width:'+c2+'%;background:#d97706;transition:width .4s"></div>'+
          '<div style="width:'+c3+'%;background:#ea580c;transition:width .4s"></div>'+
          '<div style="width:'+c4+'%;background:#dc2626;transition:width .4s"></div>'+
        '</div></td><td></td></tr>';
  s('mainBody',mH);
}}
render();
</script></body></html>"""

html_clean = html.encode('utf-8','replace').decode('utf-8')
components.html(html_clean, height=5500, scrolling=True)
