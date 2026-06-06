"""
NimbusWMS – Warehouse Management System
Role-based cloud demo (BTEC Unit 6)
"""
import os
import socket
import sqlite3
import time
import hashlib
from datetime import datetime
from functools import wraps
from flask import (Flask, g, render_template, request, redirect,
                   url_for, session, flash, jsonify)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WMS_DB", os.path.join(APP_DIR, "wms.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("WMS_SECRET", "change-me-in-production")

# ── Role permission sets ──────────────────────────────────────────────────────
ALL_ROLES        = ["superadmin", "admin", "manager", "sales", "warehouse", "staff"]

# admin = view-only checker; only superadmin has full control
MANAGE_USERS     = {"superadmin"}                               # create/edit/delete users
VIEW_USERS       = {"superadmin", "admin"}                      # view user list
MANAGE_PRODUCTS  = {"superadmin", "manager", "warehouse"}       # create/edit products
ALL_EXCEPT_STAFF = {"superadmin", "admin", "manager", "sales", "warehouse"}
CREATE_ORDERS    = {"superadmin", "manager", "sales"}           # admin cannot create
UPDATE_ORDERS    = {"superadmin", "manager", "warehouse"}
DELETE_PRIV      = {"superadmin", "manager"}                    # admin cannot delete
VIEW_ANALYTICS   = {"superadmin", "manager"}

ORDER_STATUSES = ["Pending", "Confirmed", "Packing", "Shipped", "Cancelled"]


# ── Instance identity ─────────────────────────────────────────────────────────
def get_instance_id():
    cached = getattr(get_instance_id, "_cache", None)
    if cached:
        return cached
    instance_id = socket.gethostname()
    try:
        import urllib.request
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        token = urllib.request.urlopen(token_req, timeout=0.3).read().decode()
        meta_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token})
        instance_id = urllib.request.urlopen(meta_req, timeout=0.3).read().decode()
    except Exception:
        pass
    get_instance_id._cache = instance_id
    return instance_id


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username   TEXT UNIQUE NOT NULL,
        password   TEXT NOT NULL,
        full_name  TEXT,
        email      TEXT,
        role       TEXT NOT NULL DEFAULT 'staff',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS customers (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT NOT NULL,
        email          TEXT,
        phone          TEXT,
        address        TEXT,
        contact_person TEXT,
        created_at     TEXT
    );
    CREATE TABLE IF NOT EXISTS products (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        sku           TEXT UNIQUE NOT NULL,
        name          TEXT NOT NULL,
        category      TEXT,
        size          TEXT,
        color         TEXT,
        quantity      INTEGER NOT NULL DEFAULT 0,
        reorder_level INTEGER NOT NULL DEFAULT 10,
        price         REAL NOT NULL DEFAULT 0,
        updated_at    TEXT
    );
    CREATE TABLE IF NOT EXISTS orders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        reference   TEXT UNIQUE NOT NULL,
        customer_id INTEGER REFERENCES customers(id),
        customer    TEXT NOT NULL,
        sku         TEXT NOT NULL,
        qty         INTEGER NOT NULL,
        status      TEXT NOT NULL DEFAULT 'Pending',
        notes       TEXT,
        created_by  TEXT,
        created_at  TEXT,
        updated_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS stock_movements (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        sku        TEXT NOT NULL,
        type       TEXT NOT NULL,
        qty_change INTEGER NOT NULL,
        reference  TEXT,
        user       TEXT,
        created_at TEXT
    );
    """)
    db.commit()
    now = datetime.utcnow().isoformat(timespec="seconds")

    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_users = [
            ("superadmin", hash_pw("super123"),  "Super Admin",   "superadmin@nimbus.com", "superadmin"),
            ("admin",      hash_pw("admin123"),  "Admin User",    "admin@nimbus.com",      "admin"),
            ("manager1",   hash_pw("mgr123"),    "Sarah Johnson", "sarah@nimbus.com",      "manager"),
            ("sales1",     hash_pw("sales123"),  "Tom Richards",  "tom@nimbus.com",        "sales"),
            ("warehouse1", hash_pw("wh123"),     "Mike Chen",     "mike@nimbus.com",       "warehouse"),
            ("staff1",     hash_pw("staff123"),  "Lisa Park",     "lisa@nimbus.com",       "staff"),
        ]
        db.executemany(
            "INSERT INTO users (username,password,full_name,email,role,created_at) VALUES (?,?,?,?,?,?)",
            [(u[0], u[1], u[2], u[3], u[4], now) for u in seed_users])
    db.commit()

    if db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        seed_customers = [
            ("Hamid Textile LLC",     "hamid@hamidtextile.com",  "+971-50-1234567", "Trade Center, Dubai",      "Hamid Al-Rashid"),
            ("Bukhara Bazaar Retail", "orders@bukharabazaar.com","+998-90-1234567", "Silk Rd Market, Tashkent", "Elena Karimova"),
            ("Silk Road Outfitters",  "purchasing@silkroad.com", "+90-532-1234567", "Grand Bazaar, Istanbul",   "James Park"),
            ("Nordic Fashion Group",  "nfg@nordicfashion.com",   "+47-400-12345",   "Fjord Blvd 22, Oslo",      "Anna Lindqvist"),
        ]
        db.executemany(
            "INSERT INTO customers (name,email,phone,address,contact_person,created_at) VALUES (?,?,?,?,?,?)",
            [(c[0], c[1], c[2], c[3], c[4], now) for c in seed_customers])
    db.commit()

    if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        sample = [
            ("CLT-TS-BLK-M",  "Cotton Crew T-Shirt", "T-Shirts",    "M",  "Black",  540, 100,  6.50),
            ("CLT-TS-WHT-L",  "Cotton Crew T-Shirt", "T-Shirts",    "L",  "White",   60, 100,  6.50),
            ("CLT-HD-GRY-L",  "Pullover Hoodie",     "Hoodies",     "L",  "Grey",   220,  80, 18.00),
            ("CLT-JN-BLU-32", "Slim Fit Jeans",      "Denim",       "32", "Indigo",  95,  50, 24.00),
            ("CLT-JK-NVY-XL", "Bomber Jacket",       "Outerwear",   "XL", "Navy",    18,  40, 39.00),
            ("CLT-SK-BLK-OS", "Ribbed Socks (5pk)",  "Accessories", "OS", "Black", 1200, 200,  4.00),
            ("CLT-SH-KHK-M",  "Chino Shorts",        "Shorts",      "M",  "Khaki",   75,  60, 14.50),
            ("CLT-DR-RED-S",  "Summer Dress",        "Dresses",     "S",  "Red",     32,  45, 27.00),
        ]
        db.executemany(
            "INSERT INTO products (sku,name,category,size,color,quantity,reorder_level,price,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], now) for s in sample])
    db.commit()

    if db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        seed_orders = [
            ("SO-1001", 1, "Hamid Textile LLC",    "CLT-TS-BLK-M",  120, "Shipped",   "admin"),
            ("SO-1002", 2, "Bukhara Bazaar Retail","CLT-HD-GRY-L",   40, "Pending",   "sales1"),
            ("SO-1003", 3, "Silk Road Outfitters", "CLT-JN-BLU-32",  25, "Packing",   "sales1"),
            ("SO-1004", 1, "Hamid Textile LLC",    "CLT-SK-BLK-OS", 300, "Shipped",   "admin"),
            ("SO-1005", 4, "Nordic Fashion Group", "CLT-JK-NVY-XL",  10, "Confirmed", "manager1"),
            ("SO-1006", 2, "Bukhara Bazaar Retail","CLT-DR-RED-S",   15, "Pending",   "sales1"),
        ]
        db.executemany(
            "INSERT INTO orders (reference,customer_id,customer,sku,qty,status,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(o[0], o[1], o[2], o[3], o[4], o[5], o[6], now, now) for o in seed_orders])
        db.execute("UPDATE products SET quantity=quantity-120 WHERE sku='CLT-TS-BLK-M'")
        db.execute("UPDATE products SET quantity=quantity-40  WHERE sku='CLT-HD-GRY-L'")
        db.execute("UPDATE products SET quantity=quantity-25  WHERE sku='CLT-JN-BLU-32'")
        db.execute("UPDATE products SET quantity=quantity-300 WHERE sku='CLT-SK-BLK-OS'")
        db.execute("UPDATE products SET quantity=quantity-10  WHERE sku='CLT-JK-NVY-XL'")
        db.execute("UPDATE products SET quantity=quantity-15  WHERE sku='CLT-DR-RED-S'")
    db.commit()

    if db.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0] == 0:
        seed_movements = [
            ("CLT-TS-BLK-M",  "restock",  500, None,      "superadmin"),
            ("CLT-SK-BLK-OS", "restock", 1200, None,      "superadmin"),
            ("CLT-HD-GRY-L",  "restock",  260, None,      "superadmin"),
            ("CLT-TS-BLK-M",  "sale",    -120, "SO-1001", "admin"),
            ("CLT-SK-BLK-OS", "sale",    -300, "SO-1004", "admin"),
            ("CLT-HD-GRY-L",  "sale",     -40, "SO-1002", "sales1"),
            ("CLT-JN-BLU-32", "sale",     -25, "SO-1003", "sales1"),
            ("CLT-JK-NVY-XL", "sale",     -10, "SO-1005", "manager1"),
            ("CLT-DR-RED-S",  "sale",     -15, "SO-1006", "sales1"),
        ]
        db.executemany(
            "INSERT INTO stock_movements (sku,type,qty_change,reference,user,created_at) VALUES (?,?,?,?,?,?)",
            [(m[0], m[1], m[2], m[3], m[4], now) for m in seed_movements])
    db.commit()
    db.close()


# ── Auth helpers ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("Access denied — you don't have permission for that.", "error")
                return redirect(url_for("dashboard"))
            return f(*a, **kw)
        return wrapper
    return decorator


@app.context_processor
def inject_globals():
    return {
        "instance_id":      get_instance_id(),
        "user":             session.get("user"),
        "full_name":        session.get("full_name"),
        "role":             session.get("role"),
        "MANAGE_USERS":     MANAGE_USERS,
        "VIEW_USERS":       VIEW_USERS,
        "MANAGE_PRODUCTS":  MANAGE_PRODUCTS,
        "CREATE_ORDERS":    CREATE_ORDERS,
        "UPDATE_ORDERS":    UPDATE_ORDERS,
        "DELETE_PRIV":      DELETE_PRIV,
        "ALL_EXCEPT_STAFF": ALL_EXCEPT_STAFF,
        "VIEW_ANALYTICS":   VIEW_ANALYTICS,
    }


# ── Auth routes ───────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        row = get_db().execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (u, hash_pw(p))).fetchone()
        if row:
            session["user"]      = row["username"]
            session["role"]      = row["role"]
            session["full_name"] = row["full_name"] or row["username"]
            session["user_id"]   = row["id"]
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Dashboard — role-specific ─────────────────────────────────────────────────
@app.route("/")
@login_required
def dashboard():
    db   = get_db()
    role = session.get("role")

    if role == "superadmin":
        data = dict(
            total_users     = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
            total_customers = db.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"],
            total_skus      = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
            total_units     = db.execute("SELECT COALESCE(SUM(quantity),0) s FROM products").fetchone()["s"],
            stock_value     = db.execute("SELECT COALESCE(SUM(quantity*price),0) v FROM products").fetchone()["v"],
            open_orders     = db.execute("SELECT COUNT(*) c FROM orders WHERE status NOT IN ('Shipped','Cancelled')").fetchone()["c"],
            low_stock       = db.execute("SELECT * FROM products WHERE quantity<=reorder_level ORDER BY quantity ASC").fetchall(),
            recent          = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 8").fetchall(),
            users_by_role   = db.execute("SELECT role, COUNT(*) cnt FROM users GROUP BY role ORDER BY role").fetchall(),
        )
        return render_template("dashboard_superadmin.html", **data)

    if role == "admin":
        data = dict(
            total_skus      = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
            total_units     = db.execute("SELECT COALESCE(SUM(quantity),0) s FROM products").fetchone()["s"],
            stock_value     = db.execute("SELECT COALESCE(SUM(quantity*price),0) v FROM products").fetchone()["v"],
            open_orders     = db.execute("SELECT COUNT(*) c FROM orders WHERE status NOT IN ('Shipped','Cancelled')").fetchone()["c"],
            total_customers = db.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"],
            total_users     = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
            low_stock       = db.execute("SELECT * FROM products WHERE quantity<=reorder_level ORDER BY quantity ASC").fetchall(),
            recent          = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 6").fetchall(),
        )
        return render_template("dashboard_admin.html", **data)

    if role == "manager":
        total_revenue = db.execute(
            "SELECT COALESCE(SUM(o.qty*p.price),0) r FROM orders o "
            "JOIN products p ON o.sku=p.sku WHERE o.status!='Cancelled'"
        ).fetchone()["r"]
        orders_by_status_rows = db.execute(
            "SELECT status, COUNT(*) cnt FROM orders GROUP BY status ORDER BY cnt DESC"
        ).fetchall()
        max_status_cnt = max((r["cnt"] for r in orders_by_status_rows), default=1)
        stock_by_cat = db.execute(
            "SELECT category, COUNT(*) skus, SUM(quantity) total_qty, "
            "ROUND(SUM(quantity*price),2) total_value "
            "FROM products GROUP BY category ORDER BY total_value DESC"
        ).fetchall()
        max_cat_value = max((r["total_value"] for r in stock_by_cat), default=1) or 1
        top_customers = db.execute(
            "SELECT customer, COUNT(*) cnt, SUM(qty) total_qty "
            "FROM orders WHERE status!='Cancelled' "
            "GROUP BY customer ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        data = dict(
            total_skus           = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
            total_units          = db.execute("SELECT COALESCE(SUM(quantity),0) s FROM products").fetchone()["s"],
            stock_value          = db.execute("SELECT COALESCE(SUM(quantity*price),0) v FROM products").fetchone()["v"],
            open_orders          = db.execute("SELECT COUNT(*) c FROM orders WHERE status NOT IN ('Shipped','Cancelled')").fetchone()["c"],
            total_customers      = db.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"],
            total_revenue        = total_revenue,
            orders_by_status     = orders_by_status_rows,
            max_status_cnt       = max_status_cnt,
            stock_by_cat         = stock_by_cat,
            max_cat_value        = max_cat_value,
            top_customers        = top_customers,
            low_stock            = db.execute("SELECT * FROM products WHERE quantity<=reorder_level ORDER BY quantity ASC").fetchall(),
        )
        return render_template("dashboard_manager.html", **data)

    if role == "sales":
        mine = db.execute(
            "SELECT * FROM orders WHERE created_by=? ORDER BY id DESC", (session["user"],)
        ).fetchall()
        data = dict(
            my_orders      = mine,
            my_total       = len(mine),
            my_open        = sum(1 for o in mine if o["status"] not in ("Shipped", "Cancelled")),
            my_shipped     = sum(1 for o in mine if o["status"] == "Shipped"),
            total_customers= db.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"],
            recent_customers= db.execute("SELECT * FROM customers ORDER BY id DESC LIMIT 4").fetchall(),
            skus_available = db.execute("SELECT COUNT(*) c FROM products WHERE quantity > 0").fetchone()["c"],
        )
        return render_template("dashboard_sales.html", **data)

    if role == "warehouse":
        data = dict(
            low_stock_count  = db.execute("SELECT COUNT(*) c FROM products WHERE quantity<=reorder_level").fetchone()["c"],
            out_of_stock     = db.execute("SELECT COUNT(*) c FROM products WHERE quantity=0").fetchone()["c"],
            low_stock        = db.execute("SELECT * FROM products WHERE quantity<=reorder_level ORDER BY quantity ASC").fetchall(),
            pending_orders   = db.execute("SELECT * FROM orders WHERE status='Pending' ORDER BY id").fetchall(),
            confirmed_orders = db.execute("SELECT * FROM orders WHERE status='Confirmed' ORDER BY id").fetchall(),
            packing_orders   = db.execute("SELECT * FROM orders WHERE status='Packing' ORDER BY id").fetchall(),
            recent_movements = db.execute("SELECT * FROM stock_movements ORDER BY id DESC LIMIT 8").fetchall(),
        )
        return render_template("dashboard_warehouse.html", **data)

    # staff (default)
    data = dict(
        total_skus      = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        total_units     = db.execute("SELECT COALESCE(SUM(quantity),0) s FROM products").fetchone()["s"],
        low_stock_count = db.execute("SELECT COUNT(*) c FROM products WHERE quantity<=reorder_level").fetchone()["c"],
        recent          = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 5").fetchall(),
    )
    return render_template("dashboard_staff.html", **data)


# ── Products ──────────────────────────────────────────────────────────────────
@app.route("/products")
@login_required
def products():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q:
        rows = db.execute(
            "SELECT * FROM products WHERE sku LIKE ? OR name LIKE ? OR category LIKE ? "
            "ORDER BY name", (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    else:
        rows = db.execute("SELECT * FROM products ORDER BY name").fetchall()
    return render_template("products.html", products=rows, q=q)


@app.route("/products/new", methods=["GET", "POST"])
@role_required(*MANAGE_PRODUCTS)
def product_new():
    if request.method == "POST":
        _save_product(None)
        flash("Product created", "ok")
        return redirect(url_for("products"))
    return render_template("product_form.html", product=None)


@app.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@role_required(*MANAGE_PRODUCTS)
def product_edit(pid):
    product = get_db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not product:
        flash("Product not found", "error")
        return redirect(url_for("products"))
    if request.method == "POST":
        _save_product(pid)
        flash("Product updated", "ok")
        return redirect(url_for("products"))
    return render_template("product_form.html", product=product)


@app.route("/products/<int:pid>/delete", methods=["POST"])
@role_required(*DELETE_PRIV)
def product_delete(pid):
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit()
    flash("Product deleted", "ok")
    return redirect(url_for("products"))


def _save_product(pid):
    f   = request.form
    db  = get_db()
    now = datetime.utcnow().isoformat(timespec="seconds")
    vals = (f.get("sku"), f.get("name"), f.get("category"), f.get("size"),
            f.get("color"), int(f.get("quantity") or 0),
            int(f.get("reorder_level") or 10), float(f.get("price") or 0), now)
    if pid:
        db.execute(
            "UPDATE products SET sku=?,name=?,category=?,size=?,color=?,"
            "quantity=?,reorder_level=?,price=?,updated_at=? WHERE id=?",
            vals + (pid,))
    else:
        db.execute(
            "INSERT INTO products (sku,name,category,size,color,quantity,"
            "reorder_level,price,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", vals)
    db.commit()


# ── Orders ────────────────────────────────────────────────────────────────────
@app.route("/orders")
@login_required
def orders():
    db   = get_db()
    role = session.get("role")
    if role == "sales":
        rows = db.execute(
            "SELECT * FROM orders WHERE created_by=? ORDER BY id DESC",
            (session["user"],)).fetchall()
    else:
        rows = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    return render_template("orders.html", orders=rows)


@app.route("/orders/new", methods=["GET", "POST"])
@role_required(*CREATE_ORDERS)
def order_new():
    db = get_db()
    if request.method == "POST":
        f   = request.form
        now = datetime.utcnow().isoformat(timespec="seconds")
        ref = f.get("reference", "").strip() or ("SO-" + str(int(time.time()))[-6:])
        sku = f.get("sku", "").strip()
        qty = int(f.get("qty") or 0)
        cid = f.get("customer_id") or None

        cname = ""
        if cid:
            row = db.execute("SELECT name FROM customers WHERE id=?", (cid,)).fetchone()
            if row:
                cname = row["name"]
        if not cname:
            flash("Please select a customer.", "error")
            return render_template("order_form.html",
                                   skus=db.execute("SELECT sku,name,quantity FROM products ORDER BY sku").fetchall(),
                                   customers=db.execute("SELECT id,name FROM customers ORDER BY name").fetchall(),
                                   statuses=ORDER_STATUSES)

        product = db.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        if not product:
            flash("Invalid SKU selected.", "error")
            return redirect(url_for("order_new"))
        if qty < 1:
            flash("Quantity must be at least 1.", "error")
            return redirect(url_for("order_new"))
        if product["quantity"] < qty:
            flash(f"Insufficient stock — only {product['quantity']} units of {sku} available.", "error")
            return render_template("order_form.html",
                                   skus=db.execute("SELECT sku,name,quantity FROM products ORDER BY sku").fetchall(),
                                   customers=db.execute("SELECT id,name FROM customers ORDER BY name").fetchall(),
                                   statuses=ORDER_STATUSES)

        status = f.get("status") or "Pending"
        db.execute(
            "INSERT INTO orders (reference,customer_id,customer,sku,qty,status,notes,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ref, cid, cname, sku, qty, status, f.get("notes", ""),
             session["user"], now, now))
        db.execute("UPDATE products SET quantity=quantity-?,updated_at=? WHERE sku=?",
                   (qty, now, sku))
        db.execute(
            "INSERT INTO stock_movements (sku,type,qty_change,reference,user,created_at) VALUES (?,?,?,?,?,?)",
            (sku, "sale", -qty, ref, session["user"], now))
        db.commit()
        flash(f"Order {ref} created — {qty} units of {sku} reserved.", "ok")
        return redirect(url_for("orders"))

    skus      = db.execute("SELECT sku,name,quantity FROM products ORDER BY sku").fetchall()
    customers = db.execute("SELECT id,name FROM customers ORDER BY name").fetchall()
    return render_template("order_form.html", skus=skus, customers=customers, statuses=ORDER_STATUSES)


@app.route("/orders/<int:oid>/edit", methods=["GET", "POST"])
@role_required(*UPDATE_ORDERS)
def order_edit(oid):
    db    = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not order:
        flash("Order not found", "error")
        return redirect(url_for("orders"))
    if request.method == "POST":
        f          = request.form
        now        = datetime.utcnow().isoformat(timespec="seconds")
        old_status = order["status"]
        new_status = f.get("status", old_status)
        notes      = f.get("notes", order["notes"] or "")

        if new_status == "Cancelled" and old_status != "Cancelled":
            db.execute("UPDATE products SET quantity=quantity+?,updated_at=? WHERE sku=?",
                       (order["qty"], now, order["sku"]))
            db.execute(
                "INSERT INTO stock_movements (sku,type,qty_change,reference,user,created_at) VALUES (?,?,?,?,?,?)",
                (order["sku"], "cancellation", order["qty"], order["reference"], session["user"], now))
        elif old_status == "Cancelled" and new_status != "Cancelled":
            prod = db.execute("SELECT quantity FROM products WHERE sku=?", (order["sku"],)).fetchone()
            if not prod or prod["quantity"] < order["qty"]:
                flash("Cannot reactivate — insufficient stock.", "error")
                return render_template("order_edit.html", order=order, statuses=ORDER_STATUSES)
            db.execute("UPDATE products SET quantity=quantity-?,updated_at=? WHERE sku=?",
                       (order["qty"], now, order["sku"]))
            db.execute(
                "INSERT INTO stock_movements (sku,type,qty_change,reference,user,created_at) VALUES (?,?,?,?,?,?)",
                (order["sku"], "reactivation", -order["qty"], order["reference"], session["user"], now))

        db.execute("UPDATE orders SET status=?,notes=?,updated_at=? WHERE id=?",
                   (new_status, notes, now, oid))
        db.commit()
        flash("Order updated", "ok")
        return redirect(url_for("orders"))
    return render_template("order_edit.html", order=order, statuses=ORDER_STATUSES)


@app.route("/orders/<int:oid>/delete", methods=["POST"])
@role_required(*DELETE_PRIV)
def order_delete(oid):
    db    = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if order and order["status"] != "Cancelled":
        now = datetime.utcnow().isoformat(timespec="seconds")
        db.execute("UPDATE products SET quantity=quantity+?,updated_at=? WHERE sku=?",
                   (order["qty"], now, order["sku"]))
        db.execute(
            "INSERT INTO stock_movements (sku,type,qty_change,reference,user,created_at) VALUES (?,?,?,?,?,?)",
            (order["sku"], "deletion", order["qty"], order["reference"], session["user"], now))
    db.execute("DELETE FROM orders WHERE id=?", (oid,))
    db.commit()
    flash("Order deleted — stock restored.", "ok")
    return redirect(url_for("orders"))


# ── Customers ─────────────────────────────────────────────────────────────────
@app.route("/customers")
@role_required(*ALL_EXCEPT_STAFF)
def customers():
    q  = request.args.get("q", "").strip()
    db = get_db()
    if q:
        rows = db.execute(
            "SELECT c.*, COUNT(o.id) order_count FROM customers c "
            "LEFT JOIN orders o ON o.customer_id=c.id "
            "WHERE c.name LIKE ? OR c.email LIKE ? OR c.contact_person LIKE ? "
            "GROUP BY c.id ORDER BY c.name",
            (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    else:
        rows = db.execute(
            "SELECT c.*, COUNT(o.id) order_count FROM customers c "
            "LEFT JOIN orders o ON o.customer_id=c.id "
            "GROUP BY c.id ORDER BY c.name").fetchall()
    return render_template("customers.html", customers=rows, q=q)


@app.route("/customers/new", methods=["GET", "POST"])
@role_required(*ALL_EXCEPT_STAFF)
def customer_new():
    if request.method == "POST":
        _save_customer(None)
        flash("Customer added", "ok")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=None)


@app.route("/customers/<int:cid>/edit", methods=["GET", "POST"])
@role_required(*ALL_EXCEPT_STAFF)
def customer_edit(cid):
    customer = get_db().execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not customer:
        flash("Customer not found", "error")
        return redirect(url_for("customers"))
    if request.method == "POST":
        _save_customer(cid)
        flash("Customer updated", "ok")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=customer)


@app.route("/customers/<int:cid>/delete", methods=["POST"])
@role_required(*DELETE_PRIV)
def customer_delete(cid):
    db = get_db()
    db.execute("DELETE FROM customers WHERE id=?", (cid,))
    db.commit()
    flash("Customer deleted", "ok")
    return redirect(url_for("customers"))


def _save_customer(cid):
    f   = request.form
    db  = get_db()
    now = datetime.utcnow().isoformat(timespec="seconds")
    vals = (f.get("name", "").strip(), f.get("email", "").strip(),
            f.get("phone", "").strip(), f.get("address", "").strip(),
            f.get("contact_person", "").strip())
    if cid:
        db.execute(
            "UPDATE customers SET name=?,email=?,phone=?,address=?,contact_person=? WHERE id=?",
            vals + (cid,))
    else:
        db.execute(
            "INSERT INTO customers (name,email,phone,address,contact_person,created_at) VALUES (?,?,?,?,?,?)",
            vals + (now,))
    db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────
@app.route("/users")
@role_required(*VIEW_USERS)
def users():
    rows = get_db().execute("SELECT * FROM users ORDER BY role,username").fetchall()
    return render_template("users.html", users=rows, all_roles=ALL_ROLES)


@app.route("/users/new", methods=["GET", "POST"])
@role_required(*MANAGE_USERS)
def user_new():
    if request.method == "POST":
        f   = request.form
        db  = get_db()
        now = datetime.utcnow().isoformat(timespec="seconds")
        try:
            db.execute(
                "INSERT INTO users (username,password,full_name,email,role,created_at) VALUES (?,?,?,?,?,?)",
                (f.get("username", "").strip(), hash_pw(f.get("password", "")),
                 f.get("full_name", "").strip(), f.get("email", "").strip(),
                 f.get("role", "staff"), now))
            db.commit()
            flash("User created", "ok")
            return redirect(url_for("users"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "error")
    return render_template("user_form.html", user=None, all_roles=ALL_ROLES)


@app.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@role_required(*MANAGE_USERS)
def user_edit(uid):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        flash("User not found", "error")
        return redirect(url_for("users"))
    if request.method == "POST":
        f  = request.form
        pw = f.get("password", "").strip()
        if pw:
            db.execute(
                "UPDATE users SET full_name=?,email=?,role=?,password=? WHERE id=?",
                (f.get("full_name"), f.get("email"), f.get("role", user["role"]), hash_pw(pw), uid))
        else:
            db.execute(
                "UPDATE users SET full_name=?,email=?,role=? WHERE id=?",
                (f.get("full_name"), f.get("email"), f.get("role", user["role"]), uid))
        db.commit()
        flash("User updated", "ok")
        return redirect(url_for("users"))
    return render_template("user_form.html", user=user, all_roles=ALL_ROLES)


@app.route("/users/<int:uid>/delete", methods=["POST"])
@role_required("superadmin")
def user_delete(uid):
    db      = get_db()
    current = db.execute("SELECT id FROM users WHERE username=?", (session["user"],)).fetchone()
    if current and current["id"] == uid:
        flash("Cannot delete your own account.", "error")
        return redirect(url_for("users"))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    flash("User deleted", "ok")
    return redirect(url_for("users"))


# ── Stock log ─────────────────────────────────────────────────────────────────
@app.route("/stock-log")
@role_required("superadmin", "manager", "warehouse")
def stock_log():
    rows = get_db().execute(
        "SELECT * FROM stock_movements ORDER BY id DESC LIMIT 100").fetchall()
    return render_template("stock_log.html", movements=rows)


# ── Operational endpoints ─────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify(status="healthy", instance=get_instance_id(),
                   time=datetime.utcnow().isoformat(timespec="seconds")), 200


@app.route("/whoami")
def whoami():
    return get_instance_id() + "\n", 200, {"Content-Type": "text/plain"}


@app.route("/load")
def load():
    ms  = min(int(request.args.get("ms", 200)), 2000)
    end = time.time() + ms / 1000.0
    x   = 0
    while time.time() < end:
        x += sum(i * i for i in range(500))
    return jsonify(burned_ms=ms, instance=get_instance_id(), result=x % 7)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
