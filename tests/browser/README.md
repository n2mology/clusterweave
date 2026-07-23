# Browser regression tests

These Playwright tests exercise stable behavior in ClusterWeave's public
browser interface. They are developer tests, not stored analyses or examples
of operator data. Each specification intercepts the API calls it needs and
uses small, hand-written responses with synthetic job identifiers and tokens.

`npm run test:browser` starts `web/static` on `http://127.0.0.1:4173` for the
duration of the test run. This loopback address always refers to the machine
running the tests; it does not publish a ClusterWeave service to another
computer. The public suite deliberately has no live-server override.

To run the tests from the repository root:

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

Keep a browser test here when it protects a durable user-facing behavior and
can run without credentials, private result data, or an external service.
Operator verification, temporary screenshots, and one-time visual-alignment
work belong outside the public repository.
