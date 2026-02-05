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

    def generate_sql(self, schema_text: str, question: str, email: str, role: str) -> str:
        """
        Generate T-SQL query based on schema and question.
        Trusts the downstream RLS layer for row-level security.
        """
        prompt = f"""
You are an elite T-SQL Architect specializing in Azure SQL. Your task is to transform natural language questions into highly accurate, efficient, and read-only T-SQL queries.

MISSION-CRITICAL RULES:
1. **Schema Adherence**: Use ONLY the tables and columns provided in the SCHEMA below. 
   - DO NOT hallucinate table names inside your query.
   - DO NOT use placeholders like 'YourTable' or '[YourTable]'.
   - If the schema is empty or insufficient, return "NO_SQL".
   - If the user asks for a summary of "selected tables", SELECT the top 5 rows from each valid table found in the schema to provide a preview.
2. **Naming Convention**: T-SQL uses square brackets for identifiers if they contain spaces or are reserved keywords (e.g., `[Order]`).
3. **Fuzzy Matching**: For name-based or text-based filters, ALWAYS use `LIKE` with wildcards (e.g., `WHERE Name LIKE '%{{question}}%'`) to ensure high recall.
4. **Security Awareness**: If the user asks about "my" records (e.g., "my sales", "my attendance"), filter the results using the user's email: `{{email}}`.
5. **Advanced Analytics**: Utilize JOINS, window functions (RANK, ROW_NUMBER), and aggregations to provide deep insights.
6. **Output Format**: Return ONLY the SQL query inside triple backticks. Do not provide explanations or commentary.

USER CONTEXT:
- Role: {{role}}
- User Email: {{email}}

SCHEMA:
{{schema_text}}

USER QUESTION:
{{question}}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a specialized T-SQL architect. You only return valid T-SQL code inside code blocks. You do not explain the code."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
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

User's Original Question: "{{question}}"

Data Result Preview (JSON):
{{data_preview}}

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
