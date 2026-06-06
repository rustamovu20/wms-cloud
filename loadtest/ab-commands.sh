#!/bin/bash
# =============================================================================
# NimbusWMS Load Tests — proves ALB + Auto Scaling Group work
# Run from your laptop or a separate EC2 "attacker" instance.
# Replace ALB_DNS with your actual load balancer DNS name.
# =============================================================================

ALB="http://YOUR-ALB-DNS-NAME.elb.amazonaws.com"

# ── Quick check before starting ───────────────────────────────────────────────
echo ">>> Pinging ALB health endpoint..."
curl -s "$ALB/health" | python3 -m json.tool
echo ""

# ── TEST 1: 300,000 requests — proves the ALB handles sustained load ──────────
echo "########## TEST 1: 300k requests (throughput + zero errors) ##########"
# -n 300000 = total requests
# -c 200    = 200 concurrent connections
# -k        = keep-alive (realistic browser behaviour)
ab -n 300000 -c 200 -k "$ALB/health"

echo ""
echo ">>> Key numbers to record for your report:"
echo "    Requests per second   (higher = better)"
echo "    Mean time per request (lower = better)"
echo "    Failed requests       (should be ZERO)"
echo ""

# ── TEST 2: CPU burn — triggers Auto Scaling Group to add instances ───────────
echo "########## TEST 2: CPU burn — watch ASG add instances in Console ##########"
# Each /load?ms=300 burns 300ms of CPU on the server.
# With 150 concurrent users this will spike CPU above the ASG alarm threshold.
# Watch EC2 > Auto Scaling Groups > Activity in AWS Console.
ab -n 5000 -c 150 "$ALB/load?ms=300"

echo ""

# ── TEST 3: prove requests are spread across MULTIPLE instances ───────────────
echo "########## TEST 3: load balancer distribution proof ##########"
# /whoami returns the EC2 instance-id.
# If you see MORE THAN ONE unique instance-id, the ALB is distributing load.
echo "Instance IDs seen across 60 requests:"
for i in $(seq 1 60); do curl -s "$ALB/whoami"; done | sort | uniq -c | sort -rn

echo ""
echo ">>> If you see 2+ instance IDs above, the load balancer is working."
echo ""

# ── TEST 4: DDoS simulation — sustained high concurrency ─────────────────────
echo "########## TEST 4: sustained DDoS-style flood (5 min) ##########"
# Ramps up concurrency to simulate a traffic spike.
# Watch: EC2 > Auto Scaling Groups > Instances tab — new instances should appear.
echo "Starting 60-second wave at 500 concurrent..."
ab -n 50000 -c 500 -t 60 "$ALB/health"

echo ""
echo "########## ALL TESTS COMPLETE ##########"
echo "Take screenshots of:"
echo "  1. ab output (Requests/sec, Failed requests = 0)"
echo "  2. AWS Console > EC2 > Instances (multiple instances running)"
echo "  3. AWS Console > CloudWatch > ALB metrics (RequestCount, TargetResponseTime)"
echo "  4. The uniq -c output above showing 2+ instance IDs"
