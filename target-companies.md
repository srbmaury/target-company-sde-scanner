# Target Company List

This is the fixed company universe for the target-company SDE scanner. Companies are grouped into
tiers so a run can be scoped sensibly instead of firing 100+ searches every time. Unless the user
says otherwise, run **Tier 0 first**, report back, then ask whether to continue into Tier 1/2/3.

## Career site URLs (Tier 0 + Tier 1)

The table below has **live-verified career site URLs** for every company in Tier 0 and Tier 1
(checked via direct HTTP requests and official-site search on 2026-08-13). Open these directly instead of re-searching
for the portal every run — it saves a search per company. Tier 2 startup career surfaces are listed
below as discovery entry points, but never treat them as proof that a particular opening is live;
their ATS platforms change frequently.

Even with a known URL, don't assume it's still correct forever — career sites do get restructured.
If a fetch on one of these URLs 404s or looks stale, fall back to a fresh search rather than
reporting "no openings."

| Company | Career site URL | Notes |
|---|---|---|
| Google | careers.google.com | |
| Microsoft | jobs.careers.microsoft.com | |
| Amazon / AWS | amazon.jobs | |
| Meta | metacareers.com | |
| Apple | jobs.apple.com | |
| NVIDIA | nvidia.com/en-us/about-nvidia/careers/ | |
| Stripe | stripe.com/careers | Verified live |
| Atlassian | atlassian.com/company/careers | Verified live |
| Uber | jobs.uber.com | Verified live |
| Datadog | careers.datadoghq.com | Verified live |
| Cloudflare | cloudflare.com/careers | |
| Snowflake | careers.snowflake.com | Verified live |
| LinkedIn | careers.linkedin.com | |
| Adobe | careers.adobe.com/us/en/ | Verified live; replaces the retired `adobe.com/careers.html` route |
| Salesforce | salesforce.com/company/careers | |
| ServiceNow | careers.servicenow.com | |
| Workday | workday.com/en-us/company/careers.html | |
| SAP | jobs.sap.com | |
| VMware (by Broadcom) | broadcom.com/company/careers | **VMware no longer has a separate careers site — VMware roles are posted directly on Broadcom's careers site since the acquisition.** Verified live. |
| Goldman Sachs | goldmansachs.com/careers | |
| Morgan Stanley | morganstanley.com/careers/career-opportunities-search/ | Verified official opportunity search; avoids the generic `/careers` redirect |
| JPMorgan Chase | careers.jpmorgan.com | |
| American Express | americanexpress.com/en-us/careers | |
| Visa | visa.com/en-us/careers | Verified live; replaces the 404ing `usa.visa.com/careers` route |
| Mastercard | careers.mastercard.com | |
| Walmart Global Tech | careers.walmart.com | |
| Target | jobs.target.com | |
| Lowe's | talent.lowes.com/us/en/home | Verified official portal; replaces the TLS-failing legacy host |
| Costco | careers.costco.com | |
| Intuit | jobs.intuit.com | |
| PayPal | careers.pypl.com | |
| PayU | corporate.payu.com/careers | Not independently re-verified this run — spot-check |
| Block | block.xyz/careers | Not independently re-verified this run — spot-check |
| Expedia Group | careers.expediagroup.com | |
| Booking.com | careers.booking.com | |
| Priceline | careers.priceline.com | Verified official portal; replaces the non-resolving legacy domain |
| Cisco | jobs.cisco.com | |
| Palo Alto Networks | paloaltonetworks.com/careers | |
| CrowdStrike | crowdstrike.com/careers | |
| Zscaler | zscaler.com/careers | Not independently re-verified this run — spot-check |
| Netskope | netskope.com/company/careers | Not independently re-verified this run — spot-check |
| Rubrik | rubrik.com/company/careers | Verified live |
| Oracle | oracle.com/careers | |
| IBM (incl. IBM Research roles) | ibm.com/careers | IBM Research 1-3 YOE SDE roles are posted alongside regular IBM software engineering listings on this site, not a separate research-only portal |
| Red Hat | redhat.com/en/jobs | |
| Dell | jobs.dell.com | |
| Siemens | jobs.siemens.com | |
| Philips | careers.philips.com/global/en/ | Verified official global careers page |
| Bloomberg | bloomberg.com/company/ | Verified official corporate page with career navigation and job search; legacy careers host redirects here |
| Deutsche Bank | careers.db.com | |
| Wells Fargo | wellsfargojobs.com | |
| BlackRock | careers.blackrock.com | |
| Twilio | twilio.com/en-us/company/jobs | |
| Elastic | elastic.co/careers | |
| Confluent | careers.confluent.io | Verified live |
| MongoDB | mongodb.com/company/careers | Verified live |
| GitLab | about.gitlab.com/jobs | |
| GitHub | github.careers | |
| Disney+ Hotstar | linkedin.com/company/jiohotstar/jobs | Now branded **JioHotstar**. Use the official LinkedIn jobs page for brand-specific openings; also check `careers.jio.com` and search fresh because no standalone JioHotstar portal is confirmed. |
| Sony | sony.com/en/SonyInfo/Jobs | Not independently re-verified this run — spot-check |
| Qualcomm | qualcomm.com/company/careers | |
| Western Digital | jobs.westerndigital.com | Not independently re-verified this run — spot-check |

### Tier 0 India-based / dev-tool overlaps (also has verified URLs)

These appear in Tier 0 and also in Tier 2's category lists — verified here so they don't need
re-discovery on every Tier 0 run:

| Company | Career site URL | Notes |
|---|---|---|
| PhonePe | phonepe.com/careers | Verified live |
| Razorpay | razorpay.com/careers | Verified live |
| CRED | careers.cred.club | Verified live. **Careful**: "credplatform.com" is an unrelated company (an enterprise decision-intelligence startup) that showed up in search results — don't confuse it with CRED the fintech app |
| Groww | groww.in/careers | Verified live |
| Meesho | meesho.io/jobs | Verified live |
| Postman | postman.com/company/careers | Verified live |
| BrowserStack | browserstack.com/careers | Verified live |
| Hasura | hasura.io/careers/ | Verified official careers page; open roles may redirect to Hasura's ATS |
| Chargebee | chargebee.com/careers | Verified live |
| CleverTap | clevertap.com/careers | Verified live |
| Whatfix | whatfix.com/careers | Verified live |

## Tier 0 — Profile-priority (search these first, every run)

Grouped by the user's stated relevance ranking:

1. Stripe, Atlassian, Datadog, Snowflake, Confluent, MongoDB
2. Uber, PhonePe, Razorpay, CRED, Groww, Meesho
3. Postman, BrowserStack, Hasura, Chargebee, CleverTap, Whatfix
4. ServiceNow, Workday, Adobe, Intuit, LinkedIn, Microsoft
5. NVIDIA, Palo Alto Networks, Cloudflare, Rubrik, CrowdStrike

## Tier 1 — Highest-priority MNC / global product companies

- **Big tech**: Google, Microsoft, Amazon/AWS, Meta, Apple, NVIDIA
- **Infra/dev/cloud SaaS**: Stripe, Atlassian, Uber, Datadog, Cloudflare, Snowflake
- **Enterprise SaaS**: LinkedIn, Adobe, Salesforce, ServiceNow, Workday, SAP, VMware (by Broadcom)
- **Finance/fintech majors**: Goldman Sachs, Morgan Stanley, JPMorgan Chase, American Express, Visa, Mastercard
- **Retail tech**: Walmart Global Tech, Target, Lowe's, Costco
- **Payments/travel**: Intuit, PayPal, PayU, Block, Expedia Group, Booking.com, Priceline
- **Security**: Cisco, Palo Alto Networks, CrowdStrike, Zscaler, Netskope, Rubrik
- **Enterprise/legacy tech**: Oracle, IBM Research, Red Hat, Dell, Siemens, Philips
- **Finance/media**: Bloomberg, Deutsche Bank, Wells Fargo, BlackRock
- **Dev tools/data**: Twilio, Elastic, MongoDB, Confluent, GitLab, GitHub
- **Media/hardware**: Disney+ Hotstar (now JioHotstar), Sony, Qualcomm, Western Digital

### Tier 1 additions — global product, infrastructure, finance, and industrial companies

Search these alongside the groups above, keeping India-based and remote-eligible listings first.
Avoid duplicate searches for companies already present in Tier 1.

- **Consumer and collaboration**: Netflix, Spotify, Airbnb, Dropbox, eBay, Wayfair, Chewy, Roku,
  Zoom, RingCentral, GoDaddy
- **Industrial, engineering, and hardware**: Autodesk, Honeywell, Bosch, GE Vernova, Ciena, Juniper
  Networks, Arista Networks, F5, Akamai, Trimble, Bentley Systems, Medtronic, GE HealthCare, Roche,
  Novo Nordisk, Toyota Connected, Mercedes-Benz Research, Ford, Volvo Cars
- **Observability, Linux, and cloud**: Sumo Logic, Dynatrace, New Relic, Splunk, Grafana Labs, SUSE,
  DigitalOcean, Canonical
- **Finance and market data**: FIS, Fiserv, Nasdaq, S&P Global, FactSet, LSEG, BNY Mellon, UBS,
  Barclays, HSBC, Capital One
- **Storage and enterprise infrastructure**: Turing, Cohesity, Pure Storage, Nutanix, NetApp

**Classification notes**: Paytm is an India scale-up (Tier 2), not a Tier 1 MNC. GE Vernova and
GE HealthCare are distinct employers. Search Mercedes-Benz Research under the current India entity
name if the former brand does not surface a board.

### Tier 1 additions — frontier AI, developer platforms, security, fintech, and global product

Search India-based roles first, then India-eligible remote roles. For employers with limited India
presence, do not spend a full sweep on US-only boards unless the user asks for global roles.

- **Frontier AI and AI infrastructure**: OpenAI, Anthropic, Cohere, Perplexity, Mistral AI, Scale AI
- **Data, developer, and collaboration products**: Databricks, Palantir, Figma, Notion, Canva,
  HashiCorp, Redis, Sentry, Vercel
- **Identity and security**: Okta, Auth0, GitGuardian, Wiz, Check Point, Tenable
- **Engineering services / product delivery**: EPAM, Thoughtworks, Globant, Nagarro
- **Autonomy, EV, and mobility**: Cruise, Waymo, Zoox, Rivian, Tesla, Lucid Motors
- **Semiconductor, telecom, and systems**: ARM, Intel, AMD, Samsung Research, MediaTek, Samsung
  SDS, LG Soft India, Ericsson, Nokia, Hitachi Energy
- **Fintech and HR SaaS**: Checkout.com, Adyen, Wise, Revolut, Klarna, Affirm, Brex, Rippling, Deel,
  Gusto
- **Consumer, marketplace, and social**: Pinterest, Reddit, Discord, Twitch, Snap, Roblox, DoorDash,
  Instacart, Lyft, Grab, Gojek
- **Games and creator platforms**: Unity, Epic Games, Electronic Arts, Ubisoft, Zynga / Take-Two
- **Networking and enterprise systems**: Cisco Meraki, VMware Tanzu, HPE Aruba, Lenovo
- **Health, information, and education technology**: Optum, UnitedHealth Group, Cigna, IQVIA,
  Clarivate, Kyndryl, Thomson Reuters, Elsevier, RELX, Coursera, Duolingo, Udemy, Udacity

**Alias notes**: GitHub, GitLab, Grafana Labs, Temporal, Supabase, Qualcomm, PayPal, Cisco,
Broadcom, HPE, Siemens, and Spotify are already listed above; search each only once. Treat Auth0 as
Okta, Cisco Meraki and HPE Aruba as their parent-company career surfaces when necessary, and search
Zynga under Take-Two's current careers site when its standalone board is absent.

### Career surfaces for the new additions

Use these official entry points before a search-engine fallback. They are discovery surfaces, not
proof that a specific role remains open: always verify the exact posting and active application
control in the current run. Parent-company surfaces are deliberately used for acquired brands.

| Company | Official career surface |
|---|---|
| OpenAI | `openai.com/careers` |
| Anthropic | `anthropic.com/careers` |
| Cohere | `cohere.com/careers` |
| Perplexity | `perplexity.ai/careers` |
| Mistral AI | `mistral.ai/careers` |
| Scale AI | `scale.com/careers` |
| Databricks | `databricks.com/company/careers` |
| Palantir | `palantir.com/careers` |
| Figma | `figma.com/careers` |
| Notion | `notion.so/careers` |
| Canva | `canva.com/careers` |
| HashiCorp | `hashicorp.com/careers` |
| Redis | `redis.io/careers` |
| Sentry | `sentry.io/careers` |
| Vercel | `vercel.com/careers` |
| Okta / Auth0 | `okta.com/company/careers` |
| GitGuardian | `gitguardian.com/jobs` |
| Wiz | `wiz.io/careers` |
| Check Point | `checkpoint.com/careers` |
| Tenable | `tenable.com/careers` |
| EPAM | `careers.epam.com` |
| Thoughtworks | `thoughtworks.com/careers` |
| Globant | `careers.globant.com` |
| Nagarro | `nagarro.com/en/careers` |
| Cruise | `getcruise.com/careers` |
| Waymo | `waymo.com/careers` |
| Zoox | `zoox.com/careers` |
| Rivian | `rivian.com/careers` |
| Tesla | `tesla.com/careers` |
| Lucid Motors | `lucidmotors.com/careers` |
| ARM | `arm.com/company/careers` |
| Intel | `jobs.intel.com` |
| AMD | `careers.amd.com` |
| Samsung Research | `research.samsung.com/careers` |
| MediaTek | `careers.mediatek.com` |
| Samsung SDS | `samsungsds.com/careers` |
| LG Soft India | `lgsoftindia.com/careers` |
| Ericsson | `ericsson.com/en/careers` |
| Nokia | `nokia.com/careers` |
| Hitachi Energy | `careers.hitachienergy.com` |
| Checkout.com | `checkout.com/careers` |
| Adyen | `adyen.com/careers` |
| Wise | `wise.jobs` |
| Revolut | `revolut.com/careers` |
| Klarna | `klarna.com/careers` |
| Affirm | `affirm.com/careers` |
| Brex | `brex.com/careers` |
| Rippling | `https://ats.rippling.com/rippling/jobs` | Verified live ATS board (2026-08-13). Prefer this board over the marketing careers page; verify each exact job because the board is paginated and roles change quickly. |
| Deel | `deel.com/careers` |
| Gusto | `gusto.com/about/careers` |
| Pinterest | `careers.pinterest.com` |
| Reddit | `redditinc.com/careers` |
| Discord | `discord.com/careers` |
| Twitch | `twitch.tv/jobs` |
| Snap | `snap.com/en-US/jobs` |
| Roblox | `roblox.com/careers` |
| DoorDash | `doordash.com/careers` |
| Instacart | `instacart.careers` |
| Lyft | `lyft.com/careers` |
| Grab | `grab.careers` |
| Gojek | `gojek.com/careers` |
| Unity | `unity.com/careers` |
| Epic Games | `epicgames.com/site/en-US/careers` |
| Electronic Arts | `ea.com/careers` |
| Ubisoft | `ubisoft.com/en-us/company/careers` |
| Take-Two / Zynga | `take2games.com/careers` |
| Lenovo | `lenovo.com/us/en/careers` |
| Optum / UnitedHealth Group | `careers.unitedhealthgroup.com` |
| Cigna | `cigna.com/about-us/careers` |
| IQVIA | `iqvia.com/careers` |
| Clarivate | `clarivate.com/careers` |
| Kyndryl | `kyndryl.com/us/en/careers` |
| Thomson Reuters | `careers.thomsonreuters.com` |
| Elsevier | `elsevier.com/careers` |
| RELX | `relx.com/careers` |
| Coursera | `coursera.org/about/careers` |
| Duolingo | `careers.duolingo.com` |
| Udemy | `about.udemy.com/careers` |
| Udacity | `udacity.com/careers` |

## Tier 2 — Strong India-based startups / scale-ups

**Fintech and payments**: Razorpay, CRED, PhonePe, Groww, Navi, Jupiter, Fi, Fampay, Cashfree,
Pine Labs, BharatPe, Slice, KreditBee, Zeta, Meesho, Rupeek, Perfios, Acko, Policybazaar, OneCard,
CoinDCX, Mudrex, Khatabook, Niyo

**SaaS, dev tools, data and AI**: Postman, BrowserStack, Chargebee, Freshworks, Zoho, Hasura,
Whatfix, CleverTap, MoEngage, Unacademy, Mindtickle, HighRadius, Icertis, HackerRank, InMobi,
Observe.AI, Yellow.ai, Gupshup, Krutrim, Sarvam AI, Mad Street Den, Pixis, Rephrase.ai, Ema, Neysa,
Darwinbox, LeadSquared, Wingify/VWO, WebEngage

**Consumer, commerce and logistics**: Flipkart, Myntra, Swiggy, Zepto, Zomato, Blinkit, Ola, Rapido,
Porter, Ninjacart, Delhivery, BlackBuck, Urban Company, Dream11, Games24x7, MPL, Lenskart, Livspace,
PharmEasy, Tata 1mg, Practo, ShareChat, InMobi/Glance, Dailyhunt, Kuku FM

### Tier 2 additions — India startups and scale-ups

**Developer infrastructure, SaaS, and cloud**: Harness, Druva, DevRev, Uniphore, Amagi,
Infra.Market, Innovaccer, InVideo, Scaler, Sanity.io, Signeasy, Plotline, Appsmith, Supabase, Neon,
Temporal, Cockroach Labs, PlanetScale, Paytm

**AI, data, and health-tech**: Fractal Analytics, Tredence, Tiger Analytics, Arya.ai, Gnani.ai,
CoRover, Wysa, Qure.ai, SigTuple, Niramai, HealthPlix, Haptik, Locus.sh, Newton School, Jify,
Spektra Systems, Spotdraft, Leena AI

**Fintech**: Open Financial Technologies, Juspay, Setu, M2P Fintech, Decimal Technologies, Signzy,
Ezetap, Zaggle, Jar, Stable Money, Fam, IndigoLearn, ClearTax, OfBusiness, Flexiloans

**Commerce, consumer, and mobility**: Udaan, Moglix, Apna, NoBroker, CarDekho, Spinny, Cars24,
OLA Electric, Rebel Foods, Cure.fit, Dunzo, HealthifyMe, MediBuddy, HealthKart, MyGate, ChargeZone,
Yulu, BluSmart

**Stability note**: treat Dunzo as lower-priority and verify its current hiring operation before
spending search budget. Supabase, Neon, Temporal, Cockroach Labs, PlanetScale, and Sanity.io may
primarily have global/remote roles; retain them only when India eligibility is explicit.

### Tier 2 additions — India / remote-friendly startups to watch

Search these after the Tier 0 and priority queue, favoring roles with an explicit India location or
remote-in-India eligibility.

- **AI, developer, and creator tooling**: Emergent, CodeRabbit, Graphy, Replit, Lovable
- **Consumer and content**: Pocket FM, Pratilipi, Lokal
- **Web3 and fintech**: Biconomy, Polygon Labs, CoinSwitch, OnMeta, Smallcase, INDmoney, Dezerv
- **Agritech and B2B commerce**: Fyllo, AgroStar, DeHaat, Bijak
- **Edtech**: Classplus, Teachmint, Physics Wallah
- **Security, cloud, and deep tech**: Sprinto, Vanta, Drata, Snyk, E2E Networks, CloudSEK, Atomberg,
  Zetwerk

**Classification notes**: Replit, Lovable, Vanta, Drata, Snyk, CodeRabbit, and Polygon Labs often
hire globally; retain only listings clearly open to candidates in India unless global search is
requested. Koo is not added as an employer target because its service shut down; continue to search
ShareChat, Lokal, Pratilipi, and other active alternatives instead.

### Career surfaces for the new startup additions

For fast-moving startups, these are first stops rather than permanently trusted links; if an ATS has
moved, find the new employer-hosted board and update the reference in a future maintenance pass.

| Company | Official career surface |
|---|---|
| Emergent | `emergent.sh/careers` |
| CodeRabbit | `https://jobs.ashbyhq.com/coderabbit` | Official Ashby board discovered from the company careers flow; verify the exact posting and India eligibility. |
| Graphy | `graphy.com/careers` |
| Replit | `replit.com/careers` |
| Lovable | `lovable.dev/careers` |
| Pocket FM | `pocketfm.com/careers` |
| Pratilipi | `pratilipi.com/careers` |
| Lokal | `getlokalapp.com/careers` |
| Biconomy | `biconomy.io/careers` |
| Polygon Labs | `polygon.technology/careers` |
| CoinSwitch | `coinswitch.co/careers` |
| OnMeta | `onmeta.in/careers` |
| Fyllo | `fyllo.in/careers` |
| AgroStar | `agrostar.in/careers` |
| DeHaat | `dehaat.in/careers` |
| Bijak | `bijak.in/careers` |
| Classplus | `classplusapp.com/careers` |
| Teachmint | `teachmint.com/careers` |
| Physics Wallah | `physicswallah.com/careers` |
| Smallcase | `smallcase.com/careers` |
| INDmoney | `indmoney.com/careers` |
| Dezerv | `dezerv.in/careers` |
| Sprinto | `sprinto.com/careers` |
| Vanta | `vanta.com/careers` |
| Drata | `drata.com/careers` |
| Snyk | `snyk.io/careers` |
| E2E Networks | `e2enetworks.com/careers` |
| CloudSEK | `https://job-boards.greenhouse.io/cloudsek` | Verified live Greenhouse board (2026-08-13); open the exact `.../jobs/<id>` posting and confirm its Apply control. |
| Atomberg | `atomberg.com/careers` |
| Zetwerk | `zetwerk.com/careers` |

### Priority queue — search first after Tier 0

1. Harness, Druva, DevRev, Amagi, Uniphore
2. Splunk, Dynatrace, New Relic, Akamai, Arista Networks
3. Visa, Mastercard, American Express, Capital One, Bloomberg
4. Nutanix, Pure Storage, Cohesity, NetApp, DigitalOcean
5. Juspay, Open Financial Technologies, M2P Fintech, Setu, Innovaccer
6. Qure.ai, Fractal Analytics, Tiger Analytics, Tredence, Yellow.ai

## Tier 3 — Expanded employer pool for "more" requests

Use this pool after the higher-priority tiers, or immediately when the user says that MNC vs startup
does not matter. Discover every listing fresh; these employers use several ATS providers and a
previous role URL is never evidence that it remains open.

**Fresh official ATS sources**:

| Company | Official hiring surface | Search focus |
|---|---|---|
| YipitData | `job-boards.greenhouse.io/yipitdata` | India Remote; Go/Python/backend; 2+ years |
| project44 | `job-boards.greenhouse.io/project44` | Bengaluru; Software Engineer 2; Java/cloud |
| Welo Global | `jobs.lever.co/weloglobal` | Noida/India; JavaScript, Node, Vue |
| Point72 | `job-boards.greenhouse.io/point72` | Bengaluru; BPM/Appian and platform roles |
| UiPath | `jobs.ashbyhq.com/uipath` | Bangalore engineering; render the role page before using |
| Starburst | `job-boards.greenhouse.io/starburst` | India; Java, infrastructure, data platform |
| Addepar | `job-boards.greenhouse.io/addepar1` | Pune; backend and AI-platform engineering |
| Arcadia | `job-boards.greenhouse.io/arcadiacareers` | Chennai/India engineering |

**Additional companies to search fresh**: Baya Systems, Bolna AI, Hinge Health, Sarvam AI, Coram AI,
Redwood Software, Diligent, Poshmark, MiQ, Pfizer Digital, HPE, JLL, R1 RCM, Columbia Sportswear,
MakeMyTrip, Availity, Alegeus, Surya Digital, Appian, Truveta, Veeva Systems, Minitab, PAR Technology,
Observe.AI, HackerRank, Imply, Abnormal AI, Cerebras, Ownwell, Salary Finance, and Welo Global.

### Newly discovered employer surfaces

These employers surfaced in verified India/remote engineering searches. Use the listed employer
board first, then verify the exact posting and its experience band before returning it.

| Company | Official hiring surface | Search focus |
|---|---|---|
| AI Squared | `job-boards.greenhouse.io/aisquared` | India Remote; backend / SDE2 |
| Alif Semiconductor | `jobs.lever.co/alifsemi` | Bangalore; embedded / RTOS; 2–4 years |
| BJAK | `jobs.ashbyhq.com/bjakcareer` | Remote India; full-stack / fintech / AI |
| Dialpad | `job-boards.greenhouse.io/dialpad` | Bengaluru; backend / integrations / platform |
| Dun & Bradstreet | `jobs.lever.co/dnb` | Hyderabad; Java / API / cloud services |
| HighLevel | `jobs.lever.co/gohighlevel` | India Remote; mobile / backend / platform |
| Perch Energy | `job-boards.greenhouse.io/perchenergycareers` | Remote India; L2 full-stack |
| Shield AI | `jobs.lever.co/shieldai` | Bangalore / Delhi; C++ / Python / autonomy |
| SolarWinds | `solarwinds.com/careers` | Bengaluru; platform engineering / SDE-2 |
| Workloom (Tetriz) | `jobs.lever.co/epifi` | Bangalore; backend / full-stack / AI systems |

### Additional product and AI companies

Prioritize India-based roles, then remote roles explicitly eligible for candidates in India.

| Company | Official hiring surface | Search focus |
|---|---|---|
| Atlan | `atlan.com/careers` | India/remote; data platform / AI / backend |
| ClickHouse | `job-boards.greenhouse.io/clickhouse` | Remote; databases / cloud infrastructure / C++ |
| Commure | `commure.com/careers` | India; healthcare platform / data engineering |
| ElevenLabs | `elevenlabs.io/careers` | Remote; AI audio / developer platform |
| Glean | `job-boards.greenhouse.io/gleanwork` | Bengaluru; enterprise AI / search / backend |
| Harvey | `harvey.ai/careers` | India-eligible remote; AI platform / reliability |
| MishiPay | `mishipay.com/career` | Bengaluru; retail-tech / payments / backend |
| PostHog | `posthog.com/careers` | India-eligible remote; developer tools / analytics |

### Additional expansion — developer products, data platforms, and India scale-ups

Use this queue after the profile-priority companies and before broad Tier 3 discovery. The career
surfaces are starting points only: re-check the exact employer-hosted posting and live application
control before returning a role.

- **Global developer, data, and SaaS**: HubSpot, Shopify, Zendesk, Braze, Amplitude, Mixpanel,
  Kong, Neo4j, Couchbase, Dataiku, Celonis, Tyk, 6sense, Algonomy
- **India SaaS and enterprise platforms**: Keka, Capillary Technologies, Vymo, Kissflow,
  Kapture CX, GreyOrange, Mettl (Mercer), Xoxoday, Exotel, Shiprocket
- **Consumer, mobility, and commerce**: Ather Energy, OYO, Licious, Purplle, boAt, Wakefit,
  Pristyn Care, Country Delight

| Company | Official career surface | Search focus |
|---|---|---|
| HubSpot | `hubspot.com/careers` | India / remote; backend, platform, data |
| Shopify | `shopify.com/careers` | Remote India eligibility; backend / infrastructure |
| Zendesk | `jobs.zendesk.com` | India; SaaS platform / backend |
| Braze | `braze.com/company/careers` | India / remote; messaging infrastructure |
| Amplitude | `amplitude.com/careers` | India-eligible remote; product analytics |
| Mixpanel | `mixpanel.com/careers` | India-eligible remote; data / backend |
| Kong | `konghq.com/careers` | Bengaluru / remote; API platform / Go |
| Neo4j | `neo4j.com/careers` | India; databases / distributed systems |
| Couchbase | `couchbase.com/careers` | Bengaluru; databases / cloud |
| Dataiku | `dataiku.com/careers` | India; AI platform / full-stack |
| Celonis | `celonis.com/careers` | India; data platform / backend |
| Tyk | `tyk.io/careers` | India-eligible remote; API management |
| 6sense | `6sense.com/careers` | Bengaluru / Pune; data and platform |
| Algonomy | `algonomy.com/careers` | Bengaluru; decisioning / data platform |
| Keka | `keka.com/careers` | Hyderabad; SaaS backend / full-stack |
| Capillary Technologies | `capillarytech.com/careers` | Bengaluru; retail SaaS / Java |
| Vymo | `vymo.com/careers` | Bengaluru; enterprise mobile / backend |
| Kissflow | `kissflow.com/careers` | Chennai; workflow SaaS |
| Kapture CX | `kapturecx.com/careers` | Bengaluru; customer-support SaaS |
| GreyOrange | `greyorange.com/careers` | Gurgaon / Bengaluru; robotics / platform |
| Mettl (Mercer) | `mercer.com/careers` | Gurgaon; assessment platform / backend |
| Xoxoday | `xoxoday.com/careers` | Bengaluru; rewards-platform backend |
| Exotel | `exotel.com/careers` | Bengaluru; communications platform |
| Shiprocket | `shiprocket.in/careers` | Delhi / Gurgaon; logistics platform |
| Ather Energy | `atherenergy.com/careers` | Bengaluru; EV software / platform |
| OYO | `careers.oyorooms.com` | India; marketplace / backend |
| Licious | `licious.in/careers` | Bengaluru; commerce / supply-chain systems |
| Purplle | `purplle.com/careers` | Mumbai / Bengaluru; commerce platform |
| boAt | `boat-lifestyle.com/careers` | India; consumer-commerce systems |
| Wakefit | `wakefit.co/careers` | Bengaluru; commerce / data |
| Pristyn Care | `pristyncare.com/careers` | Gurgaon; health-tech platform |
| Country Delight | `countrydelight.in/careers` | Gurgaon; consumer / logistics platform |

**ATS query toolkit** (use company name plus the target location/level):

- Greenhouse: `site:job-boards.greenhouse.io "<company>" "Software Engineer" India`
- Lever: `site:jobs.lever.co "<company>" "Software Engineer" India`
- Ashby: `site:jobs.ashbyhq.com "<company>" "Software Engineer" India`
- Workday: `site:myworkdayjobs.com "<company>" "Software Engineer II" India`
- Amazon: official India search filtered to `1-3 years`, then direct-job-ID verification.

## Notes on coverage

- Some names above are duplicated across tiers (e.g. Razorpay, CRED, PhonePe, Groww, Meesho are
  both Tier 0 and Tier 2; NVIDIA/Palo Alto/Cloudflare/Rubrik are both Tier 0 and Tier 1) — search
  them once, not twice.
- "Unacademy" was flagged by the user as "more variable" — treat as lower priority if the run needs
  to be trimmed for time.
- IBM Research is a research org; its openings for 1-3 YOE SDE roles will mostly be regular IBM
  software engineering postings rather than pure-research roles — search IBM's general careers site.
