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
            raise Exception(f"LLM Generation Failed: {str(e)}")

    def summarize_results(self, question: str, rows: list) -> str:
        """
        Generate a conversational summary of the data.
        """
        if not rows:
            return "I found no records matching your criteria. It might be due to the current filters or permissions."

        # Truncate rows for token limit safety
        data_preview = json.dumps(rows[:20], default=str) 
        
        prompt = f"""
You are a professional Business Intelligence Assistant.
Analyze the following dataset returned by a SQL query in response to the user's question.

User Question: "{question}"

Data (First 20 rows):
{data_preview}

Instructions:
1. Provide a concise, high-level summary of the results.
2. Highlight key metrics (totals, averages, trends) if visible.
3. Use a professional, helpful tone.
4. Do NOT mention "SQL" or technical database terms. Focus on the business insight.
5. Keep it under 3-4 sentences.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return "Here are the results from your query."

llm_service = LLMService()

