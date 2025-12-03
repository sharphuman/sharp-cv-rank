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
# Secrets must be set in Streamlit Cloud
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GMAIL_USER = st.secrets["GMAIL_USER"]
GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]

client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER: TEXT EXTRACTION ---

def extract_text_from_file(uploaded_file):
    """
    Reads PDF or DOCX and returns raw text.
    """
    text = ""
    try:
        # 1. Handle PDF
        if uploaded_file.type == "application/pdf":
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t: text += t + "\n"
        
        # 2. Handle DOCX
        elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        
        # 3. Handle TXT
        elif uploaded_file.type == "text/plain":
            text = str(uploaded_file.read(), "utf-8")
            
    except Exception as e:
        return f"Error reading file: {e}"
        
    return text[:4000] # Limit char count to save tokens

# --- AI ANALYSIS ---

def analyze_candidate(candidate_text, jd_text, filename):
    """
    The Core Brain. Compares CV to JD.
    """
    prompt = f"""
    You are a Senior Technical Recruiter. Evaluate this candidate.
    
    JOB DESCRIPTION:
    {jd_text[:3000]}
    
    CANDIDATE CV TEXT ({filename}):
    {candidate_text[:3000]}
    
    TASK:
    1. Score (0-100): Based on strict requirements match.
    2. Summary: 2 sentences on who they are.
    3. Pros: Top 3 strengths relative to THIS job.
    4. Cons/Red Flags: Missing skills, job hopping, or lack of specific experience mentioned in JD.
    5. Interview Q: Generate 1 hard technical question specific to their resume gaps.
    
    OUTPUT JSON keys: "score", "summary", "pros", "cons", "interview_q"
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Use 4o for reasoning capability
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
    
    # HTML Table of Top 5
    top_5 = df.head(5)[['Score', 'Name', 'Summary', 'Red Flags']].to_html(index=False)
    
    body = f"""
    <h3>Candidate Ranking Report</h3>
    <p>Attached is the detailed breakdown of all candidates for <strong>{jd_title}</strong>.</p>
    <h4>Top Matches:</h4>
    {top_5}
    """
    msg.attach(MIMEText(body, 'html'))
    
    # Attach Excel
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

st.title("⚖️ Sharp CV Rank")
st.markdown("Upload a **Job Description** and a stack of **Resumes**. AI will rank them, find red flags, and draft interview questions.")

# 1. INPUTS
with st.sidebar:
    st.header("1. The Job")
    jd_input_method = st.radio("Input Method", ["Paste Text", "Upload File"])
    
    jd_text = ""
    if jd_input_method == "Paste Text":
        jd_text = st.text_area("Paste JD Here", height=300)
    else:
        jd_file = st.file_uploader("Upload JD", type=["pdf", "docx", "txt"])
        if jd_file:
            jd_text = extract_text_from_file(jd_file)

    st.divider()
    st.header("2. Settings")
    email_recipient = st.text_input("Email Report To", "judd@sharphuman.com")

# 2. CV UPLOAD
st.subheader("2. Upload Candidates")
uploaded_cvs = st.file_uploader("Drop up to 20 CVs here (PDF/DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

# 3. RUN BUTTON
if st.button("Analyze & Rank Candidates", type="primary"):
    if not jd_text or not uploaded_cvs:
        st.error("Please provide a Job Description and at least one CV.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # --- PROCESSING LOOP ---
        for i, cv_file in enumerate(uploaded_cvs):
            status_text.text(f"Analyzing {cv_file.name}...")
            
            # 1. Read CV
            cv_text = extract_text_from_file(cv_file)
            
            # 2. Analyze
            analysis = analyze_candidate(cv_text, jd_text, cv_file.name)
            
            # 3. Store
            results.append({
                "Score": analysis.get('score', 0),
                "Name": cv_file.name,
                "Summary": analysis.get('summary', ''),
                "Strengths": analysis.get('pros', ''),
                "Red Flags": analysis.get('cons', ''),
                "Interview Q": analysis.get('interview_q', '')
            })
            
            # Update Progress
            progress_bar.progress((i + 1) / len(uploaded_cvs))
            
        status_text.text("Finalizing Report...")
        
        # --- DISPLAY RESULTS ---
        df = pd.DataFrame(results)
        df = df.sort_values(by="Score", ascending=False)
        
        # Top Metrics
        best_candidate = df.iloc[0]
        st.success(f" Analysis Complete! Top Pick: **{best_candidate['Name']}** ({best_candidate['Score']}%)")
        
        # Detailed View
        st.divider()
        for index, row in df.iterrows():
            with st.expander(f"{row['Score']}% - {row['Name']}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write("**✅ Strengths:**")
                    st.info(row['Strengths'])
                with c2:
                    st.write("**🚩 Risks / Gaps:**")
                    st.warning(row['Red Flags'])
                
                st.write("**💡 Suggested Interview Question:**")
                st.markdown(f"> *{row['Interview Q']}*")
        
        # Email
        if email_recipient:
            if send_summary_email(email_recipient, df, "Job Analysis"):
                st.toast(f"Report emailed to {email_recipient}", icon="📧")
            else:
                st.error("Could not send email.")
