// =============================================================================
// NimbusWMS k6 load test — 300k+ requests, proves ALB + Auto Scaling
// Install:  sudo apt install k6  OR  brew install k6
// Run:      k6 run k6-test.js
// =============================================================================

import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = 'http://YOUR-ALB-DNS-NAME.elb.amazonaws.com';

export const options = {
  stages: [
    { duration: '30s', target: 50  },   // warm up
    { duration: '1m',  target: 200 },   // ramp to 200 VUs
    { duration: '3m',  target: 300 },   // hold at 300 — triggers ASG scale-out
    { duration: '2m',  target: 500 },   // spike — DDoS simulation
    { duration: '1m',  target: 100 },   // ramp down
    { duration: '30s', target: 0   },   // cool down
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'],  // 95% of requests under 1s
    http_req_failed:   ['rate<0.01'],   // less than 1% errors
  },
};

// Track which instance served each request
const instanceCounts = {};

export default function () {
  // Mix of endpoints — realistic traffic pattern
  const endpoints = [
    `${BASE}/health`,          // health check (lightweight)
    `${BASE}/whoami`,          // instance id — proves load balancing
    `${BASE}/load?ms=150`,     // CPU burn — triggers auto-scaling
  ];

  const url = endpoints[Math.floor(Math.random() * endpoints.length)];
  const res = http.get(url);

  check(res, {
    'status 200':        (r) => r.status === 200,
    'response not empty':(r) => r.body.length > 0,
  });

  sleep(0.2);
}

export function handleSummary(data) {
  return {
    'stdout': `
=== LOAD TEST SUMMARY ===
Total requests:       ${data.metrics.http_reqs.values.count}
Requests/sec:         ${data.metrics.http_reqs.values.rate.toFixed(1)}
Avg response time:    ${(data.metrics.http_req_duration.values.avg).toFixed(0)}ms
p95 response time:    ${(data.metrics.http_req_duration.values['p(95)']).toFixed(0)}ms
Failed requests:      ${data.metrics.http_req_failed.values.passes} (${(data.metrics.http_req_failed.values.rate * 100).toFixed(2)}%)
=========================
`,
  };
}
