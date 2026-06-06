#!/bin/bash
# =============================================================================
# EC2 user-data bootstrap for NimbusWMS
# Paste this into the "User data" field of your Launch Template.
# Every instance the Auto Scaling Group launches will run this on boot,
# install the app from scratch and come up healthy behind the load balancer.
# Target OS: Ubuntu 22.04 / 24.04 LTS
# =============================================================================
set -e
exec > /var/log/wms-bootstrap.log 2>&1

# --- pull the application code -----------------------------------------------
# OPTION A (recommended): clone from your GitHub repo
APP_REPO="https://github.com/rodrygoes211/wms-cloud.git"   # ← your GitHub repo

apt-get update -y
apt-get install -y python3-venv python3-pip nginx git

rm -rf /opt/wms
git clone "$APP_REPO" /opt/wms || {
  # OPTION B fallback: if you did not use git, the code was baked into the AMI
  echo "git clone failed - assuming code already in /opt/wms (baked AMI)";
}

cd /opt/wms
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# initialise the SQLite database
.venv/bin/python3 -c "import app; app.init_db()"

chown -R www-data:www-data /opt/wms

# --- systemd service (gunicorn) ---------------------------------------------
cp /opt/wms/deploy/wms.service /etc/systemd/system/wms.service
systemctl daemon-reload
systemctl enable wms
systemctl start wms

# --- nginx reverse proxy -----------------------------------------------------
cp /opt/wms/deploy/nginx.conf /etc/nginx/sites-available/wms
ln -sf /etc/nginx/sites-available/wms /etc/nginx/sites-enabled/wms
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "NimbusWMS bootstrap complete on $(hostname)"
