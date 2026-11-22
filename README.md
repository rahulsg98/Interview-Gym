# AlongSide

AlongSide is a personal desktop app for practising tough mock interviews for IT roles on Ubuntu (GNOME, Wayland).

The interviewer, "Arjun", speaks in an Indian English male voice and acts as a **harsh bar-raiser**:
- He drills every topic deep (concept → internals → edge cases → scale → real world) and doesn't let vague answers slide.
- He sets hidden **interview traps**: false premises, pushback on correct answers, missing constraints and moving goalposts.
- He never repeats a question from your past sessions.
- Even **Easy** follows today's market bar, with LeetCode medium as the floor.

He also judges your **communication and confidence**, from your voice and your webcam.

## Resume grilling and timed interviews
- **Upload resume** (.pdf, .docx, .txt or .md). Claude analyses the experience section:
  - every role and each concrete claim
  - the numbers you quote, and a risk level for inflated or team-credit claims
  - red flags such as vague claims, missing baselines and timeline gaps
  - a list of verification questions

  **Analysis** shows you exactly what Arjun will probe.
- **Every interview includes a resume segment.** Arjun goes claim by claim and checks the work is really yours: architecture, your exact part, how you measured the numbers, failures, and what you'd change. He cross-checks for consistency. Each answer gets a **claim check**: *Convincing*, *Shaky* or *Likely inflated*.
- **Duration:** 15 min, 30 min, 45 min, 1 hr, 1.5 hr or 2 hr. Claude plans an **agenda** to fit, splitting the time between resume, theory, DSA coding, machine coding/LLD, system design and behavioral, based on duration, role, level and round type. Roughly:
  - **15 min:** resume plus rapid theory
  - **45 min:** resume, theory and one coding problem
  - **2 hr:** resume, theory, coding, machine coding and HLD

  A countdown and the agenda are shown above the chat. Questions follow the current segment, and the interview ends when time is up.
- **One big workspace:** the live screen has a single editor that Arjun reads, next to the question and chat. What you *say* is captured automatically and shown in a slim **Heard** line above it.
  - Pick a **Language** (Java, Python, C++, C, JavaScript, TypeScript, Go, Kotlin, SQL, Bash, YAML/JSON) for syntax colouring, line numbers and auto-indent. Enter keeps the indent and adds a level after `{` `(` `[` (or `:` in Python). Tab and Shift+Tab indent and dedent, also for a selection. A closing bracket on an empty line dedents itself. There is no compiler.
  - **Notes** mode is for theory and system design: headings, bullets and **{ } Code block** snippets (```` ```java ```` … ```` ``` ````), each coloured in its own language.
  - Coding questions switch to your last-used language; theory and design switch to Notes. To draw diagrams, use a whiteboard app and press **Review my screen**.

## Only completed interviews count
An interview is **completed** when:
- the timer runs out,
- Arjun wraps up, or
- you press End after at least 90% of the time has passed.

A Round Builder loop is completed when every selected round has finished.

Anything ended earlier is **discarded**: no report, no history entry and nothing added to the Dashboard. You'll be asked to confirm before it's thrown away. Closing the app mid-interview also discards it.

## Tabs

| Tab | What it does |
|---|---|
| **Interview** | A question-by-question mock tailored to your resume or job description, role, difficulty and company tier. After each answer you get a score, a trap verdict, the gaps, a model answer, and soft-skill feedback. |
| **Past Interviews** | Every completed interview and company loop, titled with its date and time, mode, role, difficulty and duration (planned and actual), plus its score. Search and filter the list. Click an entry for **Feedback** (per question or round: score, traps, resume claim checks, gaps, soft skills, model answers), the **Report**, the full **History** transcript, and **Learnings**: for every question, your actual answer next to a detailed ideal answer, key points, where you fell short, a 60-90 s "how to say it" version, likely follow-ups with answers, and what to study next. Learnings are written automatically after each completed interview; older ones have a **Generate learnings** button. Each entry can also be opened as a file or deleted. |
| **Round Builder** | Enter a company. Claude researches the company's real interview loop on the web (LeetCode Discuss, GfG, Glassdoor, blogs) and lists the rounds with questions candidates reported. AlongSide then creates *similar* (not identical) problems and runs a **timed, hands-free loop**. The interviewer hears you out before replying, watches the built-in code editor, and gives a hiring-committee debrief at the end. |
| **Dashboard** | Progress by field and difficulty: score trend, weakest areas, a readiness matrix (difficulty × company tier) and a "next step" suggestion. It has a **Soft skills** section with pace, filler words, eye contact, dimension scores and what you're lacking, plus an improvement plan written by Claude. |

## Difficulty and company tiers
- **Easy** is 0-2 years, **Medium** is 2-4 years, **Hard** is 4-5+ years. All of them are pitched at today's tougher market.
- **Tiers**, from lowest bar to highest:
  - Startup
  - Product unicorn (Flipkart, Razorpay, Swiggy, CRED, PhonePe…)
  - Big Tech (Microsoft, Amazon, Atlassian, Uber…)
  - Top tier (Google, Meta…)

The question pools and expectations are in [alongside/knowledge.py](alongside/knowledge.py), compiled from 2024-2026 candidate reports.

## Soft skills
- **Voice:** words per minute, filler words ("um", "basically", "you know"), hedging ("I think", "maybe") and long pauses. All of it is measured locally.
- **Camera:** time in frame, eye contact (estimated from head pose) and fidgeting. This runs locally with OpenCV's YuNet face detector. The live preview tells you if your lighting or framing is wrong.
- **Claude** scores Clarity, Structure, Conciseness, Confidence, Presence, Listening and Thinking aloud. It uses your transcript, the measurements above, and an occasional webcam snapshot.

For the camera to work well, sit **facing** a light source, not with a window or lamp behind you, and keep your whole face in frame.

## How it works

| Part | Tool | Cost |
|---|---|---|
| Questions, scoring, research, screen and camera review | Claude, through the Claude Code CLI (`claude -p`) with your subscription login. Web search is used for company research. | No API key |
| Speech to text | faster-whisper (`small.en`, int8 on the CPU) | Free, offline |
| Voice | Piper TTS, `en_US-l2arctic` speaker ASI (Indian English male) | Free, offline |
| Hands-free listening | Voice-activity detection on `arecord`. Your speech is transcribed in pieces *while* you talk, so your words are ready about 1 s after the 2 s pause. Arjun never treats "still transcribing" as silence, and his text appears the moment his voice starts. | Local |
| Camera | OpenCV and the YuNet face detector | Local |
| Screen capture | xdg-desktop-portal Screenshot | Built in |
| Data | SQLite at `~/.local/share/alongside/progress.db`, sessions in `~/.local/share/alongside/sessions` | Local |

## Setup (one time only)

Run these once from the project folder:

```bash
claude                 # log in: type /login, choose "Claude account with subscription", then /exit
./run.sh               # first run creates .venv, installs dependencies and starts the app
./install-desktop.sh   # adds AlongSide (with its icon) to the Applications menu
```

On the first run, the app downloads the Whisper model (~250 MB), the voice (~75 MB) and the face model (0.2 MB).

The first time you use screen review, GNOME asks for screenshot permission. Choose **Allow**.

## Opening the app (every day)

**You don't need the terminal.** After the one-time setup, AlongSide is a normal app and stays installed after restarts and power-offs:

1. Press the **Super** (Windows) key or click **Activities**.
2. Type **AlongSide** and press **Enter**.

Tip: right-click the icon in the dock and choose **Pin to Dash** for one-click access.

Your login, profiles, resume analyses, history and dashboard data are kept in `~/.local/share/alongside`, so nothing is lost when you close the app or restart.

### When you would use the terminal
- **To see errors live while troubleshooting:** `./run.sh` from the project folder. Errors also always appear in a pop-up and in `~/.local/share/alongside/alongside.log`.
- **If Claude asks you to log in again** (questions fail with a "log in" error): run `claude`, then `/login`.
- **If you move or rename the project folder:** run `./install-desktop.sh` again from the new location so the launcher points to it.
- **After pulling updates from GitHub:** if `requirements.txt` changed, run `.venv/bin/pip install -r requirements.txt`.

## Keys (Interview tab)
- **Ctrl+Space:** mic on/off
- **Ctrl+Enter:** submit your answer
- **Ctrl+H:** hint
- **Ctrl+Shift+S:** review my screen

## Tips
- Use headphones in the Round Builder. Then tick "I'm wearing headphones" so you can talk over the interviewer.
- Set "Time scale" to 0.5× for a quick loop.
- Company research is cached. Use **Re-research** to refresh it.

## Project layout
```
alongside/
  ui.py         main window, Interview tab, camera preview
  builder.py    Round Builder: research UI, timed hands-free loop, editor
  loop.py       company research (web), loop engine, traps & escalations, round scoring
  interview.py  interview engine, harsh interviewer prompts, scoring, reports
  knowledge.py  difficulty bars, company tiers, topic ladders, trap catalogue
  soft.py       speech delivery metrics, webcam tracker, soft-skill rubric
  dashboard.py  progress + soft-skills dashboard (QtCharts)
  progress.py   SQLite progress store and queries
  editor.py     workspace editor: languages, syntax colouring, auto-indent, code blocks
  llm.py        Claude via `claude -p` (stream-json, tools)
  stt.py        push-to-talk recorder, hands-free listener, faster-whisper
  tts.py        Piper voice playback
  screen.py     Wayland screenshots via the portal
```
