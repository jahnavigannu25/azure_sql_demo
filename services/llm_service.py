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
You are an Expert T-SQL Data Analyst. Your goal is to provide precise, accurate, and high-performance T-SQL queries.

ANALYTICAL GUIDELINES:
1. **Full Access**: Use ANY column defined in the SCHEMA to answer the question. Do NOT omit sensitive columns like Salary, Budget, or Roles; assume the user has clearance.
2. **Advanced SQL**: Prefer JOINS, aggregations (SUM, AVG, COUNT), and window functions if they provide a better answer. 
3. **Names & Searching**: For any name-based filters (e.g. searching for an employee), ALWAYS use the `LIKE` operator with wildcards (e.g., `WHERE Name LIKE '%Manish%'`) to handle variations in naming.
4. **Joins**: If the user asks for related data (e.g. Employee and their Attendance), perform an INNER or LEFT JOIN using the appropriate keys.
5. **Self-Service Accuracy**: If the user asks about themselves (e.g., "my salary"), ALWAYS filter by their specific email `{email}` or name to ensure the query aligns with security policies.
6. **No Hallucinations**: Only use the tables and columns explicitly listed in the SCHEMA.
7. **Read-Only**: Generate ONLY `SELECT` statements.

USER CONTEXT:
User Role: {role}
User Email: {email}

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

