# Supplemental job platforms

Use these after the employer-careers pass. They are discovery sources, not a substitute for opening
and verifying the exact employer posting.

| Platform | Entry point | Best use | Handling |
|---|---|---|---|
| YC Jobs (Work at a Startup) | `ycombinator.com/jobs` | YC-backed startups, including India and remote filters | Prefer company ATS link; retain YC-only apply routes only after visible current-run verification. |
| Wellfound | `wellfound.com/jobs` | Global startup and remote roles | Keep only India or explicitly global-remote listings. |
| Cutshort | `cutshort.io` | India product/startup engineering | Board-only route is acceptable only with a visible active application action. |
| Hirist | `hirist.tech` | India product, fintech, backend, data, and DevOps roles | Prefer the employer link when exposed; otherwise label as Hirist. |
| Foundit | `foundit.in` | Broad India technology coverage | Use as a secondary discovery pass; de-duplicate aggressively. |
| Unstop | `unstop.com/jobs` | India early-career through 1–3 YOE roles | Filter out internships and campus-only drives unless requested. |
| Internshala | `internshala.com/jobs` | India entry-level and junior full-time roles | Filter strictly for full-time, non-intern listings with 1–3 YOE overlap. |

CareerHound (`careerhound.ai`) is an application tracker/aggregator rather than a primary
posting board. Use it to surface a company careers URL, then verify the employer page independently.

## Added sources

| Platform | Entry point | Best use | Handling |
|---|---|---|---|
| LinkedIn | `linkedin.com/jobs` | Broad India and employer-posted discovery | Prefer the employer link; retain a LinkedIn-only route only after its active Apply control is visible. |
| Indeed | `indeed.com` / `in.indeed.com` | Broad India discovery | Follow the employer apply link; label a board-only route. |
| Glassdoor | `glassdoor.com/Job` | Cross-check company and role discovery | Treat as a lead; verify the employer page or visibly active board application. |
| Google job cards | Google Search | Discover canonical employer and ATS URLs | Never treat a job card or search snippet as verification; open the exact posting. |
| SubmitX | `submitx.com` | Application/workflow discovery when a real employer link is exposed | Treat as an aggregator or workflow tool, not a verification source. Do not automate submissions without the user's confirmation. |
| Handshake | `joinhandshake.com` | Student/early-career roles | Retain only roles explicitly open to India or globally remote candidates. |
| Built In | `builtin.com/jobs` | Product and technology-company discovery | India eligibility is often limited; require an India location or explicit global-remote eligibility. |
| Jobs24x7 | `jobs24x7.com` | India discovery | Verify employer identity and active application control; de-duplicate heavily. |
| Remote OK | `remoteok.com` | Global remote engineering | Require explicit India eligibility; generic “remote” is insufficient. |
| We Work Remotely | `weworkremotely.com` | Global remote engineering | Require explicit India eligibility; use the employer posting where available. |
| Himalayas | `himalayas.app/jobs` | Remote-first company discovery | Retain only India/global-remote roles and verify the employer URL. |
| Jobspresso | `jobspresso.co` | Curated remote roles | Check employer page and India eligibility. |
| Dynamite Jobs | `dynamitejobs.com` | Distributed remote companies | Check India eligibility and employment type. |
| Working Nomads | `workingnomads.com/jobs` | Remote job discovery | Treat as an aggregator; verify the canonical employer posting. |
| Remote.co | `remote.co/remote-jobs` | Remote company/role discovery | Treat as an aggregator; verify India eligibility and the employer posting. |
| SkipTheDrive | `skipthedrive.com` | Remote discovery | Treat as an aggregator; verify the canonical employer posting. |
| Jobgether | `jobgether.com` | Remote hiring discovery | Verify country eligibility and the employer/ATS application route. |
| Underdog.io | `underdog.io` | Talent-network and startup discovery | Usually geography-dependent; retain only explicit India/global-remote matches. |

## Recruiters, contracting networks, and freelance marketplaces

| Source | Scope | Handling |
|---|---|---|
| Michael Page, Randstad, Adecco, ABC Consultants, TeamLease, Quess | India recruiting agencies | Use to discover specific client roles. Verify the client/job details and label the agency route; never infer compensation, employer, or status from a generic recruiter profile. |
| Turing, Arc, Andela, Toptal | Talent networks / contract platforms | Use only when the user accepts contract or remote-network work. Do not promise “no HR rounds” or a paid trial; each role's process varies. |
| Upwork, Fiverr, Truelancer | Freelance marketplaces | Exclude from default full-time SDE searches. Include only when the user asks for freelance/side work; never submit proposals without specific approval. |
| Automattic | Employer careers | Search its official careers page directly; do not treat it as a trial-only platform. |
| Apna, WorkIndia | India hiring boards | Useful for direct employer contact, but verify the exact job and active apply/contact control. |

## Social and content channels

Terms such as `OnlineJobs`, `WorkFromHome`, `CareerTips`, `JobTips`, `FreshersJobs`, `TechJobs`,
`Freelancing`, `SideHustle`, `CareerGrowth`, `JobOpportunities`, `Hiring`, `Internships`,
`RemoteWork`, `ContentWriting`, `VideoEditing`, `InstagramJobs`, and `LinkedInJobs` are search
topics or social-content labels, not reliable job platforms. Use them only for lead discovery. Do
not report a social post, Instagram reel, hashtag, Telegram/WhatsApp forward, or SEO article as a
job opening until the exact employer or active board posting is verified. Filter internships,
student jobs, content work, and non-engineering freelance work out of the default 1–3 YOE SDE scan.

`OnlineJobs.ph` is a Philippines-focused remote marketplace; include it only if the posting
explicitly permits applicants based in India. “Jobs without interview/degree” claims are never a
selection criterion and must not bypass normal legitimacy checks.

## Research-tool boundary

If a Firecrawl connector is configured and callable, it may be used to extract public employer job
pages for discovery. It does not replace browser verification of the exact live posting. Do not
assume a connection to Claude or use another model/service without an installed connector and the
user's authorization.
