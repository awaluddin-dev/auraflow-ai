// load-test.js
import http from "k6/http";
import { check } from "k6";

export const options = {
  vus: 5, // 5 virtual users
  duration: "10s",
};

export default function () {
  const payload = JSON.stringify({
    rawData: `budi santoso ${__VU}, ${__VU * 1000000}, 2024-01-01`,
  });

  const res = http.post("http://localhost:3000/jobs", payload, {
    headers: { "Content-Type": "application/json" },
  });

  check(res, {
    "status 202": (r) => r.status === 202,
    "has jobId": (r) => JSON.parse(r.body).jobId !== undefined,
  });
}
