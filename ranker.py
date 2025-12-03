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
    You are an Elite Technical Recruiter. Evaluate this candidate.
    
    JOB DESCRIPTION:
    {jd_text[:2000]}
    
    CANDIDATE CV:
    {candidate_text[:3000]}
    
    TASK:
    1. Score (0-100): Strict match.
    2. Summary: 2 sentences.
    3. Red Flags: Gaps, hopping, missing skills.
    
    4. INTERROGATION KIT:
       - Q1/A1, Q2/A2, Q3/A3: Closed fact-check questions with answers.
       - Open Q: Behavioral question for gaps.
    
    5. MANAGER BLURB: 1-sentence sales pitch for Slack.
    
    6. OUTREACH EMAIL: Write a short, personalized email TO the candidate. Reference a specific project/skill from their CV to prove a human read it. Keep it casual.
    
    7. BLIND SUMMARY: Write a detailed paragraph of their experience but REMOVE Name, Gender (use 'The Candidate'), University Names, and Location. Focus only on skills/years.
    
    OUTPUT JSON KEYS: 
    "score", "summary", "pros", "cons", 
    "q1", "a1", "q2", "a2", "q3", "a3", "open_q", 
    "manager_blurb", "outreach_email", "blind_summary"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"score": 0, "summary": "Error", "q1": "", "a1": "", "manager_blurb": "", "outreach_email": "", "blind_summary": ""}

# --- EMAIL REPORT ---
def send_summary_email(user_email, df, jd_title):
    msg = MIMEMultipart()
    msg['Subject'] = f"Ranked Candidates: {jd_title}"
    msg['From'] = GMAIL_USER
    msg['To'] = user_email
    
    top_5 = df.head(5)[['Score', 'Name', 'Summary', 'Red Flags']].to_html(index=False)
    
    body = f"""
    <h3>Candidate Ranking Report</h3>
    <p>Attached is the analysis for <strong>{jd_title}</strong>.</p>
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

st.title("⚖️ Sharp CV Rank")
st.markdown("### The AI Assistant for High-Volume Recruiters")

# Selling Points Grid
with st.container():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.info("**🚀 Stop Ctrl+F**\n\nContextual matching, not keywords.")
    with c2:
        st.warning("**🚩 Catch Red Flags**\n\nSpot job hopping & gaps instantly.")
    with c3:
        st.success("**👻 Ghost-Buster**\n\nAuto-write personalized outreach emails.")
    with c4:
        st.error("**🙈 Blind Hiring**\n\nOne-click unbiased profile generation.")

st.divider()

# Sidebar Inputs
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

st.subheader("2. Upload Candidates")
uploaded_cvs = st.file_uploader("Upload CVs (PDF/DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

if st.button("Rank Candidates", type="primary"):
    if not jd_text or not uploaded_cvs:
        st.error("Missing Data")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, cv_file in enumerate(uploaded_cvs):
            status_text.text(f"Analyzing {cv_file.name}...")
            cv_text = extract_text_from_file(cv_file)
            a = analyze_candidate(cv_text, jd_text, cv_file.name)
            
            results.append({
                "Score": a.get('score', 0),
                "Name": cv_file.name,
                "Summary": a.get('summary', ''),
                "Strengths": a.get('pros', ''),
                "Red Flags": a.get('cons', ''),
                "Manager Blurb": a.get('manager_blurb', ''),
                "Outreach Email": a.get('outreach_email', ''),
                "Blind Summary": a.get('blind_summary', ''),
                "Q1": a.get('q1', ''), "A1": a.get('a1', ''),
                "Q2": a.get('q2', ''), "A2": a.get('a2', ''),
                "Q3": a.get('q3', ''), "A3": a.get('a3', ''),
                "Open Q": a.get('open_q', '')
            })
            progress_bar.progress((i + 1) / len(uploaded_cvs))
            
        status_text.text("Done!")
        
        df = pd.DataFrame(results).sort_values(by="Score", ascending=False)
        
        # Top Match
        best = df.iloc[0]
        st.balloons()
        st.success(f"🏆 Top Pick: **{best['Name']}** ({best['Score']}%)")
        
        # Detailed Cards
        for index, row in df.iterrows():
            with st.expander(f"{row['Score']}% - {row['Name']}"):
                
                # Top Row: Strengths & Risks
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.write("**✅ Strengths**")
                    st.write(row['Strengths'])
                with c2:
                    st.write("**🚩 Red Flags**")
                    st.error(row['Red Flags'])
                
                st.divider()
                
                # Tabbed Interface for the Tools
                tab1, tab2, tab3, tab4 = st.tabs(["🕵️ Interrogation", "💬 Slack Blurb", "📧 Outreach Email", "🙈 Blind Profile"])
                
                with tab1:
                    st.markdown(f"**1. Closed:** {row['Q1']} *(Ans: {row['A1']})*")
                    st.markdown(f"**2. Closed:** {row['Q2']} *(Ans: {row['A2']})*")
                    st.markdown(f"**3. Closed:** {row['Q3']} *(Ans: {row['A3']})*")
                    st.markdown(f"**4. Open:** {row['Open Q']}")
                
                with tab2:
                    st.info("Copy/Paste to Slack/Teams:")
                    st.code(row['Manager Blurb'], language="text")
                
                with tab3:
                    st.success("Personalized draft to candidate:")
                    st.text_area("Copy Email:", value=row['Outreach Email'], height=150)
                
                with tab4:
                    st.warning("Bias-Free Summary (No Name/Gender/School):")
                    st.text_area("Copy Blind Summary:", value=row['Blind Summary'], height=150)

        if email_recipient:
            if send_summary_email(email_recipient, df, "Ranked Report"):
                st.toast("Email Sent!", icon="📧")
