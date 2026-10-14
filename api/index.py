# api/index.py
# Flask app adapted for Vercel serverless (pure HTTP, no Playwright).
# Vercel expects a module-level WSGI callable named `app`.

from flask import Flask, request, jsonify
import requests
import re
import time
import random
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SITE CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PAYMENT_SITES = {
    "pixelcraft": {
        "name": "PIXEL CRAFT",
        "url": "https://razorpay.me/@pixelcraft",
        "merchant_id": "NK4vZaNgI2K8Hu",
        "payment_link_id": "pl_NVzgjMSIIkHYOh",
        "key_id": "rzp_live_fznVYsMZcAQfBp",
    }
}

RAZORPAY_API = "https://api.razorpay.com/v1"
TIMEOUT = 15

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://razorpay.me",
    "Referer": "https://razorpay.me/",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORDER CREATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_order(site="pixelcraft", amount=100):
    """
    Create a Razorpay order against the payment page.
    Returns (order_id, error).
    """
    site_config = PAYMENT_SITES.get(site)
    if not site_config:
        return None, f"Site '{site}' not found. Available: {list(PAYMENT_SITES.keys())}"

    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)

    order_id = None
    error = None

    try:
        # Step 1: Open the payment page to pick up any session cookies / csrf.
        s = requests.Session()
        s.verify = False
        s.headers.update(headers)

        r_page = s.get(site_config["url"], timeout=TIMEOUT)
        if r_page.status_code >= 400:
            return None, f"Page load failed: HTTP {r_page.status_code}"

        # Step 2: Extract a csrf token / key if present in the page.
        csrf = None
        m = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', r_page.text)
        if m:
            csrf = m.group(1)
        key_id = site_config["key_id"]
        mk = re.search(r'(rzp_live_[A-Za-z0-9]+)', r_page.text)
        if mk:
            key_id = mk.group(1)

        # Step 3: Extract payment_link_id / merchant info from page if present.
        plink = site_config["payment_link_id"]
        mp = re.search(r'(pl_[A-Za-z0-9]+)', r_page.text)
        if mp:
            plink = mp.group(1)

        # Step 4: Create the order via Razorpay's public order endpoint.
        # This endpoint is what the browser checkout calls internally.
        payload = {
            "amount": int(amount) * 100,  # paise
            "currency": "INR",
            "receipt": f"rcpt_{int(time.time())}_{random.randint(1000, 9999)}",
            "notes": {
                "site": site,
                "payment_link_id": plink,
            },
        }
        order_headers = dict(headers)
        order_headers["Authorization"] = f"Basic {key_id}:"
        order_headers["X-Razorpay-Key"] = key_id
        if csrf:
            order_headers["X-CSRF-Token"] = csrf

        r_order = s.post(
            f"{RAZORPAY_API}/orders",
            json=payload,
            headers=order_headers,
            timeout=TIMEOUT,
        )

        if r_order.status_code in (200, 201):
            data = r_order.json()
            order_id = data.get("id") or data.get("order_id")
        else:
            # Fallback: pull any order_ id from the response body.
            m = re.search(r'(order_[A-Za-z0-9]+)', r_order.text)
            if m:
                order_id = m.group(1)
            else:
                error = f"Order HTTP {r_order.status_code}: {r_order.text[:180]}"

        # Fallback: some pages pre-bake an order id.
        if not order_id:
            m = re.search(r'(order_[A-Za-z0-9]+)', r_page.text)
            if m:
                order_id = m.group(1)

    except requests.exceptions.Timeout:
        error = "Request timed out"
    except requests.exceptions.RequestException as e:
        error = f"Network error: {e}"
    except Exception as e:
        error = f"Unexpected: {e}"

    return order_id, error

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/")
def home():
    return jsonify({
        "api": "Razorpay Order API",
        "endpoints": ["/api/razorpay_order", "/api/razorpay_charge", "/api/sites", "/api/health"],
        "Owner": "t.me/RASHIK_69",
    })

@app.route("/api/razorpay_order")
def razorpay_order():
    site = request.args.get("site", "pixelcraft")
    try:
        amount = int(request.args.get("amount", 100))
    except ValueError:
        return jsonify({
            "status": "ERROR",
            "message": "amount must be an integer",
            "Owner": "t.me/RASHIK_69",
        }), 400

    order_id, error = create_order(site, amount)

    if order_id:
        return jsonify({
            "status": "SUCCESS",
            "message": "Order created successfully",
            "order_id": order_id,
            "amount": f"₹{amount}",
            "merchant": PAYMENT_SITES.get(site, {}).get("name", "UNKNOWN"),
            "payment_link": PAYMENT_SITES.get(site, {}).get("url"),
            "Owner": "t.me/RASHIK_69",
        })

    return jsonify({
        "status": "ERROR",
        "message": f"Could not create order: {error}",
        "order_id": None,
        "amount": f"₹{amount}",
        "Owner": "t.me/RASHIK_69",
    }), 500

@app.route("/api/razorpay_charge")
def razorpay_charge():
    return razorpay_order()

@app.route("/api/sites")
def list_sites():
    return jsonify({"sites": list(PAYMENT_SITES.keys())})

@app.route("/api/health")
def health():
    return jsonify({"status": "OK"})

# Vercel uses the module-level `app` WSGI callable.
# Do NOT include app.run() here.
