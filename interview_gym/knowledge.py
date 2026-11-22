"""Interview calibration knowledge: difficulty bands, company tiers, per-role topics, and the area taxonomy.

Compiled from 2024-2026 candidate reports (LeetCode Discuss, Medium, Substack, Glassdoor) for Indian product
companies and Big Tech India. Recurring patterns:
- Indian product unicorns (Flipkart, Razorpay, Swiggy, CRED, PhonePe, Uber India) open SDE-2 loops with a
  60-150 min machine-coding round that expects *running*, extensible code, then LLD + HLD + hiring manager.
  Many SDE-2 rejections come from LLD / schema design, not DSA.
- Google L3 is mostly coding (LC easy/medium, some hard); from L4 one round becomes system design and coding
  skews medium/hard with heavy follow-ups. Googleyness is behavioral (ambiguity, conflict, influence).
- Frontend loops (Flipkart UI-2 and similar) include machine coding in vanilla JS/React, JS deep dive (event loop,
  promises, polyfills for bind/reduce/Promise.all, debounce/throttle), DOM/browser, frontend system design.
- DevOps/SRE loops at product companies are scenario-heavy: "pods Running but users get 503", failed terraform
  apply, CrashLoopBackOff, plus Linux/networking, CI/CD design and an incident you personally handled.
"""
from __future__ import annotations

DIFFICULTIES = {
    "Easy": "0-2 years (SDE-1 / fresher / junior)",
    "Medium": "2-4 years (SDE-2 / mid-level)",
    "Hard": "4-5+ years (Senior SDE / SDE-2 high bar / SDE-3)",
}
DIFFICULTY_LABELS = [f"{k} - {v.split(' (')[0]}" for k, v in DIFFICULTIES.items()]

COMPANY_TIERS = {
    "Startup": {
        "examples": "seed to Series C startups, early-stage SaaS",
        "style": "Practical and project-heavy. Framework depth, 'how did you build X', debugging, take-home or "
                 "pairing. DSA usually LeetCode easy/medium. Light system design focused on what they actually run.",
    },
    "Product unicorn": {
        "examples": "Flipkart, Razorpay, Swiggy, Zomato, CRED, PhonePe, Meesho, Zepto, Groww, Paytm",
        "style": "Machine-coding round (60-150 min, working + extensible code, SOLID, design patterns, in-memory "
                 "stores), LLD (classes, schema, APIs), HLD from SDE-2 (business-flavoured: payments, orders, "
                 "delivery), DSA LeetCode medium, hiring-manager round with project deep dive.",
    },
    "Big Tech": {
        "examples": "Microsoft, Amazon, Atlassian, Uber, Adobe, Salesforce, Walmart, Intuit, Oracle",
        "style": "2-3 DSA rounds (medium, some hard) with clean code and complexity analysis, LLD (parking lot, "
                 "BookMyShow, vending machine, rate limiter), HLD from SDE-2, behavioral bar raiser "
                 "(Amazon Leadership Principles, Atlassian values) using STAR stories.",
    },
    "Top tier": {
        "examples": "Google, Meta, Apple, Netflix, top quant/HFT tech",
        "style": "Coding LeetCode medium-hard/hard with multiple follow-ups and optimal complexity expected; "
                 "system design from L4/E4 upward with deep trade-offs and scale numbers; behavioral "
                 "(Googleyness: ambiguity, conflict, influence without authority). Very high bar on communication "
                 "and testing your own code.",
    },
}
TIER_NAMES = list(COMPANY_TIERS)

# What each difficulty band means, independent of role.
# The market has moved up: even fresher loops at product companies no longer ask "easy" questions.
DIFFICULTY_BAR = {
    "Easy": "Today's fresher/SDE-1 bar at product companies (there are no easy interviews any more): LeetCode medium "
            "is the floor, usually with a harder follow-up; CS fundamentals asked down to internals (how a mutex is "
            "implemented, what happens on a page fault, how a B+ tree index is laid out, what really happens when "
            "you type a URL); OOP with real class design; every line on the resume grilled for depth and numbers.",
    "Medium": "SDE-2: LeetCode medium-hard with optimal complexity and clean code; machine coding that runs and "
              "survives changing requirements; LLD with concurrency and schema; HLD with capacity numbers, "
              "bottlenecks, failure handling and trade-offs; production debugging stories with specifics.",
    "Hard": "Senior: hard-level problem solving with multiple follow-ups; HLD with deep trade-offs (consistency, "
            "partitioning, multi-region, cost, failure modes); ownership, ambiguity, influence and mentoring stories "
            "with measurable impact; constant pushback that you must handle calmly.",
}

HARSH_RULES = """Interviewer stance (non-negotiable):
- You are a strict bar-raiser who does not want to pass anyone easily. Neutral-to-skeptical tone; no praise, no \
"great answer", no reassurance. Acknowledge with "Ok.", "Got it.", "Right." or "Alright." (never write "Okay") and move deeper.
- Go DEEP before going wide. On every topic, drill one level deeper per follow-up: definition -> how it works \
internally -> edge cases and failure modes -> scale/performance/trade-offs -> real-world experience ("when did you \
hit this in production?"). Keep drilling while there is scope; switch topic only when the candidate has clearly \
hit their ceiling twice, or the topic is genuinely exhausted.
- Never accept vague, buzzword or textbook answers: ask "why?", "how exactly?", "what would break?", "give me \
numbers", "what did YOU do?".
- Set interview traps regularly (at least one in every 2-3 questions, even at Easy level), and never reveal them.
- Prefer variety: unusual angles, scenario framing, and less-common sub-topics over the standard textbook question.
- If a topic was already covered or the candidate is strong in it, escalate the difficulty instead of repeating."""

TRAPS = [
    "False premise: put a subtly wrong assumption in the question (e.g. 'since HashMap is thread-safe...'); a strong "
    "candidate challenges it.",
    "Pushback on a correct answer: say 'Are you sure? I don't think that's right.'; a strong candidate holds their "
    "position with reasoning instead of caving.",
    "Missing constraints: give an ambiguous problem; a strong candidate asks clarifying questions before solving.",
    "Moving goalposts: after they solve it, change a constraint (10x scale, memory cap, concurrent writers, "
    "streaming input, strict latency).",
    "Edge-case bait: give examples that hide the hard case (empty input, duplicates, overflow, negatives, time zones, "
    "unicode, retries, partial failure).",
    "Complexity bait: ask 'so that's O(n), right?' when it isn't (amortised, hidden sort, recursion stack, hashing "
    "worst case).",
    "Buzzword probe: when they name-drop a tool (Kafka, Redis, Kubernetes, microservices), drill into its internals "
    "and ask why not the alternative.",
    "Resume depth probe: take a resume claim and demand numbers, their exact contribution, what failed, what they'd "
    "change.",
    "'It depends' trap: ask for 'the best' approach where the right answer is trade-offs; a strong candidate states "
    "the conditions.",
    "Over-engineering bait: invite a complex design where a simple one is enough; a strong candidate keeps it simple "
    "and says why.",
    "Silent treatment: give no reaction after an answer; a strong candidate summarises and checks in instead of "
    "rambling.",
]

# Per-role topic ladders. Interviewer picks from the band (and may dip one band lower to warm up).
ROLE_TOPICS: dict[str, dict[str, list[str]]] = {
    "Software Developer": {
        "Easy": ["arrays/strings/hashmaps", "two pointers & sliding window", "OOP pillars", "OS: process vs thread, "
                 "deadlock", "DBMS: normalization, indexes, joins, ACID", "CN: TCP vs UDP, HTTP, DNS",
                 "project walkthrough", "Git basics"],
        "Medium": ["trees/graphs/DP medium", "LLD with SOLID & patterns", "machine coding (in-memory system)",
                   "REST API design", "caching & DB indexing trade-offs", "concurrency basics", "HLD of a common app",
                   "debugging a production issue"],
        "Hard": ["hard DSA with follow-ups", "HLD at scale with numbers", "distributed systems (consistency, "
                 "replication, partitioning)", "leading projects, trade-off decisions", "performance tuning",
                 "mentoring and conflict stories"],
    },
    "Frontend Developer": {
        "Easy": ["HTML semantics & accessibility", "CSS box model, flex, grid, specificity", "JS: var/let/const, "
                 "hoisting, closures, this", "DOM events, bubbling, delegation", "React basics: props, state, "
                 "useEffect", "fetch & promises"],
        "Medium": ["event loop, microtasks", "polyfills: bind, reduce, Promise.all, debounce, throttle",
                   "React reconciliation, keys, memo, useCallback, custom hooks", "state management (Context, Redux, "
                   "Zustand)", "machine coding: autocomplete, infinite scroll, modal, star rating, todo with filters",
                   "web performance: Core Web Vitals, code splitting, lazy loading", "browser storage, CORS, cookies "
                   "& security (XSS, CSRF)"],
        "Hard": ["frontend system design (news feed, Google Docs-like editor, design system, micro-frontends)",
                 "rendering strategies (CSR, SSR, SSG, ISR, streaming, RSC)", "performance at scale, bundle "
                 "analysis", "offline/PWA, service workers", "testing strategy", "leading frontend architecture"],
    },
    "Backend Developer": {
        "Easy": ["OOP & language basics (Java/Python/Node)", "REST & HTTP status codes", "SQL queries, joins, "
                 "indexes", "ACID & transactions", "basic auth (sessions vs JWT)", "DSA easy/medium"],
        "Medium": ["machine coding: Splitwise, parking lot, rate limiter, pub/sub, logger, in-memory KV",
                   "DB design & isolation levels", "caching (Redis) & invalidation", "message queues (Kafka, "
                   "RabbitMQ), idempotency", "Spring Boot / Node internals", "API design, pagination, versioning",
                   "HLD: URL shortener, notification service, payment flow"],
        "Hard": ["distributed transactions, saga, outbox", "consistency models, CAP/PACELC", "sharding & "
                 "rebalancing", "high-throughput system design (payments, order management, feed)", "observability "
                 "& incident ownership", "JVM/GC or runtime tuning"],
    },
    "Full Stack Developer": {
        "Easy": ["JS fundamentals", "React basics", "REST API in Node/Express or Spring", "SQL basics", "auth flow "
                 "end to end", "deploying an app"],
        "Medium": ["machine coding: full feature (UI + API)", "React performance & state", "API design & DB "
                   "schema", "caching layers (browser, CDN, Redis)", "security: XSS, CSRF, CORS, JWT pitfalls",
                   "HLD of a web product"],
        "Hard": ["end-to-end system design with frontend + backend trade-offs", "SSR/edge rendering", "scaling DB "
                 "& services", "CI/CD & release strategy", "architecture ownership"],
    },
    "DevOps / Cloud Engineer": {
        "Easy": ["Linux commands, permissions, processes", "networking: DNS, TCP, ports, load balancer", "Git "
                 "workflows", "Docker basics: image vs container, Dockerfile", "CI/CD concepts", "AWS core: EC2, "
                 "S3, IAM, VPC basics", "bash scripting"],
        "Medium": ["Kubernetes: pods, deployments, services, ingress, probes, HPA", "troubleshooting: "
                   "CrashLoopBackOff, ImagePullBackOff, 503s with Running pods", "Terraform: state, modules, "
                   "plan/apply failures, drift", "CI/CD pipeline design (Jenkins, GitHub Actions, ArgoCD)",
                   "Helm", "monitoring: Prometheus, Grafana, alerting", "secrets management"],
        "Hard": ["designing a multi-env platform", "SRE: SLO/SLI/error budgets, incident response, postmortems",
                 "K8s networking & scheduling internals", "zero-downtime deploys: blue-green, canary", "cost "
                 "optimization", "multi-region DR", "security & compliance at scale"],
    },
    "System Design - LLD": {
        "Easy": ["OOP pillars with examples", "SOLID with code", "basic patterns: singleton, factory, strategy, "
                 "observer", "class design: library system, tic-tac-toe"],
        "Medium": ["parking lot, BookMyShow, Splitwise, elevator, vending machine, snake & ladder", "rate limiter, "
                   "LRU cache, logger, pub/sub", "design patterns in context", "DB schema for the design",
                   "concurrency in LLD (locks, thread safety)"],
        "Hard": ["extensible frameworks (workflow engine, rule engine, in-memory SQL)", "concurrency-heavy LLD "
                 "(job scheduler, distributed lock client)", "API + schema + class design together",
                 "trade-offs of patterns"],
    },
    "System Design - HLD": {
        "Easy": ["client-server, load balancer, caching basics", "SQL vs NoSQL", "vertical vs horizontal scaling",
                 "design a URL shortener (basic)"],
        "Medium": ["URL shortener, pastebin, notification service, rate limiter, chat app, Splitwise, food "
                   "delivery", "capacity estimation", "caching strategies, CDN", "queues & async processing",
                   "DB replication & sharding basics"],
        "Hard": ["Google Docs, YouTube, Uber, payments, ad click aggregation, distributed KV store", "consistency, "
                 "consensus, leader election", "multi-region, failure modes", "deep trade-off discussions and "
                 "bottleneck analysis"],
    },
    "DSA / Coding": {
        "Easy": ["arrays, strings, hashing", "two pointers, sliding window", "stack/queue", "binary search basics",
                 "linked list", "recursion"],
        "Medium": ["trees & BST", "graphs: BFS/DFS, topological sort, Dijkstra", "heaps", "DP 1D/2D",
                   "backtracking", "intervals", "tries", "union find"],
        "Hard": ["advanced DP (bitmask, interval, digit)", "segment tree / BIT", "hard graph problems", "string "
                 "algorithms (KMP, rolling hash)", "multiple follow-ups and optimization"],
    },
}

# Fixed taxonomy for dashboard grouping. Claude must classify every question into one of these.
AREAS = [
    "DSA", "CS Fundamentals", "OOP & LLD", "Machine Coding", "HLD / System Design", "JavaScript",
    "React & Frontend Frameworks", "HTML/CSS & Browser", "Web Performance & Security", "Backend & APIs",
    "Databases & SQL", "Distributed Systems & Messaging", "Language Internals", "Linux & Networking",
    "Containers & Kubernetes", "CI/CD", "Cloud (AWS/GCP/Azure)", "Infrastructure as Code",
    "Observability & SRE", "Testing", "Behavioral & Projects", "Resume & Experience",
]


def calibration(role: str, difficulty: str, tier: str, company: str = "") -> str:
    diff = difficulty.split(" ")[0] if difficulty else "Medium"
    diff = diff if diff in DIFFICULTIES else "Medium"
    t = COMPANY_TIERS.get(tier, COMPANY_TIERS["Product unicorn"])
    topics = ROLE_TOPICS.get(role, ROLE_TOPICS["Software Developer"])
    lines = [
        f"Difficulty band: {diff} = {DIFFICULTIES[diff]}.",
        f"Bar for this band: {DIFFICULTY_BAR[diff]}",
        f"Company tier: {tier} (e.g. {t['examples']}). Interview style at this tier: {t['style']}",
        f"Topic pool for {role} at {diff}: {'; '.join(topics[diff])}.",
    ]
    if diff != "Easy":
        lower = "Easy" if diff == "Medium" else "Medium"
        lines.append(f"You may open with one warm-up from the {lower} pool: {'; '.join(topics[lower][:4])}.")
    if company.strip():
        lines.append(f"Target company: {company.strip()}. Mirror its known interview style and domain "
                     f"(e.g. its products) when framing scenario and design questions.")
    return "\n".join(lines)


# How Claude should format anything the candidate will read (rendered with cards, callouts, colour code and diagrams).
RICH_FORMAT = """Formatting (it is rendered as a rich page, so use structure instead of walls of text):
- Short paragraphs (2-3 sentences) under clear `###` subheadings; **bold** the key terms.
- Fenced code blocks ALWAYS with a language tag (```java, ```python, ```sql, ```yaml…), with comments and Big-O.
- Tables for comparisons, trade-offs, complexities, scores or options.
- A Mermaid diagram (```mermaid) whenever structure or flow helps: system architecture (flowchart LR with \
services/DBs/caches/queues), request or data flow (sequenceDiagram), algorithm steps or state (flowchart TD / \
stateDiagram-v2), class design for LLD (classDiagram), data model (erDiagram). Keep node labels short; quote labels \
that contain special characters, e.g. A["Cache (Redis)"]. No styling directives.
- Callouts as blockquotes: `> [!KEY] ...` must-know point, `> [!TIP] ...` how to answer well, `> [!WARNING] ...` \
trap or edge case, `> [!MISTAKE] ...` common wrong answer, `> [!EXAMPLE] ...` concrete example. Use a few, not many.
- Numbered steps for procedures; bullet lists for points."""
