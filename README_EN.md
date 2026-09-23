<div align="center">

**English** | [中文](README.md)

# Tide · 潮汐蒸馏

<img src="assets/banner.png" alt="Tide" width="100%">


> *The waves rise and fall with the moon, keeping faith with a rhythm it never chose.*

<br>

**Turn the traces a person leaves behind into a thinking style an AI can run.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/code)

</div>

---

## Why "Tide"

A casual watcher sees only waves; a tide reader sees the moon's pull.

A single essay, a single viral video, a single quote — those are just spray. The **recurring verbal tics, consistent trade-offs, admitted failures, unresolved contradictions** — those are the gravity that drives a person.

Tide extracts the cognitive context behind the traces — how beliefs formed, what real decisions were made, which failures were admitted, where the person contradicts themselves — so an AI can reason with that "lived experience", not just quote it.

## Three Distillation Channels

| Channel | Input | Output |
|---------|-------|--------|
| **Person** | Name / essays / interviews / web search | Thinking Skill |
| **Book** | A whole book (PDF/EPUB/TXT) | Thinking Skill |
| **Video Creator** ⭐ | Douyin viral video links | Thinking Skill + copy-structure analysis |

### Video Creator Distillation (highlight)

Drop in a creator's viral video links and get two things back: a thinking Skill for that creator, and a structural breakdown of their viral copy.

```
Douyin links → watermark-free download → audio/cover extraction
            → speech-to-text transcript → hook/pain/value/CTA breakdown
            → cognitive extraction → [name]-perspective/SKILL.md
```

Spoken scripts are the most honest first-hand material: tics, trade-offs and narrative habits are all on display. A quote that recurs across videos is a belief; one that appears once is just a topic.

## Install

```bash
npx skills add jasonxxzhou/tide-skill
```

```
> Use Tide to distill Charlie Munger.
> Distill this creator. [paste 3 viral video links]
```

## Pipeline

```
Step 0  Route detection (person / book / video creator)
Step 1  Material collection (upload / 6-dimension web search / video extraction)
Step 2  Structured research files + cross validation
Step 3  Cognitive extraction (beliefs-with-origin-stories, decisions-with-retros,
        admitted failures, inner contradictions, cognitive limits,
        first-person thinking habits, minimal expression DNA)
Step 4  Summary confirmation → Step 5 Assemble → Step 6 QA (12 checks) → Step 7 Deliver
```

## Notice

> Extracting Douyin content is for learning and research only. Respect platform terms and copyright.

MIT License
