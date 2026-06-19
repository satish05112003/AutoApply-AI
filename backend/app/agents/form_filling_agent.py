import json
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from app.agents.base_agent import BaseAgent, AgentResult
from app.config import settings

logger = logging.getLogger("autoapply_ai.agents.form_filling")

class FieldClassification(BaseModel):
    selector: str
    field_type: str = "UNKNOWN" # PERSONAL_INFO, EDUCATION, WORK_EXPERIENCE, SKILLS, RESUME_UPLOAD, SALARY, NOTICE_PERIOD, COVER_LETTER, SCREENING, UNKNOWN
    mapped_property: str = "" # e.g. full_name, email, phone, college, degree, cgpa, min_salary, etc.
    custom_question_text: str = "" # if SCREENING, the extracted clean question

class FormFillingStructure(BaseModel):
    classifications: List[FieldClassification] = Field(default=[])

class FormFillingAgent(BaseAgent):
    agent_name = "FormFillingAgent"
    run_type = "FORM_FIELD_CLASSIFICATION"

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        Input keys:
            fields: list of dicts (HTML form elements info)
            profile: dict (candidate profile details)
            preferences: dict (candidate preferences details)
        """
        fields = input_data["fields"]
        profile = input_data["profile"]
        preferences = input_data["preferences"]
        
        await self.initialize_run({"fields_count": len(fields)})
        await self.log_info(f"Classifying {len(fields)} HTML form input selectors...")

        try:
            # 1. Ask LLM to map selectors to profile fields
            system_prompt = (
                "You are an AI browser form filler assistant. "
                "Your job is to read list of HTML inputs metadata and classify their field_type into: "
                "[PERSONAL_INFO, EDUCATION, WORK_EXPERIENCE, SKILLS, RESUME_UPLOAD, SALARY, NOTICE_PERIOD, COVER_LETTER, SCREENING, UNKNOWN] "
                "and specify the mapped_property string (e.g. email, phone, full_name, expected_salary, college, degree, resume, cover_letter, etc.) "
                "If it is a custom screening question, set field_type to SCREENING and set custom_question_text. "
                "Output ONLY a raw valid JSON object matching the schema. No markdown code fences, no formatting."
            )
            
            prompt = f"HTML input fields to classify:\n\n{json.dumps(fields, indent=2)}"
            await self.log_info("Asking LLM to classify form field selectors...")
            
            classifications = []
            try:
                llm_response = await self.think(prompt, system_prompt, model=settings.OLLAMA_DEFAULT_MODEL, response_model=FormFillingStructure)
                # Clean markers
                clean_json = llm_response.strip().replace("```json", "").replace("```", "").strip()
                parsed_data = json.loads(clean_json)
                classifications = parsed_data.get("classifications", [])
            except Exception as llm_err:
                await self.log_warning(f"LLM think or parse failed, falling back to rule-based: {llm_err}")

            if not classifications:
                await self.log_info("No classifications returned by LLM. Applying rule-based heuristic classification fallback.")
                classifications = self._rule_based_classification(fields)

            # 2. Map classifications to actual candidate values
            field_values = {}
            screening_questions = []

            for cls in classifications:
                selector = cls["selector"]
                f_type = cls["field_type"]
                prop = cls["mapped_property"]
                
                if f_type == "PERSONAL_INFO":
                    if "email" in prop or "email" in selector:
                        field_values[selector] = profile.get("email", "")
                    elif "phone" in prop or "phone" in selector:
                        field_values[selector] = profile.get("phone", "")
                    elif "name" in prop or "name" in selector:
                        field_values[selector] = profile.get("full_name", "")
                    elif "address" in prop or "city" in prop:
                        field_values[selector] = f"{profile.get('address_city', '')}, {profile.get('address_state', '')}"

                elif f_type == "RESUME_UPLOAD":
                    # Mark that this selector is for resume upload
                    field_values[selector] = "__RESUME_UPLOAD__"

                elif f_type == "SALARY":
                    field_values[selector] = preferences.get("preferred_salary_inr", 800000)

                elif f_type == "NOTICE_PERIOD":
                    field_values[selector] = preferences.get("notice_period_days", 30)

                elif f_type == "COVER_LETTER":
                    # Generate simple default cover letter
                    field_values[selector] = (
                        f"Dear Hiring Manager,\n\nI am writing to express my strong interest in this position. "
                        f"With technical skills in {', '.join(profile.get('skills', []))[:100]} and experience in software development, "
                        f"I am confident in my capability to add immediate value to your engineering team.\n\nBest regards,\n{profile.get('full_name')}"
                    )

                elif f_type == "SCREENING":
                    # Add to list of custom questions that need answers
                    screening_questions.append({
                        "selector": selector,
                        "question_text": cls["custom_question_text"] or selector
                    })

            await self.log_info(f"Classified {len(field_values)} standard values and identified {len(screening_questions)} screening questions.")
            
            result = AgentResult(success=True, output_data={
                "field_values": field_values,
                "screening_questions": screening_questions
            })
            await self.finalize_run(result)
            return result

        except Exception as e:
            await self.log_error(f"Failed to classify form fields: {e}")
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result

    def _rule_based_classification(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        classifications = []
        for field in fields:
            selector = field.get("selector", "")
            name_attr = (field.get("name") or "").lower()
            id_attr = (field.get("id") or "").lower()
            placeholder = (field.get("placeholder") or "").lower()
            label = (field.get("label") or "").lower()
            aria_label = (field.get("aria_label") or "").lower()
            el_type = (field.get("type") or "").lower()
            tag_name = (field.get("tag_name") or "").lower()

            field_type = "UNKNOWN"
            mapped_property = ""
            custom_question_text = ""

            # 1. Resume
            if el_type == "file" or any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["resume", "cv", "curriculum"]):
                field_type = "RESUME_UPLOAD"
                mapped_property = "resume"
            # 2. Email
            elif el_type == "email" or any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["email", "e-mail"]):
                field_type = "PERSONAL_INFO"
                mapped_property = "email"
            # 3. Phone
            elif el_type == "tel" or any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["phone", "mobile", "telephone", "contact_number", "contact number"]):
                field_type = "PERSONAL_INFO"
                mapped_property = "phone"
            # 4. Name
            elif any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["full name", "fullname", "first name", "last name"]) or (("name" in label or "name" in name_attr) and not any(y in label or y in name_attr for y in ["company", "reference", "school", "university", "college", "job", "position"])):
                field_type = "PERSONAL_INFO"
                mapped_property = "full_name"
            # 5. Salary
            elif any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["salary", "compensation", "package", "ctc"]):
                field_type = "SALARY"
                mapped_property = "expected_salary"
            # 6. Notice Period / Start Date
            elif any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["notice", "notice period", "start date", "availability"]):
                field_type = "NOTICE_PERIOD"
                mapped_property = "notice_period_days"
            # 7. Cover Letter
            elif any(x in label or x in name_attr or x in id_attr or x in placeholder for x in ["cover letter", "coverlet", "letter of intent"]):
                field_type = "COVER_LETTER"
                mapped_property = "cover_letter"
            # 8. Screening Questions (for inputs that are required or seem custom)
            elif tag_name in ["textarea", "select"] or el_type in ["text", "radio", "checkbox"] or field.get("required", False):
                field_type = "SCREENING"
                custom_question_text = field.get("label") or field.get("placeholder") or selector

            classifications.append({
                "selector": selector,
                "field_type": field_type,
                "mapped_property": mapped_property,
                "custom_question_text": custom_question_text
            })
        return classifications
