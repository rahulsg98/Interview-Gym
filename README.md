# Interview Gym

Interview Gym is a personal desktop app for practising tough mock interviews for IT roles on Ubuntu (GNOME, Wayland). (The project folder and code package are still named `alongside`.)

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
| **Past Interviews** | Every completed interview and company loop, titled with its date and time, mode, role, difficulty and duration (planned and actual), plus its score. Search and filter the list. Click an entry for **Feedback** (per question or round: score, traps, resume claim checks, gaps, soft skills, model answers), the **Report**, the full **History** transcript, and **Learnings**: for every question, your actual answer next to a detailed ideal answer, key points, where you fell short, a 60-90 s "how to say it" version, likely follow-ups with answers, what to study next, and **Learn more** links: docs and practice pages (each link is checked to open) plus YouTube searches on trusted channels such as NeetCode, Abdul Bari, ByteByteGo and Gaurav Sen. Learnings are written automatically after each completed interview; older ones have a **Generate learnings** or **Add study links** button. Each entry can also be opened as a file or deleted. |
| **Round Builder** | Enter a company. Claude researches the company's real interview loop on the web (LeetCode Discuss, GfG, Glassdoor, blogs) and lists the rounds with questions candidates reported. Interview Gym then creates *similar* (not identical) problems and runs a **timed, hands-free loop**. The interviewer hears you out before replying, watches the built-in code editor, and gives a hiring-committee debrief at the end. |
| **Dashboard** | Progress by field and difficulty: score trend, weakest areas, a readiness matrix (difficulty × company tier) and a "next step" suggestion. It has a **Soft skills** section with pace, filler words, eye contact, dimension scores and what you're lacking, plus an improvement plan written by Claude. |

## Difficulty and company tiers
- **Easy** is 0-2 years, **Medium** is 2-4 years, **Hard** is 4-5+ years. All of them are pitched at today's tougher market.
- **Tiers**, from lowest bar to highest:
  - Startup
  - Product unicorn (Flipkart, Razorpay, Swiggy, CRED, PhonePe…)
  - Big Tech (Microsoft, Amazon, Atlassian, Uber…)
  - Top tier (Google, Meta…)

The question pools and expectations are in [alongside/knowledge.py](alongside/knowledge.py), compiled from 2024-2026 candidate reports.

## Readable reports
Feedback, Report, History and Learnings are shown as designed pages, not plain text:
- **Feedback and scores:** score badges, side-by-side *what you got right* and *missed or wrong*, coloured trap and claim-check chips, communication bars, and collapsible model answers.
- **Claude's notes** use tables, syntax-highlighted code, coloured callouts (key point, tip, watch out, common mistake) and **diagrams**: architecture, flows, class designs and data models, drawn with Mermaid.
- **History** is a chat view.

Mermaid is downloaded once (3 MB). Links open in your normal browser.

## Layout
- **Resizable setup column:** drag the divider and the form reflows. Button rows stack, dropdowns shrink and labels move above their fields. Below its minimum width the column folds away; **▸ Show setup** brings it back. **◂ Hide setup** folds it in one click.
- **⛶ Full screen** on Past Interviews and on the Interview side panel shows that reading block on the whole screen. **F11** toggles full screen, and **Esc** exits.

## Camera and clearing
- The camera only runs **during** an interview or Round Builder loop. It switches off and releases the webcam the moment the interview ends.
- Turn it off or on at any time with **📷 Camera** on the live screen. The setup checkbox only sets the default.
- **🧹 Clear** on the Interview tab resets the form (resume, JD, company, focus). It can also delete saved resume analyses and the resume/JD stored in profiles.
- **🧹 Clear** in Round Builder resets the company, findings and rounds. It can also delete all saved company research.
- The live screens are wiped after every interview. Everything stays in Past Interviews.

## Microphone
- **Microphone** in the Interview setup: **Auto** uses your default mic, but skips any mic that sends silence. For example, Bluetooth earbuds in music mode have no working mic, so Auto falls back to the laptop mic. You can also pick a mic yourself, and **Test** checks that it actually hears you.
- If the mic goes silent during an interview, a red warning says Arjun can't hear you.
- **Wait after I stop** (3 s by default): how long you stay quiet before Arjun treats your answer as finished, then thinks and replies. A short thinking pause mid-answer doesn't make him interrupt: he only responds when your answer sounds finished.
- **"Take your time"** only comes after about 5 s with no speech at all, and later nudges wait longer (about 15 s, then 30 s). Background noise doesn't count as speech.
- **Background noise is ignored.** A neural voice detector (Silero, bundled with faster-whisper) only counts real human speech, so fans, typing and traffic don't keep your turn open.
- **Arjun always finishes his sentence**, even if you start talking. With **headphones/earbuds** ticked, the mic stays on while he talks, so you're still heard, and he says a quick "Okay." or "I see." the moment you pause.

## Soft skills
- **Voice:** words per minute, filler words ("um", "basically", "you know"), hedging ("I think", "maybe") and long pauses. All of it is measured locally.
- **Camera:** time in frame, eye contact (estimated from head pose) and fidgeting. This runs locally with OpenCV's YuNet face detector. The live preview tells you if your lighting or framing is wrong.
- **Claude** scores Clarity, Structure, Conciseness, Confidence, Presence, Listening and Thinking aloud. It uses your transcript, the measurements above, and an occasional webcam snapshot.

For the camera to work well, sit **facing** a light source, not with a window or lamp behind you, and keep your whole face in frame.

## How it works

| Part | Tool | Cost |
|---|---|---|
| Questions, scoring, research, screen and camera review | Claude, through the Claude Code CLI (`claude -p`) with your subscription login. Web search is used for company research. | No API key |
| Speech to text | **NVIDIA Parakeet TDT 0.6B v2** (ONNX, int8, CC-BY-4.0). In tests on accented, noisy technical answers it was the most accurate (9.2% word errors vs 9.8% for Whisper small.en) and ~8× faster. Whisper models remain selectable. | Free, offline |
| Voice | **Natural:** Kokoro-82M (Apache-2.0) on the CPU, default an Indian male voice (`hm_psi`), plus US, British and blended male voices. **Classic:** Piper voices (faster, but robotic). Pick one under **Voice** and press **▶ Preview**. A headset-style EQ trims the bass for clarity, and **Voice speed** (Slow to Fast, default Normal) sets the pace. | Free, offline |
| Hands-free listening | Silero neural voice detection plus the room's noise level on `arecord`, so background noise is ignored and quiet speech in a noisy room is still caught (1 s of audio before detection is kept, so first words aren't lost). Your speech is transcribed in pieces *while* you talk, so your words are ready right after the 3 s pause. Arjun never treats "still transcribing" as silence, and his text appears the moment his voice starts. | Local |
| Camera | OpenCV and the YuNet face detector | Local |
| Screen capture | xdg-desktop-portal Screenshot | Built in |
| Data | SQLite at `~/.local/share/alongside/progress.db`, sessions in `~/.local/share/alongside/sessions` | Local |

## Setup (one time only)

Run these once from the project folder:

```bash
claude                 # log in: type /login, choose "Claude account with subscription", then /exit
./run.sh               # first run creates .venv, installs dependencies and starts the app
./install-desktop.sh   # adds Interview Gym (with its icon) to the Applications menu
```

On the first run, the app downloads the speech-to-text model (~650 MB), the natural voice model (~120 MB) and the face model (0.2 MB).

The first time you use screen review, GNOME asks for screenshot permission. Choose **Allow**.

## Opening the app (every day)

**You don't need the terminal.** After the one-time setup, Interview Gym is a normal app and stays installed after restarts and power-offs:

1. Press the **Super** (Windows) key or click **Activities**.
2. Type **Interview Gym** (or just **gym**) and press **Enter**.

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
  richview.py   rich pages: cards, callouts, coloured code, Mermaid diagrams
  editor.py     workspace editor: languages, syntax colouring, auto-indent, code blocks
  llm.py        Claude via `claude -p` (stream-json, tools)
  stt.py        push-to-talk recorder, hands-free listener, faster-whisper
  tts.py        Piper voice playback
  screen.py     Wayland screenshots via the portal
```
