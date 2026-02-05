import os
import re
import json
from openai import AzureOpenAI

class LLMService:
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        )
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        # Pre-compile regex for performance
        self.DANGEROUS_PATTERN = re.compile(r"\b(insert|update|delete|truncate|drop|alter|create|replace|merge)\b", re.I)

    def extract_sql(self, text_in: str) -> str:
        """Pull a single runnable SELECT from LLM output inside triple backticks."""
        if "```" in text_in:
            parts = text_in.split("```")
            for p in parts:
                if re.search(r"\bselect\b|\bwith\b", p, flags=re.I):
                    cleaned = "\n".join(
                        ln for ln in p.splitlines()
                        if not ln.strip().lower().startswith("sql")
                    )
                    return cleaned.strip()
        return text_in.strip()

    def is_unsafe(self, sql: str) -> bool:
        """Check for dangerous keywords."""
        return bool(self.DANGEROUS_PATTERN.search(sql))

    def generate_sql(self, schema_text: str, question: str, email: str) -> str:
        """
        Generate T-SQL query based on schema and question.
        Enforces strict project isolation.
        """
        prompt = f"""
You are a highly restricted T-SQL Query Generator for an Azure SQL Database.
You are interacting with the database for a specific project. 

CRITICAL SECURITY & LOGIC RULES:
1. **Scope Isolation**: You MUST ONLY use tables and columns explicitly defined in the SCHEMA below. Do not assume the existence of any other tables. If the information cannot be found in the provided schema, reply with "I cannot answer this from the selected tables."
2. **Read-Only**: Generate ONLY `SELECT` queries. No INSERT, UPDATE, DELETE, DROP, etc.
3. **Data Security**: 
   - If a table contains columns like `Email`, `UserEmail`, or `Username`, you MUST filter the query to only show data for `{email}` (e.g., `WHERE Email = '{email}'`).
   - If no user-specific column exists, ensure the query is an aggregation (COUNT, SUM, AVG) or generic list that doesn't leak sensitive personal row data unless explicitly appropriate.
4. **Syntax**: Use T-SQL (Microsoft SQL Server) syntax.
5. **Output**: Return ONLY the raw SQL query inside triple backticks (```sql ... ```). No explanation, no conversational text.

SCHEMA:
{schema_text}

USER QUESTION:
{question}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a strict T-SQL generator. You never output anything other than valid SQL code inside code blocks."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0  # Zero temperature for maximum determinism
            )
            raw_content = response.choices[0].message.content
            return self.extract_sql(raw_content)
        except Exception as e:
            raise Exception(f"I'm sorry, I couldn't generate the data query. Error details: {str(e)}")

    def summarize_results(self, question: str, rows: list) -> str:
        """
        Generate a conversational summary of the data.
        """
        if not rows:
            return "I couldn't find any data matching your request. Would you like to try a different question or select more tables?"

        # Truncate rows for token limit safety
        data_preview = json.dumps(rows[:20], default=str) 
        
        prompt = f"""
You are Lumina, a friendly and highly professional Business Intelligence Analyst.
Analyze the following data results and provide a clear, concise, and insightful summary for the user.

User's Original Question: "{question}"

Data Result Preview (JSON):
{data_preview}

GUIDELINES:
1. **Be Insightful**: Don't just list numbers; tell the story. For example, "Your average sales are trending up" instead of "Sales are 500."
2. **Be Professional & Friendly**: Maintain a helpful, "Silicon Valley startup" vibe—clean, direct, and premium.
3. **No Tech Jargon**: Never mention "SQL," "Rows," "Tables," or "Database." Talk about "records," "information," or specific business entities.
4. **Brevity**: Keep the summary between 2 to 4 impactful sentences.
5. **Formatting**: Use bold text for key numbers or highlights.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return "I've analyzed the data and presented the results in the table below. Let me know if you need any specific insights!"

llm_service = LLMService()

