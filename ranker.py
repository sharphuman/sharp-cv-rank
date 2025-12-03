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
    with c2:
        st.warning("**🚩 Catch Red Flags**\n\nInstantly spot job hoppers, employment gaps, and skills mismatches before you call.")
    with c3:
        st.success("**📝 Interview Prep**\n\nGet custom, hard-hitting technical questions generated for every candidate's weak spots.")

st.divider()

# --- MAIN APP ---
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
st.write("Drag and drop your stack of resumes here. We'll rank them instantly.")
uploaded_cvs = st.file_uploader("Upload CVs (PDF/DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

if st.button("Analyze & Rank Candidates", type="primary"):
    if not jd_text or not uploaded_cvs:
        st.error("Please provide a Job Description and at least one CV.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, cv_file in enumerate(uploaded_cvs):
            status_text.text(f"Analyzing {cv_file.name}...")
            cv_text = extract_text_from_file(cv_file)
            analysis = analyze_candidate(cv_text, jd_text, cv_file.name)
            
            results.append({
                "Score": analysis.get('score', 0),
                "Name": cv_file.name,
                "Summary": analysis.get('summary', ''),
                "Strengths": analysis.get('pros', ''),
                "Red Flags": analysis.get('cons', ''),
                "Interview Q": analysis.get('interview_q', '')
            })
            progress_bar.progress((i + 1) / len(uploaded_cvs))
            
        status_text.text("Finalizing Report...")
        
        df = pd.DataFrame(results)
        df = df.sort_values(by="Score", ascending=False)
        
        # Display Top Result
        best = df.iloc[0]
        st.success(f"🏆 Top Match: **{best['Name']}** ({best['Score']}%)")
        
        # Detailed Table
        for index, row in df.iterrows():
            with st.expander(f"{row['Score']}% - {row['Name']}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write("**✅ Strengths:**")
                    st.write(row['Strengths'])
                    st.write("**💡 Interview Question:**")
                    st.info(row['Interview Q'])
                with c2:
                    st.write("**🚩 Risks:**")
                    st.warning(row['Red Flags'])
                    st.write("**📝 Summary:**")
                    st.caption(row['Summary'])
        
        if email_recipient:
            if send_summary_email(email_recipient, df, "Job Analysis"):
                st.toast(f"Report emailed to {email_recipient}", icon="📧")
            else:
                st.error("Could not send email.")
