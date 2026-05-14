# Draft Note To Upstream Tool Maintainers

Subject: ClusterWeave hosted portal, citation posture, and aggregate usage reporting

Hello <maintainer/team>,

I am writing because ClusterWeave uses <tool name> as part of a guided biosynthetic gene cluster
analysis workflow. ClusterWeave is not intended to replace your official service or imply
endorsement by your team. It is a portal and workflow wrapper that helps non-coding researchers run
publicly available BGC discovery tools together, keep provenance, and recover results through a
private result link.

Our current public-facing posture is:

- We identify <tool name> by name in the ClusterWeave interface and documentation.
- We link users to the official project/source page.
- We include your preferred citation in the ClusterWeave citation and third-party tool section.
- We preserve version/container provenance for runs where practical.
- We do not present ClusterWeave outputs as official <tool name> web-service reports.
- We do not share user-submitted data, private result links, job IDs, or unpublished outputs with
  third parties.

One concern raised during our deployment review is that third-party portals can make upstream web
service metrics undercount real scientific use. We would like ClusterWeave to expand access while
still making upstream impact visible. If useful to your team, we can periodically share aggregate,
non-identifying usage summaries such as approximate run counts, tool versions used, and citation
language used in the portal. We would not share submitted genomes, accession lists tied to users,
private links, emails, IP addresses, job IDs, or result payloads without explicit permission.

Please let us know if you have preferred citation wording, logo/name usage preferences, a preferred
metrics format, or any deployment guidance we should follow. We are grateful that your work is
available to the community; ClusterWeave exists because tools like <tool name> make open,
interdisciplinary natural-products research possible.

Best,

<name>

## Manuscript-Ready Short Version

ClusterWeave is a portal and workflow wrapper around publicly available BGC discovery tools, not a
replacement for official upstream services. The interface links to upstream projects, reports
tool/container provenance, and asks users to cite each underlying tool. To support upstream impact
tracking, the ClusterWeave operators will offer aggregate, non-identifying usage summaries to tool
maintainers on request while never sharing private user data, job IDs, submitted genomes, result
links, or unpublished outputs without permission.
