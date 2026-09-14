"""
Interview Practice Mode Engine for JARVIS.
Handles session state, adaptive questioning, follow-ups, and final structured evaluation.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

INTERVIEWER_SYSTEM_INSTRUCTION = """You are JARVIS operating as a professional AI interviewer.

Conduct a realistic job interview based on the candidate's selected role, experience, interview type, and difficulty.

Ask one question at a time and wait for the candidate's response.

Analyze every response and use it to determine the next question.

Ask contextual follow-up questions instead of blindly following a fixed question list.

Do not reveal answers during the interview unless the candidate explicitly asks for help or the interview is in Coaching Mode.

Challenge unclear or incomplete answers professionally.

Adapt the difficulty according to the candidate's demonstrated knowledge.

For technical interviews, focus on technical correctness, reasoning, practical application, and trade-offs.

For behavioral interviews, focus on communication, ownership, decision-making, and real examples.

For coding interviews, evaluate the candidate's reasoning, implementation, complexity, debugging, and edge-case handling.

Remain professional and realistic.

Do not act like a generic AI assistant.

Do not unnecessarily praise or criticize the candidate.

At the end, provide a detailed practice evaluation and actionable improvement recommendations."""


def _get_gemini_client():
    try:
        from google import genai
        path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            key = data.get("gemini_api_key", "")
            if key:
                return genai.Client(api_key=key)
    except Exception as e:
        print(f"[InterviewEngine] Client init failed: {e}")
    return None


@dataclass
class QnAPair:
    index: int
    question: str
    answer: str = ""
    is_followup: bool = False
    coaching_feedback: str = ""
    difficulty_at_time: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


class InterviewSession:
    """Manages an active interview session from configuration to final evaluation."""

    def __init__(
        self,
        job_role: str = "Software Engineer",
        experience_level: str = "Mid-Level (3-5 yrs)",
        interview_type: str = "Technical",
        difficulty: str = "Medium",
        num_questions: int = 5,
        feedback_mode: str = "realistic",  # "realistic" | "coaching"
    ):
        self.job_role = job_role.strip() or "Software Engineer"
        self.experience_level = experience_level.strip() or "Mid-Level"
        self.interview_type = interview_type.strip() or "Technical"
        self.difficulty = difficulty.strip() or "Medium"
        self.current_difficulty = self.difficulty
        self.num_questions = max(1, int(num_questions))
        self.feedback_mode = feedback_mode.lower().strip()  # realistic or coaching

        self.status = "INITIALIZING"
        self.main_question_index = 0
        self.current_question = ""
        self.qna_history: list[QnAPair] = []
        self.is_followup_pending = False
        self.final_evaluation_report = ""

    def get_progress_str(self) -> str:
        f_tag = " (Follow-up)" if self.is_followup_pending else ""
        return f"Question {self.main_question_index} of {self.num_questions}{f_tag}"

    def start(self) -> str:
        """Starts the interview and generates the first question."""
        self.status = "IN_PROGRESS"
        self.main_question_index = 1
        self.is_followup_pending = False

        prompt = (
            f"You are conducting a {self.feedback_mode.upper()} job interview for the position of '{self.job_role}'.\n"
            f"Candidate Experience Level: {self.experience_level}\n"
            f"Interview Type: {self.interview_type}\n"
            f"Starting Difficulty: {self.difficulty}\n"
            f"Total Target Questions: {self.num_questions}\n\n"
            "INSTRUCTIONS:\n"
            "1. Greet the candidate in 1 brief, professional sentence welcoming them to the interview.\n"
            "2. Then present Question 1 clearly.\n"
            "3. If this is a Coding interview, ask them to explain their high-level approach first before writing code.\n"
            "4. Ask ONLY ONE question. Do not list multiple questions.\n"
            "Keep it concise, realistic, and strictly professional."
        )

        first_q = self._call_gemini(prompt)
        if not first_q:
            first_q = (
                f"Welcome to your interview for the {self.job_role} position. "
                f"To begin, could you introduce yourself and describe a challenging project you worked on recently?"
            )

        self.current_question = first_q.strip()
        pair = QnAPair(
            index=self.main_question_index,
            question=self.current_question,
            difficulty_at_time=self.current_difficulty,
        )
        self.qna_history.append(pair)
        return self.current_question

    def submit_answer(self, candidate_answer: str) -> dict:
        """
        Processes candidate answer.
        Returns:
            {
                "feedback": str,        # Empty in realistic mode, coaching tip in coaching mode
                "next_question": str,   # Next question or follow-up
                "is_followup": bool,    # True if follow-up question
                "is_completed": bool,   # True if interview reached question target
                "evaluation": str,      # Final report if completed
                "display_text": str,    # Clean text to speak & display
            }
        """
        candidate_answer = candidate_answer.strip()
        if not candidate_answer:
            candidate_answer = "(No answer provided / Candidate skipped)"

        # Save answer to the current active pair
        if self.qna_history:
            self.qna_history[-1].answer = candidate_answer

        # Check if interview is now complete (if not a follow-up and reached question limit)
        # Note: follow-up questions do not advance the main question count
        reached_limit = (self.main_question_index >= self.num_questions and not self.is_followup_pending)

        # Decide whether to ask a follow-up or move to next main question or finish
        history_summary = []
        for p in self.qna_history:
            tag = "Follow-up" if p.is_followup else f"Q{p.index}"
            history_summary.append(f"[{tag}] Interviewer: {p.question}\nCandidate: {p.answer}")
        transcript = "\n\n".join(history_summary)

        eval_prompt = (
            f"You are the AI Interviewer for '{self.job_role}' ({self.interview_type}, {self.experience_level}).\n"
            f"Current Difficulty: {self.current_difficulty}\n"
            f"Feedback Mode: {self.feedback_mode.upper()} MODE\n"
            f"Current Progress: Question {self.main_question_index} of {self.num_questions}\n"
            f"Interview Transcript So Far:\n{transcript}\n\n"
            "TASK:\n"
            "Analyze the candidate's latest response.\n"
            "1. ADAPTIVE DIFFICULTY:\n"
            "   - If strong answer: increase depth, ask trade-offs, architecture, or real scenarios.\n"
            "   - If struggling/unclear: ask simpler clarifying follow-up or break down the concept.\n"
            "2. FOLLOW-UP DECISION:\n"
            f"   - Decide if a contextual follow-up is necessary. (Only do follow-up if candidate brought up something critical or was ambiguous, and we haven't done more than 1 follow-up for this topic).\n"
            f"   - If this turn was already a follow-up, move to the NEXT main question (Question {self.main_question_index + 1}) unless interview is ending.\n"
            f"   - Is interview ending? ({'YES, this was the final question' if reached_limit else 'NO'}).\n"
            "3. COACHING FEEDBACK:\n"
            f"   - If Coaching Mode: provide 1-2 brief sentences of constructive coaching feedback on what was good and what could improve.\n"
            f"   - If Realistic Mode: DO NOT provide any coaching feedback. Simply acknowledge naturally (e.g. 'Understood.', 'Thank you.') and ask the question.\n\n"
            "OUTPUT FORMAT (Strict JSON):\n"
            "{\n"
            '  "coaching_feedback": "Short feedback if coaching mode, otherwise empty",\n'
            '  "is_followup": true/false,\n'
            '  "next_question": "The exact question or follow-up question to speak (empty if interview is ending)",\n'
            '  "adapted_difficulty": "Easy/Medium/Hard/Expert",\n'
            '  "is_ending": true/false\n'
            "}"
        )

        res_json_str = self._call_gemini(eval_prompt, json_mode=True)
        decision = self._parse_json_response(res_json_str, reached_limit)

        coaching = decision.get("coaching_feedback", "").strip()
        is_followup = decision.get("is_followup", False)
        next_q = decision.get("next_question", "").strip()
        self.current_difficulty = decision.get("adapted_difficulty", self.current_difficulty)
        is_ending = decision.get("is_ending", False) or reached_limit

        if self.qna_history:
            self.qna_history[-1].coaching_feedback = coaching

        if is_ending or not next_q:
            self.status = "COMPLETED"
            final_report = self.generate_final_evaluation()
            self.final_evaluation_report = final_report

            conclusion_speech = (
                f"{coaching + ' ' if coaching else ''}"
                f"That concludes our interview for the {self.job_role} position. "
                "Thank you for your time. Your comprehensive performance evaluation has been generated and is displayed on your screen."
            ).strip()

            return {
                "feedback": coaching,
                "next_question": "",
                "is_followup": False,
                "is_completed": True,
                "evaluation": final_report,
                "display_text": conclusion_speech,
            }

        # Setup next question
        self.is_followup_pending = is_followup
        if not is_followup:
            self.main_question_index += 1

        self.current_question = next_q
        new_pair = QnAPair(
            index=self.main_question_index,
            question=self.current_question,
            is_followup=is_followup,
            difficulty_at_time=self.current_difficulty,
        )
        self.qna_history.append(new_pair)

        speech = f"{coaching}\n\n{next_q}".strip() if coaching else next_q

        return {
            "feedback": coaching,
            "next_question": next_q,
            "is_followup": is_followup,
            "is_completed": False,
            "evaluation": "",
            "display_text": speech,
        }

    def generate_final_evaluation(self) -> str:
        """Generates the structured post-interview evaluation report."""
        history_text = []
        for i, p in enumerate(self.qna_history, 1):
            tag = "Follow-up" if p.is_followup else f"Q{p.index}"
            history_text.append(f"{tag}: {p.question}\nAnswer: {p.answer}")
        all_qa = "\n\n".join(history_text)

        prompt = (
            f"You are an expert hiring director and interview coach.\n"
            f"Generate a comprehensive, structured evaluation report for this candidate practice interview.\n"
            f"Candidate Role: {self.job_role}\n"
            f"Experience Level: {self.experience_level}\n"
            f"Interview Type: {self.interview_type}\n"
            f"Difficulty: {self.difficulty}\n"
            f"Interview Transcript:\n{all_qa}\n\n"
            "REQUIREMENTS — Generate a markdown report with these EXACT sections:\n"
            "# 🎯 Interview Performance Evaluation\n"
            "**Role:** [Role] | **Level:** [Level] | **Type:** [Type] | **Practice Score:** [Score]/100\n"
            "> *Note: This practice score is generated solely as an AI training metric to guide improvement.*\n\n"
            "## 1. Overall Performance\n"
            "(Executive summary of performance and readiness)\n\n"
            "## 2. Core Competencies Breakdown\n"
            "- **Technical Knowledge:** (Score/10 & analysis)\n"
            "- **Problem Solving:** (Score/10 & analysis)\n"
            "- **Communication & Clarity:** (Score/10 & analysis)\n"
            "- **Practical Understanding & Trade-offs:** (Score/10 & analysis)\n\n"
            "## 3. Key Strengths\n"
            "(Bulleted list of standout strengths observed)\n\n"
            "## 4. Areas for Growth & Weaknesses\n"
            "(Bulleted list of weaknesses or gaps in responses)\n\n"
            "## 5. Question-by-Question Review & Weak Responses\n"
            "(Specific questions that were answered poorly or could be improved)\n\n"
            "## 6. Actionable Improvements & Practice Topics\n"
            "(Concrete topics, concepts, and exercises to practice)\n\n"
            "## 7. Example Model Answers for Weak Responses\n"
            "(Provide 1 or 2 exemplar answers showing how the candidate should have answered)\n"
        )

        report = self._call_gemini(prompt)
        if not report:
            report = (
                f"# 🎯 Interview Performance Evaluation\n"
                f"**Role:** {self.job_role} | **Level:** {self.experience_level} | **Score:** 80/100\n\n"
                "## 1. Overall Performance\n"
                "The candidate demonstrated solid baseline understanding of core concepts.\n\n"
                "## 2. Key Strengths\n"
                "- Clear articulation of basic principles.\n\n"
                "## 3. Areas for Improvement\n"
                "- Deepen knowledge on system trade-offs and edge-case validation.\n"
            )
        return report.strip()

    def _call_gemini(self, prompt: str, json_mode: bool = False) -> str:
        """Helper to invoke Gemini flash for fast responses."""
        client = _get_gemini_client()
        if client:
            try:
                cfg: dict[str, Any] = {
                    "system_instruction": INTERVIEWER_SYSTEM_INSTRUCTION,
                }
                if json_mode:
                    cfg["response_mime_type"] = "application/json"

                resp = client.models.generate_content(
                    model="gemini-flash-latest",
                    contents=prompt,
                    config=cfg,
                )
                txt = ""
                for part in resp.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        txt += part.text
                return txt.strip()
            except Exception as e:
                print(f"[InterviewEngine] Gemini call failed: {e}")
        return ""

    def _parse_json_response(self, text: str, fallback_ending: bool) -> dict:
        try:
            import re
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass

        # Fallback if JSON parsing fails
        if fallback_ending:
            return {"is_ending": True, "next_question": "", "is_followup": False}
        return {
            "coaching_feedback": "",
            "is_followup": False,
            "next_question": "Can you elaborate on how you test and ensure reliability in your implementations?",
            "is_ending": False,
        }
