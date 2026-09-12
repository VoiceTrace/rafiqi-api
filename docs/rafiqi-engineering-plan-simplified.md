# Rafiqi — MVP Plan (Simple Tickets)

Scope: Student Profile, Pre-Class, During-Class — for both teacher and student. Everything else in the mockups is out of scope for now.

For each ticket: what it is, who it's for, and why it matters. Stories are written from the teacher's or student's point of view. Foundation tickets (data models, infrastructure) don't have a real user behind them — those are just labeled "Foundation."

## Epic A — Student Profile

**A1 — Profile data model (Foundation)**
Set up the database structure that holds a student's profile: trait scores, written notes about them, teaching tips, and how confident Rafiqi is in each. Everything else in this epic depends on this existing first.

**A2 — Cave chat**
As a student, I chat with Rafiqi in "Rafiqi's Cave" so it can get to know me, instead of me filling out a form.

**A3 — Profile updates from chat**
As a student, when I talk to Rafiqi, my profile should update automatically — no one has to type it in by hand. Each part of the profile gets a "confident" or "still forming" label depending on how sure Rafiqi is.

**A4 — Show where a trait came from**
As a teacher, if a profile trait looks off, I want to see which conversation it came from, so I can understand why Rafiqi thinks that.

**A5 — "Not quite me?" correction**
As a student, I can tell Rafiqi a profile card is wrong and explain why, so my profile stays accurate.

**A6 — "How Rafiqi sees you" (student view)**
As a student, I want to see my own profile update live as we talk, so I can trust it and correct it early if needed.

**A7 — Class roster with profile cards (teacher view)**
As a teacher, I want to see each student's profile in my roster, so I know how to teach them individually. Students who haven't chatted with Rafiqi yet should show clearly as "new," not blank or broken.

**A8 — Data privacy review (Foundation — do this early, not last)**
Before this ships, the school/parents need clarity on how a minor's personal and behavioral data is stored and used. This affects how much detail A3 is even allowed to save.

**A9 — Teacher can edit a profile by hand (nice-to-have)**
As a teacher, I can correct a profile field myself, instead of waiting on Rafiqi to fix it through chat.

## Epic B — Pre-Class

**B1 — Lesson prep data model (Foundation)**
Set up where a lesson's objectives, flow, check-questions, and materials live.

**B2 — Generate lesson prep with AI**
As a teacher, I click "generate" and get a first draft of objectives, a lesson flow, and check-questions, so I'm not starting from a blank page.

**B3 — Edit anything generated**
As a teacher, I can edit, reorder, or delete anything Rafiqi generated, so the plan matches how I actually want to teach.

**B4 — Attach materials**
As a teacher, I can attach files from my library to a lesson, so everything I need is in one place.

**B5 — Student warm-up ("Prime")**
As a student, I get a short prediction game before class starts, so I show up already thinking about the topic.

**B6 — See the class's misconceptions before teaching**
As a teacher, I want to see the most common wrong guesses from students' warm-ups, so I can plan to address them directly.

**B7 — Ask my teacher, ahead of time**
As a student, I can flag a question for my teacher while chatting with Rafiqi, so it doesn't get lost before class.

**B8 — Turn prep into slides (nice-to-have)**
As a teacher, I can generate a presentation from my finished prep, instead of rebuilding it in a slide tool.

## Epic C — During Class

**C1 — Start and join a class session**
As a teacher, I can start a live session and have my students join it, so we have one shared "room" for the class.

**C2 — Live connection between teacher and students (Foundation — build this early, everything else needs it)**
Set up the live connection that lets engagement, questions, and highlights sync instantly between the teacher and every student in the session.

**C3 — See what students are doing, live**
As a teacher, I can see in real time who's taking notes, who's asking questions, and who's checked out, so I know who to check in on.

**C4 — Similar questions grouped together**
As a teacher, I want student questions grouped by topic and ranked by how many students asked, so I answer the class's real confusion instead of the same question five times. I can tap a group to see exactly who asked and how they phrased it.

**C5 — Push a "highlight this" to everyone**
As a teacher, when I mark something as important, it should appear live on every student's screen right away.

**C6 — Student notes and questions during class**
As a student, I can jot notes and questions during class, so I have a record and my teacher can see what I need help with.

**C7 — Rafiqi connects your own notes to your questions (nice-to-have)**
As a student, if my own note already answers a question I had, Rafiqi should notice and tell me — I shouldn't have to track it myself.

**C8 — Lock in the data when class ends (Foundation)**
When a session ends, freeze the engagement and question data so it can feed into after-class summaries and profile updates without changing underneath them.

## Suggested Order

1. Foundations: A1, A2, B1, C1, C2
2. Get the profile loop working end-to-end: A3 → A6 → A7
3. Pre-class loop: B2/B3 → B5 → B6/B7
4. Live-class loop: C3 → C4 → C5 → C6
5. Don't leave for later: A5, A8 (privacy review)
6. Nice-to-haves: A9, B4, B8, C7, C8