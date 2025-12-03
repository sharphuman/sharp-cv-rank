import streamlit as st
import pandas as pd
import pdfplumber
import docx
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import io
import json

# --- CONFIGURATION ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GMAIL_USER = st.secrets["GMAIL_USER"]
GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]

client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER: TEXT EXTRACTION ---
def extract_text_from_file(uploaded_file):
    text = ""
    try:
        if uploaded_file.type == "application/pdf":
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t: text += t + "\n"
        elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif uploaded_file.type == "text/plain":
            text = str(uploaded_file.read(), "utf-8")
    except Exception as e:
        return f"Error reading file: {e}"
    return text[:4000]

# --- AI ANALYSIS ---
def analyze_candidate(candidate_text, jd_text, filename):
    prompt = f"""
    You are a Senior Technical Recruiter. Evaluate this candidate.
    
    JOB DESCRIPTION:
    {jd_text[:3000]}
    
    CANDIDATE CV TEXT ({filename}):
    {candidate_text[:3000]}
    
    TASK:
    1. Score (0-100): Strict match.
    2. Summary: 2 sentences on who they are.
    3. Pros: Top 3 strengths.
    4. Cons/Red Flags: Job hopping, gaps, missing specific tech, or weak experience.
    5. Interview Q: Generate 1 hard technical question to test their specific weak point.
    
    OUTPUT JSON keys: "score", "summary", "pros", "cons", "interview_q"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"score": 0, "summary": f"Error: {e}", "pros": "", "cons": "", "interview_q": ""}

# --- EMAIL ---
def send_summary_email(user_email, df, jd_title):
    msg = MIMEMultipart()
    msg['Subject'] = f"Candidate Ranking: {jd_title}"
    msg['From'] = GMAIL_USER
    msg['To'] = user_email
    
    top_5 = df.head(5)[['Score', 'Name', 'Summary', 'Red Flags']].to_html(index=False)
    
    body = f"""
    <h3>Candidate Ranking Report</h3>
    <p>Attached is the detailed breakdown for <strong>{jd_title}</strong>.</p>
    <h4>Top Matches:</h4>
    {top_5}
    """
    msg.attach(MIMEText(body, 'html'))
    
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    part = MIMEApplication(excel_buffer.getvalue(), Name="Ranking.xlsx")
    part['Content-Disposition'] = 'attachment; filename="Ranking.xlsx"'
    msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except: return False

# --- UI ---
st.set_page_config(page_title="Sharp CV Rank", page_icon="⚖️", layout="wide")

# --- HEADER & SELLING POINTS ---
st.title("⚖️ Sharp CV Rank")
st.markdown("### The AI Assistant for High-Volume Recruiters")

# The "Selling Points" Grid
with st.container():
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("**🚀 Stop Ctrl+F**\n\nAI reads for *context*, not just keywords. It knows that 'React' implies 'JS' experience.")
    with c2
