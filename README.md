# Learning-Reinforcement
A learning reinforcement tool that quizzes you on the lecture you're watching, as you watch it, and adapts questions based on what you already know.

## The Problem
In a classroom, a teacher stops to check understanding: they ask questions, notice confusion, and revisit weak spots. 

This classic teaching method is lost in recorded online lectures, which tend to be unengaging and forgettable. There is nothign tht makes you actively recall what you just heard.

## How It Works
This app is an overlay that sits on top of your browser and listens to system audio, detects topic changes, and generates quiz questions about chunks of audio. 

A small overlay runs on top of whatever you're watching. It:
1. Listens to your Mac's system audio and transcribes it
2. Detects topic changes
3. Pauses the video and asks a question
4. Grades your answer and updates a mastery score for each concept
5. Adapts future questions to reinforce topics you're still weak on

### Why system audio?
Platform APIs (like YouTube's) lock functionality to one site. 

Capturing system audio makes it universal to all websites, downloaded videos, and even video calls (Zoom, Meet).

The tradeoff is that ScreenCaptureKit is limited to macOS.

## Stack
- **Audio ingestion:** Apple ScreenCaptureKit
- **Transcription:** OpenAI Whisper API
- **LLM:** Sonnet 5
- **Backend:** FastAPI, SQLAlchemy, Alembic
- **Data:** Postgres + pgvector
- **Frontend:** Electron.js (Node.js)
- **Desktop controls:** nut.js
- **Cloud:** AWS
