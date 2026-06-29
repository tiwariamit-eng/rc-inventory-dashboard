# RC Inventory Dashboard

## Files needed on your Desktop

```
rc-inventory-dashboard/
├── app.py                  ← Main dashboard file
├── requirements.txt        ← Python packages
├── secrets_template.toml   ← Copy this to .streamlit/secrets.toml
└── README.md
```

## Setup Steps

### Step 1 — Create folder on Desktop
```
C:\Users\tiwari.amit\OneDrive - Flipkart Internet Pvt. Ltd\Desktop\rc-inventory-dashboard\
```

### Step 2 — Create secrets file
Create folder `.streamlit` inside the project folder and add `secrets.toml`:
```
rc-inventory-dashboard/
└── .streamlit/
    └── secrets.toml   ← copy from secrets_template.toml and fill values
```

Use the SAME credentials as your resealing dashboard.

### Step 3 — Push to GitHub
```cmd
cd "C:\Users\tiwari.amit\OneDrive - Flipkart Internet Pvt. Ltd\Desktop\rc-inventory-dashboard"
git init
git add .
git commit -m "Initial RC inventory dashboard"
git branch -M main
git remote add origin https://github.com/tiwariamit-eng/rc-inventory-dashboard.git
git push -u origin main
```

### Step 4 — Deploy on Streamlit Cloud
1. Go to https://share.streamlit.io
2. New app → connect GitHub repo `rc-inventory-dashboard`
3. Add secrets (same Google OAuth tokens as resealing dashboard)
4. Deploy!

## Data
- Google Drive Folder: 1n2MfzEAcQegvJ8djT4_ZKNRbKEMG7kq6
- Each CSV file = one week of inventory data
- Naming: Consolidated_Inventory_Data_YYYY-MM-DD.csv
- Data refreshes every 1 hour automatically

## Access
- Share the Streamlit URL with your team
- Anyone with the link can view
- Data is read-only from Drive
