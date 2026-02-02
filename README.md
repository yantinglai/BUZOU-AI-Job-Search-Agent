# BUZOU-AI-Job-Search-Agent

# buzou.com — AI Job Agent

I got laid off by Amazon, and the irony is I still have to rely on the same internal systems to find my next role.

**buzou.com** is a small protest and a survival tool:  
I’m not leaving quietly — but I’m also not wasting time.

## What it does (today)

- Scrapes recommended roles from the internal job portal
- Extracts key fields (title, location, job id, hiring manager, recruiter)
- Scores and ranks roles based on my preferences
- Exports results to `jobs.json` / `jobs.csv`

## Roadmap (next)

- Improve extraction reliability (job id / title / description)
- Generate a “why I’m a match” draft for each role
- Auto-monitor new roles on a schedule
- (Later) one-click apply workflows

## Personal preferences (current config)

Right now this repo is tuned for **my** search:

- Prefer: Bay Area / NYC / LA
- Avoid: Seattle
- Avoid: frontend / full-stack
- Prefer: systems + AI/ML infra signals

The goal is to make this configurable so anyone can plug in their own priorities.

## Notes

Have fun and happy coding!
