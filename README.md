# NimbusWMS — AWS Deployment Runbook
### Networking in the Cloud (BTEC Unit 6) — practical evidence guide

This is the build guide for the practical criteria. Every numbered step that says
**📷 Figure** is a screenshot you must take for the assignment. Take it, number it,
and write a one-line caption underneath in your report.

Region: pick **one** region (e.g. `eu-west-1` / `eu-central-1`) and stay in it.
Platform: **AWS only** (do not mix in Azure/GCP).

---

## 0. What you are building (the design — C.P5)

```
                        Internet
                           │
                    ┌──────▼───────┐
                    │ Internet GW  │
                    └──────┬───────┘
            ┌──────────────▼───────────────┐  VPC  10.0.0.0/16
            │      Application Load Balancer (public subnets)      │
            │            listens on :80  → /health check           │
            └───────┬───────────────────────────┬─────────────────┘
        PUBLIC SUBNET 10.0.1.0/24        PUBLIC SUBNET 10.0.2.0/24
        (AZ-a)                            (AZ-b)
            │                                 │
   ┌────────▼─────────┐   Auto Scaling   ┌────▼──────────────┐
   │ EC2  app server  │ ◄─────────────►  │ EC2  app server   │   ← 2..N instances
   │ nginx + gunicorn │     Group        │ nginx + gunicorn  │
   └────────┬─────────┘                  └────┬──────────────┘
            │  (private subnets in the "improved" design + NAT GW)
            ▼
      SQLite on instance (baseline)  →  RDS / multi-AZ DB (improvement, D.P8)
```

For the C.P5 design diagram, redraw the above in **draw.io** (cleaner for the report).
IP plan: VPC `10.0.0.0/16`, public subnets `10.0.1.0/24` + `10.0.2.0/24`,
private subnets `10.0.11.0/24` + `10.0.12.0/24`.

---

## 1. Network foundation — covers **C.P6 (part 1)**

The fastest reliable path is the **VPC → "VPC and more"** wizard.

1. VPC console → **Create VPC** → choose **VPC and more**.
   - Name: `wms-vpc`, CIDR `10.0.0.0/16`
   - 2 Availability Zones, 2 public + 2 private subnets
   - NAT gateways: **1 per AZ** (or "In 1 AZ" to save cost)
   - **📷 Figure 1** — the VPC wizard summary / the **Resource map** after creation
     (shows VPC, subnets, route tables, IGW, NAT all wired together). *(A.P2 + C.P6)*
2. Open **Subnets** → **📷 Figure 2** — the list showing your 2 public + 2 private subnets with their CIDRs.
3. Open **Internet Gateways** → **📷 Figure 3** — the IGW attached to `wms-vpc`.
4. Open **NAT Gateways** → **📷 Figure 4** — the NAT gateway (Available).
5. Open **Route Tables** → click the public RT → Routes tab → **📷 Figure 5** —
   route `0.0.0.0/0 → igw-...`. Then the private RT → `0.0.0.0/0 → nat-...`.

---

## 2. Security group — covers **C.P6 (part 2)** + the security design in **C.P5**

Create SG `wms-web-sg` in `wms-vpc`. Inbound rules:

| Type  | Port | Source            | Why |
|-------|------|-------------------|-----|
| HTTP  | 80   | 0.0.0.0/0         | public web + ALB health check |
| SSH   | 22   | **My IP only**    | admin access (not the whole world) |

**📷 Figure 6** — the inbound rules of `wms-web-sg`. *(Mention in C.P5 why 22 is admin-only.)*

> In the *improved* design you put the EC2 instances in **private** subnets and only
> the ALB SG is open to the internet — note this for D.P7/D.P8.

---

## 3. First app server (manual) — covers **B.P3** + **C.P6 (part 3)**

This single instance lets you collect the B.P3 evidence and confirm the app works
before you automate it.

1. EC2 → **Launch instance**
   - Name `wms-app-1`, AMI **Ubuntu 22.04 LTS**, type `t3.micro`
   - Key pair: create/select one (this is your SSH key)
   - Network: `wms-vpc`, a **public** subnet, **auto-assign public IP = Enable**
   - Security group: `wms-web-sg`
   - **📷 Figure 7** — the launch/configuration summary screen *(B.P3: VM creation)*
2. After ~1 min → Instances list → **📷 Figure 8** — instance state **Running** *(B.P3)*
3. From your terminal: `ssh -i your-key.pem ubuntu@<PUBLIC-IP>`
   - **📷 Figure 9** — the successful SSH session prompt *(B.P3: remote OS access)*
4. On the server, install the app (or just paste `deploy/user-data.sh` contents):
   ```bash
   sudo apt-get update -y
   sudo apt-get install -y python3-venv nginx git
   sudo git clone https://github.com/YOUR_USERNAME/wms-cloud.git /opt/wms
   cd /opt/wms && sudo python3 -m venv .venv
   sudo .venv/bin/pip install -r requirements.txt
   sudo .venv/bin/python3 -c "import app; app.init_db()"
   sudo cp deploy/wms.service /etc/systemd/system/ && sudo systemctl enable --now wms
   sudo cp deploy/nginx.conf /etc/nginx/sites-available/wms
   sudo ln -sf /etc/nginx/sites-available/wms /etc/nginx/sites-enabled/wms
   sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl restart nginx
   ```
   - **📷 Figure 10** — terminal showing `systemctl status wms` = active (running)
     and `nginx -t` = OK *(C.P6: web server installed)*
5. Browser → `http://<PUBLIC-IP>/` → log in `admin / admin123`
   - **📷 Figure 11** — the **working NimbusWMS dashboard in the browser, URL visible**
     *(C.P6: the dynamic website is live — the single most important screenshot)*

### B.P4 evidence (how clients connect)
- **📷 Figure 12** — the app open over the public endpoint in a browser
  (this is your "remote client → HTTPS/HTTP → cloud service" evidence).
  For the padlock/HTTPS version, see the optional ACM + HTTPS listener note in §6.

---

## 4. Turn it into a fleet: AMI + Launch Template + ALB + ASG — covers **C.P6 (part 4)** and powers **C.M3**

### 4a. Launch Template
- EC2 → **Launch Templates** → Create
  - AMI Ubuntu 22.04, type `t3.micro`, key pair, SG `wms-web-sg`
  - **Advanced → User data**: paste the whole of `deploy/user-data.sh`
    (set `APP_REPO` to your GitHub URL first)
- **📷 Figure 13** — the launch template summary (showing user-data present).

### 4b. Target group + Application Load Balancer
1. EC2 → **Target Groups** → Create → target type **Instances**, protocol HTTP:80,
   VPC `wms-vpc`. **Health check path = `/health`**. *(this is why the app has /health)*
2. EC2 → **Load Balancers** → Create **Application Load Balancer**
   - Internet-facing, both **public** subnets, SG allowing :80
   - Listener HTTP:80 → forward to your target group
3. **📷 Figure 14** — the ALB details page showing its **DNS name** (`...elb.amazonaws.com`).

### 4c. Auto Scaling Group
- EC2 → **Auto Scaling Groups** → Create
  - Use your launch template; VPC `wms-vpc`; select the **2 public subnets** (2 AZs)
  - Attach to the **existing target group** (the ALB one)
  - Group size: desired **2**, min **2**, max **4**
  - Scaling policy: **Target tracking → Average CPU 50%**
- **📷 Figure 15** — the ASG showing **2 instances Healthy / InService**.
- Open the target group → Targets tab → **📷 Figure 16** — both targets **healthy**
  (load-balancer health check passing). *(C.M3: LB target status)*

### Confirm load balancing
- Browse to `http://<ALB-DNS>/` and refresh a few times → the **"SERVED BY"** code
  in the sidebar changes between instance-ids.
- **📷 Figure 17** — two browser shots (or the `/whoami` loop output) showing
  **two different instance-ids** answering. *(Strong B.P4 + C.M3 evidence.)*

---

## 5. Load & scalability test — covers **C.M3** (and re-used for **D.M4**)

From your laptop, edit `loadtest/ab-commands.sh` (set `ALB=`), then:

```bash
ab -n 2000 -c 50  http://<ALB-DNS>/health        # throughput
ab -n 3000 -c 100 http://<ALB-DNS>/load?ms=200   # CPU load -> triggers scaling
```

- **📷 Figure 18** — the `ab` results (Requests/sec, Time per request, Failed=0). *(C.M3)*
- **📷 Figure 19** — **CloudWatch** CPU graph of the ASG climbing during the test.
- **📷 Figure 20** — the ASG instance count rising **2 → 3 → 4** (Activity tab). *(C.M3: auto-scaling)*

Record these numbers in a table — they are the evidence for **C.D2** (justify the design).

| Metric | Baseline result |
|---|---|
| Requests / sec | … |
| Mean response time (ms) | … |
| Failed requests | 0 |
| Instances at peak | … |

---

## 6. Improvements — covers **D.P7 / D.P8**

Pick 2–3 and implement. Each maps to a weakness you found in §5.

1. **CI/CD pipeline (required for D.P8).**
   - Push the repo to GitHub. Add repo **Secrets**: `EC2_HOST`, `EC2_USER=ubuntu`,
     `EC2_SSH_KEY` (private key). The workflow is already in `.github/workflows/deploy.yml`.
   - Make a small change, push to `main`.
   - **📷 Figure 21** — the Actions tab with a **green ✓ passed** run.
   - **📷 Figure 22** — the `deploy.yml` file contents.
   - **📷 Figure 23** — the updated site after auto-deploy.
2. **HTTPS / TLS (for the padlock B.P4 + security improvement).**
   Request a certificate in **ACM**, add an **HTTPS:443 listener** on the ALB.
   **📷** browser padlock + `https://` URL.
3. **CDN (CloudFront)** in front of the ALB for static assets / latency.
4. **Move EC2 to private subnets + NAT** (no public IPs on app servers) — security hardening.
5. **RDS multi-AZ** instead of on-instance SQLite — reliability.

---

## 7. Re-test — covers **D.M4 / D.D3**

Run the **exact same** `ab` / k6 test from §5 against the improved system.
- **📷 Figure 24** — new `ab` results.
- **📷 Figure 25** — new CloudWatch graph.
- Build a **before vs after** table (this is the core of D.D3):

| Metric | Baseline (C) | Improved (D) |
|---|---|---|
| Mean response time | … | … |
| Requests / sec | … | … |
| Deploy time (manual vs CI/CD) | ~X min | ~Y min |
| Failover / reliability | single point | multi-AZ |

---

## Screenshot → criteria quick map

| Figures | Criterion |
|---|---|
| 1, 2, 5 | A.P2 (how communication flows), C.P6 |
| 7, 8, 9 | B.P3 (deploy remote OS service + SSH) |
| 11, 12, 17 | B.P4 (clients connect to cloud services) |
| 0-diagram | C.P5 (design) |
| 1–11, 13, 14 | C.P6 (implement) |
| 16, 18, 19, 20 | C.M3 (performance + scalability test) |
| table from §5 | C.D2 (justify with evidence) |
| 21, 22, 23 | D.P8 (CI/CD + improvements) |
| 24, 25, table §7 | D.M4 / D.D3 (re-test + justify) |

---

## Tear-down (avoid charges)
Delete in this order: ASG → ALB → target group → launch template →
NAT gateway → release Elastic IPs → VPC (the wizard delete removes subnets/IGW).
NAT gateways and ALBs cost money per hour — delete them when you finish testing.

## Local test (before AWS)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app.py            # open http://localhost:8000  (admin / admin123)
```
