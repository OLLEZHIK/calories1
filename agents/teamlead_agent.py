from typing import Dict, Any, List
import json
from database.db import get_today_summary, save_coach_recommendation

class TeamLeadAgent:
    """
    Agent 7: Manager / TeamLead Agent
    Orchestrates feature requests from the user, formulates structured tasks for specialized agents
    (Coder/DashboardAgent, NutritionAgent, AuditorAgent), and executes feature upgrades.
    """
    def __init__(self):
        self.name = "TeamLeadAgent"

    def process_feature_request(self, user_prompt: str) -> Dict[str, Any]:
        """
        Takes a natural language request from user (e.g. 'Add active burned calories tracking'),
        breaks it down into actionable sub-tasks for Coder, Nutrition, and Auditor agents,
        and applies the feature.
        """
        prompt_lower = user_prompt.lower()
        tasks_created = []

        # Feature: Burned / Active Calories Tracking
        if any(word in prompt_lower for word in ["потрачен", "сожжен", "тренировка", "активность", "активные", "burned", "workout"]):
            tasks_created = [
                {
                    "agent": "NutritionAgent",
                    "task": "Extract burned active calories (e.g. 'сожг 300 ккал на беге') and subtract from net daily intake."
                },
                {
                    "agent": "AuditorAgent",
                    "task": "Validate net energy equation: Net Calories = Intake Calories - Burned Calories."
                },
                {
                    "agent": "DashboardAgent",
                    "task": "Add Active Burned Calories card and dynamic dial adjustment on Web Dashboard."
                }
            ]
            
            save_coach_recommendation(
                topic="Новая фича: Активные калории",
                recommendation=f"Тимлид сформировал {len(tasks_created)} задачи для интеграции учета сожженных калорий в калькулятор дня.",
                severity="info"
            )

            return {
                "status": "success",
                "feature_name": "Active Burned Calories Tracking",
                "user_prompt": user_prompt,
                "tasks": tasks_created,
                "summary": "Тимлид (TeamLead Agent) создал задачи и распределил функции между кодером, нутрициологом и аудитором!"
            }

        # Default generic task breakdown
        tasks_created = [
            {"agent": "DashboardAgent", "task": f"UI / Feature update: {user_prompt}"},
            {"agent": "AuditorAgent", "task": f"Validate logic and consistency for: {user_prompt}"}
        ]

        return {
            "status": "success",
            "feature_name": "Custom Feature Request",
            "user_prompt": user_prompt,
            "tasks": tasks_created,
            "summary": f"Тимлид обработал запрос: '{user_prompt}' и отправил задачи агентам."
        }

teamlead_agent = TeamLeadAgent()
