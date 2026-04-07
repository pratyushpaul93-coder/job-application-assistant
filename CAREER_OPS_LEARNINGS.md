# Career-Ops Reference: Learnings & API Research
# Source: santifer/career-ops (8.2k stars) + our own API testing
# Updated: April 7 2026

## Key Architectural Difference
career-ops: Claude Code local, Playwright primary, PDF output
our system: OpenClaw VPS, ATS APIs primary, WhatsApp interface

## ATS Public APIs (NO AUTH REQUIRED - ZERO HALLUCINATION RISK)

### Ashby
GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
Returns: jobs[], title, isRemote, jobUrl, applyUrl, compensation, location
Confirmed working: ramp(130), notion(161), vanta(163)

### Greenhouse  
GET https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Returns: jobs[], title, location{name}, absolute_url, content
EU variant: https://job-boards.eu.greenhouse.io/{slug}
Confirmed working: brex(250), gleanwork(testing)
NOTE: slug != company name always. glean -> gleanwork, wandb -> wandb

### Lever
GET https://api.lever.co/v0/postings/{slug}
Returns: [] array of {text(title), hostedUrl, categories{location,team}}
Confirmed: figma(returns 0 S&O -- need better keyword matching)

### ATS Detection Order
Try each in sequence, use first that returns jobs > 0:
1. Ashby: api.ashbyhq.com/posting-api/job-board/{slug}
2. Greenhouse: api.greenhouse.io/v1/boards/{slug}/jobs
3. Lever: api.lever.co/v0/postings/{slug}
4. Fallback: custom_ats -> Tavily search or Playwright

## Company List (ATS verified)
company | ats | slug | fit_score | notes
ramp | ashby | ramp | 5 | Fintech S&O roles
notion | ashby | notion | 4 | 161 jobs, 19 S&O
vanta | ashby | vanta | 5 | Security SaaS
harvey | ashby | harvey | 5 | AI legal (test needed)
glean | greenhouse | gleanwork | 5 | Enterprise AI search
brex | greenhouse | brex | 4 | Fintech
cyera | greenhouse | cyera | 5 | Security (test needed)
airtable | greenhouse | airtable | 4 | No-code
vercel | greenhouse | vercel | 3 | Dev tooling
intercom | greenhouse | intercom | 4 | CX/AI
anthropic | greenhouse | anthropic | 4 | AI lab
figma | lever | figma | 3 | Design tool
mistral | lever | mistral | 3 | AI lab EU
wandb | lever | wandb | 3 | MLOps
spotify | lever | spotify | 3 | Marketplace

## From career-ops portals.yml (45+ companies)
elevenlabs | ashby | elevenlabs
cohere | ashby | cohere
langchain | ashby | langchain
pinecone | ashby | pinecone
n8n | ashby | n8n
zapier | ashby | zapier
sierra | ashby | sierra
decagon | ashby | decagon
retool | custom | websearch only
openai | custom | websearch only
salesforce | custom | websearch only

## career-ops 3-Tier Strategy (adapted for us)
Their priority: Playwright > Greenhouse API > WebSearch
Our priority:   ATS JSON API > Tavily WebSearch > Playwright (last resort)

Reason we flip it: VPS without persistent browser session makes Playwright
expensive. ATS APIs are instant, free, and return structured JSON with ZERO
hallucination risk because they're real data not LLM-generated.

## Liveness Verification (career-ops insight)
WebSearch results can be WEEKS stale (Google caches job listings).
Before adding WebSearch results to shortlist, verify URL is still live.
Dead job signals:
  - URL contains ?error=true (Greenhouse expired redirect)
  - Page says "no longer available" / "position filled"
  - Page content < 300 chars (just navbar/footer)
ATS API results are inherently live -- no verification needed.

## Scoring Improvements to Borrow from career-ops
Add these dimensions to Matcher:
  - comp_estimate: WebSearch for salary range at this company/level
  - red_flags: funding unclear, requires relocation without support, 
               company < 20 people, no remote policy stated
  - north_star_fit: does role match Pratyush target archetype exactly

## PDF Generation Insight (for Resume Tailor)
career-ops approach: HTML template -> Playwright -> PDF
For our .docx problem: HTML template -> pandoc -> .docx
pandoc is already available on Ubuntu, can convert HTML to docx cleanly
Command: pandoc resume.html -o resume.docx --reference-doc=template.docx

## Files to Review in /root/career-ops/
modes/scan.md -- REVIEWED (3-tier strategy, dedup logic)
templates/portals.example.yml -- REVIEWED (45+ companies, slugs)
modes/_shared.md -- REVIEWED (scoring system, rules)
modes/oferta.md -- TODO (single job evaluation)
modes/pdf.md -- TODO (PDF generation details)
templates/cv-template.html -- TODO (ATS-optimized HTML template)
config/profile.example.yml -- TODO (candidate profile structure)
